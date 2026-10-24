"""The schema catalog: documented tables, columns, and foreign-key references.

demo_catalog() adapts the checked-in, documented CREATE TABLE statements. This is intentionally not a general SQL
parser or live database introspector. Product families remain descriptive metadata; routing scores their
physical tables individually. Production callers can supply an approved Catalog to answer(..., catalog=...).
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache, cached_property
from types import MappingProxyType

_STATEMENT = re.compile(r"(?:^[ \t]*--[^\n]*\n)*^CREATE TABLE \w+\.\w+\s*\([\s\S]*?^\);", re.MULTILINE | re.IGNORECASE)
_NAME = re.compile(r"\bCREATE TABLE\s+(\w+\.\w+)", re.IGNORECASE)
_REFERENCE = re.compile(r"\bREFERENCES\s+(\w+\.\w+)", re.IGNORECASE)
_COLUMN_NAME = re.compile(r"^([A-Za-z_]\w*)\s+", re.IGNORECASE)
_SQL_TEXT = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*[\s\S]*?\*/")


def _code(ddl: str) -> str:
    """Remove comments without altering quoted SQL literals."""
    def strip_comment(match: re.Match) -> str:
        token = match[0]
        # Preserve offsets so names located in cleaned SQL still index the original documentation.
        return re.sub(r"[^\n]", " ", token) if token.startswith(("--", "/*")) else token

    return _SQL_TEXT.sub(strip_comment, ddl)


_CONSTRAINTS = {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}


def _definitions(ddl: str) -> list[str]:
    """Split this project's documented CREATE TABLE body at top-level commas."""
    name = _NAME.search(_code(ddl))
    if name is None:
        raise ValueError("Not a schema-qualified CREATE TABLE statement")
    start = ddl.find("(", name.end())
    if start < 0:
        raise ValueError(f"Table {name[1]} has no column definitions")

    parts, current = [], []
    depth, index = 1, start + 1
    while index < len(ddl) and depth:
        char = ddl[index]
        # Quoted values and comments are opaque: their commas/parentheses are not delimiters.
        if token := _SQL_TEXT.match(ddl, index):
            current.append(token[0])
            index = token.end()
            continue
        if char in "'\"" or ddl.startswith("/*", index):
            raise ValueError(f"Unclosed literal or comment in {name[1]}")
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if not depth:
                break
        elif char == "," and depth == 1:
            # Inline comments after a column's comma describe that column.
            next_index = index + 1
            while next_index < len(ddl) and ddl[next_index] in " \t":
                next_index += 1
            if ddl.startswith("--", next_index):
                end = ddl.find("\n", next_index)
                if end < 0:
                    end = len(ddl)
                current.append(" " + ddl[next_index:end])
                index = end
            parts.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    if depth:
        raise ValueError(f"Unclosed table definition for {name[1]}")
    if current:
        parts.append("".join(current).strip())
    return parts


@dataclass(frozen=True)
class Table:
    """One queryable table: its schema-qualified name, documented definition, and the tables it references."""

    name: str
    ddl: str
    references: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "references", frozenset(self.references))
        if not self.columns:
            raise ValueError(f"Table {self.name} has no supported column definitions")

    @cached_property
    def definitions(self) -> tuple[str, ...]:
        """Parse once; column scoring and schema rendering share this immutable metadata."""
        return tuple(_definitions(self.ddl))

    @cached_property
    def columns(self) -> Mapping[str, str]:
        """Column name -> documented definition, preserving inline comments."""
        columns = {}
        for definition in self.definitions:
            code = _code(definition).strip()
            match = _COLUMN_NAME.match(code)
            if match is None:
                raise ValueError(f"Unsupported column definition in {self.name}: {code!r}")
            if match[1].upper() not in _CONSTRAINTS:
                name = match[1].lower()
                if name in columns:
                    raise ValueError(f"Duplicate column {self.name}.{name}")
                columns[name] = definition
        return MappingProxyType(columns)

    @cached_property
    def structural_columns(self) -> frozenset[str]:
        """Keep declared keys and time columns even when their relevance score is low.

        Identifier/code suffixes remain a conservative fallback for this demo's DDL.
        Unique keys can be targets of foreign keys even when they are not primary keys.
        """
        keys = set()
        for definition in self.definitions:
            code = _code(definition)
            for match in re.finditer(r"\b(?:PRIMARY KEY|FOREIGN KEY|UNIQUE)\s*\(([^)]*)\)", code, re.I):
                keys.update(name.strip().lower() for name in match[1].split(","))
        for name, definition in self.columns.items():
            if name.endswith(("_id", "_code")) or re.search(
                r"\b(?:DATE|TIMESTAMP|TIMESTAMPTZ|REFERENCES|PRIMARY KEY|UNIQUE)\b", _code(definition), re.I
            ):
                keys.add(name)
        return frozenset(keys & self.columns.keys())

    def selected_schema(self, columns: Iterable[str]) -> str:
        """A compact schema excerpt for SQL generation, retaining table documentation."""
        selected = set(columns)
        if unknown := selected - self.columns.keys():
            raise ValueError(f"Unknown columns for {self.name}: {sorted(unknown)}")
        preamble = self.ddl[:_NAME.search(_code(self.ddl)).start()].strip()
        definitions = [description for name, description in self.columns.items() if name in selected]
        if not definitions:
            raise ValueError(f"No columns selected for {self.name}")
        # Retain declared join/key constraints when their local columns are present.
        for definition in self.definitions:
            code = _code(definition).strip()
            if constraint := re.match(r"(?:CONSTRAINT\s+\w+\s+)?(?:PRIMARY KEY|FOREIGN KEY|UNIQUE)\s*\(([^)]*)\)", code, re.I):
                names = {name.strip().lower() for name in constraint[1].split(",")}
                if names <= selected:
                    definitions.append(definition)
        lines = []
        for index, definition in enumerate(definitions):
            code = _code(definition).strip()
            comments = [match[0] for match in _SQL_TEXT.finditer(definition)
                        if match[0].startswith(("--", "/*"))]
            suffix = "," if index < len(definitions) - 1 else ""
            lines.append(f"    {code}{suffix}{'  ' + ' '.join(comments) if comments else ''}")
        header = f"{preamble}\n" if preamble else ""
        if primary_key := re.search(r"\bPRIMARY KEY\s*\(([^)]*)\)", _code(self.ddl), re.I):
            header += f"-- Primary key: ({primary_key[1]})\n"
        return f"{header}CREATE TABLE {self.name} (\n" + "\n".join(lines) + "\n);"

    @classmethod
    def parse(cls, ddl: str) -> "Table":
        """A table from one documented CREATE TABLE statement. References come from its code, not its comments;
        names are lower-cased, as DuckDB resolves them case-insensitively."""
        code = _code(ddl)
        if not (name := _NAME.search(code)):
            raise ValueError(f"Not a schema-qualified CREATE TABLE statement: {ddl.strip()[:80]!r}")
        return cls(name[1].lower(), ddl.strip(), frozenset(table.lower() for table in _REFERENCE.findall(code)))


