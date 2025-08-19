# backend/app.py
import os, json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text, bindparam

# -----------------------------------------------------------------------------
# DB
DATABASE_URL = os.getenv("DATABASE_URL") or \
    "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres"
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

# -----------------------------------------------------------------------------
# CORS
DEFAULT_CORS = "http://localhost:3000"
_origins = os.getenv("CORS_ORIGINS", DEFAULT_CORS)
allow_origins = [o.strip() for o in _origins.split(",") if o.strip()]

app = FastAPI(title="Construction Editor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Sections – explicit list, no remapping
SECTION_ORDER: List[str] = [
    "Outside",
    "Ground Floor",
    "1st Floor",
    "Roof",
    "Waste Removal",
    "Staffing expenses",
    "Staffing Needed",
]
PRIMARY_SECTIONS = set(SECTION_ORDER)

def norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()

# -----------------------------------------------------------------------------
# Audit
def write_audit(who: str, action: str, payload: Dict[str, Any]) -> None:
    js = json.dumps(payload, ensure_ascii=False)
    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO audit_log (who, action, payload) VALUES (%s, %s, %s::jsonb)",
                (who or "anonymous", action, js),
            )
        except Exception:
            conn.rollback()
            cur.execute(
                "INSERT INTO audit_log (who, action, payload) VALUES (%s, %s, %s)",
                (who or "anonymous", action, js),
            )
        conn.commit()
        cur.close()
    finally:
        conn.close()

# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/sheets")
def get_sheets() -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name FROM sheets ORDER BY id")).mappings().all()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

@app.get("/sections")
def get_sections(sheet_id: int = Query(...)) -> List[str]:
    # Always show the full, canonical section list
    return SECTION_ORDER[:]

@app.get("/subsections")
def get_subsections(
    sheet_id: int = Query(...),
    section: str = Query(...),
) -> List[str]:
    # Roof and Staffing expenses: no subsections in the UI
    if section in ("Roof", "Staffing expenses"):
        return ["(none)"]

    with engine.connect() as conn:
        # normalize section compare: lower(trim(section)) = lower(:sec)
        res = conn.execute(
            text("""
                SELECT DISTINCT
                    COALESCE(NULLIF(TRIM(subsection), ''), '(none)') AS ss
                FROM rows
                WHERE sheet_id = :sid
                  AND LOWER(TRIM(section)) = LOWER(:sec)
                ORDER BY 1
            """),
            {"sid": sheet_id, "sec": section},
        ).all()
    return [r[0] for r in res]

@app.get("/block")
def get_block(
    sheet_id: int = Query(...),
    section: str = Query(...),
    subsection: Optional[str] = Query(""),
    start_day: int = Query(1, ge=1),
    end_day: int = Query(14, ge=1),
) -> Dict[str, Any]:
    if start_day > end_day:
        return {"rows": []}

    with engine.connect() as conn:
        # ---------------- pick rows ----------------
        if section in ("Roof", "Staffing expenses"):
            row_sql = text("""
                SELECT id, section, subsection
                FROM rows
                WHERE sheet_id = :sid
                  AND LOWER(TRIM(section)) = LOWER(:sec)
                ORDER BY id
            """)
            row_meta = conn.execute(row_sql, {"sid": sheet_id, "sec": section}).all()

        else:
            if subsection and subsection != "(none)":
                row_sql = text("""
                    SELECT id, section, subsection
                    FROM rows
                    WHERE sheet_id = :sid
                      AND LOWER(TRIM(section)) = LOWER(:sec)
                      AND COALESCE(NULLIF(TRIM(subsection), ''), '(none)') = :ss
                    ORDER BY id
                """)
                row_meta = conn.execute(
                    row_sql, {"sid": sheet_id, "sec": section, "ss": subsection}
                ).all()
            else:
                row_sql = text("""
                    SELECT id, section, subsection
                    FROM rows
                    WHERE sheet_id = :sid
                      AND LOWER(TRIM(section)) = LOWER(:sec)
                    ORDER BY id
                """)
                row_meta = conn.execute(row_sql, {"sid": sheet_id, "sec": section}).all()

        row_ids = [r[0] for r in row_meta]

        # ---------------- shape output ----------------
        def build_row_dict(row_id: int, sec_out: str, sub_out: str) -> Dict[str, Any]:
            base = {"row_id": row_id, "section": sec_out, "subsection": sub_out}
            for d in range(start_day, end_day + 1):
                base[f"day_{d}_task"]  = None
                base[f"day_{d}_time"]  = None
                base[f"day_{d}_labor"] = None
            return base

        def apply_cell(rd: Dict[str, Any], day: int, task, hours, labor):
            rd[f"day_{day}_task"]  = task
            rd[f"day_{day}_time"]  = float(hours) if hours is not None else None
            rd[f"day_{day}_labor"] = labor

        row_lookup: Dict[int, Dict[str, Any]] = {}
        for rid, sec, sub in row_meta:
            # For Roof & Staffing expenses: force subsection label "(none)"
            if section in ("Roof", "Staffing expenses"):
                sub_out = "(none)"
            else:
                sub_out = sub.strip() if (sub and sub.strip()) else "(none)"
            row_lookup[rid] = build_row_dict(rid, sec, sub_out)

        # ---------------- fetch day cells ----------------
        if row_ids:
            stmt = text("""
                SELECT row_id, day, task, hours, labor_code
                FROM day_cells
                WHERE row_id IN :ids
                  AND day BETWEEN :s AND :e
            """).bindparams(bindparam("ids", expanding=True))
            cells = conn.execute(stmt, {"ids": row_ids, "s": start_day, "e": end_day}).all()
            for rid, d, task, hrs, code in cells:
                apply_cell(row_lookup[rid], int(d), task, hrs, code)

        return {"rows": [row_lookup[r] for r in row_ids]}

@app.post("/cells/bulk_upsert")
def bulk_upsert(request: Request, body: Dict[str, Any]):
    records = body.get("records", []) or []
    if not records:
        return {"updated": 0}

    user = request.headers.get("X-User", "anonymous")
    updated = 0

    # one transaction
    with engine.begin() as conn:
        for rec in records:
            rid  = int(rec["row_id"])
            day  = int(rec["day"])
            task = rec.get("task")
            hrs  = rec.get("hours")
            lab  = rec.get("labor_code")

            # upsert; fall back to update->insert if needed
            try:
                conn.execute(
                    text("""
                        INSERT INTO day_cells (row_id, day, task, hours, labor_code)
                        VALUES (:rid, :day, :task, :hrs, :lab)
                        ON CONFLICT (row_id, day)
                        DO UPDATE SET task=EXCLUDED.task,
                                      hours=EXCLUDED.hours,
                                      labor_code=EXCLUDED.labor_code
                    """),
                    {"rid": rid, "day": day, "task": task, "hrs": hrs, "lab": lab},
                )
            except Exception:
                res = conn.execute(
                    text("""
                        UPDATE day_cells
                        SET task=:task, hours=:hrs, labor_code=:lab
                        WHERE row_id=:rid AND day=:day
                    """),
                    {"rid": rid, "day": day, "task": task, "hrs": hrs, "lab": lab},
                )
                if res.rowcount == 0:
                    conn.execute(
                        text("""
                            INSERT INTO day_cells (row_id, day, task, hours, labor_code)
                            VALUES (:rid, :day, :task, :hrs, :lab)
                        """),
                        {"rid": rid, "day": day, "task": task, "hrs": hrs, "lab": lab},
                    )
            updated += 1

    write_audit(user, "bulk_upsert", {"updated": updated, "records": records})
    return {"updated": updated}
