"""Read-only warehouse access for model-written SQL.

One read-only DuckDB connection per process, locked down: no file or network access from SQL and
configuration that cannot be changed from a query. run_model_sql() accepts a single SELECT over core
tables and returns errors as data, so a model can repair its query instead of the program raising.
"""

import json

import duckdb

from gridrag.config import DB

_db: duckdb.DuckDBPyConnection | None = None


def _database() -> duckdb.DuckDBPyConnection:
    global _db
    if _db is None:
        if not DB.exists():
            raise FileNotFoundError(f"warehouse missing: {DB}; run python -m gridrag.warehouse.build")
        _db = duckdb.connect(
            str(DB), read_only=True, config={"enable_external_access": False, "lock_configuration": True}
        )
    return _db


SAFE_TABLE_FUNCTIONS = {"range", "generate_series", "unnest"} 

def _references(node, tables: set, functions: set, ctes: set) -> None:
    """Collects (schema, table) references, table functions and CTE names from a parsed query tree."""
    if isinstance(node, dict):
        ctes = ctes | {entry["key"] for entry in (node.get("cte_map") or {}).get("map", [])}
        if node.get("type") == "BASE_TABLE":
            schema, name = node.get("schema_name") or "", node["table_name"]
            if catalog := node.get("catalog_name"):
                schema = f"{catalog}.{schema}"
            if schema or name not in ctes:
                tables.add((schema, name))
        elif node.get("type") == "TABLE_FUNCTION":
            functions.add((node.get("function") or {}).get("function_name", "?"))
        for value in node.values():
            _references(value, tables, functions, ctes)
    elif isinstance(node, list):
        for value in node:
            _references(value, tables, functions, ctes)


def _check(cur: duckdb.DuckDBPyConnection, sql: str, allowed_tables: set[str] | None = None) -> str | None:
    """one SELECT, tables only from core (or the query's own CTEs) and, when given, only from
    allowed_tables, and no table functions beyond SAFE_TABLE_FUNCTIONS."""
    (text,) = cur.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()
    parsed = json.loads(text)
    if parsed.get("error"):
        if parsed.get("error_type") == "not implemented":  # json_serialize_sql only accepts SELECT rn
            return "only a single SELECT (or WITH ... SELECT) query is allowed"
        return f"{parsed.get('error_type', 'parser')} error: {parsed.get('error_message', '')}"[:600]
    if len(parsed["statements"]) != 1:
        return "only a single SELECT (or WITH ... SELECT) query is allowed"
    tables, functions = set(), set()
    _references(parsed["statements"], tables, functions, set())
    if bad := sorted(f"{schema}.{name}" if schema else name for schema, name in tables if schema != "core"):
        return f"not available: {', '.join(bad)}. Use schema-qualified tables from core."
    if allowed_tables is not None and (
        bad := sorted(f"{schema}.{name}" for schema, name in tables if f"{schema}.{name}" not in allowed_tables)
    ):
        return f"outside the selected tables: {', '.join(bad)}. Use only the supplied tables."
    if bad := sorted(functions - SAFE_TABLE_FUNCTIONS):
        return f"table functions are not allowed: {', '.join(bad)}"
    return None


def run_model_sql(sql: str, max_rows: int, allowed_tables: set[str] | None = None) -> dict:
    """Runs one model-written query: {"rows", "csv"[, "truncated"]}, or {"error"} for the model to fix.
    allowed_tables (schema-qualified) restricts the query to a routed slice; None allows any core table."""
    sql = sql.strip().rstrip(";").strip()
    cur = _database().cursor()  
    try:
        try:
            error = _check(cur, sql, allowed_tables)
        except (duckdb.Error, RecursionError) as exc:
            error = f"invalid query: {type(exc).__name__}"
        if error:
            return {"error": error}
        try:
            df = cur.execute(f"SELECT * FROM ({sql}) AS result LIMIT {max_rows + 1}").df()
        except duckdb.Error as exc:
            return {"error": f"{type(exc).__name__}: {exc}"[:600]}
    finally:
        cur.close()
    out = {"rows": min(len(df), max_rows), "csv": df.head(max_rows).to_csv(index=False, float_format="%.2f")}
    if len(df) > max_rows:
        out["truncated"] = f"more than {max_rows} rows; aggregate or filter in SQL"
    return out
