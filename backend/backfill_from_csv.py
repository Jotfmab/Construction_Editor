# backfill_from_csv.py
import os, csv, re, argparse, unicodedata
import psycopg2
import psycopg2.extras

PRIMARY_SECTIONS = [
    "Outside",
    "Ground Floor",
    "1st Floor",
    "Roof",                 # single-row section
    "Waste Removal",
    "Staffing expenses",    # single-row section
    "Staffing Needed",
]

DAY_RE   = re.compile(r"^\s*day\s*(\d+)\s*$", re.I)
TIME_RE  = re.compile(r"^\s*time\s*(\d+)\s*$", re.I)
LABOR_RE = re.compile(r"^\s*labor\s*(\d+)\s*$", re.I)

def norm_spaces(s: str) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\xa0", " ").replace("\u202f", " ")  # NBSP, narrow NBSP
    return " ".join(s.strip().split())

def canon(s: str) -> str:
    """Canonicalize for robust comparison: NFKC, strip punctuation, collapse spaces, lowercase."""
    s = "" if s is None else s
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\xa0", " ").replace("\u202f", " ")
    s = re.sub(r"[^0-9A-Za-z ]+", " ", s)
    s = " ".join(s.split()).lower()
    return s

PRIMARY_CANON = {canon(x) for x in PRIMARY_SECTIONS}

def is_section_label(cell_value: str) -> bool:
    return canon(cell_value) in PRIMARY_CANON

def parse_float(x):
    x = norm_spaces(x)
    if x == "": return None
    try:
        return float(x)
    except ValueError:
        return None

def next_row_order(conn, sheet_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(row_order),0)+1 FROM rows WHERE sheet_id=%s", (sheet_id,))
        return cur.fetchone()[0]

def find_existing_row(conn, sheet_id, section, subsection):
    with conn.cursor() as cur:
        if subsection is None:
            cur.execute(
                "SELECT id FROM rows WHERE sheet_id=%s AND section=%s AND subsection IS NULL",
                (sheet_id, section),
            )
        else:
            cur.execute(
                "SELECT id FROM rows WHERE sheet_id=%s AND section=%s AND subsection=%s",
                (sheet_id, section, subsection),
            )
        r = cur.fetchone()
        return r[0] if r else None

def get_or_create_row_id(conn, sheet_id, section, subsection):
    rid = find_existing_row(conn, sheet_id, section, subsection)
    if rid:
        return rid
    ro = next_row_order(conn, sheet_id)
    with conn.cursor() as cur:
        if subsection is None:
            cur.execute(
                "INSERT INTO rows (sheet_id, section, subsection, row_order) VALUES (%s,%s,NULL,%s) RETURNING id",
                (sheet_id, section, ro),
            )
        else:
            cur.execute(
                "INSERT INTO rows (sheet_id, section, subsection, row_order) VALUES (%s,%s,%s,%s) RETURNING id",
                (sheet_id, section, subsection, ro),
            )
        rid = cur.fetchone()[0]
    return rid

