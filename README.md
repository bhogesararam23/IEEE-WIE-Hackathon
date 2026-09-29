# HerMediSafe

Medicine safety for women's health — prescription reconciliation, duplicate and
interaction detection, dose reminders, a clinician-ready report, and a grounded
AI assistant.

Built by team **NOMOS** for IEEE WIE ILS 2026 (Track 2: HealthTech — Problem
Statement #4, *The Polypharmacy Crisis*).

We picked this problem because it's one almost every family has run into in
some form: a pregnant or breastfeeding woman ends up with prescriptions from
two or three different doctors, plus whatever she's bought over the counter,
and nobody in that chain has the full list in front of them at once. It's not
a hard problem to describe — it's a hard problem to actually fix without
turning it into something that pretends to diagnose or prescribe. That's the
line we tried to stay on the right side of throughout this build.

## The problem

Women often collect medicines from several disconnected sources — an
obstetrician, a general physician, a specialist, a pharmacy, and self-care
purchases — while pregnancy, pre-conception, or breastfeeding changes what is
actually safe to take together. Nobody along that chain sees the full list at
once.

The reconciliation gap is well documented, even where a single national
prevalence number is not: a Rajasthan tertiary-centre study found 1,545
medicines across 667 prescriptions for 246 pregnant women (2.32 medicines per
prescription); an AIIMS Rishikesh registry of 305 pregnancies recorded a mean
cumulative exposure of 6.32 medicines over the course of a pregnancy; and a
Mysuru hospital audit of 372 inpatients turned up 580 medication-list
discrepancies, including 345 confirmed drug interactions. This is a
communication and coordination failure, not a diagnosis problem — which is why
HerMediSafe stays firmly in the "reconcile and inform" lane rather than
attempting to prescribe, diagnose, or replace a clinician.

## The solution

The user builds a minimal profile (general, planning pregnancy, pregnant with
trimester, or breastfeeding with infant age), then uploads prescriptions as
images or PDFs. OCR proposes each medicine's name, strength, dose, frequency,
and duration — every extracted item is shown back to the user or pharmacist to
confirm or reject before it becomes part of the record. Confirmed medicines
are normalized from Indian brand names to a canonical ingredient, checked
against each other for duplicates and interactions, and enriched with a
cheaper Jan Aushadhi generic when one exists.

The design principle is **evidence before explanation**: deterministic rules
own severity and duplicate detection, and the AI layer is only ever used to
summarize what was already found in plain language (and, optionally, Hindi) —
never to invent an interaction or a recommendation on its own.

Two apps, one REST contract:

| Directory | What it is | Stack |
|---|---|---|
| [`backend/`](backend) | HerMediSafe API — auth (including Google Sign-In), profiles, prescriptions, OCR handoff, reconciliation, DDI alerts, reminders, Ask HerMedi AI, PDF reports, audit trail | FastAPI + SQLAlchemy (async) + PostgreSQL + Alembic |
| [`frontend/`](frontend) | The product UI, wired to the API | React 19 + Vite 8 + TypeScript |

The API contract both sides follow lives in
[`backend/API_CONTRACT.md`](backend/API_CONTRACT.md); live Swagger is at
`http://localhost:8010/docs` (or `https://hermedisafe-api.onrender.com/docs`
against the deployed API).

## Live deployment

| Piece | Where | Notes |
|---|---|---|
| **App** | <https://hermedisafe.pages.dev> | Cloudflare Pages, auto-deploys from `main` |
| **API** | <https://hermedisafe-api.onrender.com> | Render free tier — sleeps after ~15 min idle; the first request after that takes 30–60s to wake up |
| **Database** | Neon | Managed Postgres, TLS required (`DB_SSL_REQUIRE=True`) |

All three tiers are on genuinely free plans — no credit card was used anywhere
in this deployment. The live app takes real sign-ups only — create your own
account or use **Sign in with Google**; there are no demo/shared logins on
production.

## Features

- **Prescription intake** — upload an image/PDF, review OCR-extracted medicine
  proposals, confirm or reject each one.
- **Reconciliation** — brand names normalised to a canonical ingredient
  (`backend/app/data/indian_brand_ingredient_map.csv`, fuzzy-matched), so
  "Crocin 500mg" and "Dolo 650" both resolve to Paracetamol; duplicate
  detection runs on confirmed medicines.
- **Drug interaction (DDI) alerts** — pairwise check against a seed dataset,
  severity-sorted, with a professional-review flag.
- **Jan Aushadhi generic pricing** — confirmed medicines carry a
  `jan_aushadhi` field naming a cheaper PMBJP government generic when the
  ingredient is in the curated seed dataset (`backend/app/data/jan_aushadhi_generics.csv`).
- **Dose reminders** — schedule per medicine, with real browser
  `Notification`s while the tab is open (`frontend/src/lib/notifications.ts`).
- **Ask HerMedi AI** — grounded Q&A over the caller's own profile, confirmed
  medicines, and active alerts (`POST /assistant/ask`). Tries Gemini first,
  falls back to Groq automatically, and can answer in Hindi (translated via
  MyMemory, chunked to its request-size cap).
- **Google Sign-In** — alongside email/password, via Google Identity
  Services; the backend verifies the ID token itself (`POST /auth/google`)
  rather than trusting anything the client asserts.
- **Medication summary & PDF report** — clinician-ready, downloadable.
- **Audit trail** — every write, safety check, and report generation is
  logged and readable by the account that made it.

## Quick start (local)

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

Open the printed Vite URL (default <http://localhost:5173>, this project pins
5180 — see `frontend/vite.config.ts`).

**Optional, for the AI/Google features to work locally:** copy
`backend/.env.example` to `backend/.env` and fill in `GEMINI_API_KEY`,
`GROQ_API_KEY`, and `GOOGLE_CLIENT_ID` (all free — see the comments in that
file for exactly where to get each one), plus the matching
`VITE_GOOGLE_CLIENT_ID` in `frontend/.env`. Everything else works fine
without them; Ask HerMedi AI returns a 503 and the Google button simply
doesn't render until they're set.

**Demo accounts** (local only — created by `seed_demo.py` against your local
database, password `DemoUser123!`; production has no demo accounts, real
sign-ups only):

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
cd backend && .venv/Scripts/python.exe -m pytest      # 191 tests
cd frontend && pnpm typecheck                          # tsc --noEmit
```

`pytest` provisions its own `hermedisafe_test` database, migrates it, and truncates
that one between cases — so running the suite never touches the seeded demo data you
are about to present. Every network call to Gemini/Groq/MyMemory/Google is
monkeypatched in tests; nothing in the suite makes a real external request.

## Deploying this yourself

The live stack above is: Render (Docker build from `backend/Dockerfile`, via
`backend/start.sh` which runs `alembic upgrade head` before every start) +
Neon (managed Postgres) + Cloudflare Pages (static build of `frontend/`,
root directory `frontend`, build command `pnpm install && pnpm build`,
output directory `dist`). All three have real free tiers with no card.

To redeploy from scratch:

1. **Neon** — new project, copy its connection string, convert
   `postgresql://` → `postgresql+asyncpg://` and drop the `?sslmode=...`
   query string (handled instead by `DB_SSL_REQUIRE=True`).
2. **Render** — new Web Service from this repo, root directory `backend`,
   Docker runtime, Start Command `sh start.sh`, environment variables from
   `backend/.env.example` (at minimum `DATABASE_URL`, `DB_SSL_REQUIRE=True`,
   `SECRET_KEY` — generate with `openssl rand -hex 32`).
3. **Cloudflare Pages** — connect this repo, root directory `frontend`,
   env var `VITE_API_BASE_URL` pointing at the Render URL from step 2 (and
   `VITE_GOOGLE_CLIENT_ID` if you want Google Sign-In).
4. **Google Sign-In** (optional) — OAuth client ID from
   [Google Cloud Console](https://console.cloud.google.com) (APIs & Services
   → Credentials), Authorized JavaScript origins set to your Pages URL. To
   let *any* Google account sign in (not just ones you whitelist as test
   users), publish the OAuth consent screen to production — it needs an
   application home page, privacy policy, and terms of service URL, which is
   exactly what `frontend/public/privacy.html` and `terms.html` are for.
   Publishing doesn't trigger Google's manual review as long as you only
   request the default email/profile scopes (this app does).
5. Set the same `GOOGLE_CLIENT_ID` on Render as `VITE_GOOGLE_CLIENT_ID` on
   Cloudflare Pages — they must match exactly.

A free keep-alive ping (e.g. [UptimeRobot](https://uptimerobot.com) hitting
`/health` every 5 minutes) prevents Render's cold start during a live demo —
not required, but worth doing for the 30 minutes before you present.

## What is real, and what is still a prototype

Wired to the API: sign up / sign in (email+password or Google, with DPDP
consent stamping), health context profile, prescription upload and
extraction, medicine list with confirm/reject, duplicate resolution,
interaction checks and evidence, Jan Aushadhi generic pricing, reminders
(with real browser notifications while the tab is open), Ask HerMedi AI (see
above), the medication summary and its PDF download, and the audit trail.

Design prototype only, labelled as such in the UI: **Cycle tracker** — the API
has no endpoints for it.

## Known limitations

- Drug interactions are matched against a static dataset
  (`backend/app/data/mock_interactions.csv`) behind one loader; see
  `backend/README.md`.
- Jan Aushadhi pricing covers a curated set of 6 ingredients
  (`backend/app/data/jan_aushadhi_generics.csv`), not the full ~2,110-product
  PMBJP catalogue — a `null` `jan_aushadhi` field means "not in this demo
  dataset," not "unavailable at a real Jan Aushadhi Kendra."
- Uploaded prescriptions are served from an **unauthenticated** `/files` mount. Fine
  for demo data, not for real patient records.
- Reminder notifications only fire while the browser tab is open — there is
  no service worker or push server (yet), so a closed tab means no
  notification.
- Ask HerMedi AI answers are not persisted, only audited (that a question was
  asked, not its content). It has no memory across turns yet.
- `backend/.env`'s `SECRET_KEY` is still the insecure local-dev default —
  only Render's copy (a real `openssl rand -hex 32` value) is production-grade.
  `.env` files are gitignored throughout, so none of this is in git history,
  but generate your own values if you fork this project.

## Selected references

The problem framing above draws on:

- Saurabh S, Kumar R, Maharshi RP. *Evaluation of Medicine Exposure During
  Pregnancy at a Tertiary Center of an Indian State.* Maedica, 2020.
- Choudhary V et al. *Drug Related Adverse Pregnancy Outcomes at a Tertiary
  Care Hospital from the Foothills of the Himalayas.* J Family Med Prim Care,
  2021.
- Syju K et al. *Medication Reconciliation Practices in Two Multispeciality
  Hospitals.* Indian J Pharm Educ Res, 2023.
- Anand A et al. *Prevalence of Polypharmacy in Pregnancy: A Systematic
  Review.* BMJ Open, 2023.

---

This is Team NOMOS's submission for Round 2 — the "What is real, and what is
still a prototype" section above is not a formality, we mean it literally.
Everything listed as wired to the API is live on the deployment linked at the
top of this file, right now, and you're welcome to sign up and try it
yourself instead of taking our word for it.
