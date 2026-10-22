import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { api } from "./api/client";
import { config, detail, FakeEventSource, toolCall } from "./test/fakes";
import type { LeadDetail } from "./types";

vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() } };
});

const acme = config();
const globex = config({ slug: "globex", name: "Globex Lending", brand_color: "#16A34A", logo_url: "/api/companies/globex/logo" });
const COMPANIES = {
  default: "acme",
  companies: [acme, globex].map((c) => ({ slug: c.slug, name: c.name, brand_color: c.brand_color, logo_url: c.logo_url })),
};
const SCENARIOS = {
  scenarios: [{ id: "hot", title: "Hot lead books", description: "All info.", company: "acme", source: "web_form", followups: 1, clock: null }],
};

let lead: LeadDetail;
const ok = (data: unknown) => Promise.resolve({ data, response: { status: 200 } as Response });
const fail = (status: number, detail: string) => Promise.resolve({ error: { detail }, response: { status } as Response });

function routes() {
  vi.mocked(api.GET).mockImplementation(((path: string, opts?: { params?: { path?: Record<string, string> } }) => {
    switch (path) {
      case "/api/companies":
        return ok(COMPANIES);
      case "/api/companies/{slug}/config":
        return ok(opts?.params?.path?.slug === "globex" ? globex : acme);
      case "/api/leads/{lead_id}":
        return ok(lead);
      case "/api/scenarios":
        return ok(SCENARIOS);
      case "/api/clock":
        return ok({ now: "2026-10-27T16:00:00Z", simulated: true });
      case "/api/health":
        return ok({ ok: true, llm: "ready", model: "claude-sonnet-5-5", adapters: { crm: "mock" }, simulated_clock: true });
      default:
        return fail(404, `unmocked ${path}`);
    }
  }) as never);
  vi.mocked(api.POST).mockImplementation(((path: string) => {
    if (path === "/api/leads") return ok({ lead_id: "ld_1", created_at: "2026-10-27T16:00:00Z", status: "processing" });
    if (path === "/api/scenarios/{scenario_id}/replay") return ok({ lead_id: "ld_1", created_at: "2026-10-27T16:00:00Z", status: "processing" });
    if (path === "/api/leads/{lead_id}/messages") return ok({ lead_id: "ld_1", created_at: "x", status: "processing" });
    return fail(404, "unmocked");
  }) as never);
  vi.mocked(api.PUT).mockImplementation((() => ok({ now: "2026-10-27T16:00:00Z", simulated: true })) as never);
}

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
  localStorage.clear();
  history.replaceState(null, "", "/");
  document.documentElement.removeAttribute("style");
  lead = detail();
  routes();
});

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("brands itself from the company config at runtime", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { level: 1, name: "Acme Co" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Acme Co logo" })).toHaveAttribute("src", "/api/companies/acme/logo");
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--brand-rgb")).toBe("29 78 216"));
    expect(document.title).toBe("Acme Co · Speed to Lead");
  });

  it("renders the three panels with their empty states", async () => {
    renderApp();
    await screen.findByRole("heading", { level: 1, name: "Acme Co" });
    expect(screen.getByRole("region", { name: "Lead Simulator" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Representative View" })).toHaveTextContent("No lead selected");
    expect(screen.getByRole("region", { name: "Agent Trace" })).toHaveTextContent("No tool calls yet");
    expect(screen.getByRole("timer")).toHaveAttribute("data-phase", "idle");
  });

  it("switches company without a rebuild: new branding, new scenarios, lead cleared", async () => {
    const user = userEvent.setup();
    window.location.hash = "#lead=ld_1";
    renderApp();
    expect(await screen.findByTestId("dev-header")).toBeInTheDocument();
    await screen.findByTestId("score-value"); // the lead has loaded

    await user.selectOptions(screen.getByLabelText("Company"), "globex");
    expect(await screen.findByRole("heading", { level: 1, name: "Globex Lending" })).toBeInTheDocument();
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--brand-rgb")).toBe("22 163 74"));
    expect(screen.getByRole("region", { name: "Representative View" })).toHaveTextContent("No lead selected");
    expect(localStorage.getItem("company")).toBe("globex");
    expect(vi.mocked(api.GET)).toHaveBeenCalledWith("/api/scenarios", { params: { query: { company: "globex" } } });
  });

  it("shows a clear error when the API is down, and recovers on retry", async () => {
    const user = userEvent.setup();
    vi.mocked(api.GET).mockImplementation((() => Promise.reject(new TypeError("fetch failed"))) as never);
    renderApp();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Can't reach the API");
    expect(alert).toHaveTextContent("make demo");

    routes();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Acme Co" })).toBeInTheDocument();
  });

  it("submits a lead, follows it live, and shows the first-response time", async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByRole("heading", { level: 1, name: "Acme Co" });
    await user.type(screen.getByRole("textbox", { name: "Phone" }), "+13035550142");
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Interested");
    await user.click(screen.getByRole("button", { name: "Send lead" }));

    expect(api.POST).toHaveBeenCalledWith("/api/leads", expect.objectContaining({
      body: expect.objectContaining({ company: "acme", phone: "+13035550142", message: "Interested" }),
    }));
    // the lead loaded, the conversation shows, the stream opened
    expect(await screen.findByRole("log", { name: "Conversation" })).toHaveTextContent("Hi Jamie, thanks for reaching out!");
    expect(FakeEventSource.instances.at(-1)!.url).toBe("/api/leads/ld_1/events");
    expect(window.location.hash).toBe("#lead=ld_1");

    const timer = screen.getByRole("timer");
    await waitFor(() => expect(timer).toHaveAttribute("data-phase", "done"));
    expect(timer).toHaveTextContent("38.2s");

    // a tool call streamed over SSE appears in the trace
    act(() => FakeEventSource.instances.at(-1)!.emit("tool_call", toolCall({ id: "live1", name: "score_lead", args: { fields: { zip: "80205" } } })));
    const trace = screen.getByRole("list", { name: "Agent Trace" });
    await waitFor(() => expect(within(trace).getByText("score_lead")).toBeInTheDocument());
  });

  it("shows why a submit failed", async () => {
    const user = userEvent.setup();
    vi.mocked(api.POST).mockImplementation((() => fail(503, "ANTHROPIC_API_KEY is not set.")) as never);
    renderApp();
    await screen.findByRole("heading", { level: 1, name: "Acme Co" });
    await user.type(screen.getByRole("textbox", { name: "Phone" }), "+13035550142");
    await user.click(screen.getByRole("button", { name: "Send lead" }));
    expect(await screen.findByText("ANTHROPIC_API_KEY is not set.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send lead" })).toBeEnabled();
  });

  it("plays a saved scenario", async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByRole("heading", { level: 1, name: "Acme Co" });
    await screen.findByRole("option", { name: "Hot lead books" });
    await user.click(screen.getByRole("button", { name: "Play" }));
    expect(api.POST).toHaveBeenCalledWith("/api/scenarios/{scenario_id}/replay", { params: { path: { scenario_id: "hot" } } });
    expect(await screen.findByRole("log", { name: "Conversation" })).toBeInTheDocument();
  });

  it("restores the lead from the URL so a refresh keeps the demo state", async () => {
    window.location.hash = "#lead=ld_1";
    renderApp();
    expect(await screen.findByTestId("score-value")).toHaveTextContent("90");
  });

  it("controls the simulated clock from the dev header", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByRole("button", { name: "After hours" }));
    expect(api.PUT).toHaveBeenCalledWith("/api/clock", { body: { preset: "after_hours", company: "acme" } });
    expect(screen.getByTestId("dev-header")).toHaveTextContent("simulated");
  });

  it("surfaces a lead that cannot be loaded", async () => {
    window.location.hash = "#lead=ld_missing";
    const base = vi.mocked(api.GET).getMockImplementation()!;
    vi.mocked(api.GET).mockImplementation(((path: string, ...rest: unknown[]) =>
      path === "/api/leads/{lead_id}"
        ? fail(404, "unknown lead 'ld_missing'")
        : (base as (...a: unknown[]) => unknown)(path, ...rest)) as never);
    renderApp();
    expect((await screen.findAllByText(/unknown lead/)).length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Representative View" })).toHaveTextContent("Can't load this lead");
  });
});
