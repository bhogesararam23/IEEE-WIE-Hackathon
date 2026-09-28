import { FormEvent, useState } from "react";
import logo from "./assets/hermedisafe-logo.svg";

type IconName =
  | "home"
  | "sparkles"
  | "pill"
  | "heart"
  | "shield"
  | "bell"
  | "calendar"
  | "upload"
  | "search"
  | "plus"
  | "arrow"
  | "menu"
  | "close"
  | "check"
  | "message"
  | "book"
  | "alert";

const paths: Record<IconName, React.ReactNode> = {
  home: <><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10M9 20v-6h6v6"/></>,
  sparkles: <><path d="m12 3 1.3 3.7L17 8l-3.7 1.3L12 13l-1.3-3.7L7 8l3.7-1.3L12 3Z"/><path d="m5 14 .8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8L5 14Zm13-1 1 2.8 3 1.2-3 1.1L18 21l-1-2.9-3-1.1 3-1.2 1-2.8Z"/></>,
  pill: <><path d="M7.2 3.2a4.2 4.2 0 0 1 5.9 0l7.7 7.7a4.2 4.2 0 0 1-5.9 5.9l-7.7-7.7a4.2 4.2 0 0 1 0-5.9Z"/><path d="m10.4 12.3 5.9-5.9"/></>,
  heart: <path d="M20.8 5.7c-1.8-2.2-5.2-2.4-7.2-.4L12 6.9l-1.6-1.6a4.8 4.8 0 0 0-7.2.4c-1.6 2.2-1.2 5.2.7 7.1L12 21l8.1-8.2c1.9-1.9 2.3-4.9.7-7.1Z"/>,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-5"/></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4"/></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="1"/><path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"/></>,
  upload: <><path d="M12 16V3m0 0L7 8m5-5 5 5"/><path d="M5 14H3v7h18v-7h-2"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  arrow: <><path d="M5 12h14m-5-5 5 5-5 5"/></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  message: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z"/><path d="M8 9h8M8 13h5"/></>,
  book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5v14Z"/><path d="M8 7h8M8 11h6"/></>,
  alert: <><path d="M10.3 3.9 2.6 18a2 2 0 0 0 1.8 3h15.2a2 2 0 0 0 1.8-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 4h.01"/></>,
};

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

const nav = [
  { label: "Overview", icon: "home" as IconName },
  { label: "Ask HerMedi AI", icon: "sparkles" as IconName },
  { label: "My medicines", icon: "pill" as IconName },
  { label: "Wellbeing", icon: "heart" as IconName },
  { label: "Safety check", icon: "shield" as IconName },
  { label: "Reminders", icon: "bell" as IconName },
  { label: "Cycle tracker", icon: "calendar" as IconName },
];

const features = [
  { id: "question", icon: "message" as IconName, color: "coral", title: "Ask a health question", text: "Get a clear, evidence-grounded answer in simple language." },
  { id: "assistant", icon: "sparkles" as IconName, color: "pink", title: "HerMedi AI assistant", text: "Make sense of prescriptions and prepare questions for your doctor." },
  { id: "medicine", icon: "book" as IconName, color: "violet", title: "Medicine information", text: "Understand common uses, precautions and side effects." },
  { id: "support", icon: "heart" as IconName, color: "rose", title: "Emotional support", text: "A private check-in with gentle grounding exercises." },
  { id: "interaction", icon: "shield" as IconName, color: "plum", title: "Interaction checker", text: "Review medicines and supplements together for possible risks." },
  { id: "reminder", icon: "bell" as IconName, color: "peach", title: "Medicine reminders", text: "Create a simple routine so you never miss a dose." },
  { id: "period", icon: "calendar" as IconName, color: "berry", title: "Period tracker", text: "Log your cycle and understand your upcoming phases." },
];

function Logo() {
  return <img src={logo} className="h-12 w-auto" alt="HerMediSafe" />;
}

