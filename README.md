# Contact Discovery Tool

Standalone CLI for discovering **verified direct planning-related contacts** at local governments (population 20,000–100,000).

This tool is **not** limited to "Planning Directors." It uses a **role-family search strategy** to find the highest-ranking planning-related contact with a verified direct individual email across varying organizational structures.

## Role families

| Family | Example titles |
|--------|----------------|
| Planning leadership | Director of Planning, Planning Director, Planning Manager |
| Community development | Community Development Director, Director of Community Development |
| Development services | Development Services Director |
| Land use / growth | Director of Land Use, Land Use Director, Growth Management Director |
| Planning & zoning | Planning & Zoning Director, Planning and Zoning Director |
| County planning | County Planning Director, County Planner |
| Professional planner / admin | Town Planner, Planning Administrator, Zoning Administrator, Long Range Planning Manager |

## Title allowlist & rank selection

When multiple qualifying contacts are found on a page, the tool selects **one** contact using rank tiers:

1. **Director** (any allowlisted title containing "Director")
2. **Manager** (Planning Manager, Long Range Planning Manager)
3. **Administrator / Planner** (Planning Administrator, Zoning Administrator, County Planner, Town Planner)

## Direct email rule

Only **direct individual emails** enter the outreach list. Generic accounts are rejected:

`planning@`, `info@`, `zoning@`, `communitydevelopment@`, `admin@`, `department@`, `clerk@`, `office@`, etc.

## Workflow

1. **Run discovery** — generates `data/prospects_working.csv` (all contacts default to `review_status=pending`)
2. **Manual review** — verify name, title, email against `email_source_url`; set `review_status=approved`
3. **Export** — `build --export-only` writes `data/outreach.csv` with approved contacts only

**No contact is auto-approved.**

## Setup

```powershell
cd C:\Users\Joseph\Desktop\Contacts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Add CENSUS_API_KEY from https://api.census.gov/data/key_signup.html
```

## Commands

```powershell
# Full discovery (13 states)
python src/run.py build --states CT,DE,FL,GA,MI,MT,OR,PA,RI,VT,VA,WA,WI --min-pop 20000 --max-pop 100000

# Suggested first test (small states)
python src/run.py build --states RI,VT,DE --min-pop 20000 --max-pop 100000 --limit 10

# After manual review
python src/run.py build --export-only

# Tests
python -m pytest tests/ -v
```

## Outputs

| File | Purpose |
|------|---------|
| `data/prospects_working.csv` | All discovered contacts + metadata; manual review |
| `data/prospects_rejected.csv` | Jurisdictions without direct email |
| `data/outreach.csv` | Approved contacts only (6 columns incl. `email_source_url`) |

## Search strategy

Tiered role-family queries (not "Planning Director" only):

- **Tier 1:** `planning department`, `planning staff` (or county equivalents)
- **Tier 2:** title-specific queries across community development, land use, growth management, etc.

PDFs linked from planning pages (staff directories, agenda packets) are scanned automatically via `pdfplumber`.

## Compliance

- Public web sources only
- Respects `robots.txt`
- No CAPTCHA/login bypass, LinkedIn, or restricted directories

## Known limitations

- Many sites use contact forms instead of direct emails (~40–60% may lack direct email)
- Image-only/scanned PDFs are skipped (no OCR)
- Search rate limits may require re-running with `--force-refresh` on failed rows
- Census place names may differ from common/local names
