import { useState } from "react";
import { ActionButton, Modal, Notice } from "../components/ui";
import { api, type ContextType } from "../lib/api";
import { CONTEXT_LABELS, formatDate } from "../lib/format";
import { useSession } from "../lib/session";

const OPTIONS: { value: ContextType; hint: string }[] = [
  { value: "general", hint: "No pregnancy or breastfeeding context" },
  { value: "planning_pregnancy", hint: "Trying to conceive" },
  { value: "pregnant", hint: "Safety rules for the current trimester" },
  { value: "breastfeeding", hint: "Infant age changes what matters" },
];

export default function ProfileModal({ onClose }: { onClose: () => void }) {
  const { user, refresh } = useSession();
  const [context, setContext] = useState<ContextType>(user?.profile?.context_type ?? "general");
  const [trimester, setTrimester] = useState(user?.profile?.trimester ?? 1);
  const [infantAge, setInfantAge] = useState(user?.profile?.infant_age_months ?? 0);
  const [premature, setPremature] = useState(user?.profile?.is_premature_infant ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.saveProfile({
        context_type: context,
        trimester: context === "pregnant" ? trimester : null,
        infant_age_months: context === "breastfeeding" ? infantAge : null,
        is_premature_infant: context === "breastfeeding" ? premature : null,
      });
      await refresh();
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your health context");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Health context"
      intro="This decides which safety rules apply to your medicines. Only you can see it."
      onClose={onClose}
    >
      <p className="field-label">ACCOUNT</p>
      <div className="profile-account">
        <div>
          <strong>{user?.full_name}</strong>
          <span>{user?.email}</span>
        </div>
        <small>
          {user?.consent_given_at
            ? `Consent recorded ${formatDate(user.consent_given_at)}`
            : "Consent not recorded yet"}
        </small>
      </div>

      <p className="field-label list-gap">WHICH APPLIES TO YOU?</p>
      <div className="context-options">
        {OPTIONS.map((option) => (
          <button
            key={option.value}
            className={context === option.value ? "role-option selected" : "role-option"}
            onClick={() => setContext(option.value)}
          >
            <span className="role-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="m5 12 4 4L19 6" />
              </svg>
            </span>
            <span>
              <strong>{CONTEXT_LABELS[option.value]}</strong>
              <small>{option.hint}</small>
            </span>
            <i className="role-radio" />
          </button>
        ))}
      </div>

      {context === "pregnant" && (
        <label className="field-label">
          Trimester
          <select value={trimester} onChange={(event) => setTrimester(Number(event.target.value))}>
            {[1, 2, 3].map((value) => (
              <option key={value} value={value}>
                Trimester {value}
              </option>
            ))}
          </select>
        </label>
      )}

      {context === "breastfeeding" && (
        <div className="form-grid">
          <label className="field-label">
            Infant age (months)
            <input
              type="number"
              min={0}
              max={240}
              value={infantAge}
              onChange={(event) => setInfantAge(Number(event.target.value))}
            />
          </label>
          <label className="field-label">
            Born premature?
            <select value={premature ? "yes" : "no"} onChange={(event) => setPremature(event.target.value === "yes")}>
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </select>
          </label>
        </div>
      )}

      {error && <Notice tone="error">{error}</Notice>}
      <ActionButton tone="solid" onClick={save} disabled={busy}>
        {busy ? "Saving…" : "Save context"}
      </ActionButton>
    </Modal>
  );
}
