# HerMediSafe — Backend

FastAPI + PostgreSQL backend for HerMediSafe. Provides authentication, maternal profile management, prescription OCR ingestion, medicine list review and normalization, duplicate drug detection, drug-drug interaction (DDI) safety checks, dose reminders, medication summary reporting (JSON + downloadable PDF), and append-only audit logging.

For the detailed request/response specification for every endpoint, see [**API_CONTRACT.md**](API_CONTRACT.md).

---

## Architecture & Features

- **Auth:** Password authentication with bcrypt and 24h JWT Bearer tokens.
- **Maternal Profile:** Pregnancy trimester and infant breastfeeding context tracking with validation rules.
- **Prescription & OCR:** Prescription upload (`multipart/form-data`) with real OCR ingestion (`POST /prescriptions/{id}/ocr-results`) and deterministic mock OCR (`POST /prescriptions/{id}/mock-ocr`).
- **Medicine Reconciliation:** Ingredient normalization using a fuzzy-matching Indian brand dataset (`indian_brand_ingredient_map.csv`), duplicate drug detection, and human review confirmation/rejection workflow.
- **DDI Safety Alerts:** Pairwise interaction checking against a mock DDI dataset (`mock_interactions.csv`). Severity-first sorting (HIGH, MODERATE, LOW). Integration endpoint for AI/RAG literature citation writer (`PATCH /alerts/{id}/evidence`).
- **Reminders:** Schedule dose reminders with time of day and frequency string.
- **Reporting:** Full JSON medication state summary and downloadable styled PDF report rendered with ReportLab (`GET /reports/medication-summary/pdf`).
- **Audit Logging:** Append-only user action trail recorded for all state mutations, safety checks, and report downloads.
- **Ask HerMedi AI:** Grounded Q&A (`POST /assistant/ask`) over the caller's profile, confirmed medicines, and active alerts, via Gemini with an automatic Groq fallback. Both free-tier; see `.env.example`.
- **Jan Aushadhi pricing:** Confirmed medicines carry a `jan_aushadhi` field showing a cheaper PMBJP generic-equivalent when one is known, via `app/services/jan_aushadhi.py`.
- **Soft Delete:** Enforced globally across all domain entities via a SQLAlchemy ORM event listener (`app/core/soft_delete.py`).

---

## Quick Start — Docker Compose (Recommended)

```bash
docker compose up --build -d
```

## Quick Start — native process + containerised Postgres

Used during development so the API hot-reloads without rebuilding an image:

```bash
docker compose up -d db                       # Postgres only
uv venv --python 3.12 .venv                   # or: python -m venv .venv
uv pip install --python .venv -r requirements.txt -r requirements-dev.txt
cp .env.example .env                          # already matches the compose credentials
.venv/Scripts/python.exe seed_demo.py         # migrate + reset + seed demo accounts
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8010
```

`.env` targets `localhost:5432`, which is where compose publishes the `db` service.
Port **8010** rather than 8000 because 8000 was already taken on the development
machine; the web app's `VITE_API_BASE_URL` expects it.

### Reset Database & Seed Demo Data
To wipe the database, run pending Alembic migrations, and seed demo accounts with realistic prescriptions, medicines, interaction alerts, and reminders for presentation/demo setup:

```bash
# Option 1: Via Docker Compose
docker compose exec app python seed_demo.py

# Option 2: Native python
python seed_demo.py
```

### Pre-populated Demo Users Created by Seed:
1. **Pregnant User:**
   - **Email:** `demo_pregnant@hermedisafe.org`
   - **Password:** `DemoUser123!`
   - **Context:** Pregnant, Trimester 2
   - **Data:** 1 uploaded prescription, 2 confirmed medicines (*Ciprofloxacin 500mg* + *Moxifloxacin 400mg*) which trigger a **HIGH severity** interaction alert, 1 reminder schedule.
2. **Breastfeeding User:**
   - **Email:** `demo_breastfeeding@hermedisafe.org`
   - **Password:** `DemoUser123!`
   - **Context:** Breastfeeding, Infant age 4 months
   - **Data:** 1 uploaded prescription, 3 confirmed medicines (*Crocin 500mg* + *Dolo 650* which flag as a **duplicate pair** + *Disprin 325*), 2 interaction alerts.

---

## API Documentation

- **Interactive Swagger UI:** <http://localhost:8010/docs>
- **ReDoc:** <http://localhost:8010/redoc>
- **Full API Specification:** See [**API_CONTRACT.md**](API_CONTRACT.md)

### Endpoint Overview

