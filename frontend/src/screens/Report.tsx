import { useState } from "react";
import { Icon } from "../components/Icon";
import { ActionButton, Notice, ScreenHeader, SeverityBadge } from "../components/ui";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useAsync, useSession } from "../lib/session";

export default function Report() {
  const { user } = useSession();
  const summary = useAsync(() => api.summary(), []);
  const audit = useAsync(() => api.auditLogs(12), []);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setDownloading(true);
    setError(null);
    try {
      const response = await api.summaryPdf();
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "hermedisafe-medication-summary.pdf";
      link.click();
      URL.revokeObjectURL(url);
      audit.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The PDF could not be generated");
    } finally {
      setDownloading(false);
    }
  };

  const data = summary.data;

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="TAKE IT TO YOUR APPOINTMENT"
            title="My report"
            intro="A single document with every confirmed medicine, what is still awaiting review, and the alerts your clinician should see."
            icon="book"
            color="berry"
          />

          {error && <Notice tone="error">{error}</Notice>}
          {summary.error && <Notice tone="error">{summary.error}</Notice>}

          {data && (
            <>
              <div className="report-head">
                <div>
                  <p className="eyebrow">PREPARED FOR</p>
                  <h3>{user?.full_name}</h3>
                  <p>
                    Generated {formatDateTime(data.generated_at)} · {data.summary_counts.confirmed_active}{" "}
                    confirmed medicines
                  </p>
                </div>
                <ActionButton tone="solid" onClick={download} disabled={downloading}>
                  <Icon name="download" size={16} />
                  {downloading ? "Preparing…" : "Download PDF"}
                </ActionButton>
              </div>

              <table className="data-table">
                <thead>
                  <tr>
                    <th>Medicine</th>
                    <th>Ingredient</th>
                    <th>Dose</th>
                    <th>How often</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {data.confirmed_medicines.map((medicine) => (
                    <tr key={medicine.id}>
                      <td>{medicine.raw_name}</td>
                      <td>{medicine.normalized_ingredient ?? "—"}</td>
                      <td>{medicine.dose ?? "—"}</td>
                      <td>{medicine.frequency ?? "—"}</td>
                      <td>{medicine.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {data.pending_review.length > 0 && (
                <Notice tone="info" icon="alert">
                  {data.pending_review.length} extraction proposal(s) are still awaiting your review
                  and are excluded from the interaction check.
                </Notice>
              )}

              {data.unresolved_duplicates.length > 0 && (
                <Notice tone="error" icon="alert">
                  Unresolved duplicate pairs:{" "}
                  {data.unresolved_duplicates
                    .map((flag) => `${flag.medicine_a} + ${flag.medicine_b}`)
                    .join(", ")}
                </Notice>
              )}

              <p className="field-label list-gap">ACTIVE ALERTS · {data.active_alerts.length}</p>
              {data.active_alerts.length === 0 ? (
                <Notice tone="empty" icon="check">
                  No active interaction alerts.
                </Notice>
              ) : (
                <ul className="alert-list full">
                  {data.active_alerts.map((alert) => (
                    <li className="alert-card" key={alert.id}>
                      <div className="alert-head">
                        <SeverityBadge severity={alert.severity} />
                        <strong>{alert.medicines.join(" + ")}</strong>
                      </div>
                      <p>{alert.rationale}</p>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          <p className="field-label list-gap">RECENT ACTIVITY ON YOUR ACCOUNT</p>
          {audit.data && audit.data.items.length > 0 ? (
            <ul className="audit-list">
              {audit.data.items.map((entry) => (
                <li key={entry.id}>
                  <span>{entry.action}</span>
                  <small>
                    {entry.resource_type}
                    {entry.resource_id ? ` #${entry.resource_id}` : ""} ·{" "}
                    {formatDateTime(entry.timestamp)}
                  </small>
                </li>
              ))}
            </ul>
          ) : (
            <Notice tone="empty" icon="shield">
              Nothing recorded yet.
            </Notice>
          )}
        </section>

        <aside className="tool-aside">
          <div>
            <Icon name="shield" />
            <h3>Append-only audit trail</h3>
            <p>
              Every confirmation, safety check and report download is written to your audit log. It
              is readable only by you.
            </p>
          </div>
          <div>
            <Icon name="book" />
            <h3>Not a diagnosis</h3>
            <p>
              The report restates what you have confirmed and what the interaction dataset says
              about it. Interpretation stays with your clinician.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
