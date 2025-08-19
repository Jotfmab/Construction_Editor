from __future__ import annotations
import sys
import pandas as pd
from sqlalchemy.orm import Session
from db import engine, SessionLocal
from models import Sheet, Row, DayCell
from sqlalchemy import delete
from crud import get_or_create_sheet, bulk_upsert_cells

CANON_SECTIONS = {"Outside", "Ground Floor", "1st Floor", "Roof"}

def normalize_section(label: str) -> str | None:
    lab = (label or "").strip()
    if lab in CANON_SECTIONS:
        return lab
    if lab.lower() == "first floor":
        return "1st Floor"
    return None

def import_csv(csv_path: str, sheet_name: str):
    df = pd.read_csv(csv_path)
    cols = list(df.columns)
    first_col = cols[0]

    triplets = []
    for i, c in enumerate(cols):
        if str(c).strip().lower().startswith("day "):
            try:
                d = int(str(c).split()[-1])
                tcol = cols[i+1] if i+1 < len(cols) else None
                lcol = cols[i+2] if i+2 < len(cols) else None
                triplets.append((c, tcol, lcol, d))
            except Exception:
                continue
    if not triplets:
        raise RuntimeError("No 'Day N' columns found")

    db: Session = SessionLocal()
    try:
        sheet_id = get_or_create_sheet(db, sheet_name)
        # clear prior data for sheet
        row_ids = [r.id for r in db.query(Row).filter(Row.sheet_id == sheet_id).all()]
        if row_ids:
            db.execute(delete(DayCell).where(DayCell.row_id.in_(row_ids)))
            db.execute(delete(Row).where(Row.sheet_id == sheet_id))

        current_section = None
        row_order = 0
        records = []

        def as_text(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            s = str(v).strip()
            return s if s != "" else None

        def as_float(v):
            if v is None:
                return None
            s = str(v).strip().replace(",", "")
            if s == "":
                return None
            try:
                return float(s)
            except Exception:
                return None

        for _, r in df.iterrows():
            label = str(r[first_col]).strip() if pd.notna(r[first_col]) else None
            # header row: if no triplet has any content
            if not any(
                (r.get(dc) not in (None, "") and not pd.isna(r.get(dc))) or
                (tc and (r.get(tc) not in (None, "") and not pd.isna(r.get(tc)))) or
                (lc and (r.get(lc) not in (None, "") and not pd.isna(r.get(lc))))
                for (dc, tc, lc, _) in triplets
            ):
                canon = normalize_section(label or "")
                if canon:
                    current_section = canon
                continue

            if current_section is None:
                continue

            subsection = label or ""
            row_order += 1
            row = Row(sheet_id=sheet_id, section=current_section, subsection=subsection, row_order=row_order)
            db.add(row)
            db.flush()  # get row.id

            for (dc, tc, lc, d) in triplets:
                task = as_text(r.get(dc))
                hours = as_float(r.get(tc)) if tc else None
                labor = as_text(r.get(lc)) if lc else None

                # sometimes task-like text leaked into "Time (hours)"—treat as task if hours None
                if task is None and hours is None:
                    maybe_task = as_text(r.get(tc)) if tc else None
                    if maybe_task and any(ch.isalpha() for ch in maybe_task):
                        task = maybe_task

                if task is None and hours is None and labor is None:
                    continue

                records.append({"row_id": row.id, "day": int(d), "task": task, "hours": hours, "labor_code": labor})

        bulk_upsert_cells(db, records)
        db.commit()
        print(f"Imported: rows={row_order}, cells={len(records)} into sheet '{sheet_name}' (id={sheet_id})")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python import_csv.py <csv_path> <sheet_name>")
        sys.exit(1)
    import_csv(sys.argv[1], sys.argv[2])
