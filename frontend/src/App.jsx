import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
// A new session starts on every page load.
const newSessionId = () => "s-" + Math.random().toString(36).slice(2, 10);

function errorText(status, body) {
  if (status === 503) return "All AI providers are unavailable right now. Try again in a moment.";
  if (status === 422) return "That message was rejected. Messages must be 1–4000 characters.";
  return (typeof body?.detail === "string" && body.detail) || "Something went wrong. Please try again.";
}

export default function App() {
  const [sessionId] = useState(newSessionId);
  const [items, setItems] = useState([]);
  const [text, setText] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [items, busy]);

  async function send() {
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setItems((p) => [...p, { role: "user", content: message }]);
    setBusy(true);
    try {
      const headers = { "Content-Type": "application/json" };
      if (simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();
      const body = { session_id: sessionId, message };
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
      const res = await fetch(`${API}/chat`, { method: "POST", headers, body: JSON.stringify(body) });
      const data = await res.json().catch(() => null);
      if (res.ok) {
        setItems((p) => [...p, { role: "assistant", content: data.reply, meta: data.metadata }]);
      } else {
        setItems((p) => [...p, { role: "error", content: errorText(res.status, data) }]);
      }
    } catch {
      setItems((p) => [...p, { role: "error", content: "Cannot reach the server. Check your connection and try again." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>Resilient Chat</h1>
        <code title="Session id">{sessionId}</code>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>
          System prompt
          <textarea
            data-testid="system-prompt-input"
            rows={2}
            value={systemPrompt}
            placeholder="Optional. Overrides the default prompt for this session."
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </label>
        <label>
          Simulate failure (demo)
          <input value={simulate} placeholder="key_1=429" onChange={(e) => setSimulate(e.target.value)} />
        </label>
      </details>

      <main className="thread">
        {items.length === 0 && <p className="empty">Ask something. Send the same question again in a new tab to see a cache hit.</p>}
        {items.map((m, i) =>
          m.role === "assistant" ? (
            <article key={i} className="msg assistant" data-testid="assistant-message">
              <p>{m.content}</p>
              <dl className="meta">
                <div>
                  <dt>source</dt>
                  <dd data-testid="meta-source" className={m.meta.resolution_source === "LLM_CACHE" ? "cache" : "live"}>
                    {m.meta.resolution_source}
                  </dd>
                </div>
                <div><dt>model</dt><dd data-testid="meta-model">{m.meta.model}</dd></div>
                <div><dt>latency</dt><dd data-testid="meta-latency">{m.meta.latency_ms} ms</dd></div>
                <div><dt>in</dt><dd data-testid="meta-input-tokens">{m.meta.input_tokens}</dd></div>
                <div><dt>out</dt><dd data-testid="meta-output-tokens">{m.meta.output_tokens}</dd></div>
                <div><dt>key</dt><dd>{m.meta.key_id ?? "none"}{m.meta.fallback_attempts > 0 ? ` (+${m.meta.fallback_attempts} failed)` : ""}</dd></div>
              </dl>
            </article>
          ) : (
            <article key={i} className={`msg ${m.role}`} role={m.role === "error" ? "alert" : undefined}>
              <p>{m.content}</p>
            </article>
          )
        )}
        {busy && <p className="empty">Thinking…</p>}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea
          data-testid="chat-input"
          rows={2}
          value={text}
          placeholder="Type a message"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
        />
        <button data-testid="send-button" onClick={send} disabled={busy}>Send</button>
      </footer>
    </div>
  );
}
