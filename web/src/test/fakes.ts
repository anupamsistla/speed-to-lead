import type { CompanyConfig, LeadDetail, Message, Notification, ToolCall } from "../types";

export const T0 = "2026-10-27T16:00:00Z"; // 10:00 in Denver
export const at = (sec: number) => new Date(Date.parse(T0) + sec * 1000).toISOString();

export function message(over: Partial<Message> = {}): Message {
  return {
    id: "m1",
    lead_id: "ld_1",
    direction: "outbound",
    body: "Hi Jamie, thanks for reaching out!",
    created_at: at(1),
    sent: true,
    sender: "agent",
    ...over,
  };
}

export function toolCall(over: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "t1",
    lead_id: "ld_1",
    name: "check_existing_contact",
    args: {},
    result: { exists: false },
    latency_ms: 0.4,
    started_at: at(0),
    error: false,
    ...over,
  };
}

export function notification(over: Partial<Notification> = {}): Notification {
  return {
    kind: "hot_lead",
    channel: "#new-leads",
    title: "Hot lead: Jamie Rivera",
    fields: { Score: "90/100 (hot)", Office: "Denver Office" },
    note: "Wants to move fast",
    mention: "Maya Ortiz",
    priority: "urgent",
    lead_id: "ld_1",
    rep_id: "maya_ortiz",
    created_at: at(3),
    ...over,
  };
}

export function config(over: Partial<CompanyConfig> = {}): CompanyConfig {
  return {
    slug: "acme",
    name: "Acme Co",
    description: "A test company.",
    brand_color: "#1D4ED8",
    logo_url: "/api/companies/acme/logo",
    timezone: "America/Denver",
    tone: "Friendly.",
    reply_signature: "Acme Team",
    hot_lead_threshold: 70,
    warm_lead_threshold: 40,
    appointment_kind: "free consultation",
    appointment_minutes: 60,
    fields: [
      { key: "zip", question: "What's your zip?", type: "zip", options: [] },
      { key: "homeowner", question: "Own or rent?", type: "choice", options: ["owner", "renter"] },
      { key: "timeline", question: "When?", type: "choice", options: ["asap", "researching"] },
    ],
    offices: [{ id: "denver", name: "Denver Office", reps: 4 }],
    slack_channel: "#new-leads",
    crm_pipeline: "Sales",
    ...over,
  };
}

export function detail(over: Partial<LeadDetail> = {}): LeadDetail {
  return {
    summary: {
      id: "ld_1",
      company: "acme",
      name: "Jamie Rivera",
      phone: "+13035550142",
      source: "web_form",
      created_at: T0,
      status: "in_progress",
      score: 90,
      tier: "hot",
      first_response_seconds: 38.2,
      consent: "unknown",
      booked: false,
      escalated: false,
    },
    lead: {
      id: "ld_1",
      name: "Jamie Rivera",
      phone: "+13035550142",
      email: "jamie@example.com",
      source: "web_form",
      message: "Interested",
      created_at: T0,
    },
    messages: [message({ id: "m0", direction: "inbound", sender: "lead", body: "Interested", created_at: at(0) }), message()],
    answers: { zip: "80205", homeowner: "owner" },
    missing_fields: ["timeline"],
    score: {
      score: 90,
      tier: "hot",
      breakdown: [
        { rule: "homeowner", points: 25 },
        { rule: "timeline_asap", points: 25 },
        { rule: "bill_200_plus", points: 40 },
      ],
      complete: true,
      missing_fields: [],
      disqualified_reason: null,
      disqualified_by: null,
      close_message: null,
    },
    routing: {
      office_id: "denver",
      office_name: "Denver Office",
      rep_id: "maya_ortiz",
      rep_name: "Maya Ortiz",
      reason: "Zip 80205 is served by Denver Office. Rep assigned by round robin.",
    },
    booking: null,
    crm: {
      contact_id: null,
      pipeline: "Sales",
      stage: null,
      synced: false,
      properties: { zip: "80205", lead_score: 90 },
    },
    notifications: [],
    tool_calls: [],
    flags: [],
    events: [],
    deferred: [],
    ...over,
  };
}

type Listener = (e: MessageEvent) => void;

/** Minimal EventSource stand-in: tests push events with `emit`. */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  onerror: ((e: Event) => void) | null = null;
  onopen: ((e: Event) => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, l: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), l]);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown, id = 1) {
    const ev = { id, type, lead_id: "ld_1", company: "acme", at: T0, data };
    for (const l of this.listeners.get(type) ?? []) l({ data: JSON.stringify(ev) } as MessageEvent);
  }
  open() {
    this.onopen?.(new Event("open"));
  }
  static reset() {
    FakeEventSource.instances = [];
  }
}
