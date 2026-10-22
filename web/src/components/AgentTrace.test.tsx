import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { at, toolCall } from "../test/fakes";
import { AgentTrace, formatLatency, summarizeArgs, summarizeResult } from "./AgentTrace";

const calls = [
  toolCall({ id: "t1", name: "check_existing_contact", started_at: at(0), latency_ms: 0.3 }),
  toolCall({
    id: "t2",
    name: "score_lead",
    args: { fields: { zip: "80205", homeowner: "owner" } },
    result: { score: { score: 90, tier: "hot" } },
    started_at: at(1),
    latency_ms: 12.4,
  }),
  toolCall({
    id: "t3",
    name: "book_appointment",
    args: { slot_id: "nope" },
    result: { error: "unknown slot_id" },
    started_at: at(2),
    latency_ms: 1500,
    error: true,
  }),
];

describe("AgentTrace", () => {
  it("shows an empty state before the agent does anything", () => {
    render(<AgentTrace toolCalls={[]} />);
    expect(screen.getByText("No tool calls yet")).toBeInTheDocument();
  });

  it("says the agent is starting when work has begun", () => {
    render(<AgentTrace toolCalls={[]} working />);
    expect(screen.getByText("Agent is starting…")).toBeInTheDocument();
  });

  it("has loading and error states, and the error can be retried", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { rerender } = render(<AgentTrace toolCalls={[]} loading />);
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    rerender(<AgentTrace toolCalls={[]} error="Cannot reach the API." onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Cannot reach the API.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("lists tool calls in the order they happened with readable summaries and latency", () => {
    render(<AgentTrace toolCalls={[...calls].reverse()} />);
    const rows = within(screen.getByRole("list", { name: "Agent trace" })).getAllByRole("listitem");
    expect(rows.map((r) => within(r).getAllByText(/^[a-z_]+$/)[0].textContent)).toEqual([
      "check_existing_contact",
      "score_lead",
      "book_appointment",
    ]);
    expect(rows[1]).toHaveTextContent("zip=80205 homeowner=owner");
    expect(rows[1]).toHaveTextContent("→ hot 90/100");
    expect(rows[0]).toHaveTextContent("<1 ms");
    expect(rows[1]).toHaveTextContent("12 ms");
    expect(rows[2]).toHaveTextContent("1.5 s");
  });

  it("marks a failed call as an error", () => {
    render(<AgentTrace toolCalls={calls} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows[2]).toHaveAttribute("data-error", "true");
    expect(rows[2]).toHaveTextContent("→ unknown slot_id");
    expect(rows[0]).toHaveAttribute("data-error", "false");
  });

  it("expands a row to show the full arguments and result", async () => {
    const user = userEvent.setup();
    render(<AgentTrace toolCalls={calls} />);
    const toggle = screen.getAllByRole("button", { expanded: false })[1];
    expect(screen.queryByText("Arguments")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Arguments")).toBeInTheDocument();
    expect(screen.getByText(/"homeowner": "owner"/)).toBeInTheDocument();
    expect(screen.getByText(/"tier": "hot"/)).toBeInTheDocument();
    await user.click(toggle);
    expect(screen.queryByText("Arguments")).not.toBeInTheDocument();
  });

  it("adds new rows as they stream in", () => {
    const { rerender } = render(<AgentTrace toolCalls={calls.slice(0, 1)} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    rerender(<AgentTrace toolCalls={calls} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("shows guardrail actions between tool calls", () => {
    render(
      <AgentTrace
        toolCalls={calls.slice(0, 2)}
        guardrailEvents={[
          { type: "claim_blocked", at: at(0.5), problems: ["price $18,000 is not in the knowledge base"] },
          { type: "backstop", at: at(5), name: "holding_reply" },
          { type: "lead_received", at: at(0) }, // not a guardrail, hidden
        ]}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveAttribute("data-kind", "guardrail");
    expect(rows[1]).toHaveTextContent("Unsupported claim blocked");
    expect(rows[1]).toHaveTextContent("$18,000");
    expect(rows[3]).toHaveTextContent("Safety net completed a step");
    expect(rows[3]).toHaveTextContent("holding reply");
  });

  it("totals the calls and tool time", () => {
    render(<AgentTrace toolCalls={calls} />);
    expect(screen.getByText("3 tool calls")).toBeInTheDocument();
    expect(screen.getByText("1.5 s in tools")).toBeInTheDocument();
  });

  it("shows a working indicator mid-turn", () => {
    render(<AgentTrace toolCalls={calls} working />);
    expect(screen.getByLabelText("Agent working")).toBeInTheDocument();
  });
});

describe("summaries", () => {
  it("formats latency", () => {
    expect(formatLatency(0.2)).toBe("<1 ms");
    expect(formatLatency(42.4)).toBe("42 ms");
    expect(formatLatency(2500)).toBe("2.5 s");
  });

  it("summarizes arguments", () => {
    expect(summarizeArgs("send_message", { body: "Hello" })).toBe('"Hello"');
    expect(summarizeArgs("get_slots", {})).toBe("next openings");
    expect(summarizeArgs("get_slots", { date: "2026-10-29" })).toBe("2026-10-29");
    expect(summarizeArgs("update_crm", { summary: "x", stage_event: "booked" })).toBe("booked");
    expect(summarizeArgs("update_crm", { summary: "x", outcome: "spam" })).toBe("created (spam)");
    expect(summarizeArgs("notify_rep", { note: "Hot", flags: ["pricing_question"] })).toBe("Hot · pricing_question");
    expect(summarizeArgs("check_existing_contact", {})).toBe("");
    expect(summarizeArgs("send_message", { body: "x".repeat(200) }).length).toBeLessThanOrEqual(90);
  });

  it("summarizes results", () => {
    expect(summarizeResult("send_message", { sent: true, first_response_seconds: 6.7 })).toBe("sent (first reply 6.7s)");
    expect(summarizeResult("send_message", { sent: false, blocked: "quiet_hours" })).toBe("held: quiet_hours");
    expect(summarizeResult("get_slots", { slots: [1, 2, 3] })).toBe("3 slots");
    expect(summarizeResult("search_knowledge", { found: false })).toBe("no match");
    expect(summarizeResult("check_existing_contact", { exists: true })).toBe("existing contact");
    expect(summarizeResult("anything", { error: "boom" })).toBe("boom");
  });
});
