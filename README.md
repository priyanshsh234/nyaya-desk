# Nyaya Desk: eCourts Case Scraper and Legal Draft Generator

A full-stack app with a **FastAPI** (Python) backend and a **React** (Vite) frontend.

1. **Case Search** reproduces the eCourts District Court portal's request flow in Python. It searches by **CNR** or by **case number** (State → District → Court Complex → Establishment → Case Type → Number → Year) and returns everything the portal shows as structured JSON:
   - case details, filing and registration info
   - current status
   - parties and advocates
   - acts
   - hearing history
   - orders and judgments, with PDF links
2. **Draft Studio** is a rule-based legal draft generator written in pure Python, with no LLMs and no external APIs. It produces a legal notice, a plaint for recovery of money (civil, commercial or Order XXXVII), a regular bail application under the BNSS, and a general affidavit. Each draft has a live preview, and you can download it as `.docx`, copy it, or print it.

---

## Quick start (local)

**Prerequisites:** Python 3.11+ (tested on 3.14) and Node.js 18+ (tested on 22).

### 1. Backend (FastAPI)

```bash
cd backend
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API runs at http://127.0.0.1:8000, with interactive docs at http://127.0.0.1:8000/docs.

### 2. Frontend (React + Vite)

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5174. Vite proxies `/api` to the backend on :8000, so no CORS setup is needed.

### Single-process mode (how it is deployed)

```bash
cd frontend && npm run build      # creates frontend/dist
cd ../backend && uvicorn app.main:app --port 8000
```

When `frontend/dist` exists, FastAPI serves the UI itself at http://127.0.0.1:8000. That makes the whole app one web service with no separate static host.

### Tests

```bash
cd backend
pip install -r requirements-dev.txt   # adds pytest + httpx
python -m pytest -q
```

The tests cover:
- the parser, run against a real portal response for CNR `DLND020000602007`
- the client's token-rotation and error protocol, using a fake transport
- the draft engine: Indian number-to-words, grammar, limitation and custody calculations, and `.docx` output

### Deploying the backend to Render (free tier)

The repo includes a Render Blueprint, [`render.yaml`](render.yaml).

1. Open the Render dashboard → **New** → **Blueprint**, connect GitHub, and pick this repo.
2. Click **Apply**. Render will build `backend/` with `pip install -r requirements.txt` and start it with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Check that it's up at `https://<service>.onrender.com/api/health`; it should return `{"status":"ok"}`.

The free tier sleeps after about 15 minutes idle, so the first request after that takes around 30–60 seconds. In-memory portal sessions are also lost when it sleeps, and the UI recovers by starting a new session.

---

## How the scraper works

The request flow was reverse-engineered from the browser's DevTools Network tab and from the portal's own JavaScript (`js/components.js` → `ajaxCall`, `js/common_header.js`, `js/searchByCNR.js`, `js/searchByCaseStatus.js`).

| Step | Request | Notes |
|---|---|---|
| Bootstrap | `GET ?p=casestatus/index` | Sets the `SERVICES_SESSID` and `JSESSION` cookies. The first `app_token` comes from a hidden `<input id="app_token">` on this page. |
| Every AJAX call | `POST ?p=<controller/action>` with `…&ajax_req=true&app_token=<t>` | Every JSON response returns a **new** `app_token`, which must be sent with the next call. |
| Captcha | `GET vendor/securimage/securimage_show.php?<rand>` | The answer is stored in the PHP session, so the image must be fetched with the same cookies as the search. |
| CNR search | `POST cnr_status/searchByCNR/` with `cino`, `fcaptcha_code` | `status:0` means a wrong captcha. `casetype_list` holds the case HTML. |
| Dropdowns | `fillDistrict` → `fillcomplex` → `fillCourtEstablishment` → `set_data` → `fillCaseType` | Each complex value packs three things: `code@establishments@flag`. Flag `Y` means an establishment is mandatory. |
| Case number search | `POST casestatus/submitCaseNo` | Returns a result list. Each row has `viewHistory(...)` arguments. |
| Case details | `POST home/viewHistory` | No captcha is required for the drill-down. |
| Order PDF | `POST home/display_pdf` → `{order: "reports/x.pdf"}`, then `GET` that path | Must use the same session. |
| Hearing business | `POST home/viewBusiness` | Fetched only when the user expands a hearing. |

