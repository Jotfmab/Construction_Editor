# backend/models.py
from sqlalchemy import (
    Table, Column, Integer, String, Float, ForeignKey,
    UniqueConstraint, Index
)
from db import Base  # we defined Base in db.py

# We keep using Core-style Table objects with Base.metadata

sheets = Table(
    "sheets",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), unique=True, nullable=False, index=True),
)

rows = Table(
    "rows",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("sheet_id", Integer, ForeignKey("sheets.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("section", String(255)),
    Column("subsection", String(255)),
    Column("row_order", Integer, default=0, index=True),
    Index("ix_rows_sheet_section_subsection", "sheet_id", "section", "subsection"),
)

day_cells = Table(
    "day_cells",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("row_id", Integer, ForeignKey("rows.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("day", Integer, nullable=False),
    Column("task", String(255)),
    Column("hours", Float),
    Column("labor_code", String(16)),
    UniqueConstraint("row_id", "day", name="uq_day_cells_row_day"),
    Index("ix_day_cells_row_day", "row_id", "day"),
)
