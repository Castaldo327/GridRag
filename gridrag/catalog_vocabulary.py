"""Approved ISO entity metadata for this catalog; not used by retrieval scoring."""

from gridrag.grounding import DimensionValue

ISO_ENTITIES = (
    DimensionValue("core.dim_iso", "iso_code", "CAISO", ("California", "California ISO", "CAISO")),
    DimensionValue("core.dim_iso", "iso_code", "ERCOT", ("Texas", "ERCOT")),
    DimensionValue("core.dim_iso", "iso_code", "ISONE", ("New England", "ISO New England", "ISO-NE", "ISONE")),
    DimensionValue("core.dim_iso", "iso_code", "MISO", ("Midcontinent", "Midcontinent ISO", "MISO")),
    DimensionValue("core.dim_iso", "iso_code", "NYISO", ("New York", "New York ISO", "NYISO")),
    DimensionValue("core.dim_iso", "iso_code", "PJM", ("PJM",)),
    DimensionValue("core.dim_iso", "iso_code", "SPP", ("Southwest Power Pool", "SPP")),
)
