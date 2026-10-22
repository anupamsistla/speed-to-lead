import { at, detail } from "./test/fakes";
import { deriveTimer } from "./timerPhase";

describe("deriveTimer", () => {
  it("is idle with no lead", () => {
    expect(deriveTimer(undefined, false).phase).toBe("idle");
  });

  it("is done once the server reports a first response", () => {
    expect(deriveTimer(detail(), true)).toEqual({ phase: "done", seconds: 38.2, queuedUntil: null });
  });

  it("is running while the agent works and no reply has gone out", () => {
    const d = detail({ summary: { ...detail().summary, first_response_seconds: null } });
    expect(deriveTimer(d, true).phase).toBe("running");
  });

  it("is queued when the reply is held for quiet hours", () => {
    const d = detail({
      summary: { ...detail().summary, first_response_seconds: null },
      deferred: [{ body: "hi", deliver_after: at(3600) }],
    });
    expect(deriveTimer(d, false)).toEqual({ phase: "queued", seconds: null, queuedUntil: at(3600) });
  });

  it("is silent for a lead closed without a message, but not while still working", () => {
    const d = detail({ summary: { ...detail().summary, first_response_seconds: null, status: "spam" } });
    expect(deriveTimer(d, false).phase).toBe("silent");
    expect(deriveTimer(d, true).phase).toBe("running");
  });
});
