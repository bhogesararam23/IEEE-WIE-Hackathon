/**
 * Real dose-time notifications, browser-native only -- no service worker, no
 * push server. Fires a `Notification` from an open tab when a reminder's
 * `time_of_day` matches the current local time. That means it only works
 * while this tab is open; true background/closed-browser push needs a push
 * server (VAPID keys + `web-push`), which is future work, not this.
 */
import { useEffect, useRef } from "react";
import { api } from "./api";
import { useSession } from "./session";

const POLL_MS = 30_000;

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function notificationPermission(): NotificationPermission | "unsupported" {
  return notificationsSupported() ? Notification.permission : "unsupported";
}

/** Must be called from a user gesture (a click handler) -- browsers refuse a
 * silent permission prompt on page load. */
export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!notificationsSupported()) return "denied";
  return Notification.requestPermission();
}

function isDueNow(timeOfDay: string, now: Date): boolean {
  const [hh, mm] = timeOfDay.split(":").map(Number);
  if (Number.isNaN(hh) || Number.isNaN(mm)) return false;
  return now.getHours() === hh && now.getMinutes() === mm;
}

/**
 * Polls active reminders every 30s and fires a Notification for any whose
 * time_of_day matches the current minute. Checks `Notification.permission`
 * fresh on every tick rather than once on mount, so granting permission later
 * (from the Reminders screen's "Enable reminders" button) starts working on
 * the next tick with no extra wiring between components.
 *
 * Reads session status itself (rather than taking an `enabled` prop) so it
 * can be called unconditionally from the top of `App`, before the
 * loading/anonymous early returns there -- React's rules of hooks don't allow
 * calling it only after those.
 */
export function useReminderNotifications(): void {
  const { status } = useSession();
  const firedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!notificationsSupported() || status !== "authenticated") return;
    let cancelled = false;

    const tick = async () => {
      if (Notification.permission !== "granted") return;

      let reminders;
      try {
        reminders = await api.reminders({ is_active: true });
      } catch {
        return; // signed out, offline, etc. -- just retry next tick
      }
      if (cancelled) return;

      const now = new Date();
      const minuteKey = `${now.toDateString()} ${now.getHours()}:${now.getMinutes()}`;
      for (const reminder of reminders) {
        if (!isDueNow(reminder.time_of_day, now)) continue;
        const fireKey = `${reminder.id}|${minuteKey}`;
        if (firedRef.current.has(fireKey)) continue;
        firedRef.current.add(fireKey);
        new Notification(`Time for ${reminder.medicine_name}`, {
          body: reminder.frequency.replace(/_/g, " "),
          tag: fireKey,
        });
      }
    };

    void tick();
    const interval = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [status]);
}