function SignIn({ onSignIn }: { onSignIn: () => void }) {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-story-top"><Logo /><span>Evidence before explanation</span></div>
        <div className="auth-story-copy">
          <p className="auth-kicker">MEDICINE SAFETY, DESIGNED FOR WOMEN</p>
          <h1>Every medicine.<br />One clearer story.</h1>
          <p>Bring fragmented prescriptions together, understand possible risks, and prepare for better conversations with your care team.</p>
          <div className="auth-trust-row">
            <span><Icon name="shield" /> Private by design</span>
            <span><Icon name="book" /> Evidence-grounded</span>
            <span><Icon name="heart" /> Human-reviewed</span>
          </div>
        </div>
        <div className="auth-mission">
          <span><strong>6</strong> people</span><i />
          <span><strong>3</strong> institutions</span><i />
          <span><strong>1</strong> mission</span>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-form-wrap">
          <p className="eyebrow">WELCOME TO HERMEDISAFE</p>
          <h2>Sign in to your space</h2>
          <p className="auth-subtitle">Your private space to manage medicines, ask health questions, and care for your wellbeing.</p>
          <div className="single-role">
            <span className="role-icon"><Icon name="heart" /></span>
            <span><strong>Personal health workspace</strong><small>Designed for women and their trusted caregivers</small></span>
          </div>

          <form className="auth-form" onSubmit={(event) => { event.preventDefault(); onSignIn(); }}>
            <label>Email address<input required type="email" placeholder="you@example.com" /></label>
            <label>Password
              <span className="password-field">
                <input required type={showPassword ? "text" : "password"} placeholder="Enter your password" minLength={6} />
                <button type="button" onClick={() => setShowPassword(!showPassword)}>{showPassword ? "Hide" : "Show"}</button>
              </span>
            </label>
            <div className="auth-form-meta"><label><input type="checkbox" /> Keep me signed in</label><button type="button">Forgot password?</button></div>
            <button className="primary-btn auth-submit" type="submit">Sign in securely <Icon name="arrow" /></button>
          </form>

          <p className="create-account">New to HerMediSafe? <button onClick={onSignIn}>Create a secure account</button></p>
          <div className="auth-safety"><Icon name="shield" size={17} /><p>Your health information is encrypted and never used for advertising. By continuing, you agree to our <button>Privacy Promise</button>.</p></div>
        </div>
      </section>
    </main>
  );
}

