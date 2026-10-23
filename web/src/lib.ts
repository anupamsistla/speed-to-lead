import type { Deferred, LeadDetail, LeadStatus, Score } from "./types";

export type ChatNotice = { id: string; at: string; text: string };

/** Small in-thread lines for handoffs, like "Maya Ortiz from Sales has joined the chat". */
export function handoffNotices(detail: LeadDetail | undefined): ChatNotice[] {
  if (!detail) return [];
  const rep = detail.routing.rep_name;
  const who = rep ? `${rep} from Sales` : "A member of our Sales team";
  const out: ChatNotice[] = [];
  detail.events.forEach((e, i) => {
    const at = String((e as { at?: unknown }).at ?? "");
    if (e.type === "human_takeover") out.push({ id: `n${i}`, at, text: `${who} has taken over the chat` });
    if (e.type === "agent_resumed") {
      out.push({ id: `n${i}`, at, text: `${who} has left the chat` });
    }
  });
  return out;
}

export function formatClock(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(new Date(iso));
}

export function formatDateTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(new Date(iso));
}

export function formatSeconds(s: number): string {
  return s < 10 ? `${s.toFixed(1)}s` : s < 100 ? `${Math.round(s * 10) / 10}s` : `${Math.round(s)}s`;
}

/** 38 -> "38s", 3600 -> "1h 0m", for long queued waits. */
export function formatDuration(s: number): string {
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

export const TIER_STYLE: Record<NonNullable<Score["tier"]>, { label: string; cls: string }> = {
  hot: { label: "Hot", cls: "bg-rose-100 text-rose-800 ring-rose-200" },
  warm: { label: "Warm", cls: "bg-amber-100 text-amber-800 ring-amber-200" },
  cold: { label: "Cold", cls: "bg-sky-100 text-sky-800 ring-sky-200" },
  disqualified: { label: "Disqualified", cls: "bg-slate-200 text-slate-700 ring-slate-300" },
};

export const STATUS_LABEL: Record<LeadStatus, string> = {
  new: "New",
  in_progress: "In progress",
  booked: "Booked",
  escalated: "Needs a human",
  closed: "Closed",
  spam: "Spam",
  opted_out: "Opted out",
  human: "Human took over",
};

const ACRONYMS = new Set(["asap", "crm", "sms", "faq", "apr", "ltv"]);

export function humanize(key: string): string {
  // 1_3_months reads as "1-3 months", not "1 3 months"
  const words = key
    .replace(/(?<=\d)_plus\b/g, "+")
    .replace(/(?<=\d)_(?=\d)/g, "-").replace(/_/g, " ").split(" ");
  const out = words.map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w));
  const s = out.join(" ");
  return ACRONYMS.has(words[0].toLowerCase()) ? s : s.charAt(0).toUpperCase() + s.slice(1);
}

export function earliestDeliver(deferred: Deferred[]): string | null {
  if (!deferred.length) return null;
  return deferred.map((d) => d.deliver_after).sort()[0];
}
