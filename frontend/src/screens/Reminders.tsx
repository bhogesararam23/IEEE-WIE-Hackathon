import { useEffect, useState } from "react";
import { Icon } from "../components/Icon";
import { ActionButton, Modal, Notice, ScreenHeader } from "../components/ui";
import { api, type Reminder } from "../lib/api";
import { formatTime } from "../lib/format";
import {
  notificationPermission,
  notificationsSupported,
  requestNotificationPermission,
} from "../lib/notifications";
import { useAsync } from "../lib/session";

const FREQUENCIES: [string, string][] = [
  ["daily", "Once daily"],
  ["twice_daily", "Twice daily"],
  ["three_times_daily", "Three times daily"],
  ["every_8_hours", "Every 8 hours"],
  ["weekly", "Weekly"],
];

export default function Reminders() {
  const reminders = useAsync(() => api.reminders(), []);
  const medicines = useAsync(() => api.medicines({ confirmed: true, status: "active" }), []);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ medicine_id: 0, time_of_day: "09:00:00", frequency: "daily" });
  const [busy, setBusy] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [permission, setPermission] = useState(notificationPermission());

  // Permission is granted via a native browser popup outside React's control,
  // so poll it rather than relying on a callback that doesn't exist.
  useEffect(() => {
    const interval = setInterval(() => setPermission(notificationPermission()), 2000);
    return () => clearInterval(interval);
  }, []);

  const enableNotifications = async () => {
    setPermission(await requestNotificationPermission());
  };

  const run = async (key: number | "new", work: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await work();
      reminders.reload();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That action did not complete");
      return false;
    } finally {
      setBusy(null);
    }
  };

  const create = async () => {
    const medicine = draft.medicine_id || medicines.data?.[0]?.id;
    if (!medicine) {
      setError("Confirm a medicine first — reminders attach to something you take.");
      return;
    }
    if (await run("new", () => api.addReminder({ ...draft, medicine_id: medicine }))) {
      setCreating(false);
    }
  };

  const rows = reminders.data ?? [];
  const upcoming = [...rows]
    .filter((reminder) => reminder.is_active)
    .sort((a, b) => a.time_of_day.localeCompare(b.time_of_day));

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="ROUTINE"
            title="Medicine reminders"
            intro="A simple schedule per medicine. Notifications fire from this browser tab while it's open -- there's no phone push yet, that needs a push server this build doesn't have."
            icon="bell"
            color="peach"
          />

          {!notificationsSupported() ? (
            <Notice tone="info" icon="alert">
              This browser doesn't support notifications, so reminders here are visual only.
            </Notice>
          ) : permission === "granted" ? (
            <Notice tone="ok" icon="check">
              Notifications are on. Keep this tab open to receive them.
            </Notice>
          ) : permission === "denied" ? (
            <Notice tone="error">
              Notifications are blocked for this site. Re-enable them in your browser's site
              settings to get reminders.
            </Notice>
          ) : (
            <Notice tone="info" icon="bell">
              <span>Turn on notifications to get a real alert when a dose is due. </span>
              <ActionButton tone="solid" onClick={enableNotifications}>
                Enable reminders
              </ActionButton>
            </Notice>
          )}

          <div className="list-toolbar">
            <ActionButton tone="solid" onClick={() => setCreating(true)}>
              <Icon name="plus" size={16} /> New reminder
            </ActionButton>
            <span className="toolbar-note">{upcoming.length} active schedule(s)</span>
          </div>

          {error && <Notice tone="error">{error}</Notice>}

          {reminders.loading && !reminders.data ? (
            <Notice tone="info" icon="refresh">
              Loading reminders…
            </Notice>
          ) : reminders.error ? (
            <Notice tone="error">{reminders.error}</Notice>
          ) : rows.length === 0 ? (
            <Notice tone="empty" icon="bell">
              No reminders yet.
            </Notice>
          ) : (
            <ul className="reminder-list">
              {upcoming.concat(rows.filter((row) => !row.is_active)).map((reminder: Reminder) => (
                <li key={reminder.id} className={reminder.is_active ? "" : "muted"}>
                  <div className="reminder-time">{formatTime(reminder.time_of_day)}</div>
                  <div>
                    <strong>{reminder.medicine_name}</strong>
                    <span>
                      {FREQUENCIES.find(([value]) => value === reminder.frequency)?.[1] ??
                        reminder.frequency.replace(/_/g, " ")}
                    </span>
                  </div>
                  <div className="row-actions">
                    <ActionButton
                      disabled={busy === reminder.id}
                      onClick={() =>
                        run(reminder.id, () =>
                          api.updateReminder(reminder.id, { is_active: !reminder.is_active }),
                        )
                      }
                    >
                      {reminder.is_active ? "Pause" : "Resume"}
                    </ActionButton>
                    <ActionButton
                      tone="danger"
                      disabled={busy === reminder.id}
                      onClick={() => run(reminder.id, () => api.deleteReminder(reminder.id))}
                    >
                      <Icon name="trash" size={15} />
                    </ActionButton>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className="tool-aside">
          <div>
            <Icon name="heart" />
            <h3>Consistency over perfection</h3>
            <p>
              A schedule you keep beats one you abandon. Start with the medicines that have a fixed
              time of day.
            </p>
          </div>
        </aside>
      </div>

      {creating && (
        <Modal
          title="New reminder"
          intro="Pick a confirmed medicine, the time you take it, and how often."
          onClose={() => setCreating(false)}
        >
          <label className="field-label">
            Medicine
            <select
              value={draft.medicine_id}
              onChange={(event) => setDraft({ ...draft, medicine_id: Number(event.target.value) })}
            >
              <option value={0}>Choose a medicine…</option>
              {(medicines.data ?? []).map((medicine) => (
                <option key={medicine.id} value={medicine.id}>
                  {medicine.raw_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-label">
            Time of day
            <input
              type="time"
              step={1}
              defaultValue="09:00:00"
              onChange={(event) =>
                setDraft({ ...draft, time_of_day: `${event.target.value}:00` })
              }
            />
          </label>
          <label className="field-label">
            Frequency
            <select
              value={draft.frequency}
              onChange={(event) => setDraft({ ...draft, frequency: event.target.value })}
            >
              {FREQUENCIES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <ActionButton tone="solid" onClick={create} disabled={busy === "new"}>
            {busy === "new" ? "Saving…" : "Save reminder"}
          </ActionButton>
        </Modal>
      )}
    </div>
  );
}
