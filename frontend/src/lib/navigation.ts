import type { IconName } from "../components/Icon";

export type ScreenId =
  | "overview"
  | "ask"
  | "prescriptions"
  | "medicines"
  | "safety"
  | "reminders"
  | "report"
  | "cycle";

export interface NavItem {
  id: ScreenId;
  label: string;
  icon: IconName;
}

export const nav: NavItem[] = [
  { id: "overview", label: "Overview", icon: "home" },
  { id: "ask", label: "Ask HerMedi AI", icon: "sparkles" },
  { id: "prescriptions", label: "Prescriptions", icon: "upload" },
  { id: "medicines", label: "My medicines", icon: "pill" },
  { id: "safety", label: "Safety check", icon: "shield" },
  { id: "reminders", label: "Reminders", icon: "bell" },
  { id: "report", label: "My report", icon: "book" },
  { id: "cycle", label: "Cycle tracker", icon: "calendar" },
];

export interface Feature {
  id: ScreenId;
  icon: IconName;
  color: string;
  title: string;
  text: string;
  /** Screens with no backend endpoint yet are labelled honestly instead of faking a result. */
  offline?: boolean;
}

export const features: Feature[] = [
  {
    id: "prescriptions",
    icon: "upload",
    color: "coral",
    title: "Prescriptions",
    text: "Upload a prescription and turn it into medicine proposals you confirm yourself.",
  },
  {
    id: "medicines",
    icon: "pill",
    color: "violet",
    title: "My medicines",
    text: "Every confirmed medicine in one list, normalised to its active ingredient.",
  },
  {
    id: "safety",
    icon: "shield",
    color: "plum",
    title: "Safety check",
    text: "Review interaction alerts across your medicines, sorted by severity.",
  },
  {
    id: "reminders",
    icon: "bell",
    color: "peach",
    title: "Medicine reminders",
    text: "Create a simple routine so you never miss a dose.",
  },
  {
    id: "report",
    icon: "book",
    color: "berry",
    title: "My report",
    text: "Download a clinician-ready medication summary to take to your appointment.",
  },
  {
    id: "cycle",
    icon: "calendar",
    color: "pink",
    title: "Period tracker",
    text: "Log your cycle and understand your upcoming phases.",
    offline: true,
  },
];
