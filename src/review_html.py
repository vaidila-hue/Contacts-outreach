"""Generate local read-only HTML review table from prospects_working.csv."""

from __future__ import annotations

import html
import json
from pathlib import Path

from src.paths import REVIEW_HTML, WORKING_COLUMNS

INSTRUCTIONS = (
    "Open this file after each build to review contacts. "
    "See harvest_diagnostics.csv for per-jurisdiction crawl/extraction details. "
    "When satisfied, edit prospects_working.csv to set review_status=approved, "
    "then run: python src/run.py build --export-only"
)

DISPLAY_COLUMNS = [
    "state",
    "jurisdiction_name",
    "geography_type",
    "population",
    "contact_name",
    "contact_title",
    "email",
    "email_source_url",
    "discovery_method",
    "notes",
]


def write_review_html(rows: list[dict[str, str]], path: Path | None = None) -> None:
    path = path or REVIEW_HTML
    path.parent.mkdir(parents=True, exist_ok=True)

    safe_rows = []
    for row in rows:
        if row.get("jurisdiction_match_status") == "mismatch":
            continue
        display = {col: row.get(col, "") for col in DISPLAY_COLUMNS}
        if not display.get("notes") and row.get("jurisdiction_match_notes"):
            display["notes"] = row["jurisdiction_match_notes"]
        safe_rows.append(display)

    data_json = json.dumps(safe_rows, ensure_ascii=False)
    cols_json = json.dumps(DISPLAY_COLUMNS)

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Contacts Review</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 1.5rem; color: #1a1a1a; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .instructions {{ background: #f0f4ff; border: 1px solid #c5d4ff; padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1rem; }}
    .toolbar {{ margin-bottom: 1rem; display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f5f5f5; cursor: pointer; position: sticky; top: 0; }}
    tr.has-notes {{ background: #fff8e1; }}
    tr:hover {{ filter: brightness(0.97); }}
    a {{ color: #1565c0; }}
    .count {{ color: #555; }}
  </style>
</head>
<body>
  <h1>Contacts Review</h1>
  <p class="instructions">{html.escape(INSTRUCTIONS)}</p>
  <div class="toolbar">
    <label>Filter state
      <select id="filterState"><option value="">All</option></select>
    </label>
    <label>Filter geography
      <select id="filterGeo">
        <option value="">All</option>
        <option value="city">city</option>
        <option value="town">town</option>
        <option value="village">village</option>
        <option value="borough">borough</option>
        <option value="township">township</option>
        <option value="county">county</option>
      </select>
    </label>
    <label>Search <input type="search" id="searchBox" placeholder="jurisdiction, email…"></label>
    <span class="count" id="rowCount"></span>
  </div>
  <table id="reviewTable">
    <thead><tr id="headerRow"></tr></thead>
    <tbody id="bodyRows"></tbody>
  </table>
  <script>
    const ROWS = {data_json};
    const COLS = {cols_json};

    function rowClass(row) {{
      return row.notes ? "has-notes" : "";
    }}

    function sortRows(rows) {{
      return [...rows].sort((a, b) => {{
        if (a.state !== b.state) return a.state.localeCompare(b.state);
        const pa = parseInt(a.population || "0", 10);
        const pb = parseInt(b.population || "0", 10);
        if (pa !== pb) return pb - pa;
        return a.jurisdiction_name.localeCompare(b.jurisdiction_name);
      }});
    }}

    function cellHtml(col, val) {{
      if (col === "email_source_url" && val) {{
        const esc = val.replace(/"/g, "&quot;");
        return `<a href="${{esc}}" target="_blank" rel="noopener">${{esc}}</a>`;
      }}
      return (val || "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
    }}

    function render() {{
      const state = document.getElementById("filterState").value;
      const geo = document.getElementById("filterGeo").value;
      const q = document.getElementById("searchBox").value.toLowerCase();
      let filtered = ROWS.filter(r => {{
        if (state && r.state !== state) return false;
        if (geo && r.geography_type !== geo) return false;
        if (q) {{
          const hay = COLS.map(c => r[c] || "").join(" ").toLowerCase();
          if (!hay.includes(q)) return false;
        }}
        return true;
      }});
      filtered = sortRows(filtered);
      document.getElementById("rowCount").textContent = filtered.length + " contact(s)";
      const tbody = document.getElementById("bodyRows");
      tbody.innerHTML = "";
      for (const row of filtered) {{
        const tr = document.createElement("tr");
        tr.className = rowClass(row);
        for (const col of COLS) {{
          const td = document.createElement("td");
          td.innerHTML = cellHtml(col, row[col] || "");
          tr.appendChild(td);
        }}
        tbody.appendChild(tr);
      }}
    }}

    const states = [...new Set(ROWS.map(r => r.state).filter(Boolean))].sort();
    const stateSel = document.getElementById("filterState");
    for (const st of states) {{
      const opt = document.createElement("option");
      opt.value = st;
      opt.textContent = st;
      stateSel.appendChild(opt);
    }}

    const header = document.getElementById("headerRow");
    for (const col of COLS) {{
      const th = document.createElement("th");
      th.textContent = col;
      header.appendChild(th);
    }}
    ["filterState", "filterGeo", "searchBox"].forEach(id => {{
      document.getElementById(id).addEventListener("input", render);
      document.getElementById(id).addEventListener("change", render);
    }});
    render();
  </script>
</body>
</html>
"""
    path.write_text(content, encoding="utf-8")
