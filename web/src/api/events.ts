import type { Message, Notification, StreamEvent, ToolCall, LeadSummary, LeadDetail } from "../types";

function upsertBy<T>(list: T[], item: T, key: (t: T) => string): T[] {
  const k = key(item);
  const i = list.findIndex((x) => key(x) === k);
  if (i === -1) return [...list, item];
  const next = list.slice();
  next[i] = item;
  return next;
}

const noteKey = (n: Notification) => `${n.kind}|${n.created_at}|${n.title}`;

/**
 * Apply one streamed event to the cached lead detail. Idempotent, because the stream replays
 * history on connect and the detail query may already contain the same records.
 * Fields the server computes (score, routing, CRM) are refreshed by refetching on `state`.
 */
export function reduceEvent(detail: LeadDetail | undefined, ev: StreamEvent): LeadDetail | undefined {
  if (!detail) return detail;
  switch (ev.type) {
    case "message":
      return { ...detail, messages: upsertBy(detail.messages, ev.data as unknown as Message, (m) => m.id) };
    case "tool_call":
      return {
        ...detail,
        tool_calls: upsertBy(detail.tool_calls, ev.data as unknown as ToolCall, (t) => t.id),
      };
    case "notification":
      return {
        ...detail,
        notifications: upsertBy(detail.notifications, ev.data as unknown as Notification, noteKey),
      };
    case "first_response": {
      const seconds = (ev.data as { seconds: number }).seconds;
      return { ...detail, summary: { ...detail.summary, first_response_seconds: seconds } };
    }
    case "state":
      return { ...detail, summary: ev.data as unknown as LeadSummary };
    default:
      return detail;
  }
}

/** Is the agent working? True from lead creation / an inbound message until the turn ends. */
export function reduceProcessing(processing: boolean, ev: StreamEvent): boolean {
  switch (ev.type) {
    case "lead_created":
      return true;
    case "message":
      return (ev.data as { direction?: string }).direction === "inbound" ? true : processing;
    case "turn_done":
    case "error":
      return false;
    default:
      return processing;
  }
}
