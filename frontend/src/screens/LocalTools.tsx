import { useState } from "react";
import { Icon } from "../components/Icon";
import { ActionButton, Notice, ScreenHeader } from "../components/ui";
import { api, type AssistantLanguage } from "../lib/api";

/**
 * Cycle tracking has no backend endpoint yet -- the Round 1 brief scoped the
 * API to reconciliation and safety. This screen keeps the design prototype's
 * behaviour and says so, rather than pretending to save.
 */
function OfflineBanner() {
  return (
    <Notice tone="info" icon="alert">
      Design prototype. Nothing you enter here reaches the HerMediSafe API yet.
    </Notice>
  );
}

export function CycleTracker() {
  const [saved, setSaved] = useState(false);
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const toggle = (item: string) =>
    setSymptoms((current) =>
      current.includes(item) ? current.filter((value) => value !== item) : [...current, item],
    );

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="CYCLE"
            title="Period tracker"
            intro="Log your cycle and see the phases ahead. Estimates only — never contraception advice."
            icon="calendar"
            color="berry"
          />
          <OfflineBanner />
          <div className="period-content">
            <div className="cycle-summary">
              <div className="cycle-ring">
                <span>DAY</span>
                <strong>12</strong>
                <small>of 28</small>
              </div>
              <div>
                <p className="eyebrow">CURRENT PHASE</p>
                <h3>Follicular phase</h3>
                <p>Energy may begin to rise as your body prepares for ovulation.</p>
              </div>
            </div>
            <div className="cycle-stats">
              <div>
                <span>Next period</span>
                <strong>16 days</strong>
              </div>
              <div>
                <span>Fertile window</span>
                <strong>In 2 days</strong>
              </div>
              <div>
                <span>Cycle pattern</span>
                <strong>Regular</strong>
              </div>
            </div>
            <div className="form-grid">
              <label>
                Last period started
                <input type="date" />
              </label>
              <label>
                Usual cycle length
                <input type="number" defaultValue={28} min={20} max={45} />
              </label>
              <label>
                Period length
                <input type="number" defaultValue={5} min={2} max={12} />
              </label>
              <label>
                Flow today
                <select defaultValue="No flow">
                  {["No flow", "Light", "Medium", "Heavy"].map((option) => (
                    <option key={option}>{option}</option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field-label symptom-label">How are you feeling today?</label>
            <div className="symptom-chips">
              {["Cramps", "Headache", "Bloating", "Low mood", "Tiredness", "Good energy"].map((item) => (
                <button key={item} className={symptoms.includes(item) ? "selected" : ""} onClick={() => toggle(item)}>
                  {item}
                </button>
              ))}
            </div>
            <ActionButton tone="solid" onClick={() => setSaved(true)}>
              Save to this device
            </ActionButton>
            {saved && (
              <div className="result-box">
                <Icon name="check" />
                <p>Stored in this browser tab only. Nothing was sent to the API.</p>
              </div>
            )}
            <div className="privacy-note">
              <Icon name="shield" size={17} />
              <p>Predictions are estimates, not medical advice or contraception. Your cycle data stays private.</p>
            </div>
          </div>
        </section>
        <aside className="tool-aside">
          <div>
            <Icon name="book" />
            <h3>Why it is not saved</h3>
            <p>The backend has no cycle endpoints yet, so this screen keeps the prototype's behaviour.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}

const LANGUAGES: [AssistantLanguage, string][] = [
  ["en", "English"],
  ["hi", "हिन्दी"],
];

/** Ask HerMedi AI: a real, grounded answer from POST /assistant/ask. */
export function AskHermi() {
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState<AssistantLanguage>("en");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ answer: string; disclaimer: string; model_used: string } | null>(
    null,
  );

  const ask = async () => {
    if (!question.trim()) return;
    setAsking(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.askAssistant(question.trim(), language));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That question could not be answered");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="HERMEDI AI"
            title="Ask a health question"
            intro="Grounded in your own maternal context, confirmed medicines, and active safety alerts. Never a diagnosis or a prescription."
            icon="sparkles"
            color="pink"
          />
          <label className="field-label">Answer in</label>
          <div className="symptom-chips">
            {LANGUAGES.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={language === value ? "selected" : ""}
                onClick={() => setLanguage(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="field-label">Your question</label>
          <textarea
            placeholder="Can these medicines be taken together? What is this medicine for?"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <ActionButton tone="solid" onClick={ask} disabled={!question.trim() || asking}>
            {asking ? "Asking…" : "Ask HerMedi AI"} <Icon name="arrow" size={18} />
          </ActionButton>
          {error && <Notice tone="error">{error}</Notice>}
          {result && (
            <div className="result-box">
              <Icon name="sparkles" />
              <div>
                <p>{result.answer}</p>
                <div className="privacy-note">
                  <Icon name="shield" size={17} />
                  <p>{result.disclaimer}</p>
                </div>
              </div>
            </div>
          )}
        </section>
        <aside className="tool-aside">
          <div>
            <Icon name="shield" />
            <h3>Evidence before explanation</h3>
            <p>Answers are grounded in your safety data and never override a HIGH severity alert.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
