import { detail, message, notification, toolCall, T0 } from "../test/fakes";
import type { StreamEvent } from "../types";
import { reduceEvent, reduceProcessing } from "./events";

const ev = (type: StreamEvent["type"], data: Record<string, unknown>, id = 1): StreamEvent => ({
  id,
  type,
  lead_id: "ld_1",
  company: "acme",
  at: T0,
  data,
});

describe("reduceEvent", () => {
  it("returns undefined until the detail has loaded", () => {
    expect(reduceEvent(undefined, ev("message", {}))).toBeUndefined();
  });

  it("appends new messages and ignores replays of ones it already has", () => {
    const d = detail({ messages: [message({ id: "a" })] });
    const next = reduceEvent(d, ev("message", message({ id: "b", body: "second" })))!;
    expect(next.messages.map((m) => m.id)).toEqual(["a", "b"]);
    const again = reduceEvent(next, ev("message", message({ id: "b", body: "second" })))!;
    expect(again.messages).toHaveLength(2);
  });

  it("updates an existing message in place (a deferred one that was later sent)", () => {
    const d = detail({ messages: [message({ id: "a", sent: false })] });
    const next = reduceEvent(d, ev("message", message({ id: "a", sent: true })))!;
    expect(next.messages).toHaveLength(1);
    expect(next.messages[0].sent).toBe(true);
  });

  it("streams tool calls in and dedupes by id", () => {
    let d = detail({ tool_calls: [] });
    d = reduceEvent(d, ev("tool_call", toolCall({ id: "t1" })))!;
    d = reduceEvent(d, ev("tool_call", toolCall({ id: "t2", name: "score_lead" })))!;
    d = reduceEvent(d, ev("tool_call", toolCall({ id: "t1" })))!;
    expect(d.tool_calls.map((t) => t.name)).toEqual(["check_existing_contact", "score_lead"]);
  });

  it("dedupes notifications", () => {
    let d = detail();
    d = reduceEvent(d, ev("notification", notification()))!;
    d = reduceEvent(d, ev("notification", notification()))!;
    d = reduceEvent(d, ev("notification", notification({ kind: "booked", title: "Booked", created_at: T0 })))!;
    expect(d.notifications).toHaveLength(2);
  });

  it("records the first response and state summaries", () => {
    let d = detail({ summary: { ...detail().summary, first_response_seconds: null } });
    d = reduceEvent(d, ev("first_response", { seconds: 38 }))!;
    expect(d.summary.first_response_seconds).toBe(38);
    d = reduceEvent(d, ev("state", { ...d.summary, status: "booked", booked: true }))!;
    expect(d.summary.status).toBe("booked");
  });

  it("leaves everything else alone", () => {
    const d = detail();
    expect(reduceEvent(d, ev("turn_done", { duration_ms: 5 }))).toBe(d);
  });
});

describe("reduceProcessing", () => {
  it("is on from lead creation or an inbound message until the turn ends", () => {
    let on = reduceProcessing(false, ev("lead_created", {}));
    expect(on).toBe(true);
    on = reduceProcessing(on, ev("tool_call", {}));
    expect(on).toBe(true);
    expect(reduceProcessing(on, ev("turn_done", {}))).toBe(false);
    expect(reduceProcessing(on, ev("error", {}))).toBe(false);
    expect(reduceProcessing(false, ev("message", { direction: "inbound" }))).toBe(true);
  });

  it("an outbound message does not start work", () => {
    expect(reduceProcessing(false, ev("message", { direction: "outbound" }))).toBe(false);
    expect(reduceProcessing(true, ev("message", { direction: "outbound" }))).toBe(true);
  });
});
