from __future__ import annotations
from sqlalchemy import select, insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from models import Sheet, Row, DayCell, AuditLog

def audit(db: Session, op: str, obj: str, meta: str = ""):
    try:
        db.execute(insert(AuditLog).values(op=op, obj=obj, meta=meta))
    except Exception:
        pass

def get_or_create_sheet(db: Session, name: str) -> int:
    r = db.execute(select(Sheet.id).where(Sheet.name == name)).scalar()
    if r:
        return int(r)
    rid = db.execute(insert(Sheet).values(name=name).returning(Sheet.id)).scalar()
    return int(rid)

def list_sheets(db: Session):
    res = db.execute(select(Sheet.id, Sheet.name).order_by(Sheet.created_at.asc())).all()
    return [{"id": r.id, "name": r.name} for r in res]

def list_sections(db: Session, sheet_id: int):
    res = db.execute(select(Row.section).where(Row.sheet_id == sheet_id).distinct().order_by(Row.section)).all()
    return [r.section for r in res]

def list_subsections(db: Session, sheet_id: int, section: str):
    res = db.execute(
        select(Row.subsection).where(Row.sheet_id == sheet_id, Row.section == section).distinct().order_by(Row.subsection)
    ).all()
    return [r.subsection for r in res]

def fetch_block(db: Session, sheet_id: int, section: str, subsection: str, start_day: int, end_day: int):
    rows = db.execute(
        select(Row.id, Row.subsection, Row.row_order)
        .where(Row.sheet_id == sheet_id, Row.section == section, Row.subsection == subsection)
        .order_by(Row.row_order.asc())
    ).all()
    if not rows:
        return {"rows": [], "start_day": start_day, "end_day": end_day}

    row_ids = [r.id for r in rows]
    cells = db.execute(
        select(DayCell.row_id, DayCell.day, DayCell.task, DayCell.hours, DayCell.labor_code)
        .where(DayCell.row_id.in_(row_ids), DayCell.day >= start_day, DayCell.day <= end_day)
        .order_by(DayCell.row_id, DayCell.day)
    ).all()
    by_rd = {(c.row_id, c.day): c for c in cells}

    out = []
    for r in rows:
        rec = {"row_id": r.id, "subsection": r.subsection}
        for d in range(start_day, end_day + 1):
            c = by_rd.get((r.id, d))
            rec[f"day_{d}_task"] = c.task if c else None
            rec[f"day_{d}_time"] = float(c.hours) if c and c.hours is not None else None
            rec[f"day_{d}_labor"] = c.labor_code if c else None
        out.append(rec)
    return {"rows": out, "start_day": start_day, "end_day": end_day}

def bulk_upsert_cells(db: Session, records: list[dict]):
    if not records:
        return 0
    stmt = pg_insert(DayCell).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DayCell.row_id, DayCell.day],
        set_={
            "task": stmt.excluded.task,
            "hours": stmt.excluded.hours,
            "labor_code": stmt.excluded.labor_code,
        },
    )
    db.execute(stmt)
    audit(db, "bulk_upsert", "day_cell", f"n={len(records)}")
    return len(records)
