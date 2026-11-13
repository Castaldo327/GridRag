"""Approved dimension values, attached explicitly to a catalog; never mined from questions."""

import re
from dataclasses import dataclass


ISO_ALIASES = {
    "CAISO": ("California", "California ISO", "CAISO"),
    "ERCOT": ("Texas", "ERCOT"),
    "ISONE": ("New England", "ISO New England", "ISO-NE", "ISONE"),
    "MISO": ("Midcontinent", "Midcontinent ISO", "MISO"),
    "NYISO": ("New York", "New York ISO", "NYISO"),
    "PJM": ("PJM",),
    "SPP": ("Southwest Power Pool", "SPP"),
}


def mentioned_regions(question: str) -> set[str]:
    """Match whole aliases, including ISO-prefixed location codes; no ambiguous state abbreviations."""
    return {code for code, aliases in ISO_ALIASES.items() if any(
        re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", question, re.I)
        for alias in aliases)}


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
    regional_note = ("For regional questions, California "
                     "means iso_code = 'CAISO', Texas means 'ERCOT', and New England means 'ISONE'. "
                     "A queue project's state is a separate geography: state = 'CA' is not iso_code = 'CA'. "
                     if "iso_code" in columns.get("core.dim_iso", ())
                     and {"CAISO", "ERCOT", "ISONE"} <= {entry.value for entry in values
                         if entry.table == "core.dim_iso" and entry.column == "iso_code"} else "")
    return ("Approved dimension/entity vocabulary (use these exact database values):\n"
            "Resolve terminology using the column-specific mappings below. " + regional_note
            + "Do not invent codes or infer an unlisted entity. Ask for clarification when ambiguous.\n"
            + "\n".join(lines))


def demo_vocabulary() -> tuple[DimensionValue, ...]:
    """Values share the fictional builder's source of truth; aliases are reviewed metadata."""
    from gridrag.warehouse.build import FUELS, ISO_IDS, QUEUE_STATUSES
    from gridrag.warehouse.products import LOCATIONS

    values = [DimensionValue("core.dim_iso", "iso_code", code, aliases)
              for code, aliases in ISO_ALIASES.items() if code in ISO_IDS]
    fuel_aliases = {"natural_gas": ("gas", "natural gas"), "battery": ("battery", "battery storage", "batteries"),
                    "hydro": ("hydro", "hydroelectric")}
    values += [DimensionValue("core.dim_fuel", "fuel_code", code, fuel_aliases.get(code, (name, code)))
               for code, (name, _) in FUELS.items()]
    status_aliases = {"active": ("active", "in study", "agreement", "construction"),
                      "withdrawn": ("withdrawn", "cancelled", "terminated", "retracted"),
                      "completed": ("completed", "in service"), "suspended": ("suspended",),
                      "unknown": ("unknown", "not reported")}
    for code in QUEUE_STATUSES:
        for table in ("core.dim_queue_status", "core.queue_project"):
            values.append(DimensionValue(table, "status_code", code, status_aliases[code]))
    values += [DimensionValue("core.dim_location", "location_code", f"{iso}_{label}",
                             (f"{iso} {label.replace('_', ' ')}", f"{iso}_{label}"))
               for iso in ISO_IDS for label in LOCATIONS]
    return tuple(values)
