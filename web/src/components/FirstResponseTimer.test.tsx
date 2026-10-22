import { act, render, screen } from "@testing-library/react";
import { FirstResponseTimer } from "./FirstResponseTimer";

describe("FirstResponseTimer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows a dash before any lead", () => {
    render(<FirstResponseTimer phase="idle" />);
    expect(screen.getByRole("timer")).toHaveAttribute("data-phase", "idle");
    expect(screen.getByText("--")).toBeInTheDocument();
    expect(screen.getByText(/starts when a lead is submitted/i)).toBeInTheDocument();
  });

  it("counts up from the moment the lead was submitted", () => {
    let t = 1_000_000;
    const now = () => t;
    render(<FirstResponseTimer phase="running" startedAtMs={t} now={now} />);
    expect(screen.getByText("0.0s")).toBeInTheDocument();
    act(() => {
      t += 2300;
      vi.advanceTimersByTime(2300);
    });
    expect(screen.getByText("2.3s")).toBeInTheDocument();
    act(() => {
      t += 36_000;
      vi.advanceTimersByTime(36_000);
    });
    expect(screen.getByText("38.3s")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("stops at the server's authoritative number and says it beat the target", () => {
    let t = 0;
    const { rerender } = render(<FirstResponseTimer phase="running" startedAtMs={0} now={() => t} />);
    act(() => {
      t = 5000;
      vi.advanceTimersByTime(5000);
    });
    rerender(<FirstResponseTimer phase="done" startedAtMs={0} seconds={38.2} now={() => t} />);
    expect(screen.getByText("38.2s")).toBeInTheDocument();
    expect(screen.getByText(/under 60s target/i)).toBeInTheDocument();
    act(() => {
      t = 90_000;
      vi.advanceTimersByTime(90_000);
    });
    expect(screen.getByText("38.2s")).toBeInTheDocument(); // frozen
  });

  it("flags a slow first response", () => {
    render(<FirstResponseTimer phase="done" seconds={75} />);
    expect(screen.getByText("75s")).toBeInTheDocument();
    expect(screen.getByText(/over 60s target/i)).toBeInTheDocument();
  });

  it("explains a reply held for quiet hours", () => {
    render(<FirstResponseTimer phase="queued" queuedUntil="2026-10-28T14:00:00Z" timeZone="America/Denver" />);
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText(/goes out at 8:00 AM/)).toBeInTheDocument();
  });

  it("says when a lead was closed without a message", () => {
    render(<FirstResponseTimer phase="silent" />);
    expect(screen.getByText("No reply")).toBeInTheDocument();
  });

  it("stops its interval when it unmounts", () => {
    const { unmount } = render(<FirstResponseTimer phase="running" startedAtMs={0} now={() => 0} />);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
