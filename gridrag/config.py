"""Paths shared by the warehouse builder and its readers."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb" 