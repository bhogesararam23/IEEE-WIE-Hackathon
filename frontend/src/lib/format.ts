import type { Severity } from "../lib/api";

export const CONTEXT_LABELS: Record<string, string> = {
  general: "General profile",
  planning_pregnancy: "Planning pregnancy",
  pregnant: "Pregnant",
  breastfeeding: "Breastfeeding",
};

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString(undefined, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}

/** "08:00:00" from the API -> "08:00". */
export function formatTime(value: string): string {
  const [hh, mm] = value.split(":");
  return `${hh ?? "00"}:${mm ?? "00"}`;
}

export function severityLabel(severity: Severity): string {
  return severity.charAt(0).toUpperCase() + severity.slice(1);
}
