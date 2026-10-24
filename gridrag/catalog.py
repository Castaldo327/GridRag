"""Demo catalog adapter for the checked-in, documented CREATE TABLE statements.

This is intentionally not a general SQL parser or live database introspector.
Production callers can supply an approved catalog to answer(..., catalog=...).
"""

import re


def schema_blocks() -> dict[str, str]:
    """Load full table definitions and leading comments, including blank lines inside DDL."""
    from gridrag.warehouse.build import schema_text

    pattern = r"((?:^[ \t]*--[^\n]*\n)*^CREATE TABLE (core\.\w+)\s*\([\s\S]*?^\);)"
    blocks = {}
    for block, name in re.findall(pattern, schema_text(), re.MULTILINE):
        if name in blocks:
            raise ValueError(f"Duplicate catalog entry: {name}")
        blocks[name] = block.strip()
    if not blocks:
        raise ValueError("The schema catalog is empty")
    return blocks
