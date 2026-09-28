"""End-to-end integration test suite covering the full user lifecycle:

Signup/login -> Maternal Profile -> Prescription Upload -> Mock OCR Ingestion ->
Medicine Confirmation -> Manual Medicine Addition -> DDI Interaction Check ->
Alert Review & Evidence Attachment -> Reminder CRUD -> JSON & PDF Summary Reports ->
Audit Logs.
"""

import io
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_e2e_backend_flow():
    test_email = f"e2e_{uuid.uuid4().hex[:8]}@example.com"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:

        # 1. Health check
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # 2. Signup
        signup_payload = {
            "email": test_email,
            "password": "Password123!",
            "full_name": "E2E Test User",
        }
        resp = await client.post("/auth/signup", json=signup_payload)
        assert resp.status_code == 201
        auth_data = resp.json()
        assert "access_token" in auth_data
        token = auth_data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Create Maternal Profile (Pregnant, T2)
        profile_payload = {
            "context_type": "pregnant",
            "trimester": 2,
        }
        resp = await client.post("/users/me/profile", json=profile_payload, headers=headers)
        assert resp.status_code == 201
        assert resp.json()["trimester"] == 2

        # 4. Upload Prescription
        fake_file = ("test_rx.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...", "image/png")
        resp = await client.post(
            "/prescriptions/upload",
            files={"file": fake_file},
            headers=headers,
        )
        assert resp.status_code == 201
        prescription = resp.json()
        rx_id = prescription["id"]
        assert rx_id > 0

        # 5. Trigger Mock OCR
        resp = await client.post(f"/prescriptions/{rx_id}/mock-ocr", headers=headers)
        assert resp.status_code == 201
        ocr_result = resp.json()
        assert ocr_result["medicine_count"] == 3
        medicines = ocr_result["medicines"]
        crocin_med = next(m for m in medicines if m["raw_name"] == "Crocin 500mg")

        # 6. Confirm Medicine (Crocin 500mg -> Paracetamol)
        resp = await client.patch(
            f"/medicines/{crocin_med['id']}/confirm",
            json={"raw_name": "Crocin 500mg", "strength": "500mg"},
            headers=headers,
        )
        assert resp.status_code == 200
        confirmed_med = resp.json()
        assert confirmed_med["is_confirmed"] is True
        assert confirmed_med["normalized_ingredient"] == "Paracetamol"

        # 7. Add Manual Medicine (Disprin 325 -> Acetylsalicylic Acid)
        manual_payload = {
            "raw_name": "Disprin 325",
            "brand_name": "Disprin",
            "strength": "325mg",
            "dose": "1 tablet",
            "frequency": "once daily",
        }
        resp = await client.post("/medicines", json=manual_payload, headers=headers)
        assert resp.status_code == 201
        manual_med = resp.json()
        assert manual_med["normalized_ingredient"] == "Acetylsalicylic Acid"

        # 8. Run DDI Interaction Check (Paracetamol + Aspirin interaction)
        resp = await client.post("/medicines/check-interactions", headers=headers)
        assert resp.status_code == 200
        check_result = resp.json()
        assert check_result["total_active_alerts"] >= 1

        # 9. List Alerts & verify severity sorting
        resp = await client.get("/alerts", headers=headers)
        assert resp.status_code == 200
        alerts = resp.json()
        assert len(alerts) >= 1
        alert_id = alerts[0]["id"]

        # 10. Clinician mark reviewed
        resp = await client.patch(f"/alerts/{alert_id}/mark-reviewed", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["reviewed_by_professional"] is True

        # 11. Attach AI RAG Evidence
        evidence_payload = {
            "source_reference": "PubMed 12345: Combined analgesic study",
            "evidence_items": [
                {"title": "Analgesic Safety Paper", "url": "https://pubmed.ncbi.nlm.nih.gov/12345/"}
            ],
        }
        resp = await client.patch(f"/alerts/{alert_id}/evidence", json=evidence_payload, headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["evidence_references"]) >= 1

        # 12. Create Reminder Schedule
        reminder_payload = {
            "medicine_id": confirmed_med["id"],
            "time_of_day": "08:00:00",
            "frequency": "twice_daily",
        }
        resp = await client.post("/reminders", json=reminder_payload, headers=headers)
        assert resp.status_code == 201
        reminder = resp.json()
        assert reminder["medicine_name"] == "Crocin 500mg"

        # 13. Fetch JSON Medication Summary Report
        resp = await client.get("/reports/medication-summary", headers=headers)
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["summary_counts"]["confirmed_active"] >= 2
        assert len(summary["active_alerts"]) >= 1

        # 14. Fetch PDF Medication Summary Report
        resp = await client.get("/reports/medication-summary/pdf", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content[:4] == b"%PDF"

        # 15. Fetch Audit Trail
        resp = await client.get("/audit-logs", headers=headers)
        assert resp.status_code == 200
        logs = resp.json()
        assert logs["total"] >= 10