| Group | Method | Endpoint | Description |
|---|---|---|---|
| **Health** | `GET` | `/health` | Live service & Postgres check |
| **Auth** | `POST` | `/auth/signup` | Create account & return JWT |
| | `POST` | `/auth/login` | Log in & return JWT |
| **Profile** | `GET` | `/users/me` | Read caller's account & maternal profile |
| | `POST` | `/users/me/profile` | Create/update maternal profile |
| | `POST` | `/users/me/consent` | Stamp DPDP consent |
| | `DELETE` | `/users/me` | Soft-delete account |
| **Prescriptions** | `POST` | `/prescriptions/upload` | Upload image/PDF prescription |
| | `GET` | `/prescriptions` | List uploaded prescriptions |
| | `POST` | `/prescriptions/{id}/ocr-results` | **AI/OCR Handoff:** Ingest OCR extraction proposals |
| | `POST` | `/prescriptions/{id}/mock-ocr` | Deterministic fake OCR ingestion for dev/testing |
| **Medicines** | `GET` | `/medicines/pending-review` | Unconfirmed OCR proposals queue |
| | `GET` | `/medicines` | Confirmed/active medicines list |
| | `POST` | `/medicines` | Add manual medicine entry |
| | `PATCH` | `/medicines/{id}/confirm` | Confirm proposal, normalize ingredient & check dups |
| | `PATCH` | `/medicines/{id}/reject` | Dismiss unconfirmed proposal |
| **Duplicates** | `GET` | `/medicines/duplicates` | List suspected duplicate pairs |
| | `PATCH` | `/medicines/duplicates/{id}/resolve` | Resolve duplicate (`keep_both`, `merged`, `not_a_duplicate`) |
| **Alerts (DDI)** | `POST` | `/medicines/check-interactions` | Run DDI check over active confirmed medicines |
| | `GET` | `/alerts` | List alerts (sorted severity-first) |
| | `PATCH` | `/alerts/{id}/mark-reviewed` | Clinician mark reviewed |
| | `PATCH` | `/alerts/{id}/evidence` | **AI/RAG Handoff:** Attach source literature & citations |
| **Reminders** | `POST` | `/reminders` | Create dose reminder schedule |
| | `GET` | `/reminders` | List active reminders |
| | `PATCH` | `/reminders/{id}` | Update reminder time/frequency/active status |
| | `DELETE` | `/reminders/{id}` | Soft-delete reminder |
| **Reports** | `GET` | `/reports/medication-summary` | Full JSON medication state summary |
| | `GET` | `/reports/medication-summary/pdf` | Downloadable styled PDF report |
| **Audit Logs** | `GET` | `/audit-logs` | Paginated user audit trail, newest first |
| **Assistant** | `POST` | `/assistant/ask` | Ask HerMedi AI: grounded Q&A via Gemini, falling back to Groq |

---

## Running Pytest Suite

```bash
# Inside Docker container
docker compose exec app pytest

# Or natively
.venv/Scripts/python.exe -m pytest
```

168 tests. The suite provisions its own `hermedisafe_test` database on first run
(creating it and applying Alembic migrations) because the DB-backed tests `TRUNCATE`
every table between cases — pointing them at the development database would wipe the
seeded demo accounts. Override the name with `TEST_DATABASE_NAME`, and note that
`tests/conftest.py` rewrites `DATABASE_URL` for the whole run.

`scripts/e2e_verify.ps1` and `scripts/e2e_prescription.ps1` are curl-driven smoke
checks against a running server; edit the `$base` port at the top of each to match
wherever your API is listening.

---

## Known Limitations & Hackathon Considerations

1. **Mocked DDI Dataset:**
   Because no open-source, licensed DDI database API was available during the hackathon, drug-drug interactions are matched against a static seed dataset (`app/data/mock_interactions.csv`). The logic is isolated inside `app/services/interactions.py` behind `_load_interactions()`, so swapping in a real FDA/RxNorm API requires changing only that loader.
2. **SECRET_KEY Configuration:**
   Defaults to `dev-insecure-change-me` in local development. For staging/production, override `SECRET_KEY` in environment variables.
3. **Password Hashing / Passlib Migration:**
   Currently using `passlib[bcrypt]`. Python 3.12+ deprecated `spwd` module which generates soft warnings under `passlib`. Future work will migrate to direct `argon2-cffi` or `pyca/cryptography` password hashing.
4. **Curated Jan Aushadhi Dataset:**
   `app/data/jan_aushadhi_generics.csv` covers 6 ingredients (Paracetamol, Cetirizine, Pantoprazole, Amoxicillin, Azithromycin, Ciprofloxacin), priced from the government's published PMBJP product list — not the full ~2,110-product PMBJP catalogue, and not a live feed. A `null` `jan_aushadhi` field means "not in this demo dataset," not "unavailable at a real Jan Aushadhi Kendra." Same swap-the-loader pattern as the DDI dataset: `app/services/jan_aushadhi.py`'s `_load_generics()` is the one place to point at the live PMBI catalogue later.
5. **Hindi Translation via MyMemory:**
   `POST /assistant/ask` with `"language": "hi"` translates the answer through the free MyMemory API (`app/services/assistant.py`'s `_translate_to_hindi()`), which caps anonymous requests at 500 bytes and ~5,000 chars/day (no key) or ~50,000/day (with an email in the `de` param — not currently set). A translation failure falls back to the English chunk rather than erroring the request.
6. **Reminder Notifications Need the Tab Open:**
   `frontend/src/lib/notifications.ts` fires real browser `Notification`s by polling active reminders every 30s from an open tab — there is no service worker, Push API, or VAPID-backed push server, so a closed browser or backgrounded/killed tab will not notify. That's future work, not this build.