### Captcha policy (deliberate)

The scraper **never solves captchas automatically**. The backend proxies the portal's captcha image for the user's live session, the **user types the answer**, and the backend replays every other request. This respects the portal's anti-automation control. It is also more reliable than OCR, because each failed attempt burns the session's captcha.

### Backend layout

```
backend/app/
  main.py               FastAPI app, error handler, serves the built frontend
  config.py             env-var configuration (timeouts, TTLs, CORS, debug dumps)
  ecourts/
    client.py           EcourtsClient: replays the portal flow, token rotation
    parser.py           HTML -> structured dicts (tolerant, class-then-heading rules)
    store.py            in-memory session registry with TTL and size cap
    errors.py           typed errors -> precise HTTP statuses
  drafts/
    engine.py           field schema, validation, block-based document model
    templates.py        the four templates (plain Python functions)
    textutils.py        Indian-system amounts, dates, legal grammar helpers
    render.py           plain text and .docx renderers
  routers/              HTTP endpoints for both tools
```

### API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ecourts/sessions` | Start a portal session. Returns `session_id` and the state list. |
| GET | `/api/ecourts/sessions/{sid}/captcha` | Captcha PNG for this session |
| GET | `/api/ecourts/sessions/{sid}/districts?state_code=` | District dropdown |
| GET | `…/complexes`, `…/establishments`, `…/case-types` | Remaining dropdowns |
| POST | `/api/ecourts/sessions/{sid}/search/cnr` | `{cnr, captcha}` → full case JSON |
| POST | `/api/ecourts/sessions/{sid}/search/case-number` | Returns a list of matches |
| GET | `/api/ecourts/sessions/{sid}/cases/{ref}` | Full case JSON for one match |
| GET | `/api/ecourts/sessions/{sid}/orders/{ref}` | Order or judgment PDF |
| GET | `/api/ecourts/sessions/{sid}/business/{ref}` | What happened on a hearing date |
| GET | `/api/drafts/templates` | Templates and their field schemas (the UI builds its form from this) |
| POST | `/api/drafts/{template_id}` | Returns the draft as blocks, plain text, and warnings |
| POST | `/api/drafts/{template_id}/docx` | Returns a Word document |

### Example case JSON (abridged)

```json
{
  "source": {"portal": "eCourts District Courts", "search_type": "cnr", "cnr": "DLND020000602007"},
  "fetched_at": "2026-10-27T10:15:00+00:00",
  "case": {
    "court_name": "Chief Metropolitan Magistrate, New Delhi, PHC",
    "title": "STATE vs MOHINDER PAL SINGH ETC (2), JASWINDER SINGH",
    "case_details": {"case_type": "Cr Cases - CRIMINAL CASE", "filing_number": "72464/2007",
                     "filing_date": "18-09-2007", "registration_number": "39932/2016",
                     "registration_date": "18-09-2007", "cnr_number": "DLND020000602007"},
    "case_status": {"first_hearing_date": "25th February 2008", "next_hearing_date": "27th October 2026",
                    "case_stage": "Prosecution Evidence",
                    "court_number_and_judge": "39-Judicial Magistrate First Class (Mahila Court-01)"},
    "petitioners": [{"name": "STATE", "advocate": "", "details": ""}],
    "respondents": [{"name": "MOHINDER PAL SINGH ETC (2)"}, {"name": "JASWINDER SINGH"}],
    "acts": [], "hearing_history": [], "orders": [],
    "fir_details": {}, "subordinate_court": {}, "ia_status": [], "transfers": [], "other_sections": []
  }
}
```

---

## Design decisions and trade-offs

