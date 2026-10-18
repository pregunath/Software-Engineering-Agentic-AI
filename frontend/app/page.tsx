"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import { api, type ChatMessage, type ChatSession } from "../lib/api";

export default function ChatHomePage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    void api
      .listChatSessions()
      .then((listed) => {
        setSessions(listed);
        if (listed[0]) {
          setSessionId(listed[0].id);
          return api.listChatMessages(listed[0].id).then(setMessages);
        }
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function selectSession(id: number) {
    setSessionId(id);
    setError(null);
    try {
      setMessages(await api.listChatMessages(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load chat.");
    }
  }

  async function newChat() {
    setError(null);
    try {
      const session = await api.createChatSession();
      setSessions((current) => [session, ...current]);
      setSessionId(session.id);
      setMessages([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create chat.");
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!input.trim() || busy) return;
    const content = input.trim();
    setInput("");
    setBusy(true);
    setError(null);
    setMessages((current) => [...current, { id: Date.now(), role: "user", content }]);
    try {
      const result = await api.sendChatMessage(content, sessionId ?? undefined);
      setSessionId(result.session.id);
      setMessages(result.messages);
      setSessions((current) => {
        const others = current.filter((item) => item.id !== result.session.id);
        return [result.session, ...others];
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell mode="chat">
      <div className="chat-layout">
        <aside className="chat-history">
          <button type="button" className="btn toolbar-btn" onClick={() => void newChat()}>
            New chat
          </button>
          <ul>
            {sessions.map((session) => (
              <li key={session.id}>
                <button
                  type="button"
                  className={session.id === sessionId ? "active" : ""}
                  onClick={() => void selectSession(session.id)}
                >
                  {session.title}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="chat-stage">
          <header className="chat-hero">
            <span className="brand-mark">F</span>
            <h1>Forge</h1>
            <p>Ask anything about code. Switch to Agent mode to work on GitHub repositories.</p>
          </header>

          <div className="chat-thread">
            {messages.length === 0 && (
              <div className="chat-empty">
                <h2>How can I help you today?</h2>
              </div>
            )}
            {messages.map((message) => (
              <div key={message.id} className={`chat-bubble ${message.role}`}>
                <span>{message.role === "user" ? "You" : "Forge"}</span>
                <p>{message.content}</p>
              </div>
            ))}
            {busy && <div className="chat-bubble assistant pending">Forge is thinking…</div>}
            <div ref={endRef} />
          </div>

          {error && <p className="workspace-error">{error}</p>}

          <form className="chat-composer" onSubmit={onSubmit}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              rows={2}
              placeholder="Message Forge…"
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void onSubmit(event);
                }
              }}
            />
            <button className="btn toolbar-btn" type="submit" disabled={busy || !input.trim()}>
              Send
            </button>
          </form>
        </section>
      </div>
    </AppShell>
  );
}
