"""Optional, caller-supplied vocabulary scoped to a catalog; no built-in domain mappings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DimensionValue:
    table: str
    column: str
    value: str
    aliases: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "aliases", tuple(self.aliases))


def render_grounding(values: tuple[DimensionValue, ...], columns) -> str:
    """Only document columns actually delivered to SQL. Custom catalogs opt in explicitly."""
    lines = []
    for entry in values:
        if entry.column in columns.get(entry.table, ()):
            literal = "'" + entry.value.replace("'", "''") + "'"
            lines.append(f"{entry.table}.{entry.column}: {', '.join(entry.aliases)} => {literal}")
    if not lines:
        return ""
    return ("Approved dimension/entity vocabulary (use these exact database values):\n"
            "Resolve terminology using the column-specific mappings below. "
            + "Do not invent codes or infer an unlisted entity. Ask for clarification when ambiguous.\n"
            + "\n".join(lines))
