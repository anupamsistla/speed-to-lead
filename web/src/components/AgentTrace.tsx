import { useEffect, useRef, useState } from "react";
import type { ToolCall } from "../types";
import { EmptyState, ErrorState, Skeleton } from "./ui";

export type GuardrailEvent = { type: string; at: string; [k: string]: unknown };

interface Props {
  toolCalls: ToolCall[];
  guardrailEvents?: GuardrailEvent[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** The agent is mid-turn. */
  working?: boolean;
}

export function formatLatency(ms: number): string {
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

const clip = (s: string, n = 90) =>
  s.length > n ? `${s.slice(0, n - 1)}…` : s;

export function summarizeArgs(
  name: string,
  args: Record<string, unknown>,
): string {
  switch (name) {
    case "send_message":
      return clip(`"${String(args.body ?? "")}"`);
    case "score_lead":
      return clip(
        Object.entries((args.fields as Record<string, unknown>) ?? {})
          .map(([k, v]) => `${k}=${String(v)}`)
          .join(" "),
      );
    case "search_knowledge":
      return clip(`"${String(args.query ?? "")}"`);
    case "get_slots":
      return args.date ? String(args.date) : "next openings";
    case "book_appointment":
      return clip(String(args.slot_id ?? ""));
    case "update_crm":
      return `${String(args.stage_event ?? "created")}${args.outcome === "spam" ? " (spam)" : ""}`;
    case "escalate_to_human":
      return String(args.reason ?? "");
    case "notify_rep": {
      const flags = (args.flags as string[] | undefined)?.join(", ");
      return clip([args.note, flags].filter(Boolean).join(" · ") || "rep ping");
    }
    default: {
      const s = JSON.stringify(args);
      return s === "{}" ? "" : clip(s);
    }
  }
}

export function summarizeResult(
  name: string,
  r: Record<string, unknown>,
): string {
  if (typeof r.error === "string") return clip(r.error);
  switch (name) {
    case "send_message":
      return r.sent
        ? `sent${r.first_response_seconds != null ? ` (first reply ${r.first_response_seconds}s)` : ""}`
        : `held: ${String(r.blocked)}`;
    case "score_lead": {
      const s = r.score as { score: number; tier: string } | undefined;
      return s ? `${s.tier} ${s.score}/100` : "scored";
    }
    case "get_slots":
      return `${(r.slots as unknown[] | undefined)?.length ?? 0} slots`;
    case "book_appointment":
      return r.booked ? "booked" : "not booked";
    case "check_existing_contact":
      return r.exists ? "existing contact" : "new contact";
    case "search_knowledge":
      return r.found ? `${(r.hits as unknown[]).length} hits` : "no match";
    case "update_crm":
      return r.logged ? "logged (spam)" : `${String(r.stage ?? "")}`;
    case "notify_rep":
      return `${String(r.kind ?? "notified")} → ${String(r.channel ?? "")}`;
    case "escalate_to_human":
      return r.escalated ? "escalated" : "";
    default:
      return "";
  }
}

const GUARDRAIL_LABEL: Record<string, string> = {
  opt_out: "Opt-out recorded",
  claim_blocked: "Unsupported claim blocked",
  injection_detected: "Prompt-injection text flagged",
  backstop: "Safety net completed a step",
  human_takeover: "Human took over",
  agent_resumed: "Human handed back",
  llm_error: "Model unavailable",
  model_refusal: "Model declined",
  max_steps: "Step limit reached",
  ignored_after_opt_out: "Ignored message after opt-out",
  deferred_delivered: "Held message delivered",
};

function guardrailDetail(e: GuardrailEvent): string {
  if (e.type === "backstop") return String(e.name ?? "").replace(/_/g, " ");
  if (e.type === "claim_blocked")
    return (e.problems as string[] | undefined)?.join("; ") ?? "";
  if (e.type === "injection_detected")
    return (e.patterns as string[] | undefined)?.join(", ") ?? "";
  return "";
}

/** Handoff events are about people, not safety, so they get a timeline divider instead of a warning box. */
const HANDOFF_DETAIL: Record<string, string> = {
  human_takeover: "Agent is now silent",
  agent_resumed: "Agent active again",
};

function PersonIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      className="h-3.5 w-3.5"
      fill="currentColor"
      aria-hidden
    >
      <path d="M10 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 6.5C4 13.9 6.7 12 10 12s6 1.9 6 4.5c0 .3-.2.5-.5.5h-11a.5.5 0 0 1-.5-.5Z" />
    </svg>
  );
}

const SHOWN_EVENTS = new Set(Object.keys(GUARDRAIL_LABEL));