function ToolPage({ active, onBack }: { active: string; onBack: () => void }) {
  const feature = features.find((item) => item.id === active);
  const [result, setResult] = useState("");
  const [mood, setMood] = useState("");
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const toggleSymptom = (symptom: string) => setSymptoms((current) => current.includes(symptom) ? current.filter((item) => item !== symptom) : [...current, symptom]);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const messages: Record<string, string> = {
      question: "Your question is ready for HerMedi AI. A real product would answer from reviewed medical sources and show citations.",
      assistant: "I can help you organize this into a short summary and a list of questions to take to your clinician.",
      medicine: "Medicine found. Common uses and safety notes would appear here from a licensed medicine database.",
      interaction: "Review prepared. Never stop or change a medicine based on an app alert—confirm with a pharmacist or doctor.",
      reminder: "Reminder saved for your daily routine.",
      period: "Cycle logged. Your next period estimate has been added to the tracker.",
    };
    setResult(messages[active] || "Saved.");
  };

  if (!feature) return null;
  return (
    <div className="tool-page">
      <button className="tool-back" onClick={onBack}>← Back to overview</button>
      <div className="tool-layout">
        <section className="tool-main">
          <div className={`feature-icon ${feature.color}`}><Icon name={feature.icon} size={23} /></div>
          <p className="eyebrow">PRIVATE & SECURE</p>
          <h1>{feature.title}</h1>
          <p className="tool-intro">{feature.text}</p>

          {active === "support" ? (
            <div>
            <label className="field-label">How are you feeling right now?</label>
            <div className="mood-grid">
              {["Calm", "Low", "Anxious", "Overwhelmed"].map((item) => <button key={item} className={mood === item ? "selected" : ""} onClick={() => setMood(item)}>{item}</button>)}
            </div>
            {mood && <div className="result-box"><Icon name="heart" /><div><strong>Thank you for checking in.</strong><p>Try one slow breath: inhale for 4, hold for 2, and exhale for 6. You do not have to solve everything at once.</p></div></div>}
            <p className="crisis-note">If you may be in immediate danger or could hurt yourself, contact local emergency services or a trusted person now.</p>
            </div>
          ) : (
            <form onSubmit={submit}>
            {(active === "question" || active === "assistant") && <textarea required placeholder={active === "question" ? "What would you like to ask? Add relevant symptoms, timing and medicines…" : "Paste a prescription note or describe what you need help understanding…"} />}
            {active === "medicine" && <div className="input-with-icon"><Icon name="search" /><input required placeholder="Search a medicine, e.g. Metformin" /></div>}
            {active === "interaction" && <><label className="field-label">Medicines and supplements</label><input required placeholder="Medicine 1" /><input required placeholder="Medicine 2" /><button type="button" className="add-row"><Icon name="plus" size={16} /> Add another item</button></>}
            {active === "reminder" && <div className="form-grid"><label>Medicine<input required placeholder="Medicine name" /></label><label>Time<input required type="time" defaultValue="09:00" /></label><label>Frequency<select defaultValue="Daily"><option>Daily</option><option>Twice daily</option><option>Weekly</option></select></label><label>Start date<input required type="date" /></label></div>}
            {active === "period" && <div className="period-content">
              <div className="cycle-summary">
                <div className="cycle-ring"><span>DAY</span><strong>12</strong><small>of 28</small></div>
                <div><p className="eyebrow">CURRENT PHASE</p><h3>Follicular phase</h3><p>Energy may begin to rise as your body prepares for ovulation.</p></div>
              </div>
              <div className="cycle-stats"><div><span>Next period</span><strong>16 days</strong></div><div><span>Fertile window</span><strong>In 2 days</strong></div><div><span>Cycle pattern</span><strong>Regular</strong></div></div>
              <div className="form-grid"><label>Last period started<input required type="date" /></label><label>Usual cycle length<input required type="number" defaultValue="28" min="20" max="45" /></label><label>Period length<input required type="number" defaultValue="5" min="2" max="12" /></label><label>Flow today<select defaultValue="No flow"><option>No flow</option><option>Light</option><option>Medium</option><option>Heavy</option></select></label></div>
              <label className="field-label symptom-label">How are you feeling today?</label>
              <div className="symptom-chips">{["Cramps", "Headache", "Bloating", "Low mood", "Tiredness", "Good energy"].map((item) => <button type="button" key={item} className={symptoms.includes(item) ? "selected" : ""} onClick={() => toggleSymptom(item)}>{item}</button>)}</div>
              <div className="privacy-note"><Icon name="shield" size={17} /><p>Predictions are estimates, not medical advice or contraception. Your cycle data stays private.</p></div>
            </div>}
            <button className="primary-btn tool-submit" type="submit">{active === "reminder" || active === "period" ? "Save changes" : "Continue safely"} <Icon name="arrow" size={18} /></button>
            {result && <div className="result-box"><Icon name="check" /><p>{result}</p></div>}
            </form>
          )}
        </section>
        <aside className="tool-aside">
          <div><Icon name="shield" /><h3>Built for safe decisions</h3><p>HerMediSafe explains information clearly but never diagnoses, prescribes, or replaces your care team.</p></div>
          <div><Icon name="book" /><h3>Keep the full context</h3><p>Include medicine names, timing, symptoms, pregnancy or breastfeeding context when relevant.</p></div>
          {active === "period" && <div className="period-insight"><p className="eyebrow">THIS MONTH</p><h3>Your cycle insights</h3><ul><li>Average cycle: 28 days</li><li>Variation: 2 days</li><li>3 symptoms logged</li></ul></div>}
        </aside>
      </div>
    </div>
  );
}

