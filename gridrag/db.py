"""Read-only warehouse access for model-written SQL.

One read-only DuckDB connection per process, locked down: no file or network access from SQL and
configuration that cannot be changed from a query. run_model_sql() accepts a single SELECT over catalog
tables, runs it as DuckDB's parser regenerates it, and returns errors as data, so a model can repair its
query instead of the program raising.
"""

import csv
import io
import json
import threading
import time
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager

import duckdb

from gridrag import config
from gridrag.catalog import demo_catalog
from gridrag.records import QueryResult

SAFE_TABLE_FUNCTIONS = frozenset({"range", "generate_series", "unnest"})
# These have no role in warehouse analytics. In particular write_log could place
# attacker-controlled text in infrastructure logs, and sleep_ms needlessly holds a worker.
BLOCKED_FUNCTIONS = frozenset(
    {"write_log", "sleep_ms", "nextval", "currval", "setval", "setseed", "getenv", "getvariable", "current_setting"}
)
ONE_SELECT = "only a single SELECT (or WITH ... SELECT) query is allowed"

_db: duckdb.DuckDBPyConnection | None = None
_db_lock = threading.Lock()


class QueryRejected(Exception):
    """The guard will not run this query; the message goes back to the model."""


def _database() -> duckdb.DuckDBPyConnection:
    global _db
    with _db_lock:
        if _db is None:
            settings = config.settings
            if not settings.db_path.exists():
                raise FileNotFoundError(f"warehouse missing: {settings.db_path}; run python -m gridrag.warehouse.build")
            connection = duckdb.connect(
                str(settings.db_path),
                read_only=True,
                config={
                    "memory_limit": settings.db_memory_limit,
                    "threads": settings.db_threads,
                    "temp_directory": "",
                },
            )
            try:
                # Configure resources before locking external access and settings.
                connection.execute("SET allow_persistent_secrets = false")
                connection.execute("SET autoinstall_known_extensions = false")
                connection.execute("SET autoload_known_extensions = false")
                connection.execute("SET enable_external_access = false")
                connection.execute("SET lock_configuration = true")
            except Exception:
                connection.close()
                raise
            _db = connection
    return _db


def _references(node, tables: set, functions: set, ctes: set) -> None:
    """Collects schema.table references, table functions and CTE names from a parsed query tree. Names are
    lower-cased, as DuckDB resolves them case-insensitively."""
    if isinstance(node, dict):
        if (node.get("function_name") or "").lower() in BLOCKED_FUNCTIONS:
            raise QueryRejected("functions that expose configuration or change process state are not allowed")
        ctes = ctes | {entry["key"].lower() for entry in (node.get("cte_map") or {}).get("map", [])}
        if node.get("type") == "BASE_TABLE":
            schema, name = (node.get("schema_name") or "").lower(), node["table_name"].lower()
            if catalog := node.get("catalog_name"):
                schema = f"{catalog.lower()}.{schema}"
            if schema or name not in ctes:
                tables.add(f"{schema}.{name}" if schema else name)
        elif node.get("type") == "TABLE_FUNCTION":
            functions.add((node.get("function") or {}).get("function_name", "?"))
        for value in node.values():
            _references(value, tables, functions, ctes)
    elif isinstance(node, list):
        for value in node:
            _references(value, tables, functions, ctes)


def _check(cur: duckdb.DuckDBPyConnection, sql: str, allowed: set[str]) -> str:
    """The query as DuckDB's parser regenerates it, once it is one SELECT over allowed tables (or the query's own
    CTEs) with no table functions beyond SAFE_TABLE_FUNCTIONS. Running the regenerated text means the checked
    statement is the one that runs, and comments or semicolons cannot break the row limit. Raises QueryRejected."""
    (text,) = cur.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()
    parsed = json.loads(text)
    if parsed.get("error"):
        if parsed.get("error_type") == "not implemented":  # json_serialize_sql supports SELECT statements
            raise QueryRejected(ONE_SELECT)
        raise QueryRejected(f"{parsed.get('error_type', 'parser')} error: {parsed.get('error_message', '')}"[:600])
    if len(parsed["statements"]) != 1:
        raise QueryRejected(ONE_SELECT)
    tables: set[str] = set()
    functions: set[str] = set()
    _references(parsed["statements"], tables, functions, set())
    if bad := sorted(tables - allowed):
        raise QueryRejected(f"not available: {', '.join(bad)}. Use only the supplied schema-qualified tables.")
    if bad := sorted(functions - SAFE_TABLE_FUNCTIONS):
        raise QueryRejected(f"table functions are not allowed: {', '.join(bad)}")
    (normalized,) = cur.execute("SELECT json_deserialize_sql(?::JSON)", [text]).fetchone()
    return normalized


