# backend/models.py
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey,
    UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from db import Base  # we defined Base in db.py

# Using ORM classes that map to the tables

class Sheet(Base):
    __tablename__ = "sheets"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    rows = relationship("Row", back_populates="sheet", cascade="all, delete-orphan")

class Row(Base):
    __tablename__ = "rows"
    id = Column(Integer, primary_key=True)
    sheet_id = Column(Integer, ForeignKey("sheets.id", ondelete="CASCADE"), nullable=False, index=True)
    section = Column(String(255))
    subsection = Column(String(255))
    row_order = Column(Integer, default=0, index=True)

    sheet = relationship("Sheet", back_populates="rows")
    day_cells = relationship("DayCell", back_populates="row", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_rows_sheet_section_subsection", "sheet_id", "section", "subsection"),
    )

class DayCell(Base):
    __tablename__ = "day_cells"
    id = Column(Integer, primary_key=True)
    row_id = Column(Integer, ForeignKey("rows.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(Integer, nullable=False)
    task = Column(String(255))
    hours = Column(Float)
    labor_code = Column(String(16))

    row = relationship("Row", back_populates="day_cells")

    __table_args__ = (
        UniqueConstraint("row_id", "day", name="uq_day_cells_row_day"),
        Index("ix_day_cells_row_day", "row_id", "day"),
    )
