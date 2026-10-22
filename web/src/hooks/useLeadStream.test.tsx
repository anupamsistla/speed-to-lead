import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { keys } from "../api/queries";
import { detail, FakeEventSource, message, toolCall } from "../test/fakes";
import type { LeadDetail } from "../types";
import { useLeadStream } from "./useLeadStream";

function setup(leadId: string | null = "ld_1") {
  FakeEventSource.reset();
  const qc = new QueryClient();
  qc.setQueryData(keys.lead("ld_1"), detail({ messages: [], tool_calls: [] }));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const factory = (url: string) => new FakeEventSource(url);
  const hook = renderHook(({ id }) => useLeadStream(id, factory), { wrapper, initialProps: { id: leadId } });
  return { qc, hook, es: () => FakeEventSource.instances[FakeEventSource.instances.length - 1] };
}

describe("useLeadStream", () => {
  afterEach(() => vi.useRealTimers());

  it("does not connect without a lead", () => {
    setup(null);
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("connects to the lead's event stream and reports the connection", () => {
    const { hook, es } = setup();
    expect(es().url).toBe("/api/leads/ld_1/events");
    expect(hook.result.current.connected).toBe(false);
    act(() => es().open());
    expect(hook.result.current.connected).toBe(true);
    act(() => es().onerror?.(new Event("error")));
    expect(hook.result.current.connected).toBe(false);
  });

  it("patches the cached lead as messages and tool calls stream in", () => {
    const { qc, es } = setup();
    act(() => es().emit("message", message({ id: "m9", body: "streamed" }), 5));
    act(() => es().emit("tool_call", toolCall({ id: "t9", name: "get_slots" }), 6));
    const cached = qc.getQueryData<LeadDetail>(keys.lead("ld_1"))!;
    expect(cached.messages.map((m) => m.body)).toEqual(["streamed"]);
    expect(cached.tool_calls.map((t) => t.name)).toEqual(["get_slots"]);
  });

  it("tracks whether the agent is mid-turn", () => {
    const { hook, es } = setup();
    act(() => es().emit("lead_created", {}, 1));
    expect(hook.result.current.processing).toBe(true);
    act(() => es().emit("turn_done", { duration_ms: 5 }, 9));
    expect(hook.result.current.processing).toBe(false);
    expect(hook.result.current.lastEvent?.type).toBe("turn_done");
  });

  it("refetches the lead (debounced) after a state event", () => {
    vi.useFakeTimers();
    const { qc, es } = setup();
    const spy = vi.spyOn(qc, "invalidateQueries");
    act(() => {
      es().emit("state", {}, 2);
      es().emit("state", {}, 3);
      es().emit("state", {}, 4);
    });
    expect(spy).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(200));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ queryKey: keys.lead("ld_1") });
  });

  it("ignores malformed events instead of crashing", () => {
    const { qc, es } = setup();
    expect(() => {
      act(() => {
        (es() as unknown as { listeners: Map<string, ((e: MessageEvent) => void)[]> }).listeners
          .get("message")![0]({ data: "{not json" } as MessageEvent);
      });
    }).not.toThrow();
    expect(qc.getQueryData<LeadDetail>(keys.lead("ld_1"))!.messages).toEqual([]);
  });

  it("closes the stream when the lead changes or the component unmounts", () => {
    const { hook } = setup();
    const first = FakeEventSource.instances[0];
    hook.rerender({ id: "ld_2" });
    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].url).toBe("/api/leads/ld_2/events");
    hook.unmount();
    expect(FakeEventSource.instances[1].closed).toBe(true);
  });
});