@contextmanager
def _timed_cursor(seconds: float) -> Iterator[duckdb.DuckDBPyConnection]:
    """Bound validation, execution and fetching, including gaps between SQL statements."""
    cur = _database().cursor()
    finished, expired = threading.Event(), threading.Event()
    deadline = time.monotonic() + seconds

    def interrupt() -> None:
        if finished.wait(max(0, deadline - time.monotonic())):
            return
        expired.set()
        # An interrupt while the cursor is idle does not cancel its next query.
        # Keep interrupting until the owner stops, so validation cannot consume
        # the deadline and leave the actual query running without a watchdog.
        while not finished.is_set():
            cur.interrupt()
            finished.wait(0.01)

    watchdog = threading.Thread(target=interrupt, daemon=True)
    watchdog.start()
    try:
        try:
            yield cur
        except duckdb.InterruptException as exc:
            raise QueryRejected(f"query exceeded the {seconds:g}-second execution budget") from exc
        if expired.is_set() or time.monotonic() >= deadline:
            raise QueryRejected(f"query exceeded the {seconds:g}-second execution budget")
    finally:
        finished.set()
        watchdog.join()
        cur.close()


def _fetch(
    cur: duckdb.DuckDBPyConnection,
    sql: str,
    allowed: set[str],
    max_rows: int,
) -> tuple[list[str], Iterator[tuple]]:
    """Validate and execute, then fetch rows lazily within the cursor's lifetime."""
    try:
        normalized = _check(cur, sql, allowed)
    except duckdb.InterruptException:
        raise
    except (duckdb.Error, RecursionError) as exc:  # QueryRejected is not a duckdb.Error, so it passes through
        raise QueryRejected(f"invalid query: {type(exc).__name__}") from exc
    try:
        cur.execute(f"SELECT * FROM ({normalized}) AS result LIMIT {max_rows + 1}")
        return [column[0] for column in cur.description], iter(cur.fetchone, None)
    except duckdb.InterruptException:
        raise
    except duckdb.Error as exc:
        raise QueryRejected(f"{type(exc).__name__}: {exc}"[:600]) from exc


def _result(columns: list[str], rows: Iterable[tuple], max_rows: int) -> QueryResult:
    """The rows as CSV, flagged when truncated, or an error when the CSV is too large."""
    settings = config.settings
    # Native values preserve DECIMAL and large integers without DataFrame float coercion.
    parts: list[str] = []
    size = 0

    def append(row: Iterable) -> None:
        nonlocal size
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\n").writerow(row)
        text = buffer.getvalue()
        size += len(text.encode("utf-8"))
        if size > settings.sql_max_result_bytes:
            raise QueryRejected(
                f"result exceeds {settings.sql_max_result_bytes} bytes; aggregate or select fewer columns"
            )
        parts.append(text)

    append(columns)
    count, truncated = 0, False
    for row in rows:
        if count == max_rows:
            truncated = True
            break
        append(row)
        count += 1
    out: QueryResult = {"rows": count, "csv": "".join(parts)}
    if truncated:
        out["truncated"] = f"more than {max_rows} rows; aggregate or filter in SQL"
    return out


def run_model_sql(sql: str, max_rows: int, allowed_tables: Collection[str] | None = None) -> QueryResult:
    """Runs one model-written query: {"rows", "csv"[, "truncated"]}, or {"error"} for the model to fix.
    allowed_tables (schema-qualified) restricts the query to a routed slice; None allows every catalog table."""
    settings = config.settings
    if not isinstance(sql, str) or not sql.strip() or len(sql) > settings.sql_max_chars:
        return {"error": f"query must contain 1–{settings.sql_max_chars} characters"}
    if type(max_rows) is not int or not 1 <= max_rows <= settings.sql_max_rows:
        raise ValueError(f"max_rows must be between 1 and {settings.sql_max_rows}")
    allowed = {table.lower() for table in (demo_catalog().tables if allowed_tables is None else allowed_tables)}
    try:
        with _timed_cursor(settings.sql_timeout_s) as cur:
            columns, rows = _fetch(cur, sql.strip(), allowed, max_rows)
            result = _result(columns, rows, max_rows)
    except QueryRejected as exc:
        return {"error": str(exc)}
    return result
