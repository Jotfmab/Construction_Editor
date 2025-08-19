import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { ColDef, CellValueChangedEvent } from "ag-grid-community";
import { api } from "../src/lib/api";

// AG Grid (CSR only)
const AgGridReact = dynamic(
  () => import("ag-grid-react").then((m) => m.AgGridReact),
  { ssr: false }
);

type BlockRow = {
  row_id: number;
  subsection: string;
  [key: string]: any; // day_X_task, day_X_time, day_X_labor
};

export default function Home() {
  // --------- selectors ----------
  const [sheets, setSheets] = useState<{ id: number; name: string }[]>([]);
  const [sheetId, setSheetId] = useState<number | null>(null);

  const [sections, setSections] = useState<string[]>([]);
  const [section, setSection] = useState<string>("");

  const [subsections, setSubsections] = useState<string[]>([]);
  const [subsection, setSubsection] = useState<string>("");

  // multi-subsection support
  const [multi, setMulti] = useState<boolean>(false);
  const [selectedSubs, setSelectedSubs] = useState<string[]>([]);

  // day range (with guards while typing)
  const [startDay, setStartDay] = useState<number>(1);
  const [endDay, setEndDay] = useState<number>(14);

  // --------- grid ----------
  const [rows, setRows] = useState<BlockRow[]>([]);
  const [changed, setChanged] = useState<Map<string, any>>(new Map());
  const gridRef = useRef<any>(null);

  // ---------- bootstrap ----------
  useEffect(() => {
    api.get("/sheets").then((r) => {
      setSheets(r.data || []);
      if (r.data?.length) setSheetId(r.data[0].id);
    });
  }, []);

  useEffect(() => {
    if (!sheetId) return;
    api.get("/sections", { params: { sheet_id: sheetId } }).then((r) => {
      setSections(r.data || []);
      setSection(r.data?.[0] || "");
    });
  }, [sheetId]);

  useEffect(() => {
    if (!sheetId || !section) return;
    api
      .get("/subsections", { params: { sheet_id: sheetId, section } })
      .then((r) => {
        setSubsections(r.data || []);
        const first = r.data?.[0] || "";
        setSubsection(first);
        setSelectedSubs(first ? [first] : []);
      });
  }, [sheetId, section]);

  // ---------- helpers ----------
  const validRange = useMemo(() => {
    // don’t query while the user is mid-typing a bad value
    return (
      Number.isFinite(startDay) &&
      Number.isFinite(endDay) &&
      startDay >= 1 &&
      endDay >= startDay
    );
  }, [startDay, endDay]);

  const fetchBlock = async (oneSub: string) => {
    const { data } = await api.get("/block", {
      params: {
        sheet_id: sheetId!,
        section,
        subsection: oneSub,
        start_day: startDay,
        end_day: endDay,
      },
    });
    return (data?.rows as BlockRow[]) || [];
  };

  const loadBlock = useCallback(async () => {
    if (!sheetId || !section) return;
    if (!validRange) return; // wait until inputs are valid

    try {
      setChanged(new Map());
      if (multi) {
        const subs = selectedSubs.length ? selectedSubs : (subsection ? [subsection] : []);
        const lists = await Promise.all(subs.map((s) => fetchBlock(s)));
        // merge
        const merged: Record<number, BlockRow> = {};
        for (const list of lists) {
          for (const r of list) merged[r.row_id] = r;
        }
        setRows(Object.values(merged));
      } else {
        const list = await fetchBlock(subsection);
        setRows(list);
      }
    } catch (err: any) {
      alert(
        `Failed to load rows.\nSection: ${section}\nSubsection: ${
          multi ? selectedSubs.join(", ") : subsection
        }\n\n${err?.response?.data ? JSON.stringify(err.response.data) : err}`
      );
    }
  }, [sheetId, section, subsection, multi, selectedSubs, startDay, endDay, validRange]);

  useEffect(() => {
    loadBlock();
  }, [loadBlock]);

  // ---------- grid columns ----------
  const columnDefs: ColDef[] = useMemo(() => {
    const cols: ColDef[] = [
      { headerName: "RowID", field: "row_id", width: 110, pinned: "left" },
      { headerName: "Subsection", field: "subsection", width: 220, pinned: "left" },
    ];
    const parseNumber = (v: any) => {
      if (v === "" || v == null) return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : v;
    };

    for (let d = startDay; d <= endDay; d++) {
      cols.push({ headerName: `Day ${d}`, field: `day_${d}_task`, editable: true, width: 200 });
      cols.push({
        headerName: `Time ${d}`,
        field: `day_${d}_time`,
        editable: true,
        width: 110,
        valueParser: (p) => parseNumber(p.newValue),
      });
      cols.push({ headerName: `Labor ${d}`, field: `day_${d}_labor`, editable: true, width: 120 });
    }
    return cols;
  }, [startDay, endDay]);

  // ---------- change capture ----------
  const onCellValueChanged = useCallback(
    (e: CellValueChangedEvent) => {
      const row = e.data as BlockRow;
      const field = e.colDef.field!;
      const m = field.match(/^day_(\d+)_(task|time|labor)$/);
      if (!m) return;

      const day = parseInt(m[1], 10);
      const kind = m[2] as "task" | "time" | "labor";
      const key = `${row.row_id}:${day}`;

      const prev =
        changed.get(key) ||
        { row_id: row.row_id, day, task: null, hours: null, labor_code: null };

      if (kind === "task") prev.task = e.newValue ?? null;
      if (kind === "time")
        prev.hours =
          e.newValue === "" || e.newValue == null ? null : Number(e.newValue);
      if (kind === "labor") prev.labor_code = e.newValue ?? null;

      const next = new Map(changed);
      next.set(key, prev);
      setChanged(next);
    },
    [changed]
  );

  const saveChanges = useCallback(async () => {
    // make sure the grid commits the current edit before we read the buffer
    gridRef.current?.api?.stopEditing();

    if (changed.size === 0) {
      alert("Nothing to save.");
      return;
    }
    const payload = { records: Array.from(changed.values()) };

    try {
      await api.post("/cells/bulk_upsert", payload);
      alert(`Saved ${payload.records.length} cells.`);
      await loadBlock();
    } catch (err: any) {
      alert(
        `Save failed.\n\n${
          err?.response?.data ? JSON.stringify(err.response.data) : String(err)
        }`
      );
    }
  }, [changed, loadBlock]);

  // ---------- render ----------
  return (
    <div style={{ padding: 16 }}>
      <h2>Construction Editor (FastAPI + Next.js)</h2>

      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        {/* Sheet */}
        <label>
          Sheet:&nbsp;
          <select value={sheetId ?? ""} onChange={(e) => setSheetId(Number(e.target.value))}>
            {sheets.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>

        {/* Section */}
        <label>
          Section:&nbsp;
          <select value={section} onChange={(e) => setSection(e.target.value)}>
            {sections.map((sec) => (
              <option key={sec} value={sec}>
                {sec}
              </option>
            ))}
          </select>
        </label>

        {/* Multi toggle */}
        <label>
          <input type="checkbox" checked={multi} onChange={(e) => setMulti(e.target.checked)} />{" "}
          Multi
        </label>

        {/* Subsection(s) */}
        {!multi ? (
          <label>
            Subsection:&nbsp;
            <select
              value={subsection}
              onChange={(e) => {
                setSubsection(e.target.value);
                setSelectedSubs([e.target.value]);
              }}
            >
              {subsections.map((ss) => (
                <option key={ss} value={ss}>
                  {ss}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label>
            Subsections:&nbsp;
            <select
              multiple
              size={Math.min(8, Math.max(3, subsections.length))}
              value={selectedSubs}
              onChange={(e) =>
                setSelectedSubs(Array.from(e.target.selectedOptions, (o) => o.value))
              }
            >
              {subsections.map((ss) => (
                <option key={ss} value={ss}>
                  {ss}
                </option>
              ))}
            </select>
            <span style={{ marginLeft: 6, opacity: 0.7 }}>
              (Ctrl/⌘-click to select multiple)
            </span>
          </label>
        )}

        {/* Day range (guarded) */}
        <label>
          Start day:&nbsp;
          <input
            type="number"
            min={1}
            value={startDay}
            onChange={(e) => setStartDay(Math.max(1, Number(e.target.value || 1)))}
            onBlur={() => {
              if (endDay < startDay) setEndDay(startDay);
            }}
          />
        </label>

        <label>
          End day:&nbsp;
          <input
            type="number"
            min={startDay}
            value={endDay}
            onChange={(e) => {
              const v = Number(e.target.value || startDay);
              setEndDay(Math.max(startDay, v));
            }}
          />
        </label>

        <button onClick={loadBlock}>Reload</button>
        <button
          onClick={saveChanges}
          style={{ background: "#2563eb", color: "white", padding: "6px 10px" }}
        >
          Save
        </button>
      </div>

      <div className="ag-theme-quartz" style={{ height: "70vh", marginTop: 12 }}>
        <AgGridReact
          ref={gridRef}
          rowData={rows}
          columnDefs={columnDefs}
          defaultColDef={{ resizable: true, sortable: true }}
          animateRows
          onCellValueChanged={onCellValueChanged}
          stopEditingWhenCellsLoseFocus
        />
      </div>
    </div>
  );
}