type Row =
  | { kind: "tool"; at: string; call: ToolCall }
  | { kind: "guardrail"; at: string; event: GuardrailEvent };

export function AgentTrace({
  toolCalls,
  guardrailEvents = [],
  loading,
  error,
  onRetry,
  working,
}: Props) {
  const end = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const rows: Row[] = [
    ...toolCalls.map((call): Row => ({
      kind: "tool",
      at: call.started_at,
      call,
    })),
    ...guardrailEvents
      .filter((e) => SHOWN_EVENTS.has(e.type))
      .map((event): Row => ({ kind: "guardrail", at: event.at, event })),
  ].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [rows.length]);

  if (error)
    return (
      <ErrorState
        message={error}
        onRetry={onRetry}
        title="Can't load the trace"
      />
    );
  if (loading) return <Skeleton lines={6} />;
  if (rows.length === 0) {
    return (
      <EmptyState
        title={working ? "Agent is starting…" : "No tool calls yet"}
        hint="Each step the agent takes will appear here as it happens."
      />
    );
  }

  const totalMs = toolCalls.reduce((sum, c) => sum + c.latency_ms, 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ol
        className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3"
        aria-label="Agent Trace"
      >
        {rows.map((row, i) =>
          row.kind === "guardrail" && row.event.type in HANDOFF_DETAIL ? (
            <li
              key={`h${i}`}
              data-kind="handoff"
              className="relative flex animate-rowIn items-center py-1.5"
            >
              <span
                className="absolute inset-x-0 top-1/2 border-t border-dashed border-indigo-200"
                aria-hidden
              />
              <span className="relative mx-auto flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 py-1 pl-1.5 pr-3 text-xs shadow-sm">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white">
                  <PersonIcon />
                </span>
                <span className="font-semibold text-indigo-900">
                  {GUARDRAIL_LABEL[row.event.type]}
                </span>
                <span className="text-indigo-700">
                  {HANDOFF_DETAIL[row.event.type]}
                </span>
              </span>
            </li>
          ) : row.kind === "guardrail" ? (
            <li
              key={`g${i}`}
              data-kind="guardrail"
              className="animate-rowIn rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs"
            >
              <span className="font-semibold text-amber-900">
                {GUARDRAIL_LABEL[row.event.type]}
              </span>
              {guardrailDetail(row.event) && (
                <span className="ml-1.5 text-amber-800">
                  {guardrailDetail(row.event)}
                </span>
              )}
            </li>
          ) : (
            <li
              key={row.call.id}
              data-kind="tool"
              data-error={row.call.error}
              className={`animate-rowIn rounded-lg border bg-white ${
                row.call.error ? "border-rose-200" : "border-slate-200"
              }`}
            >
              <button
                type="button"
                aria-expanded={!!open[row.call.id]}
                onClick={() =>
                  setOpen((o) => ({ ...o, [row.call.id]: !o[row.call.id] }))
                }
                className="flex w-full items-start gap-2 px-3 py-2 text-left"
              >
                <span
                  className={`mt-1 h-2 w-2 shrink-0 rounded-full ${row.call.error ? "bg-rose-500" : "bg-emerald-500"}`}
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-[13px] font-semibold text-slate-900">
                      {row.call.name}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-slate-500">
                      {formatLatency(row.call.latency_ms)}
                    </span>
                  </span>
                  <span className="block truncate text-xs text-slate-500">
                    {summarizeArgs(row.call.name, row.call.args)}
                  </span>
                  <span
                    className={`block truncate text-xs ${row.call.error ? "text-rose-700" : "text-slate-700"}`}
                  >
                    {summarizeResult(row.call.name, row.call.result) &&
                      `→ ${summarizeResult(row.call.name, row.call.result)}`}
                  </span>
                </span>
              </button>
              {open[row.call.id] && (
                <div className="space-y-2 border-t border-slate-100 px-3 py-2">
                  <div>
                    <p className="label">Arguments</p>
                    <pre className="mt-1 max-h-40 overflow-auto rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-800">
                      {JSON.stringify(row.call.args, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <p className="label">Result</p>
                    <pre className="mt-1 max-h-56 overflow-auto rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-800">
                      {JSON.stringify(row.call.result, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </li>
          ),
        )}
        {working && (
          <li
            className="flex items-center gap-2 px-3 py-1 text-xs text-slate-500"
            aria-label="Agent working"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />{" "}
            Working…
          </li>
        )}
        <div ref={end} />
      </ol>
      <footer className="flex justify-between border-t border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
        <span>{toolCalls.length} tool calls</span>
        <span>{formatLatency(totalMs)} in tools</span>
      </footer>
    </div>
  );
}
