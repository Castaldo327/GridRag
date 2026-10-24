"""The schema catalog: documented tables with the tables their foreign keys reference, plus families of per-ISO
tables that routing scores as one unit before keeping the requested ISOs' members.

demo_catalog() adapts the checked-in, documented CREATE TABLE statements. This is intentionally not a general SQL
parser or live database introspector. Production callers can supply an approved Catalog to answer(..., catalog=...).
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from types import MappingProxyType

_STATEMENT = re.compile(r"(?:^[ \t]*--[^\n]*\n)*^CREATE TABLE \w+\.\w+\s*\([\s\S]*?^\);", re.MULTILINE | re.IGNORECASE)
_NAME = re.compile(r"\bCREATE TABLE\s+(\w+\.\w+)", re.IGNORECASE)
_REFERENCE = re.compile(r"\bREFERENCES\s+(\w+\.\w+)", re.IGNORECASE)


@dataclass(frozen=True)
class Table:
    """One queryable table: its schema-qualified name, documented definition, and the tables it references."""

    name: str
    ddl: str
    references: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "references", frozenset(self.references))

    @classmethod
    def parse(cls, ddl: str) -> "Table":
        """A table from one documented CREATE TABLE statement. References come from its code, not its comments;
        names are lower-cased, as DuckDB resolves them case-insensitively."""
        code = re.sub(r"--[^\n]*", "", ddl)
        if not (name := _NAME.search(code)):
            raise ValueError(f"Not a schema-qualified CREATE TABLE statement: {ddl.strip()[:80]!r}")
        return cls(name[1].lower(), ddl.strip(), frozenset(table.lower() for table in _REFERENCE.findall(code)))


@dataclass(frozen=True)
class Family:
    """Tables that share one definition, one per ISO. Routing reads ddl once, with the ISO left open."""

    name: str
    ddl: str
    tables: Mapping[str, str]  # ISO code -> table name

    def __post_init__(self) -> None:
        if not self.tables:
            raise ValueError(f"Family {self.name!r} has no tables")
        object.__setattr__(self, "tables", MappingProxyType(dict(self.tables)))


@dataclass(frozen=True)
class Catalog:
    """Every table SQL may query, by name, and the families routing scores in place of their members."""

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
        """What routing scores, with the definition it reads: each table outside a family, then each family."""
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
