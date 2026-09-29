# HerMediSafe Backend — API Contract & Developer Integration Specification

This document defines the REST API contract for the HerMediSafe FastAPI backend. It serves as the reference guide for frontend developers, mobile developers, and AI/OCR integration teammates.

---

## Overview & Global Conventions

- **Base URL:** `http://localhost:8010` in this checkout (compose's default is 8000;
  8010 because port 8000 is occupied on the development machine)
- **Interactive Swagger Docs:** `<base>/docs`
- **ReDoc:** `<base>/redoc`
- **Authentication:** Bearer JWT in HTTP Header: `Authorization: Bearer <access_token>`
- **Soft Delete:** Global soft-delete filter applied to all models (deleted accounts/rows are omitted from responses).
- **Audit Trail:** All write operations, safety checks, and report generations write to `audit_logs`.

---

## 🎯 Critical AI / OCR Teammate Integration Boundaries

### 1. Ingest OCR Extraction Proposals
- **Endpoint:** `POST /prescriptions/{prescription_id}/ocr-results`
- **Auth Required:** Yes (`Authorization: Bearer <token>`)
- **Purpose:** Called by the OCR pipeline after processing a prescription image/PDF to record extracted medicine proposals.
- **Request Body (`application/json`):**
```json
[
  {
    "raw_name": "Crocin 500mg",
    "brand_name": "Crocin",
    "strength": "500mg",
    "dose": "1 tablet",
    "frequency": "twice daily",
    "duration": "5 days",
    "confidence": 0.94
  },
  {
    "raw_name": "Dolo 650",
    "brand_name": "Dolo",
    "strength": "650mg",
    "dose": "1 tablet",
    "frequency": "three times daily",
    "duration": "3 days",
    "confidence": 0.88
  }
]
```
- **Response (`200 OK`):** List of unconfirmed `Medicine` objects created.

*(For local testing/dev without a live OCR service, use `POST /prescriptions/{prescription_id}/mock-ocr`).*

---

### 2. Attach RAG / AI Evidence Citations to DDI Alerts
- **Endpoint:** `PATCH /alerts/{alert_id}/evidence`
- **Auth Required:** Yes (`Authorization: Bearer <token>`)
- **Purpose:** Called by the AI/RAG service to attach source literature, PubMed references, or clinical rationale text to a flagged drug-drug interaction alert.
- **Request Body (`application/json`):**
```json
{
  "source_reference": "PubMed ID 31234567: Co-administration of Paracetamol and Aspirin increases gastrointestinal mucosal injury risk.",
  "evidence_items": [
    {
      "title": "Analgesic Combination Safety Guidelines (WHO 2024)",
      "url": "https://pubmed.ncbi.nlm.nih.gov/31234567/"
    },
    {
      "title": "Clinical Pharmacology of Combined Non-Opioid Analgesics",
      "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/"
    }
  ]
}
```
- **Response (`200 OK`):** Updated `InteractionAlertResponse` including all attached `evidence_references`.

---

### 3. Ask HerMedi AI
- **Endpoint:** `POST /assistant/ask`
- **Auth Required:** Yes (`Authorization: Bearer <token>`)
- **Purpose:** Grounded Q&A over the caller's own maternal context, confirmed
  medicines, and active interaction alerts. Tries Gemini first; falls back to
  Groq if Gemini errors, times out, or is rate-limited. Both are free-tier
  providers — see `.env.example` for where to get keys.
- **Request Body (`application/json`):**
```json
{
  "question": "Can I take paracetamol for a headache?",
  "language": "en"
}
```
  `language` is `"en"` (default) or `"hi"`; when `"hi"`, the answer is
  translated to Hindi via MyMemory (falling back to the English text if
  translation fails) and the disclaimer is returned pre-translated.
- **Response (`200 OK`):**
```json
{
  "answer": "Paracetamol is generally considered the first-choice pain reliever...",
  "model_used": "gemini",
  "disclaimer": "This is general information, not a diagnosis or prescription...",
  "language": "en"
}
```
- **Errors:** `503` if neither provider is configured, or both calls fail.

