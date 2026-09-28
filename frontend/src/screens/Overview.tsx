import { Icon } from "../components/Icon";
import { Notice, SeverityBadge } from "../components/ui";
import { api } from "../lib/api";
import { features, type ScreenId } from "../lib/navigation";
import { useAsync, useSession } from "../lib/session";
import logo from "../assets/hermedisafe-logo.svg";

export default function Overview({ open }: { open: (screen: ScreenId) => void }) {
  const { user } = useSession();
  const summary = useAsync(() => api.summary(), []);
  const today = new Date();

  if (summary.loading && !summary.data) {
    return (
      <div className="page">
        <Notice tone="info" icon="refresh">
          Loading your health overview…
        </Notice>
      </div>
    );
  }

  const counts = summary.data?.summary_counts;

  return (
    <div className="page">
      <div className="safety-banner">
        <Icon name="shield" />
        <p>
          <strong>HerMediSafe supports—not replaces—your care team.</strong> Never stop or change a
          medicine without speaking to a qualified professional.
        </p>
      </div>

      <section className="welcome">
        <div>
          <p className="eyebrow">YOUR HEALTH OVERVIEW</p>
          <h1>
            {today.getHours() < 12 ? "Good morning" : today.getHours() < 17 ? "Good afternoon" : "Good evening"}
            , {user?.full_name.split(" ")[0]}.
          </h1>
          <p>One calm place to understand your medicines and care for yourself.</p>
        </div>
        <div className="date-card">
          <span>Today</span>
          <strong>{today.getDate()}</strong>
          <small>{today.toLocaleString(undefined, { month: "long" }).toUpperCase()}</small>
        </div>
      </section>

      {summary.error && (
        <Notice tone="error" icon="alert">
          Could not load your summary: {summary.error}
        </Notice>
      )}

      {counts && (
        <section className="stat-grid">
          <div>
            <span>Confirmed medicines</span>
            <strong>{counts.confirmed_active}</strong>
          </div>
          <div>
            <span>Awaiting your review</span>
            <strong>{counts.pending_review}</strong>
          </div>
          <div>
            <span>Suspected duplicates</span>
            <strong>{counts.unresolved_duplicates}</strong>
          </div>
          <div className={counts.high_severity_alerts ? "risk" : ""}>
            <span>Active alerts</span>
            <strong>{counts.active_alerts}</strong>
          </div>
        </section>
      )}

      <section className="section-heading">
        <div>
          <p className="eyebrow">SAFETY CHECK</p>
          <h2>Interaction alerts</h2>
        </div>
        <button className="btn ghost" onClick={() => open("safety")}>
          Open safety check <Icon name="arrow" size={15} />
        </button>
      </section>

      {summary.data && summary.data.active_alerts.length > 0 ? (
        <section className="alert-list">
          {summary.data.active_alerts.slice(0, 3).map((alert) => (
            <article className="alert-card" key={alert.id}>
              <div className="alert-head">
                <SeverityBadge severity={alert.severity} />
                <strong>{alert.medicines.join(" + ")}</strong>
              </div>
              <p>{alert.rationale}</p>
              <small>
                {alert.reviewed_by_professional
                  ? "Marked as reviewed by a professional"
                  : "Not yet reviewed by a professional"}
              </small>
            </article>
          ))}
        </section>
      ) : (
        <Notice tone="empty" icon="check">
          No active interaction alerts on your confirmed medicines right now.
        </Notice>
      )}

      <div className="section-heading">
        <div>
          <p className="eyebrow">CARE TOOLS</p>
          <h2>Everything you need, thoughtfully together</h2>
        </div>
        <p>Designed around real questions women ask every day.</p>
      </div>
      <section className="feature-grid">
        {features.map((feature) => (
          <button className="feature-card" key={feature.id} onClick={() => open(feature.id)}>
            <div className={`feature-icon ${feature.color}`}>
              <Icon name={feature.icon} size={23} />
            </div>
            <div>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
              <span>
                Open tool <Icon name="arrow" size={16} />
              </span>
            </div>
          </button>
        ))}
      </section>

      <section className="review-card">
        <div className="review-visual">
          <div className="paper one" />
          <div className="paper two" />
          <div className="scan-line" />
          <div className="scan-badge">
            <Icon name="check" size={16} /> {counts?.pending_review ? "Waiting for your review" : "Ready to review"}
          </div>
        </div>
        <div className="review-copy">
          <p className="eyebrow">MEDICINE RECONCILIATION</p>
          <h2>Bring every medicine into one clear view</h2>
          <p>
            Upload prescriptions from different doctors. We identify the medicines, then ask you to
            confirm every detail before checking for duplicates and possible interactions.
          </p>
          <div className="review-points">
            <span>
              <Icon name="check" /> You confirm every item
            </span>
            <span>
              <Icon name="check" /> Sources stay attached
            </span>
            <span>
              <Icon name="check" /> Uncertainty is clearly flagged
            </span>
          </div>
          <button className="primary-btn" onClick={() => open("prescriptions")}>
            <Icon name="upload" /> Upload a prescription
          </button>
          <small>Supports clear photos and PDFs</small>
        </div>
      </section>

      <footer>
        <img src={logo} alt="HerMediSafe" />
        <p>Private by design. Grounded in evidence. Always confirmed by you.</p>
        <span>© {today.getFullYear()} HerMediSafe</span>
      </footer>
    </div>
  );
}
