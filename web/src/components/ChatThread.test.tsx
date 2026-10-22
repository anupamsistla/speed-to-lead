import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { at, message } from "../test/fakes";
import { ChatThread } from "./ChatThread";

describe("ChatThread", () => {
  it("shows an empty state before any message", () => {
    render(<ChatThread messages={[]} />);
    expect(screen.getByText("No messages yet")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument(); // no composer without onSend
  });

  it("labels who said what and when, in the company's timezone", () => {
    render(
      <ChatThread
        timeZone="America/Denver"
        messages={[
          message({ id: "1", direction: "inbound", sender: "lead", body: "I own a home", created_at: at(0) }),
          message({ id: "2", body: "Great, what's your zip?", created_at: at(5) }),
          message({ id: "3", sender: "human", body: "Maya here, I'll call you.", created_at: at(60) }),
        ]}
      />,
    );
    expect(screen.getByText("I own a home")).toHaveAttribute("data-sender", "lead");
    expect(screen.getByText("Great, what's your zip?")).toHaveAttribute("data-sender", "agent");
    expect(screen.getByText("Maya here, I'll call you.")).toHaveAttribute("data-sender", "human");
    expect(screen.getByText("Lead · 10:00 AM")).toBeInTheDocument();
    expect(screen.getByText("Agent · 10:00 AM")).toBeInTheDocument();
    expect(screen.getByText("Rep (human) · 10:01 AM")).toBeInTheDocument();
  });

  it("shows a typing indicator while the agent works", () => {
    const { rerender } = render(<ChatThread messages={[]} typing />);
    expect(screen.getByRole("status", { name: "Agent is typing" })).toBeInTheDocument();
    expect(screen.queryByText("No messages yet")).not.toBeInTheDocument();
    rerender(<ChatThread messages={[]} typing={false} />);
    expect(screen.queryByRole("status", { name: "Agent is typing" })).not.toBeInTheDocument();
  });

  it("shows a held message distinctly, with when it will send", () => {
    render(
      <ChatThread
        timeZone="America/Denver"
        messages={[]}
        deferred={[{ body: "Hi Jamie!", deliver_after: "2026-10-28T14:00:00Z" }]}
      />,
    );
    expect(screen.getByTestId("deferred-message")).toHaveTextContent("Hi Jamie!");
    expect(screen.getByText(/Held for quiet hours · sends at 8:00 AM/)).toBeInTheDocument();
  });

  it("lets the operator reply as the lead with Enter or the button", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatThread messages={[]} onSend={onSend} />);
    const box = screen.getByLabelText("Reply as the lead");
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();

    await user.type(box, "  yes please{enter}");
    expect(onSend).toHaveBeenLastCalledWith("yes please");
    expect(box).toHaveValue("");

    await user.type(box, "second");
    await user.click(send);
    expect(onSend).toHaveBeenLastCalledWith("second");
    expect(onSend).toHaveBeenCalledTimes(2);
  });

  it("sends a quick reply with one click and disables them while sending", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const { rerender } = render(<ChatThread messages={[]} onSend={onSend} quickReplies={["STOP", "The first one works"]} />);
    await user.click(screen.getByRole("button", { name: "STOP" }));
    expect(onSend).toHaveBeenCalledWith("STOP");
    rerender(<ChatThread messages={[]} onSend={onSend} sending quickReplies={["STOP"]} />);
    expect(screen.getByRole("button", { name: "STOP" })).toBeDisabled();
  });

  it("is an accessible live log", () => {
    render(<ChatThread messages={[message()]} />);
    expect(screen.getByRole("log", { name: "Conversation" })).toHaveAttribute("aria-live", "polite");
  });
});
