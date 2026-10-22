import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { at, config, detail, notification } from "../test/fakes";
import { RepView } from "./RepView";

const cfg = config();

describe("RepView", () => {
  it("shows an empty state with no lead", () => {
    render(<RepView detail={undefined} config={cfg} />);
    expect(screen.getByText("No lead selected")).toBeInTheDocument();
  });

  it("has loading and error states", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <RepView detail={undefined} config={undefined} loading />,
    );
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    rerender(
      <RepView
        detail={undefined}
        config={cfg}
        error="Lead not found"
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Lead not found");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("shows the score, tier and breakdown", () => {
    render(<RepView detail={detail()} config={cfg} />);
    expect(screen.getByTestId("score-value")).toHaveTextContent("90");
    const card = screen.getByRole("region", { name: "Lead score" });
    expect(within(card).getByText("Hot")).toBeInTheDocument();
    const items = within(
      within(card).getByRole("list", { name: "Score breakdown" }),
    ).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual([
      "Homeowner+25",
      "Timeline ASAP+25",
      "Bill 200 plus+40",
    ]);
    expect(
      within(card).getByText(/Warm from 40, hot from 70/),
    ).toBeInTheDocument();
  });

  it("marks a partial score as provisional", () => {
    const d = detail();
    d.score = { ...d.score!, complete: false, tier: "warm", score: 50 };
    render(<RepView detail={d} config={cfg} />);
    expect(
      screen.getByText(/provisional until all answers are in/),
    ).toBeInTheDocument();
  });

  it("explains a disqualified lead instead of showing a score", () => {
    const d = detail();
    d.score = {
      ...d.score!,
      tier: "disqualified",
      score: 0,
      breakdown: [],
      disqualified_reason: "Zip 10001 is outside the service area.",
      disqualified_by: "out_of_area",
    };
    d.routing = {
      office_id: null,
      office_name: null,
      rep_id: null,
      rep_name: null,
      reason: "Zip 10001 is outside the service area.",
    };
    render(<RepView detail={d} config={cfg} />);
    expect(screen.getByTestId("score-value")).toHaveTextContent("n/a");
    expect(screen.getByText("Disqualified")).toBeInTheDocument();
    expect(
      screen.getAllByText(/outside the service area/).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/Not booked/)).toBeInTheDocument();
    expect(screen.getByText(/closed, not booked/)).toBeInTheDocument();
  });

  it("says when the lead has not been scored", () => {
    render(<RepView detail={detail({ score: null })} config={cfg} />);
    expect(screen.getByText(/Not scored yet/)).toBeInTheDocument();
  });

  it("lists qualification answers and flags the missing ones, using field names from config", () => {
    render(<RepView detail={detail()} config={cfg} />);
    const card = screen.getByRole("region", { name: "Qualification answers" });
    expect(within(card).getByText("80205")).toBeInTheDocument();
    expect(within(card).getByText("Owner")).toBeInTheDocument();
    expect(within(card).getByText("Missing")).toBeInTheDocument(); // timeline
    expect(within(card).getByText("What's your zip?")).toBeInTheDocument();
  });

  it("shows the routing decision", () => {
    render(<RepView detail={detail()} config={cfg} />);
    const card = screen.getByRole("region", { name: "Routing" });
    expect(card).toHaveTextContent("Denver Office");
    expect(card).toHaveTextContent("Rep: Maya Ortiz");
    expect(card).toHaveTextContent("round robin");
  });

  it("shows the booked appointment, or that there is none", () => {
    const { rerender } = render(<RepView detail={detail()} config={cfg} />);
    expect(
      screen.getByRole("region", { name: "Appointment" }),
    ).toHaveTextContent("No appointment yet");
    rerender(
      <RepView
        config={cfg}
        detail={detail({
          booking: {
            id: "bk1",
            lead_id: "ld_1",
            rep_id: "maya_ortiz",
            rep_name: "Maya Ortiz",
            office_id: "denver",
            office_name: "Denver Office",
            start: "2026-10-27T18:00:00Z",
            end: "2026-10-27T19:00:00Z",
            label: "Tue Oct 27, 12:00 PM",
            kind: "free consultation",
          },
        })}
      />,
    );
    const booking = screen.getByTestId("booking");
    expect(booking).toHaveTextContent("Booked");
    expect(booking).toHaveTextContent("Tue, Oct 27, 12:00 PM");
    expect(booking).toHaveTextContent("Maya Ortiz · Denver Office");
  });

  it("previews the CRM record and whether it was written", () => {
    const { rerender } = render(<RepView detail={detail()} config={cfg} />);
    let card = screen.getByRole("region", { name: "CRM record" });
    expect(card).toHaveTextContent("Sales");
    expect(card).toHaveTextContent("not created yet");
    expect(card).toHaveTextContent("Preview");
    expect(card).toHaveTextContent("lead_score");
    expect(card).toHaveTextContent("90");

    const d = detail();
    d.crm = {
      ...d.crm,
      synced: true,
      stage: "Consultation Booked",
      contact_id: "crm_1",
    };
    rerender(<RepView detail={d} config={cfg} />);
    card = screen.getByRole("region", { name: "CRM record" });
    expect(card).toHaveTextContent("Consultation Booked");
    expect(card).toHaveTextContent("Written · crm_1");
  });

  it("renders Slack-style notification cards", () => {
    render(
      <RepView
        config={cfg}
        detail={detail({
          notifications: [
            notification(),
            notification({
              kind: "booked",
              title: "Booked!",
              priority: "normal",
              mention: null,
              note: null,
              created_at: at(9),
            }),
          ],
        })}
      />,
    );
    const cards = screen.getAllByTestId("slack-card");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("@Maya Ortiz");
    expect(cards[0]).toHaveTextContent("Hot lead: Jamie Rivera");
    expect(cards[0]).toHaveTextContent("Score");
    expect(cards[0]).toHaveTextContent("90/100 (hot)");
    expect(cards[0]).toHaveTextContent("#new-leads");
    expect(cards[0]).toHaveTextContent("Wants to move fast");
    expect(cards[0]).toHaveAttribute("data-priority", "urgent");
    expect(cards[0]).toHaveTextContent("🚨");
    expect(cards[1]).not.toHaveTextContent("🚨");
  });

  it("says nobody has been pinged yet", () => {
    render(<RepView detail={detail()} config={cfg} />);
    expect(screen.getByText("No one has been pinged yet.")).toBeInTheDocument();
  });

  it("shows flags only when there are some", () => {
    const { rerender } = render(<RepView detail={detail()} config={cfg} />);
    expect(
      screen.queryByRole("region", { name: "Flags" }),
    ).not.toBeInTheDocument();
    rerender(
      <RepView
        detail={detail({ flags: ["prompt_injection_attempt"] })}
        config={cfg}
      />,
    );
    expect(screen.getByRole("region", { name: "Flags" })).toHaveTextContent(
      "prompt_injection_attempt",
    );
  });

  it("lets a person take over, then message the lead as the rep", async () => {
    const user = userEvent.setup();
    const onTakeover = vi.fn();
    const onHumanMessage = vi.fn();
    const { rerender } = render(
      <RepView
        detail={detail()}
        config={cfg}
        onTakeover={onTakeover}
        onHumanMessage={onHumanMessage}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Take over" }));
    expect(onTakeover).toHaveBeenCalled();
    expect(screen.queryByLabelText("Message as rep")).not.toBeInTheDocument();

    const human = detail();
    human.summary = { ...human.summary, status: "human" };
    rerender(
      <RepView
        detail={human}
        config={cfg}
        onTakeover={onTakeover}
        onHumanMessage={onHumanMessage}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Take over" }),
    ).not.toBeInTheDocument();
    await user.type(
      screen.getByLabelText("Message as rep"),
      "Hi, it's Maya{enter}",
    );
    expect(onHumanMessage).toHaveBeenCalledWith("Hi, it's Maya");
  });

  it("shows status and consent for the lead", () => {
    render(<RepView detail={detail()} config={cfg} />);
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("SMS: Unknown")).toBeInTheDocument();
    expect(screen.getByText("Web form")).toBeInTheDocument();
  });
});

