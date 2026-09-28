import { useState } from "react";
import { Icon } from "../components/Icon";
import { ActionButton, Notice, ScreenHeader } from "../components/ui";

/**
 * Cycle tracking and the AI question box have no backend endpoints yet — the
 * Round 1 brief scoped the API to reconciliation and safety. These screens keep
 * the design prototype's behaviour and say so, rather than pretending to save.
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

/** The AI question box has no retrieval service wired up either. */
export function AskHermi() {
  const [question, setQuestion] = useState("");
  const [answered, setAnswered] = useState(false);

  return (
    <div className="tool-page">
      <div className="tool-layout">
        <section className="tool-main">
          <ScreenHeader
            eyebrow="HERMEDI AI"
            title="Ask a health question"
            intro="Retrieval over reviewed sources is the AI teammate's boundary. This box records the question and hands off to that service."
            icon="sparkles"
            color="pink"
          />
          <OfflineBanner />
          <label className="field-label">Your question</label>
          <textarea
            placeholder="Can these medicines be taken together? What is this medicine for?"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <ActionButton tone="solid" onClick={() => setAnswered(true)} disabled={!question.trim()}>
            Continue safely <Icon name="arrow" size={18} />
          </ActionButton>
          {answered && (
            <div className="result-box">
              <Icon name="alert" />
              <p>
                No answer service is attached to this build yet. Your medicines, alerts and report are
                live — this screen is the handoff point the AI teammate fills in.
              </p>
            </div>
          )}
        </section>
        <aside className="tool-aside">
          <div>
            <Icon name="shield" />
            <h3>Evidence before explanation</h3>
            <p>Answers are expected to cite the source they came from, the same way alerts do.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
