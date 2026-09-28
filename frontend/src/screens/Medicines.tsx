import { useState } from "react";
import { Icon } from "../components/Icon";
import { ActionButton, Modal, Notice, Pill, ScreenHeader } from "../components/ui";
import { api } from "../lib/api";
import { useAsync } from "../lib/session";

interface Draft {
  raw_name: string;
  brand_name: string;
  strength: string;
  dose: string;
  frequency: string;
}

const emptyDraft: Draft = { raw_name: "", brand_name: "", strength: "", dose: "", frequency: "" };

export default function Medicines() {
  // `status=active` alone still returns unconfirmed OCR proposals, which would
  // then appear twice — once here, once in the review queue.
  const active = useAsync(() => api.medicines({ confirmed: true, status: "active" }), []);
  const pending = useAsync(() => api.pendingReview(), []);
  const duplicates = useAsync(() => api.duplicates(false), []);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<number | string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshAll = () => {
    active.reload();
    pending.reload();
    duplicates.reload();
  };

  const run = async (key: number | string, work: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await work();
      refreshAll();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That action did not complete");
    } finally {
      setBusy(null);
    }
  };

  const submitDraft = async () => {
    if (!draft) return;
    await run("new", async () => {
      const body = Object.fromEntries(
        Object.entries(draft).filter(([, value]) => value.trim() !== ""),
      );
      await api.addMedicine(body as Parameters<typeof api.addMedicine>[0]);
      setDraft(null);
    });
  };

  const resolve = (flagId: number, resolution: "keep_both" | "merged" | "not_a_duplicate", keep?: number) =>
    run(`flag-${flagId}`, () => api.resolveDuplicate(flagId, { resolution, kept_medicine_id: keep }));

  const rows = active.data ?? [];
  const queue = pending.data ?? [];
  const flags = duplicates.data ?? [];

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="ONE CLEAR LIST"
            title="My medicines"
            intro="Medicines are normalised to their active ingredient, so two brands of the same drug stop looking like two different drugs."
            icon="pill"
            color="violet"
          />

          {error && <Notice tone="error">{error}</Notice>}

          <div className="list-toolbar">
            <p className="field-label">CONFIRMED · {rows.length}</p>
            <ActionButton tone="solid" onClick={() => setDraft(emptyDraft)}>
              <Icon name="plus" size={16} /> Add a medicine
            </ActionButton>
          </div>

          {active.loading && !active.data ? (
            <Notice tone="info" icon="refresh">
              Loading medicines…
            </Notice>
          ) : active.error ? (
            <Notice tone="error">{active.error}</Notice>
          ) : rows.length === 0 ? (
            <Notice tone="empty" icon="pill">
              Nothing confirmed yet. Add one by hand, or confirm a proposal below.
            </Notice>
          ) : (
            <ul className="medicine-list">
              {rows.map((medicine) => (
                <li key={medicine.id}>
                  <div>
                    <strong>{medicine.raw_name}</strong>
                    <span>
                      {medicine.normalized_ingredient ?? "Ingredient not matched yet"}
                      {medicine.frequency ? ` · ${medicine.frequency}` : ""}
                      {medicine.dose ? ` · ${medicine.dose}` : ""}
                    </span>
                  </div>
                  <div className="row-badges">
                    <Pill tone={medicine.source === "prescription" ? "info" : "muted"}>
                      {medicine.source === "prescription" ? "From prescription" : "Added by you"}
                    </Pill>
                    {medicine.jan_aushadhi && (
                      <Pill tone="low">
                        Generic via Jan Aushadhi · ₹{medicine.jan_aushadhi.mrp_inr.toFixed(2)}
                      </Pill>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          <p className="field-label list-gap">AWAITING YOUR REVIEW · {queue.length}</p>
          {queue.length === 0 ? (
            <Notice tone="empty" icon="check">
              Nothing is waiting for you.
            </Notice>
          ) : (
            <ul className="medicine-list review">
              {queue.map((medicine) => (
                <li key={medicine.id}>
                  <div>
                    <strong>{medicine.raw_name}</strong>
                    <span>
                      {medicine.strength ?? "no strength read"} ·{" "}
                      {medicine.confidence_score !== null
                        ? `${Math.round(medicine.confidence_score * 100)}% extraction confidence`
                        : "confidence not recorded"}
                    </span>
                  </div>
                  <div className="row-actions">
                    <ActionButton
                      tone="solid"
                      disabled={busy === medicine.id}
                      onClick={() =>
                        run(medicine.id, () =>
                          api.confirmMedicine(medicine.id, { raw_name: medicine.raw_name }),
                        )
                      }
                    >
                      <Icon name="check" size={15} /> Confirm
                    </ActionButton>
                    <ActionButton
                      tone="danger"
                      disabled={busy === medicine.id}
                      onClick={() => run(medicine.id, () => api.rejectMedicine(medicine.id, "not my medicine"))}
                    >
                      Reject
                    </ActionButton>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <p className="field-label list-gap">SUSPECTED DUPLICATES · {flags.length}</p>
          {flags.length === 0 ? (
            <Notice tone="empty" icon="check">
              No two medicines look like the same drug.
            </Notice>
          ) : (
            <ul className="duplicate-list">
              {flags.map((flag) => (
                <li key={flag.id}>
                  <div>
                    <strong>
                      {flag.medicine_a.raw_name} + {flag.medicine_b.raw_name}
                    </strong>
                    <span>
                      Both resolve to {flag.medicine_a.normalized_ingredient ?? "the same ingredient"}.
                      Keeping both would double the dose.
                    </span>
                  </div>
                  <div className="row-actions">
                    <ActionButton
                      disabled={busy === `flag-${flag.id}`}
                      onClick={() => resolve(flag.id, "merged", flag.medicine_a.id)}
                    >
                      Merge, keep first
                    </ActionButton>
                    <ActionButton
                      disabled={busy === `flag-${flag.id}`}
                      onClick={() => resolve(flag.id, "keep_both")}
                    >
                      Keep both
                    </ActionButton>
                    <ActionButton
                      disabled={busy === `flag-${flag.id}`}
                      onClick={() => resolve(flag.id, "not_a_duplicate")}
                    >
                      Not duplicates
                    </ActionButton>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className="tool-aside">
          <div>
            <Icon name="shield" />
            <h3>Why confirmation matters</h3>
            <p>
              Duplicate detection and interaction checks only run over medicines you have confirmed.
              A wrong OCR read stays out of your safety checks.
            </p>
          </div>
          <div>
            <Icon name="book" />
            <h3>Ingredient mapping</h3>
            <p>
              Brand names are matched against an Indian brand-to-ingredient table, so Crocin 500mg
              and Dolo 650 are both read as Paracetamol.
            </p>
          </div>
        </aside>
      </div>

      {draft && (
        <Modal
          title="Add a medicine"
          intro="Type it the way it is written on the strip. We normalise the ingredient after you save."
          onClose={() => setDraft(null)}
        >
          {(
            [
              ["raw_name", "Medicine as written", "Dolo 650"],
              ["brand_name", "Brand (optional)", "Dolo"],
              ["strength", "Strength (optional)", "650mg"],
              ["dose", "Dose (optional)", "1 tablet"],
              ["frequency", "How often (optional)", "twice daily"],
            ] as const
          ).map(([key, label, placeholder]) => (
            <label className="field-label" key={key}>
              {label}
              <input
                value={draft[key]}
                placeholder={placeholder}
                onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
              />
            </label>
          ))}
          <ActionButton tone="solid" type="submit" onClick={submitDraft} disabled={busy === "new"}>
            {busy === "new" ? "Saving…" : "Save medicine"}
          </ActionButton>
        </Modal>
      )}
    </div>
  );
}
