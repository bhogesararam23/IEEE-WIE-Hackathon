import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import { severityLabel } from "../lib/format";
import type { Severity } from "../lib/api";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge ${severity}`}>{severityLabel(severity)}</span>;
}

export function Pill({ tone, children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone ?? ""}`}>{children}</span>;
}

/** Errors, empty states and confirmations all read the same way across screens. */
export function Notice({
  tone = "info",
  icon = "alert",
  children,
}: {
  tone?: "info" | "error" | "empty" | "ok";
  icon?: IconName;
  children: ReactNode;
}) {
  return (
    <p className={`notice ${tone}`}>
      <Icon name={icon} size={17} />
      <span>{children}</span>
    </p>
  );
}

export function Modal({
  title,
  intro,
  onClose,
  children,
}: {
  title: string;
  intro?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">
          <Icon name="close" size={17} />
        </button>
        <h2>{title}</h2>
        {intro && <p className="modal-intro">{intro}</p>}
        {children}
      </div>
    </div>
  );
}

export function ScreenHeader({
  eyebrow,
  title,
  intro,
  icon,
  color = "pink",
}: {
  eyebrow: string;
  title: string;
  intro: string;
  icon: IconName;
  color?: string;
}) {
  return (
    <>
      <div className={`feature-icon ${color}`}>
        <Icon name={icon} size={23} />
      </div>
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="tool-intro">{intro}</p>
    </>
  );
}

export function ActionButton({
  children,
  onClick,
  disabled,
  tone = "ghost",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "ghost" | "danger" | "solid";
  type?: "button" | "submit";
}) {
  const className = tone === "solid" ? "primary-btn" : `btn ${tone}`;
  return (
    <button className={className} type={type} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