def upsert_cell(conn, rid, day, task, hours, labor):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO day_cells (row_id, day, task, hours, labor_code)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (row_id, day)
            DO UPDATE SET task=EXCLUDED.task, hours=EXCLUDED.hours, labor_code=EXCLUDED.labor_code
            """,
            (rid, day, task, hours, labor),
        )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--sheet", required=True, type=int)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--debug-scan", action="store_true")
    ap.add_argument("--print-headers", action="store_true")
    ap.add_argument("--dump-names", type=int, default=0, help="Print first N names from the chosen label column")
    ap.add_argument("--name-col-index", type=int, default=None, help="Force label/section column index (0-based)")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "Set DATABASE_URL first, e.g.\n"
            "  set DATABASE_URL=postgresql://postgres:...@trolley.proxy.rlwy.net:31764/railway?sslmode=require"
        )

    # --- Read raw CSV as lists (more reliable than DictReader for blank headers)
    with open(args.csv, newline="", encoding="utf-8-sig", errors="ignore") as f:
        r = csv.reader(f)
        rows = list(r)

    if not rows:
        raise SystemExit("CSV appears empty.")

    header = [norm_spaces(x) for x in rows[0]]
    data   = rows[1:]

    # --- Map Day/Time/Labor columns by index
    day_cols, time_cols, labor_cols = {}, {}, {}
    for idx, h in enumerate(header):
        if not h:
            continue
        if DAY_RE.match(h):
            d = int(DAY_RE.match(h).group(1))
            day_cols[d] = idx
        elif TIME_RE.match(h):
            d = int(TIME_RE.match(h).group(1))
            time_cols[d] = idx
        elif LABOR_RE.match(h):
            d = int(LABOR_RE.match(h).group(1))
            labor_cols[d] = idx

    # --- Auto-detect label/section column if not forced
    name_col_idx = args.name_col_index
    if name_col_idx is None:
        # Look across first ~300 rows and count how many canonical matches to PRIMARY_SECTIONS
        limit = min(300, len(data))
        scores = {}
        for col in range(len(header)):
            hits = 0
            for i in range(limit):
                cell = norm_spaces(data[i][col] if col < len(data[i]) else "")
                if is_section_label(cell):
                    hits += 1
            scores[col] = hits
        # pick column with max hits (ties -> smaller index)
        name_col_idx = max(scores, key=scores.get) if scores else 0

    if args.print_headers:
        print("header columns:")
        for i, h in enumerate(header):
            print(f"  [{i}] {repr(h)}")
        print(f"\nChosen label/section column index: {name_col_idx}")
        if not day_cols:
            print("\n!! No 'Day N' columns recognized.")
        print("\nday/time/labor columns discovered:")
        for d in sorted(day_cols):
            print(f"  Day {d}: day_idx={day_cols[d]}, time_idx={time_cols.get(d)}, labor_idx={labor_cols.get(d)}")
        return

    if args.dump_names:
        print(f"Dumping first {args.dump_names} names from column {name_col_idx}:")
        n = min(args.dump_names, len(data))
        for i in range(n):
            raw = norm_spaces(data[i][name_col_idx] if name_col_idx < len(data[i]) else "")
            print(f"[{i}] {repr(raw)} -> {canon(raw)}")
        return

    conn = psycopg2.connect(dsn)
    conn.autocommit = False

    total_rows = len(data)
    section_rows_seen = 0
    data_rows_seen = 0
    cells_detected = 0
    sections_found = set()

    current_section = None
    single_row_id = None

    try:
        for ridx, row in enumerate(data, start=1):
            name = norm_spaces(row[name_col_idx] if name_col_idx < len(row) else "")

            if is_section_label(name):
                # normalize to canonical casing from our list
                c = canon(name)
                for s in PRIMARY_SECTIONS:
                    if canon(s) == c:
                        current_section = s
                        break
                sections_found.add(current_section)
                section_rows_seen += 1
                single_row_id = None
                if current_section in ("Roof", "Staffing expenses"):
                    single_row_id = get_or_create_row_id(conn, args.sheet, current_section, None)
                if args.debug_scan:
                    print(f"[SECTION] -> {current_section!r} (from {repr(name)})")
                continue

            if not current_section:
                continue

            # choose subsection / row id
            if current_section in ("Roof", "Staffing expenses"):
                rid = single_row_id
                subsection = None
                label = f"{current_section} (single)"
            else:
                if not name:
                    continue
                subsection = name
                rid = get_or_create_row_id(conn, args.sheet, current_section, subsection)
                data_rows_seen += 1
                label = f"{current_section} / {subsection}"

            # days
            for d in sorted(day_cols):
                d_idx = day_cols[d]
                t_idx = time_cols.get(d)
                l_idx = labor_cols.get(d)

                task  = norm_spaces(row[d_idx] if d_idx < len(row) else "")
                hours = parse_float(row[t_idx]) if t_idx is not None and t_idx < len(row) else None
                labor = norm_spaces(row[l_idx]) if l_idx is not None and l_idx < len(row) else None

                if task or hours is not None or labor:
                    if args.debug_scan:
                        print(f"[{rid}] {label} -> day {d}: task={task!r} hrs={hours} labor={labor!r}")
                    cells_detected += 1
                    if not args.dry:
                        upsert_cell(conn, rid, d, task, hours, labor)

        if args.dry:
            conn.rollback()
        else:
            conn.commit()

    finally:
        conn.close()

    print(f"Scanned rows: {total_rows}")
    print(f"Section header rows seen: {section_rows_seen} -> {sorted(sections_found) or 'NONE'}")
    print(f"Data rows seen (non-single sections): {data_rows_seen}")
    if not day_cols:
        print("!! No 'Day N' columns recognized — cannot write any cells.")
    if not sections_found:
        print("!! No section headers recognized — check which column actually contains them (use --print-headers / --dump-names).")
    if args.dry:
        print(f"DRY RUN: would upsert {cells_detected} day-cells")
    else:
        print(f"Done. Upserted {cells_detected} day-cells.")
if __name__ == "__main__":
    main()