---

## Section 1: Health & System

### `GET /health`
- **Auth Required:** No
- **Summary:** Service health and DB connectivity check.
- **Response (`200 OK`):**
```json
{
  "status": "ok",
  "service": "HerMediSafe API",
  "version": "0.1.0",
  "environment": "local",
  "database": "up"
}
```

---

## Section 2: Authentication (`/auth`)

### `POST /auth/signup`
- **Auth Required:** No
- **Request Body:**
```json
{
  "email": "user@example.com",
  "password": "Password123!",
  "full_name": "Jane Doe"
}
```
- **Response (`201 Created`):**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user_id": 1,
  "email": "user@example.com"
}
```

### `POST /auth/login`
- **Auth Required:** No
- **Request Body:** `{"email": "user@example.com", "password": "Password123!"}`
- **Response (`200 OK`):** Returns token dictionary.

### `POST /auth/google`
- **Auth Required:** No
- **Purpose:** Verifies a Google Identity Services ID token server-side
  (against Google's own public keys), then finds or creates an account by the
  token's verified email.
- **Request Body:** `{"credential": "<Google ID token JWT>"}`
- **Response (`200 OK`):** Same token dictionary as `/auth/login`.
- **Errors:** `503` if `GOOGLE_CLIENT_ID` isn't configured on the server;
  `401` if the token fails verification.

---

## Section 3: Profile & Maternal Context (`/users`)

### `GET /users/me`
- **Auth Required:** Yes
- **Response (`200 OK`):** Returns caller's user record and `profile` object (if set).

### `POST /users/me/profile`
- **Auth Required:** Yes
- **Request Body:**

`context_type` is one of `general`, `planning_pregnancy`, `pregnant`, `breastfeeding`.
`trimester` (1-3) is required for `pregnant` and must be null otherwise;
`infant_age_months` (0-240) is required for `breastfeeding` and must be null otherwise.

```json
{
  "context_type": "pregnant",
  "trimester": 2,
  "infant_age_months": null,
  "is_premature_infant": null
}
```
- **Response (`201 Created` / `200 OK`):** Updated user profile.
- **Errors:** `422` when the fields contradict `context_type` (validated in
  `UserProfilePayload`, mirrored by DB CHECK constraints).

### `POST /users/me/consent`
- **Auth Required:** Yes
- **Response (`200 OK`):** `{"consent_given_at": "2026-09-27T14:00:00Z", "already_recorded": false}`

### `DELETE /users/me`
- **Auth Required:** Yes
- **Response (`200 OK`):** Soft-deletes user account and all personal data rows.

---

## Section 4: Prescriptions (`/prescriptions`)

### `POST /prescriptions/upload`
- **Auth Required:** Yes
- **Content-Type:** `multipart/form-data` (`file` parameter)
- **Response (`201 Created`):**
```json
{
  "id": 1,
  "file_url": "/files/prescriptions/1/abc123.png",
  "file_type": "image",
  "uploaded_at": "2026-09-27T14:30:00Z",
  "source_type": "prescription",
  "medicine_count": 0,
  "pending_review_count": 0
}
```

### `GET /prescriptions`
- **Auth Required:** Yes
- **Response (`200 OK`):** List of user's uploaded prescriptions.

### `GET /prescriptions/{id}`
- **Auth Required:** Yes
- **Response (`200 OK`):** Prescription details with extracted medicines list.

### `DELETE /prescriptions/{id}`
- **Auth Required:** Yes
- **Response (`204 No Content`):** Soft-deletes prescription row & removes disk file.

---

## Section 5: Medicines & Reconciliation (`/medicines`)

### `GET /medicines/pending-review`
- **Auth Required:** Yes
- **Response (`200 OK`):** List of unconfirmed OCR extraction proposals awaiting review.

### `GET /medicines`
- **Auth Required:** Yes
- **Query Params:** `confirmed=true|false`, `status=active|discontinued|rejected`, `limit`, `offset`
- **Response (`200 OK`):** Page of user's medicines with `normalized_ingredient`, `source`, `confidence_score`, and `jan_aushadhi` (a cheaper PMBJP generic-equivalent — `{product_name, unit, mrp_inr}` — when the ingredient is in the curated seed dataset, else `null`).

### `POST /medicines`
- **Auth Required:** Yes
- **Request Body (Manual Entry):**
```json
{
  "raw_name": "Disprin 325",
  "brand_name": "Disprin",
  "strength": "325mg",
  "dose": "1 tablet",
  "frequency": "once daily"
}
```
- **Response (`201 Created`):** Automatically confirmed, normalized, and checked for duplicates.

### `PATCH /medicines/{id}/confirm`
- **Auth Required:** Yes
- **Request Body:** `{"raw_name": "Crocin 500mg", "strength": "500mg"}`
- **Response (`200 OK`):** Confirms medicine proposal, computes `normalized_ingredient`, clears extractor confidence, and triggers duplicate detection.

### `PATCH /medicines/{id}/reject`
- **Auth Required:** Yes
- **Request Body:** `{"reason": "not my medicine"}`
- **Response (`200 OK`):** Marks status `rejected`.

---

## Section 6: Duplicate Flags (`/medicines/duplicates`)

### `GET /medicines/duplicates`
- **Auth Required:** Yes
- **Query Params:** `include_resolved=false`
- **Response (`200 OK`):** Suspected duplicate pairs with `medicine_a` and `medicine_b`.

### `PATCH /medicines/duplicates/{flag_id}/resolve`
- **Auth Required:** Yes
- **Request Body:** `{"resolution": "merged", "kept_medicine_id": 4}` (resolutions: `keep_both`, `merged`, `not_a_duplicate`).
- **Response (`200 OK`):** Resolves flag and tombstones non-kept row if merged.

---

## Section 7: Interaction Alerts (`/alerts` & `/medicines/check-interactions`)

### `POST /medicines/check-interactions`
- **Auth Required:** Yes
- **Response (`200 OK`):**
```json
{
  "new_alerts_created": 1,
  "total_active_alerts": 1
}
```

### `GET /alerts`
- **Auth Required:** Yes
- **Response (`200 OK`):** Alerts ordered severity-first (`high` -> `moderate` -> `low`). Includes `medicine_names` and `evidence_references`.

### `PATCH /alerts/{id}/mark-reviewed`
- **Auth Required:** Yes
- **Response (`200 OK`):** Sets `reviewed_by_professional = true`.

---

## Section 8: Reminder Schedules (`/reminders`)

### `POST /reminders`
- **Auth Required:** Yes
- **Request Body:**
```json
{
  "medicine_id": 4,
  "time_of_day": "08:00:00",
  "frequency": "twice_daily"
}
```
- **Response (`201 Created`):** Created schedule with `medicine_name`.

### `GET /reminders`
- **Auth Required:** Yes
- **Query Params:** `is_active=true`
- **Response (`200 OK`):** List of reminders.

### `PATCH /reminders/{id}`
- **Auth Required:** Yes
- **Request Body:** `{"time_of_day": "09:30:00", "is_active": true}`
- **Response (`200 OK`):** Updated schedule.

### `DELETE /reminders/{id}`
- **Auth Required:** Yes
- **Response (`200 OK`):** Soft-deletes reminder schedule.

---

## Section 9: Reports (`/reports`)

### `GET /reports/medication-summary`
- **Auth Required:** Yes
- **Response (`200 OK`):** JSON document containing confirmed medicines, pending proposals, unresolved duplicates, active interaction alerts, and count summaries.

### `GET /reports/medication-summary/pdf`
- **Auth Required:** Yes
- **Response (`200 OK`):** Binary PDF stream (`application/pdf`, filename: `medication_summary.pdf`).

---

## Section 10: Audit Logs (`/audit-logs`)

### `GET /audit-logs`
- **Auth Required:** Yes
- **Query Params:** `limit=50`, `offset=0`
- **Response (`200 OK`):** Paginated trail of caller's actions, newest first.
