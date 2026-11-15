"""Immutable schema metadata and prompt rendering, independent of SQL parsing."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType

_TIME_TYPES = frozenset(
    {
        "DATE",
        "TIME",
        "TIME WITH TIME ZONE",
        "TIMESTAMP",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMP_S",
        "TIMESTAMP_MS",
        "TIMESTAMP_NS",
    }
)
_KEY_TYPES = frozenset({"PRIMARY KEY", "FOREIGN KEY", "UNIQUE"})


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _comment(text: str, indent: str = "") -> str:
    return "".join(f"{indent}-- {line}\n" for line in text.splitlines())


@dataclass(frozen=True)
class Column:
    """A column as reported by DuckDB, including its persisted documentation."""

    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    description: str = ""
    generation_expression: str | None = None

    def render(self, indent: str = "", *, include_generation: bool = True) -> str:
        definition = f"{quote_identifier(self.name)} {self.data_type}"
        description = self.description
        if self.generation_expression is not None:
            if include_generation:
                definition += f" GENERATED ALWAYS AS ({self.generation_expression})"
            else:
                # An excerpt can omit the columns used by this expression.
                description += f"\nGenerated as: {self.generation_expression}"
        else:
            if not self.nullable:
                definition += " NOT NULL"
            if self.default is not None:
                definition += f" DEFAULT {self.default}"
        # Indent the beginning of SQL only: newlines inside defaults are data.
        return _comment(description.strip(), indent) + indent + definition


@dataclass(frozen=True)
class Constraint:
    """A constraint's SQL and column dependencies, both supplied by DuckDB."""

    kind: str
    columns: tuple[str, ...]
    sql: str
    referenced_table: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))


@dataclass(frozen=True)
class Table:
    """A table snapshot with enough metadata to score columns and render excerpts."""

    schema: str
    table: str
    column_metadata: tuple[Column, ...]
    constraints: tuple[Constraint, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "column_metadata", tuple(self.column_metadata))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        if not self.column_metadata:
            raise ValueError(f"Table {self.name} has no columns")
        if len(self.columns) != len(self.column_metadata):
            raise ValueError(f"Duplicate columns in {self.name}")
        for constraint in self.constraints:
            if unknown := set(constraint.columns) - self.columns.keys():
                raise ValueError(f"Unknown constraint columns in {self.name}: {sorted(unknown)}")

    @property
    def name(self) -> str:
        """The case-insensitive routing identifier used by the SQL guard."""
        return f"{self.schema.lower()}.{self.table.lower()}"

    @cached_property
    def columns(self) -> Mapping[str, str]:
        """Read-only column name -> documented definition, in declaration order."""
        return MappingProxyType({column.name.lower(): column.render() for column in self.column_metadata})

    @cached_property
    def references(self) -> frozenset[str]:
        return frozenset(constraint.referenced_table for constraint in self.constraints if constraint.referenced_table)

    @cached_property
    def structural_columns(self) -> frozenset[str]:
        """Keep declared keys and time columns regardless of their relevance scores."""
        keys = {name for constraint in self.constraints if constraint.kind in _KEY_TYPES for name in constraint.columns}
        times = {column.name.lower() for column in self.column_metadata if column.data_type in _TIME_TYPES}
        return frozenset(keys | times)

    @cached_property
    def ddl(self) -> str:
        """The complete documented schema, rendered from the metadata snapshot."""
        return self.selected_schema(self.columns)

    def selected_schema(self, columns: Iterable[str]) -> str:
        """Render selected columns and constraints whose local columns remain available."""
        selected = set(columns)
        if unknown := selected - self.columns.keys():
            raise ValueError(f"Unknown columns for {self.name}: {sorted(unknown)}")
        if not selected:
            raise ValueError(f"No columns selected for {self.name}")
        complete = selected == self.columns.keys()
        definitions = [
            column.render("    ", include_generation=complete)
            for column in self.column_metadata
            if column.name.lower() in selected
        ]
        definitions.extend(
            f"    {constraint.sql}" for constraint in self.constraints if set(constraint.columns) <= selected
        )
        documentation = _comment(self.description)
        for constraint in self.constraints:
            if constraint.kind == "PRIMARY KEY":
                documentation += f"-- Primary key: ({', '.join(constraint.columns)})\n"
        name = f"{quote_identifier(self.schema)}.{quote_identifier(self.table)}"
        body = ",\n".join(definitions)
        return f"{documentation}CREATE TABLE {name} (\n{body}\n);"


@dataclass(frozen=True)
class DimensionValue:
    """An approved column value with the terms callers may use for it."""

    table: str
    column: str
    value: str
    aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", tuple(self.aliases))


def render_grounding(values: tuple[DimensionValue, ...], columns: Mapping[str, Collection[str]]) -> str:
    """Only document columns actually delivered to SQL. Custom catalogs opt in explicitly."""
    lines = []
    for entry in values:
        if entry.column in columns.get(entry.table, ()):
            literal = "'" + entry.value.replace("'", "''") + "'"
            lines.append(f"{entry.table}.{entry.column}: {', '.join(entry.aliases)} => {literal}")
    if not lines:
        return ""
    instructions = (
        "Approved dimension/entity vocabulary (use these exact database values):\n"
        "Resolve terminology using the column-specific mappings below. "
        "Do not invent codes or infer an unlisted entity. Ask for clarification when ambiguous.\n"
    )
    return instructions + "\n".join(lines)


@dataclass(frozen=True)
class Catalog:
    """Every table SQL may query, with optional entity vocabulary and displayed regions."""

    tables: Mapping[str, Table]
    vocabulary: tuple[DimensionValue, ...] = ()
    isos: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tables", MappingProxyType(dict(self.tables)))
        object.__setattr__(self, "vocabulary", tuple(self.vocabulary))
        object.__setattr__(self, "isos", tuple(self.isos))
        if not self.tables:
            raise ValueError("The schema catalog is empty")
        for entry in self.vocabulary:
            if entry.table not in self.tables or entry.column not in self.tables[entry.table].columns:
                raise ValueError(f"Unknown grounding column: {entry.table}.{entry.column}")
        for name, table in self.tables.items():
            if name != table.name:
                raise ValueError(f"Catalog key {name!r} does not match table {table.name!r}")
            if missing := sorted(table.references - self.tables.keys()):
                raise ValueError(f"Catalog is missing referenced table {', '.join(missing)}")

    @classmethod
    def of(
        cls, tables: Iterable[Table], *, vocabulary: Iterable[DimensionValue] = (), isos: Iterable[str] = ()
    ) -> "Catalog":
        """A read-only catalog, in the given order. Duplicate table names are an error."""
        by_name: dict[str, Table] = {}
        for table in tables:
            if table.name in by_name:
                raise ValueError(f"Duplicate catalog entry: {table.name}")
            by_name[table.name] = table
        return cls(by_name, tuple(vocabulary), tuple(isos))