export default function App() {
  const [active, setActive] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const open = (id: string) => { setActive(id); setMobileNav(false); };
  const profile = { name: "Hetvi", initials: "HK", label: "General profile", greeting: "Good morning, Hetvi." };

  if (!signedIn) {
    return <SignIn onSignIn={() => setSignedIn(true)} />;
  }

  return (
    <div className="app-shell">
      <aside className={mobileNav ? "sidebar open" : "sidebar"}>
        <div className="sidebar-logo"><Logo /></div>
        <nav>
          {nav.map((item, index) => {
            const destination = index ? ["assistant", "medicine", "support", "interaction", "reminder", "period"][index - 1] : "";
            return <button key={item.label} className={active === destination ? "nav-item active" : "nav-item"} onClick={() => index ? open(destination) : (setActive(""), setMobileNav(false))}><Icon name={item.icon} /><span>{item.label}</span></button>;
          })}
        </nav>
        <div className="trust-card">
          <div className="trust-icon"><Icon name="shield" /></div>
          <strong>Your health, protected</strong>
          <p>Your data stays private and is never used for advertising.</p>
          <button>Privacy promise <Icon name="arrow" size={14} /></button>
        </div>
        <div className="sidebar-profile"><div className="avatar">{profile.initials}</div><div><strong>{profile.name}</strong><span>{profile.label}</span></div><button aria-label="Sign out" title="Sign out" onClick={() => setSignedIn(false)}>Sign out</button></div>
      </aside>

      {mobileNav && <button className="nav-scrim" aria-label="Close menu" onClick={() => setMobileNav(false)} />}

      <main>
        <header>
          <button className="menu-btn" onClick={() => setMobileNav(true)} aria-label="Open menu"><Icon name="menu" /></button>
          <div className="mobile-logo"><Logo /></div>
          <div className="header-context"><span>Health context</span><button>General <span>⌄</span></button></div>
          <button className="notification-btn" aria-label="Notifications"><Icon name="bell" /><i /></button>
          <div className="header-avatar">{profile.initials}</div>
        </header>

        {active ? <ToolPage active={active} onBack={() => setActive("")} /> : <div className="page">
          <div className="safety-banner"><Icon name="shield" /><p><strong>HerMediSafe supports—not replaces—your care team.</strong> Never stop or change a medicine without speaking to a qualified professional.</p><button>Learn how we keep you safe</button></div>

          <section className="welcome">
            <div>
              <p className="eyebrow">YOUR HEALTH OVERVIEW</p>
              <h1>{profile.greeting}</h1>
              <p>One calm place to understand your medicines and care for yourself.</p>
            </div>
            <div className="date-card"><span>Today</span><strong>22</strong><small>SEPTEMBER</small></div>
          </section>

          <section className="ask-card">
            <div className="ask-copy"><div className="ai-mark"><Icon name="sparkles" size={25} /></div><div><p className="eyebrow">HERМEDI AI</p><h2>What can we help you understand?</h2><p>Ask about a medicine, a symptom, or prepare for your next appointment.</p></div></div>
            <button className="ask-input" onClick={() => open("question")}><span>Type your health question here…</span><span className="send-btn"><Icon name="arrow" /></span></button>
            <div className="prompt-row">{["Can these medicines be taken together?", "What is this medicine for?", "Help me prepare for my doctor"].map((text) => <button key={text} onClick={() => open(text.includes("together") ? "interaction" : text.includes("medicine for") ? "medicine" : "assistant")}>{text}</button>)}</div>
          </section>

          <div className="section-heading"><div><p className="eyebrow">CARE TOOLS</p><h2>Everything you need, thoughtfully together</h2></div><p>Designed around real questions women ask every day.</p></div>
          <section className="feature-grid">
            {features.map((feature) => <button className="feature-card" key={feature.id} onClick={() => open(feature.id)}><div className={`feature-icon ${feature.color}`}><Icon name={feature.icon} size={23} /></div><div><h3>{feature.title}</h3><p>{feature.text}</p><span>Open tool <Icon name="arrow" size={16} /></span></div></button>)}
          </section>

          <section className="review-card">
            <div className="review-visual">
              <div className="paper one" /><div className="paper two" />
              <div className="scan-line" />
              <div className="scan-badge"><Icon name="check" size={16} /> Ready to review</div>
            </div>
            <div className="review-copy"><p className="eyebrow">MEDICINE RECONCILIATION</p><h2>Bring every medicine into one clear view</h2><p>Upload prescriptions from different doctors. We’ll help identify the medicines, then ask you to confirm every detail before checking for duplicates and possible interactions.</p><div className="review-points"><span><Icon name="check" /> You confirm every item</span><span><Icon name="check" /> Sources stay attached</span><span><Icon name="check" /> Uncertainty is clearly flagged</span></div><button className="primary-btn" onClick={() => open("assistant")}><Icon name="upload" /> Upload a prescription</button><small>Supports clear photos and PDFs</small></div>
          </section>

          <footer><Logo /><p>Private by design. Grounded in evidence. Always human-reviewed.</p><span>© 2026 HerMediSafe</span></footer>
        </div>}
      </main>
    </div>
  );
}
