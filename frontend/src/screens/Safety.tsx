import { useState } from "react";
import { Icon } from "../components/Icon";
import { ActionButton, Modal, Notice, ScreenHeader, SeverityBadge } from "../components/ui";
import { api, type InteractionAlert } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useAsync } from "../lib/session";

export default function Safety() {
  const alerts = useAsync(() => api.alerts(), []);
  const [busy, setBusy] = useState<number | "check" | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evidenceFor, setEvidenceFor] = useState<InteractionAlert | null>(null);
  const [evidence, setEvidence] = useState({ title: "", url: "", source_reference: "" });

  const run = async (key: number | "check", work: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    setStatus(null);
    try {
      const result = await work();
      alerts.reload();
      return result;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That action did not complete");
    } finally {
      setBusy(null);
    }
  };

  const check = async () => {
    const result = await run("check", () => api.checkInteractions());
    if (result) {
      const { new_alerts_created: created, total_active_alerts: total } =
        result as { new_alerts_created: number; total_active_alerts: number };
      setStatus(
        created === 0
          ? `Check complete. No new alerts; ${total} active in total.`
          : `Check complete. ${created} new alert${created === 1 ? "" : "s"} added.`,
      );
    }
  };

  const saveEvidence = async () => {
    if (!evidenceFor) return;
    await run(evidenceFor.id, () =>
      api.addEvidence(evidenceFor.id, {
        source_reference: evidence.source_reference || undefined,
        evidence_items: evidence.title && evidence.url ? [{ title: evidence.title, url: evidence.url }] : [],
      }),
    );
    setEvidenceFor(null);
    setEvidence({ title: "", url: "", source_reference: "" });
  };

  const rows = alerts.data ?? [];

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="DDI SAFETY CHECK"
            title="Safety check"
            intro="Every confirmed medicine is compared pairwise against the interaction dataset. Results are ordered by severity, and nothing here is an instruction to stop a medicine."
            icon="shield"
            color="plum"
          />

          <div className="list-toolbar">
            <ActionButton tone="solid" onClick={check} disabled={busy === "check"}>
              <Icon name="refresh" size={16} /> {busy === "check" ? "Checking…" : "Run interaction check"}
            </ActionButton>
            <span className="toolbar-note">
              {rows.length} active alert{rows.length === 1 ? "" : "s"}
            </span>
          </div>

          {status && <Notice tone="ok" icon="check">{status}</Notice>}
          {error && <Notice tone="error">{error}</Notice>}

          {alerts.loading && !alerts.data ? (
            <Notice tone="info" icon="refresh">
              Loading alerts…
            </Notice>
          ) : alerts.error ? (
            <Notice tone="error">{alerts.error}</Notice>
          ) : rows.length === 0 ? (
            <Notice tone="empty" icon="check">
              No interaction alerts. Run the check after you confirm a new medicine.
            </Notice>
          ) : (
            <ul className="alert-list full">
              {rows.map((alert) => (
                <li className="alert-card" key={alert.id}>
                  <div className="alert-head">
                    <SeverityBadge severity={alert.severity} />
                    <strong>{alert.medicine_names.join(" + ")}</strong>
                    <span className="alert-time">{formatDateTime(alert.created_at)}</span>
                  </div>
                  <p>{alert.rationale}</p>
                  {alert.source_reference && <small className="source">{alert.source_reference}</small>}
                  {alert.evidence_references.length > 0 && (
                    <ul className="evidence-list">
                      {alert.evidence_references.map((item) => (
                        <li key={item.id}>
                          <a href={item.url} target="_blank" rel="noreferrer">
                            {item.title}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="alert-foot">
                    <span className={alert.reviewed_by_professional ? "reviewed" : "unreviewed"}>
                      <Icon name={alert.reviewed_by_professional ? "check" : "alert"} size={15} />
                      {alert.reviewed_by_professional
                        ? "Reviewed by a professional"
                        : "Waiting on a professional"}
                    </span>
                    <div className="row-actions">
                      {!alert.reviewed_by_professional && (
                        <ActionButton
                          disabled={busy === alert.id}
                          onClick={() => run(alert.id, () => api.markReviewed(alert.id))}
                        >
                          Mark reviewed
                        </ActionButton>
                      )}
                      <ActionButton
                        disabled={busy === alert.id}
                        onClick={() => setEvidenceFor(alert)}
                      >
                        Attach evidence
                      </ActionButton>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className="tool-aside">
          <div>
            <Icon name="alert" />
            <h3>What this is not</h3>
            <p>
              An alert is a prompt to ask, not a verdict. Dosing decisions stay with your pharmacist
              or doctor.
            </p>
          </div>
          <div>
            <Icon name="book" />
            <h3>Evidence handoff</h3>
            <p>
              Citations are written through the same <code>/alerts/&#123;id&#125;/evidence</code>{" "}
              boundary the RAG service uses, so a literature answer can be attached without a
              frontend change.
            </p>
          </div>
        </aside>
      </div>

      {evidenceFor && (
        <Modal
          title="Attach evidence"
          intro={`Reference for ${evidenceFor.medicine_names.join(" + ")}.`}
          onClose={() => setEvidenceFor(null)}
        >
          <label className="field-label">
            Source reference
            <input
              value={evidence.source_reference}
              placeholder="PubMed ID 2891234: additive QT prolongation…"
              onChange={(event) => setEvidence({ ...evidence, source_reference: event.target.value })}
            />
          </label>
          <label className="field-label">
            Citation title
            <input
              value={evidence.title}
              placeholder="Fluoroquinolone Co-Administration & Cardiotoxicity Risk"
              onChange={(event) => setEvidence({ ...evidence, title: event.target.value })}
            />
          </label>
          <label className="field-label">
            Link
            <input
              value={evidence.url}
              placeholder="https://pubmed.ncbi.nlm.nih.gov/…"
              onChange={(event) => setEvidence({ ...evidence, url: event.target.value })}
            />
          </label>
          <ActionButton tone="solid" onClick={saveEvidence} disabled={busy === evidenceFor.id}>
            Save evidence
          </ActionButton>
        </Modal>
      )}
    </div>
  );
}
