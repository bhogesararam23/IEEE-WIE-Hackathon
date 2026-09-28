import { useState } from "react";
import { Icon } from "./components/Icon";
import { nav, type ScreenId } from "./lib/navigation";
import { CONTEXT_LABELS, initials } from "./lib/format";
import { useSession } from "./lib/session";
import Medicines from "./screens/Medicines";
import Overview from "./screens/Overview";
import Prescriptions from "./screens/Prescriptions";
import ProfileModal from "./screens/ProfileModal";
import { AskHermi, CycleTracker } from "./screens/LocalTools";
import Reminders from "./screens/Reminders";
import Report from "./screens/Report";
import Safety from "./screens/Safety";
import SignIn from "./screens/SignIn";
import logo from "./assets/hermedisafe-logo.svg";

function Loading() {
  return (
    <main className="splash">
      <img src={logo} alt="HerMediSafe" />
      <p>Checking your session…</p>
    </main>
  );
}

export default function App() {
  const { status, user, logout } = useSession();
  const [screen, setScreen] = useState<ScreenId>("overview");
  const [mobileNav, setMobileNav] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

  if (status === "loading") return <Loading />;
  if (status === "anonymous" || !user) return <SignIn />;

  const open = (next: ScreenId) => {
    setScreen(next);
    setMobileNav(false);
  };

  const contextLabel = user.profile ? CONTEXT_LABELS[user.profile.context_type] : "Not set";

  return (
    <div className="app-shell">
      <aside className={mobileNav ? "sidebar open" : "sidebar"}>
        <div className="sidebar-logo">
          <img src={logo} alt="HerMediSafe" />
        </div>
        <nav>
          {nav.map((item) => (
            <button
              key={item.id}
              className={screen === item.id ? "nav-item active" : "nav-item"}
              onClick={() => open(item.id)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="trust-card">
          <div className="trust-icon">
            <Icon name="shield" />
          </div>
          <strong>Your health, protected</strong>
          <p>Your data stays in your account and is never used for advertising.</p>
          <button onClick={() => open("report")}>
            See your audit trail <Icon name="arrow" size={14} />
          </button>
        </div>
        <div className="sidebar-profile">
          <div className="avatar">{initials(user.full_name)}</div>
          <div>
            <strong>{user.full_name}</strong>
            <span>{contextLabel}</span>
          </div>
          <button onClick={logout}>Sign out</button>
        </div>
      </aside>

      {mobileNav && <button className="nav-scrim" aria-label="Close menu" onClick={() => setMobileNav(false)} />}

      <main>
        <header>
          <button className="menu-btn" onClick={() => setMobileNav(true)} aria-label="Open menu">
            <Icon name="menu" />
          </button>
          <div className="mobile-logo">
            <img src={logo} alt="HerMediSafe" />
          </div>
          <div className="header-context">
            <span>Health context</span>
            <button onClick={() => setProfileOpen(true)}>
              {contextLabel} <span>⌄</span>
            </button>
          </div>
          <button className="notification-btn" aria-label="Safety alerts" onClick={() => open("safety")}>
            <Icon name="bell" />
            <i />
          </button>
          <div className="header-avatar">{initials(user.full_name)}</div>
        </header>

        {screen === "overview" && <Overview open={open} />}
        {screen === "ask" && <AskHermi />}
        {screen === "prescriptions" && <Prescriptions />}
        {screen === "medicines" && <Medicines />}
        {screen === "safety" && <Safety />}
        {screen === "reminders" && <Reminders />}
        {screen === "report" && <Report />}
        {screen === "cycle" && <CycleTracker />}
      </main>

      {profileOpen && <ProfileModal onClose={() => setProfileOpen(false)} />}
    </div>
  );
}
