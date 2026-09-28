import { useState, type FormEvent } from "react";
import { Icon } from "../components/Icon";
import { Notice } from "../components/ui";
import { useSession } from "../lib/session";
import logo from "../assets/hermedisafe-logo.svg";

function Logo() {
  return <img src={logo} className="h-12 w-auto" alt="HerMediSafe" />;
}

export default function SignIn() {
  const { login, signup } = useSession();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await signup(fullName, email, password);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const useDemoAccount = () => {
    setMode("login");
    setEmail("demo_pregnant@hermedisafe.org");
    setPassword("DemoUser123!");
    setError(null);
  };

  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-story-top">
          <Logo />
          <span>Evidence before explanation</span>
        </div>
        <div className="auth-story-copy">
          <p className="auth-kicker">MEDICINE SAFETY, DESIGNED FOR WOMEN</p>
          <h1>
            Every medicine.
            <br />
            One clearer story.
          </h1>
          <p>
            Bring fragmented prescriptions together, understand possible risks, and prepare for
            better conversations with your care team.
          </p>
          <div className="auth-trust-row">
            <span>
              <Icon name="shield" /> Private by design
            </span>
            <span>
              <Icon name="book" /> Evidence-grounded
            </span>
            <span>
              <Icon name="heart" /> You confirm every item
            </span>
          </div>
        </div>
        <div className="auth-mission">
          <span>
            <strong>6</strong> people
          </span>
          <i />
          <span>
            <strong>3</strong> institutions
          </span>
          <i />
          <span>
            <strong>1</strong> mission
          </span>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-form-wrap">
          <p className="eyebrow">WELCOME TO HERMEDISAFE</p>
          <h2>{mode === "login" ? "Sign in to your space" : "Create your space"}</h2>
          <p className="auth-subtitle">
            Your private space to manage medicines, review safety alerts, and care for your
            wellbeing.
          </p>
          <div className="single-role">
            <span className="role-icon">
              <Icon name="heart" />
            </span>
            <span>
              <strong>Personal health workspace</strong>
              <small>Designed for women and their trusted caregivers</small>
            </span>
          </div>

          <form className="auth-form" onSubmit={submit}>
            {mode === "signup" && (
              <label>
                Full name
                <input
                  required
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="Priya Sharma"
                />
              </label>
            )}
            <label>
              Email address
              <input
                required
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
              />
            </label>
            <label>
              Password
              <span className="password-field">
                <input
                  required
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={mode === "signup" ? "At least 8 characters" : "Enter your password"}
                  minLength={mode === "signup" ? 8 : 1}
                />
                <button type="button" onClick={() => setShowPassword(!showPassword)}>
                  {showPassword ? "Hide" : "Show"}
                </button>
              </span>
            </label>
            {error && (
              <Notice tone="error" icon="alert">
                {error}
              </Notice>
            )}
            <button className="primary-btn auth-submit" type="submit" disabled={busy}>
              {busy ? "Working…" : mode === "login" ? "Sign in securely" : "Create account"}
              <Icon name="arrow" />
            </button>
          </form>

          <p className="create-account">
            {mode === "login" ? "New to HerMediSafe?" : "Already have an account?"}{" "}
            <button onClick={() => setMode(mode === "login" ? "signup" : "login")}>
              {mode === "login" ? "Create a secure account" : "Sign in instead"}
            </button>
          </p>
          <p className="create-account">
            Reviewing a build? <button onClick={useDemoAccount}>Fill in the demo account</button>
          </p>
          <div className="auth-safety">
            <Icon name="shield" size={17} />
            <p>
              Your health information is stored in your own account and never used for advertising.
              Creating an account records DPDP consent with the API before any health data is saved.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
