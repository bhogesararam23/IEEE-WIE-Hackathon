# HerMediSafe

Medicine safety for women's health — prescription reconciliation, duplicate and
interaction detection, dose reminders, and a clinician-ready report. Built for the
IEEE WIE ILS 2026 hackathon.

Two apps, one REST contract:

| Directory | What it is | Stack |
|---|---|---|
| [`backend/`](backend) | HerMediSafe API — auth, profiles, prescriptions, OCR handoff, reconciliation, DDI alerts, reminders, PDF reports, audit trail | FastAPI + SQLAlchemy (async) + PostgreSQL + Alembic |
| [`frontend/`](frontend) | The product UI, wired to the API | React 19 + Vite 8 + TypeScript |

The API contract both sides follow lives in
[`backend/API_CONTRACT.md`](backend/API_CONTRACT.md); live Swagger is at
`http://localhost:8010/docs`.

## Quick start

```bash
# 1. Database
cd backend && docker compose up -d db

# 2. API  (Python 3.12; .env already points at the compose database)
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python.exe seed_demo.py          # migrate + create the demo accounts
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8010

# 3. Web app, in a second terminal
cd ../frontend && cp .env.example .env && pnpm install && pnpm dev
```

Open the printed Vite URL (default <http://localhost:5173>).

**Demo accounts** (created by `seed_demo.py`, password `DemoUser123!`):

- `demo_pregnant@hermedisafe.org` — pregnant, trimester 2, one HIGH severity
  interaction alert (Ciprofloxacin + Moxifloxacin).
- `demo_breastfeeding@hermedisafe.org` — breastfeeding, a suspected duplicate pair
  (Crocin 500 + Dolo 650) plus a Paracetamol + Aspirin alert.

## Ports

The API runs on **8010**, not the documented 8000, because port 8000 is already taken
on the machine this was developed on. Change it in `backend/.env` (`API_PORT` for
compose), `frontend/.env` (`VITE_API_BASE_URL`), and `frontend/vite.config.ts` stays
out of it — the browser talks to the API directly and the backend sends
`Access-Control-Allow-Origin: *`.

Fully containerised alternative: `docker compose up --build` starts Postgres and the
API together on 8000, then point `VITE_API_BASE_URL` at it.

## Tests

```bash
cd backend && .venv/Scripts/python.exe -m pytest      # 168 tests
cd frontend && pnpm typecheck                          # tsc --noEmit
```

`pytest` provisions its own `hermedisafe_test` database, migrates it, and truncates
that one between cases — so running the suite never touches the seeded demo data you
are about to present.

## What is real, and what is still a prototype

Wired to the API: sign up / sign in (with DPDP consent stamping), health context
profile, prescription upload and extraction, medicine list with confirm/reject,
duplicate resolution, interaction checks and evidence, reminders (with real
browser notifications while the tab is open), the medication summary and its
PDF download, the audit trail, and **Ask HerMedi AI** — a grounded chat
endpoint (`POST /assistant/ask`, see `backend/API_CONTRACT.md`) that answers
over the caller's own profile, confirmed medicines, and active alerts using
Gemini, falling back to Groq if Gemini is unreachable, with an optional Hindi
translation of the answer. Confirmed medicines also carry a `jan_aushadhi`
field naming a cheaper government generic-equivalent when one is known. All of
Gemini/Groq/MyMemory are free-tier APIs; see `backend/.env.example` for where
to get keys.

Design prototype only, labelled as such in the UI: **Cycle tracker** — the API
has no endpoints for it.

## Known limitations

- Drug interactions are matched against a static dataset
  (`backend/app/data/mock_interactions.csv`) behind one loader; see
  `backend/README.md`.
- Uploaded prescriptions are served from an **unauthenticated** `/files` mount. Fine
  for demo data, not for real patient records.
- `SECRET_KEY` is still the development default. Generate one before deploying.
- Ask HerMedi AI answers are not persisted, only audited (that a question was
  asked, not its content). It has no memory across turns yet.
