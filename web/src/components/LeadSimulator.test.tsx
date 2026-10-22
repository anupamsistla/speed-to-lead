import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { detail } from "../test/fakes";
import type { ScenarioBrief } from "../types";
import { EMPTY_FORM, LeadSimulator, toLeadIn, validateLead } from "./LeadSimulator";
import { ScenarioReplay } from "./ScenarioReplay";

const scenarios: ScenarioBrief[] = [
  { id: "hot", title: "Hot lead books", description: "All info up front.", company: "acme", source: "web_form", followups: 1, clock: null },
  { id: "stop", title: "Lead texts STOP", description: "", company: "acme", source: "text", followups: 0, clock: null },
];

function setup(over: Partial<Parameters<typeof LeadSimulator>[0]> = {}) {
  const props = {
    companySlug: "acme",
    detail: undefined,
    hasLead: false,
    typing: false,
    submitting: false,
    onSubmit: vi.fn(),
    onReply: vi.fn(),
    onNewLead: vi.fn(),
    scenarios,
    onPlayScenario: vi.fn(),
    ...over,
  };
  render(<LeadSimulator {...props} />);
  return props;
}

describe("validateLead", () => {
  const ok = { ...EMPTY_FORM, phone: "+13035550142", message: "hi" };

  it("accepts a phone or an email", () => {
    expect(validateLead(ok)).toEqual({});
    expect(validateLead({ ...EMPTY_FORM, email: "a@b.co" })).toEqual({});
  });
  it("needs some way to reach the lead", () => {
    expect(validateLead(EMPTY_FORM).phone).toMatch(/phone number or an email/);
  });
  it("requires a phone for texts and missed calls", () => {
    expect(validateLead({ ...EMPTY_FORM, source: "text", email: "a@b.co", message: "hi" }).phone).toBeDefined();
    expect(validateLead({ ...EMPTY_FORM, source: "missed_call", email: "a@b.co" }).phone).toBeDefined();
  });
  it("requires a message for a text but not a missed call", () => {
    expect(validateLead({ ...ok, source: "text", message: " " }).message).toBeDefined();
    expect(validateLead({ ...ok, source: "missed_call", message: "" })).toEqual({});
  });
  it("rejects a malformed email", () => {
    expect(validateLead({ ...ok, email: "nope" }).email).toBeDefined();
  });
});

describe("toLeadIn", () => {
  it("trims, nulls empties and drops the message for a missed call", () => {
    expect(toLeadIn({ ...EMPTY_FORM, name: " Jamie ", phone: "123", message: " hi ", consent: true }, "acme")).toEqual({
      company: "acme",
      source: "web_form",
      name: "Jamie",
      phone: "123",
      email: null,
      message: "hi",
      consent: true,
    });
    const call = toLeadIn({ ...EMPTY_FORM, source: "missed_call", phone: "1", message: "ignored" }, undefined);
    expect(call.message).toBe("");
    expect(call.consent).toBeNull();
  });
});

describe("LeadSimulator", () => {
  it("submits a valid lead", async () => {
    const user = userEvent.setup();
    const p = setup();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Jamie Rivera");
    await user.type(screen.getByRole("textbox", { name: "Phone" }), "+13035550142");
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Interested");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Send lead" }));
    expect(p.onSubmit).toHaveBeenCalledWith({
      company: "acme",
      source: "web_form",
      name: "Jamie Rivera",
      phone: "+13035550142",
      email: null,
      message: "Interested",
      consent: true,
    });
  });

  it("blocks an invalid lead and tells the user why", async () => {
    const user = userEvent.setup();
    const p = setup();
    await user.click(screen.getByRole("button", { name: "Send lead" }));
    expect(p.onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/phone number or an email/);
  });

  it("switches source and hides the message box for a missed call", async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.getByRole("radio", { name: "Web form" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("radio", { name: "Missed call" }));
    expect(screen.getByRole("radio", { name: "Missed call" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("textbox", { name: "Message" })).not.toBeInTheDocument();
    expect(screen.getByText(/texts the caller back/)).toBeInTheDocument();
  });

  it("shows an API error and disables the button while sending", () => {
    setup({ submitError: "ANTHROPIC_API_KEY is not set.", submitting: true });
    expect(screen.getByRole("alert")).toHaveTextContent("ANTHROPIC_API_KEY is not set.");
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
  });

  it("switches to the conversation once a lead exists", async () => {
    const user = userEvent.setup();
    const p = setup({ hasLead: true, detail: detail(), typing: true });
    expect(screen.queryByRole("button", { name: "Send lead" })).not.toBeInTheDocument();
    expect(screen.getByRole("log", { name: "Conversation" })).toHaveTextContent("Hi Jamie, thanks for reaching out!");
    expect(screen.getByRole("status", { name: "Agent is typing" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "STOP" }));
    expect(p.onReply).toHaveBeenCalledWith("STOP");
    await user.click(screen.getByRole("button", { name: "New lead" }));
    expect(p.onNewLead).toHaveBeenCalled();
  });
});

describe("ScenarioReplay", () => {
  it("plays the selected scenario", async () => {
    const user = userEvent.setup();
    const onPlay = vi.fn();
    render(<ScenarioReplay scenarios={scenarios} onPlay={onPlay} />);
    expect(screen.getByText("All info up front.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Play" }));
    expect(onPlay).toHaveBeenLastCalledWith("hot");
    await user.selectOptions(screen.getByLabelText("Scenario"), "stop");
    await user.click(screen.getByRole("button", { name: "Play" }));
    expect(onPlay).toHaveBeenLastCalledWith("stop");
  });

  it("has empty, loading, error and playing states", () => {
    const { rerender } = render(<ScenarioReplay scenarios={[]} onPlay={vi.fn()} />);
    expect(screen.getByText(/No saved scenarios/)).toBeInTheDocument();
    rerender(<ScenarioReplay scenarios={undefined} loading onPlay={vi.fn()} />);
    expect(screen.getByRole("status", { name: "Loading scenarios" })).toBeInTheDocument();
    rerender(<ScenarioReplay scenarios={undefined} error="boom" onPlay={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    rerender(<ScenarioReplay scenarios={scenarios} playing onPlay={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled();
  });
});