**Scraper**
- **One `EcourtsClient` per user search, held server-side.** The captcha answer lives in the portal's PHP session and the token rotates on every call, so the process that shows the captcha must be the one that submits the search. Each client has a lock, because two concurrent requests with the same token would fail.
- **In-memory session store (TTL 15 minutes, capped at 500 sessions).** It is simple, and portal sessions are short-lived anyway. The trade-off is that sessions don't survive a restart and don't share across worker processes. Scaling out would mean moving this to Redis with sticky routing.
- **Tolerant parser.** Sections are classified by the portal's semantic CSS classes first (`case_details_table`, `history_table`, …), then by nearby heading text. Anything unrecognised still lands in `other_sections` rather than being dropped. Two edge cases came from real portal data:
  - Parties are rendered as `<ul>` lists, not tables.
  - Bootstrap's `table-bordered`/`border` classes contain the substring "order", so only underscore-style class names are matched.
- **Opaque references for follow-ups.** Order PDF and hearing-detail arguments are stored server-side, and the client gets a short `ref`. This keeps URLs short and stops callers from injecting arbitrary parameters into requests made with a session.
- **Fail fast before spending a captcha.** The backend validates CNR format (4 letters + 12 digits, normalising spaces, dashes and case) and the "establishment required" rule before calling the portal.
- **Typed errors map to precise HTTP statuses:** 422 for a wrong captcha, 404 for not found, 440 for an expired session, 503 for the portal being down. The UI reacts to each one: it refreshes the captcha, or silently starts a new session, and so on.
- **`ECOURTS_DEBUG_DUMP_DIR`** saves every raw portal response, which makes re-tuning the parser easy if the portal's markup changes.

**Draft generator**
- **Schema-driven.** Each template declares its fields once. The same schema drives backend validation and the dynamically rendered React form, so adding a template is Python-only.
- **Block-based output.** A template emits typed blocks (title, numbered paragraph, prayer, signature…). The on-screen paper, the plain text and the `.docx` are all pure functions of those blocks, so they can't drift apart.
- **Templates as Python, not Jinja.** Legal prose is full of conditionals: singular or plural parties, optional paragraphs, computed periods. That reads more clearly as code than as `{% if %}` blocks.
- **Indian drafting conventions:**
  - amounts in the lakh/crore system (`Rs. 8,85,000/- (Rupees Eight Lakh Eighty Five Thousand Only)`)
  - verification dates written as "27th day of October, 2026"
  - party labels that agree in number ("Defendants are… jointly and severally")
  - criminal provisions cited from the **BNSS, 2023**
- **Warnings instead of silent assumptions.** The generator flags a likely time-barred suit (more than 3 years since the cause of action), possible **default bail** under S.187(3) BNSS (custody over 60 days with no charge-sheet), the Statement of Truth requirement for commercial suits, and similar issues. Facts it cannot know are left as visible blanks (`________`).

---

## Known limitations

- Hearing-business details and order PDFs are tied to the portal session that found them. Links stop working after about 15 minutes of inactivity, so you need to search again.
- The parser was built from the portal's JS and a real CNR response. If eCourts changes its markup, set `ECOURTS_DEBUG_DUMP_DIR` to capture the new responses for re-tuning.
- eCourts may rate-limit or block traffic from some cloud hosting IP ranges. If the hosted app can't reach the portal, run it locally.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `ECOURTS_BASE_URL` | `https://services.ecourts.gov.in/ecourtindia_v6/` | Portal base URL |
| `ECOURTS_TIMEOUT` | `45` | Upstream timeout in seconds |
| `SESSION_TTL_SECONDS` | `900` | Idle session lifetime |
| `MAX_SESSIONS` | `500` | Session cap |
| `ECOURTS_DEBUG_DUMP_DIR` | *(off)* | Directory for raw portal responses |
| `CORS_ORIGINS` | `*` | Allowed origins, comma-separated |
| `VITE_API_BASE` (frontend build) | *(empty)* | Only needed if the frontend is hosted separately from the API |