@dataclass(frozen=True)
class Family:
    """Tables that share one product definition, one per ISO."""

    name: str
    ddl: str
    tables: Mapping[str, str]  # ISO code -> table name

    def __post_init__(self) -> None:
        if not self.tables:
            raise ValueError(f"Family {self.name!r} has no tables")
        object.__setattr__(self, "tables", MappingProxyType(dict(self.tables)))


@dataclass(frozen=True)
class Catalog:
    """Every table SQL may query, by name, plus optional product-family metadata."""

    tables: Mapping[str, Table]
    families: Mapping[str, Family] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "tables", MappingProxyType(dict(self.tables)))
        object.__setattr__(self, "families", MappingProxyType(dict(self.families)))
        if not self.tables:
            raise ValueError("The schema catalog is empty")
        for name, table in self.tables.items():
            if name != table.name:
                raise ValueError(f"Catalog key {name!r} does not match table {table.name!r}")
            if missing := sorted(table.references - self.tables.keys()):
                raise ValueError(f"Catalog is missing referenced table {', '.join(missing)}")
        members: set[str] = set()
        for name, family in self.families.items():
            if name != family.name or name in self.tables:
                raise ValueError(f"Invalid or conflicting family name: {name!r}")
            if missing := sorted(set(family.tables.values()) - self.tables.keys()):
                raise ValueError(f"Catalog is missing family table {', '.join(missing)}")
            for table in family.tables.values():
                if table in members:
                    raise ValueError(f"Table belongs to multiple family members: {table}")
                members.add(table)

    @classmethod
    def of(cls, tables: Iterable[Table], families: Iterable[Family] = ()) -> "Catalog":
        """A read-only catalog, in the given order. Duplicate table names are an error."""
        by_name: dict[str, Table] = {}
        for table in tables:
            if table.name in by_name:
                raise ValueError(f"Duplicate catalog entry: {table.name}")
            by_name[table.name] = table
        by_family: dict[str, Family] = {}
        for family in families:
            if family.name in by_family:
                raise ValueError(f"Duplicate family entry: {family.name}")
            by_family[family.name] = family
        return cls(by_name, by_family)

    @property
    def isos(self) -> tuple[str, ...]:
        """The ISOs that families split by, in catalog order."""
        return tuple(dict.fromkeys(iso for family in self.families.values() for iso in family.tables))

    def units(self) -> dict[str, str]:
        """A compact product-level catalog view for display and inspection."""
        members = {name for family in self.families.values() for name in family.tables.values()}
        return {**{name: table.ddl for name, table in self.tables.items() if name not in members},
                **{name: family.ddl for name, family in self.families.items()}}


def parse(script: str) -> list[Table]:
    """Every CREATE TABLE in a DDL script, each with the comment lines directly above it, including blank lines
    inside the statement."""
    return [Table.parse(statement) for statement in _STATEMENT.findall(script)]


@cache
def demo_catalog() -> Catalog:
    """The checked-in warehouse: schema.sql's tables and every product's per-ISO tables, one family per product."""
    from gridrag.warehouse import build, products
    isos = list(build.ISO_IDS)
    return Catalog.of(parse(build.schema_text()), [
        Family(f"core.<iso>_{product.suffix}", products.family_ddl(product, isos, build.FIVE_START, build.END),
               MappingProxyType({iso: products.table_name(iso, product) for iso in isos}))
        for product in products.PRODUCTS
    ])