describe("RepView conversation", () => {
  it("hides the conversation until a human has taken over", () => {
    render(<RepView detail={detail()} config={cfg} />);
    expect(
      screen.queryByRole("region", { name: "Lead conversation" }),
    ).not.toBeInTheDocument();
  });

  it("shows what the lead writes, including after a takeover", () => {
    const d = detail({
      summary: { ...detail().summary, status: "human" },
      messages: [
        {
          id: "m1",
          lead_id: "ld_1",
          direction: "inbound",
          body: "Can you do Thursday instead?",
          created_at: at(9),
          sender: "lead",
          sent: true,
        },
      ],
    });
    render(<RepView detail={d} config={cfg} onHumanMessage={() => {}} />);
    expect(
      screen.getByRole("log", { name: "Live messages" }),
    ).toHaveTextContent("Can you do Thursday instead?");
  });

  it("lets a person hand the lead back to the agent", async () => {
    const user = userEvent.setup();
    const onResume = vi.fn();
    const human = detail({ summary: { ...detail().summary, status: "human" } });
    const { rerender } = render(
      <RepView detail={human} config={cfg} onResume={onResume} />,
    );
    await user.click(
      screen.getByRole("button", { name: "Hand back to agent" }),
    );
    expect(onResume).toHaveBeenCalled();
    rerender(<RepView detail={detail()} config={cfg} onResume={onResume} />);
    expect(
      screen.queryByRole("button", { name: "Hand back to agent" }),
    ).not.toBeInTheDocument();
  });

  it("names the rep in the thread when they take over or hand back", () => {
    const d = detail({
      summary: { ...detail().summary, status: "human" },
      events: [
        { type: "human_takeover", at: at(2) },
        { type: "agent_resumed", at: at(3) },
      ],
    });
    render(<RepView detail={d} config={cfg} />);
    const notices = screen.getAllByTestId("chat-notice");
    expect(notices[0]).toHaveTextContent(
      "Maya Ortiz from Sales has taken over the chat",
    );
    expect(notices[1]).toHaveTextContent("Maya Ortiz from Sales has left the chat");
  });
});
