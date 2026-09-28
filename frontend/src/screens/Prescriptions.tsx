import { useState, type ChangeEvent } from "react";
import { Icon } from "../components/Icon";
import { ActionButton, Notice, ScreenHeader } from "../components/ui";
import { api, type PrescriptionDetail } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useAsync } from "../lib/session";

export default function Prescriptions() {
  const list = useAsync(() => api.prescriptions(), []);
  const [uploading, setUploading] = useState(false);
  const [working, setWorking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<PrescriptionDetail | null>(null);

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadPrescription(file);
      list.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const runOcr = async (id: number) => {
    setWorking(id);
    setError(null);
    try {
      const result = await api.runMockOcr(id);
      setDetail(result);
      list.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Extraction failed");
    } finally {
      setWorking(null);
    }
  };

  const remove = async (id: number) => {
    setWorking(id);
    try {
      await api.deletePrescription(id);
      if (detail?.id === id) setDetail(null);
      list.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Delete failed");
    } finally {
      setWorking(null);
    }
  };

  const openDetail = async (id: number) => {
    setError(null);
    try {
      setDetail(await api.prescription(id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not open this prescription");
    }
  };

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="MEDICINE RECONCILIATION"
            title="Prescriptions"
            intro="Upload a prescription, then run extraction. Everything found arrives as a proposal — nothing enters your medicine list until you confirm it."
            icon="upload"
            color="coral"
          />

          <label className="upload-drop">
            <input type="file" accept="image/*,application/pdf" onChange={onFile} disabled={uploading} />
            <Icon name="upload" size={22} />
            <strong>{uploading ? "Uploading…" : "Choose a photo or PDF"}</strong>
            <small>Up to 10 MB. Clear photos of printed prescriptions work best.</small>
          </label>

          {error && <Notice tone="error">{error}</Notice>}

          <p className="field-label upload-history">UPLOAD HISTORY</p>
          {list.loading && !list.data ? (
            <Notice tone="info" icon="refresh">
              Loading prescriptions…
            </Notice>
          ) : list.error ? (
            <Notice tone="error">{list.error}</Notice>
          ) : !list.data?.items.length ? (
            <Notice tone="empty" icon="file">
              No prescriptions uploaded yet.
            </Notice>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Uploaded</th>
                  <th>Type</th>
                  <th>Found</th>
                  <th>Awaiting review</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.uploaded_at)}</td>
                    <td>{item.file_type}</td>
                    <td>{item.medicine_count}</td>
                    <td>{item.pending_review_count}</td>
                    <td className="row-actions">
                      <ActionButton onClick={() => openDetail(item.id)}>View</ActionButton>
                      <ActionButton
                        tone="solid"
                        disabled={working === item.id}
                        onClick={() => runOcr(item.id)}
                      >
                        {working === item.id ? "Extracting…" : "Run extraction"}
                      </ActionButton>
                      <ActionButton
                        tone="danger"
                        disabled={working === item.id}
                        onClick={() => remove(item.id)}
                      >
                        <Icon name="trash" size={15} />
                      </ActionButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {detail && (
            <div className="extract-panel">
              <p className="field-label">EXTRACTED FROM PRESCRIPTION #{detail.id}</p>
              {detail.medicines.length === 0 ? (
                <Notice tone="empty" icon="pill">
                  Nothing extracted yet. Run extraction to create proposals.
                </Notice>
              ) : (
                <ul className="compact-list">
                  {detail.medicines.map((medicine) => (
                    <li key={medicine.id}>
                      <span>{medicine.raw_name}</span>
                      <small>
                        {medicine.normalized_ingredient ?? "ingredient not matched"} ·{" "}
                        {medicine.is_confirmed ? "confirmed" : "awaiting review"}
                        {medicine.confidence_score !== null &&
                          ` · ${Math.round(medicine.confidence_score * 100)}% confidence`}
                      </small>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>

        <aside className="tool-aside">
          <div>
            <Icon name="shield" />
            <h3>You confirm every item</h3>
            <p>
              Extraction never writes to your medicine list directly. Proposals sit in My medicines
              until you accept or reject them.
            </p>
          </div>
          <div>
            <Icon name="book" />
            <h3>OCR handoff</h3>
            <p>
              The demo uses the backend's deterministic mock extractor. A live OCR service posts to
              the same <code>/prescriptions/&#123;id&#125;/ocr-results</code> boundary.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
