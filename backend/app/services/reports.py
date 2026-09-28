"""Reports service: builds the medication summary dict and renders the PDF.

The JSON shape drives both the REST response and the PDF; the reporter reads
from the dict rather than hitting the DB a second time, so both endpoints
always describe the same snapshot.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import MedicineStatus
from app.models.interaction import InteractionAlert
from app.models.medicine import DuplicateFlag, Medicine
from app.models.reminder import ReminderSchedule

logger = logging.getLogger(__name__)

__all__ = ["build_medication_summary", "render_pdf"]


async def build_medication_summary(
    session: AsyncSession, *, user_id: int
) -> dict:
    """Aggregate the user's full medication status into a single dict."""

    # --- Confirmed active medicines ---
    confirmed = list(
        (
            await session.scalars(
                select(Medicine)
                .where(
                    Medicine.user_id == user_id,
                    Medicine.is_confirmed.is_(True),
                    Medicine.status == MedicineStatus.ACTIVE,
                )
                .order_by(Medicine.created_at.asc())
            )
        ).all()
    )

    # --- Pending (unconfirmed, not rejected) ---
    pending = list(
        (
            await session.scalars(
                select(Medicine)
                .where(
                    Medicine.user_id == user_id,
                    Medicine.is_confirmed.is_(False),
                    Medicine.status != MedicineStatus.REJECTED,
                )
            )
        ).all()
    )

    # --- Unresolved duplicate flags ---
    duplicates = list(
        (
            await session.scalars(
                select(DuplicateFlag)
                .join(DuplicateFlag.medicine_a)
                .options(
                    selectinload(DuplicateFlag.medicine_a),
                    selectinload(DuplicateFlag.medicine_b),
                )
                .where(
                    Medicine.user_id == user_id,
                    DuplicateFlag.resolved.is_(False),
                )
            )
        ).all()
    )

    # --- Active alerts ---
    alerts = list(
        (
            await session.scalars(
                select(InteractionAlert)
                .where(InteractionAlert.user_id == user_id)
                .options(selectinload(InteractionAlert.medicines))
                .order_by(InteractionAlert.created_at.desc())
            )
        ).all()
    )

    _SEVERITY_ORDER = {"high": 0, "moderate": 1, "low": 2, "none": 3}
    alerts.sort(key=lambda a: _SEVERITY_ORDER.get(str(a.severity), 9))

    return {
        # `isoformat()` already ends in "+00:00"; appending "Z" produced
        # "...+00:00Z", which is not valid ISO 8601 and parses as Invalid Date in
        # JavaScript. Match the "Z" form Pydantic emits for every other timestamp.
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "user_id": user_id,
        "confirmed_medicines": [
            {
                "id": m.id,
                "raw_name": m.raw_name,
                "brand_name": m.brand_name,
                "normalized_ingredient": m.normalized_ingredient,
                "strength": m.strength,
                "dose": m.dose,
                "frequency": m.frequency,
                "duration": m.duration,
                "source": str(m.source),
                "confidence_score": m.confidence_score,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in confirmed
        ],
        "pending_review": [
            {
                "id": m.id,
                "raw_name": m.raw_name,
                "confidence_score": m.confidence_score,
            }
            for m in pending
        ],
        "unresolved_duplicates": [
            {
                "flag_id": f.id,
                "medicine_a": f.medicine_a.raw_name,
                "medicine_b": f.medicine_b.raw_name,
            }
            for f in duplicates
        ],
        "active_alerts": [
            {
                "id": a.id,
                "severity": str(a.severity),
                "rationale": a.rationale,
                "reviewed_by_professional": a.reviewed_by_professional,
                "medicines": [m.raw_name for m in a.medicines],
            }
            for a in alerts
        ],
        "summary_counts": {
            "confirmed_active": len(confirmed),
            "pending_review": len(pending),
            "unresolved_duplicates": len(duplicates),
            "active_alerts": len(alerts),
            "high_severity_alerts": sum(1 for a in alerts if str(a.severity) == "high"),
        },
    }


def render_pdf(summary: dict) -> bytes:
    """Render the medication summary dict as a PDF using ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    normal = styles["Normal"]
    bold_style = ParagraphStyle("bold", parent=normal, fontName="Helvetica-Bold")

    story = []

    # Title
    story.append(Paragraph("HerMediSafe — Medication Summary Report", h1))
    story.append(Paragraph(f"Generated: {summary['generated_at']}", normal))
    story.append(Spacer(1, 0.5 * cm))

    counts = summary["summary_counts"]
    story.append(Paragraph("Summary", h2))
    count_data = [
        ["Confirmed Active Medicines", str(counts["confirmed_active"])],
        ["Pending Review", str(counts["pending_review"])],
        ["Unresolved Duplicates", str(counts["unresolved_duplicates"])],
        ["Interaction Alerts", str(counts["active_alerts"])],
        ["High-Severity Alerts", str(counts["high_severity_alerts"])],
    ]
    t = Table(count_data, colWidths=[10 * cm, 3 * cm])
    t.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a90d9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.whitesmoke, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))

    # Confirmed Medicines
    story.append(Paragraph("Confirmed Medicines", h2))
    if summary["confirmed_medicines"]:
        med_data = [["Name", "Ingredient", "Strength", "Dose", "Frequency", "Source"]]
        for m in summary["confirmed_medicines"]:
            med_data.append([
                Paragraph(m["raw_name"] or "", normal),
                Paragraph(m["normalized_ingredient"] or "—", normal),
                m["strength"] or "—",
                m["dose"] or "—",
                m["frequency"] or "—",
                m["source"],
            ])
        mt = Table(med_data, colWidths=[4 * cm, 3.5 * cm, 2 * cm, 2 * cm, 2.5 * cm, 2.5 * cm])
        mt.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e7d32")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.lightgreen, colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        story.append(mt)
    else:
        story.append(Paragraph("No confirmed medicines.", normal))
    story.append(Spacer(1, 0.5 * cm))

    # Interaction Alerts
    story.append(Paragraph("Interaction Alerts", h2))
    if summary["active_alerts"]:
        _SEV_COLOUR = {"high": "#c62828", "moderate": "#e65100", "low": "#f9a825"}
        for alert in summary["active_alerts"]:
            sev = str(alert["severity"])
            colour = _SEV_COLOUR.get(sev, "#555555")
            drugs = ", ".join(alert["medicines"])
            reviewed = "✓ Reviewed by professional" if alert["reviewed_by_professional"] else "Pending professional review"
            story.append(
                Paragraph(
                    f'<font color="{colour}"><b>[{sev.upper()}]</b></font> '
                    f'{drugs} — {alert["rationale"]} ({reviewed})',
                    normal,
                )
            )
            story.append(Spacer(1, 0.2 * cm))
    else:
        story.append(Paragraph("No active interaction alerts.", normal))
    story.append(Spacer(1, 0.5 * cm))

    # Pending review
    if summary["pending_review"]:
        story.append(Paragraph("Pending Review", h2))
        for p in summary["pending_review"]:
            conf = f" (confidence: {p['confidence_score']:.0%})" if p.get("confidence_score") else ""
            story.append(Paragraph(f"• {p['raw_name']}{conf}", normal))
        story.append(Spacer(1, 0.3 * cm))

    # Duplicates
    if summary["unresolved_duplicates"]:
        story.append(Paragraph("Unresolved Duplicates", h2))
        for dup in summary["unresolved_duplicates"]:
            story.append(
                Paragraph(f"• Flag #{dup['flag_id']}: {dup['medicine_a']} vs {dup['medicine_b']}", normal)
            )
        story.append(Spacer(1, 0.3 * cm))

    doc.build(story)
    return buffer.getvalue()
