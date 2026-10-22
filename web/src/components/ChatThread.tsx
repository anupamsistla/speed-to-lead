import { useEffect, useRef, useState } from "react";
import { formatClock } from "../lib";
import type { Deferred, Message } from "../types";
import { EmptyState } from "./ui";

interface Props {
  messages: Message[];
  deferred?: Deferred[];
  /** The agent is mid-turn: show the typing indicator. */
  typing?: boolean;
  timeZone?: string;
  /** If given, a composer lets the demo operator reply as the lead. */
  onSend?: (text: string) => void;
  sending?: boolean;
  quickReplies?: string[];
}

const WHO: Record<Message["sender"] & string, { label: string; side: "left" | "right" }> = {
  lead: { label: "Lead", side: "left" },
  agent: { label: "Agent", side: "right" },
  human: { label: "Rep (human)", side: "right" },
};

export function ChatThread({
  messages,
  deferred = [],
  typing = false,
  timeZone,
  onSend,
  sending = false,
  quickReplies = [],
}: Props) {
  const end = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, deferred.length, typing]);

  const send = (text: string) => {
    const t = text.trim();
    if (!t || !onSend) return;
    onSend(t);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-slate-50 px-4 py-4"
        role="log"
        aria-label="Conversation"
        aria-live="polite"
      >
        {messages.length === 0 && deferred.length === 0 && !typing && (
          <EmptyState title="No messages yet" hint="Submit a lead to start the conversation." />
        )}

        {messages.map((m) => {
          const who = WHO[m.sender ?? "agent"];
          const mine = who.side === "right";
          return (
            <div key={m.id} className={`flex animate-rowIn flex-col ${mine ? "items-end" : "items-start"}`}>
              <div
                data-sender={m.sender}
                className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-snug ${
                  mine
                    ? m.sender === "human"
                      ? "rounded-br-sm bg-slate-800 text-white"
                      : "rounded-br-sm bg-brand text-brand-fg"
                    : "rounded-bl-sm bg-white text-slate-800 shadow-sm ring-1 ring-slate-200"
                }`}
              >
                {m.body}
              </div>
              <span className="mt-1 px-1 text-[11px] text-slate-400">
                {who.label} · {formatClock(m.created_at, timeZone)}
              </span>
            </div>
          );
        })}

        {deferred.map((d, i) => (
          <div key={`d${i}`} className="flex flex-col items-end">
            <div
              data-testid="deferred-message"
              className="max-w-[85%] rounded-2xl rounded-br-sm border border-dashed border-slate-300 bg-white px-3.5 py-2 text-sm text-slate-500"
            >
              {d.body}
            </div>
            <span className="mt-1 px-1 text-[11px] text-amber-600">
              Held for quiet hours · sends at {formatClock(d.deliver_after, timeZone)}
            </span>
          </div>
        ))}

        {typing && (
          <div className="flex items-start">
            <div
              role="status"
              aria-label="Agent is typing"
              className="flex items-center gap-1 rounded-2xl rounded-br-sm bg-white px-3.5 py-3 shadow-sm ring-1 ring-slate-200"
            >
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-1.5 w-1.5 animate-blink rounded-full bg-slate-400"
                  style={{ animationDelay: `${i * 0.2}s` }}
                />
              ))}
            </div>
          </div>
        )}
        <div ref={end} />
      </div>

      {onSend && (
        <div className="border-t border-slate-200 bg-white p-3">
          {quickReplies.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {quickReplies.map((q) => (
                <button
                  key={q}
                  type="button"
                  disabled={sending}
                  onClick={() => send(q)}
                  className="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              send(draft);
            }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Reply as the lead…"
              aria-label="Reply as the lead"
              className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
            <button
              type="submit"
              disabled={sending || !draft.trim()}
              className="rounded-lg bg-brand px-3.5 py-2 text-sm font-semibold text-brand-fg hover:bg-brand-strong disabled:opacity-50"
            >
              Send
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
