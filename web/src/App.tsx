import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  keys,
  useClock,
  useCompanies,
  useCompanyConfig,
  useHealth,
  useHumanMessage,
  useResume,
  useLead,
  useReplayScenario,
  useReply,
  useScenarios,
  useSetClock,
  useSubmitLead,
  useTakeover,
} from "./api/queries";
import { AgentTrace, type GuardrailEvent } from "./components/AgentTrace";
import { DevHeader } from "./components/DevHeader";
import { FirstResponseTimer } from "./components/FirstResponseTimer";
import { LeadSimulator } from "./components/LeadSimulator";
import { RepView } from "./components/RepView";
import { ErrorState, GhostButton, Panel, Skeleton } from "./components/ui";
import { useLeadStream } from "./hooks/useLeadStream";
import { deriveTimer } from "./timerPhase";
import { applyBrand } from "./theme/branding";
import type { LeadIn } from "./types";

/** ?dev=1 or ?dev=0 wins, then the saved switch, then on only in the Vite dev server. */
const isDev = () => {
  const q = new URLSearchParams(location.search).get("dev");
  if (q === "1" || q === "0") return q === "1";
  try {
    const saved = localStorage.getItem("devMode");
    if (saved === "1" || saved === "0") return saved === "1";
  } catch {
    // storage unavailable: fall through to the default
  }
  return import.meta.env.DEV;
};

function readLeadFromHash(): string | null {
  return new URLSearchParams(location.hash.slice(1)).get("lead");
}

export default function App() {
  const qc = useQueryClient();
  const [dev, setDev] = useState(isDev);
  const toggleDev = () =>
    setDev((on) => {
      try {
        localStorage.setItem("devMode", on ? "0" : "1");
      } catch {
        // not persisted, still toggles for this session
      }
      return !on;
    });

  const companies = useCompanies();
  const [slug, setSlug] = useState<string | undefined>(
    () =>
      new URLSearchParams(location.search).get("company") ??
      localStorage.getItem("company") ??
      undefined,
  );
  const activeSlug = slug ?? companies.data?.default;
  const config = useCompanyConfig(activeSlug);

  const [leadId, setLeadId] = useState<string | null>(readLeadFromHash);
  // Bumped on reset so the simulator remounts with an empty form and the first scenario selected.
  const [resetCount, setResetCount] = useState(0);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const lead = useLead(leadId);
  const stream = useLeadStream(leadId);

  const scenarios = useScenarios(activeSlug);
  const submit = useSubmitLead();
  const replay = useReplayScenario();
  const reply = useReply(leadId);
  const takeover = useTakeover(leadId);
  const human = useHumanMessage(leadId);
  const resume = useResume(leadId);
  const clock = useClock();
  const health = useHealth();
  const setClock = useSetClock();

  // Branding comes from the active company's config, applied through CSS variables.
  useEffect(() => {
    if (config.data) {
      applyBrand(config.data.brand_color);
      document.title = `${config.data.name} · Speed to Lead`;
    }
  }, [config.data]);

  useEffect(() => {
    history.replaceState(
      null,
      "",
      leadId ? `#lead=${leadId}` : location.pathname + location.search,
    );
  }, [leadId]);

  const resetInteraction = () => {
    setLeadId(null);
    setStartedAt(null);
    submit.reset();
    setResetCount((n) => n + 1);
    replay.reset();
    reply.reset();
    takeover.reset();
    resume.reset();
    human.reset();
  };

  const startLead = (id: string) => {
    setStartedAt(Date.now());
    setLeadId(id);
  };

  const switchCompany = (next: string) => {
    setSlug(next);
    localStorage.setItem("company", next);
    setLeadId(null);
    setStartedAt(null);
    const url = new URL(location.href);
    url.searchParams.set("company", next);
    url.hash = "";
    history.replaceState(null, "", url);
  };

  const submitLead = (body: LeadIn) =>
    submit.mutate(body, { onSuccess: (r) => startLead(r.lead_id) });

  const detail = lead.data;
  const working = stream.processing;
  const timer = deriveTimer(detail, working);
  const guardrails = (detail?.events ?? []) as GuardrailEvent[];

  const apiDown = companies.isError;

  return (
    <div className="flex h-full flex-col">
      {dev && (
        <DevHeader
          companies={companies.data?.companies ?? []}
          current={activeSlug}
          onCompany={switchCompany}
          clock={clock.data}
          onPreset={(preset) =>
            setClock.mutate({ preset, company: activeSlug })
          }
          health={health.data}
          timeZone={config.data?.timezone}
        />
      )}

      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-center gap-3">
          {config.data ? (
            <img
              src={config.data.logo_url}
              alt={`${config.data.name} logo`}
              className="h-10 w-auto max-w-[140px] rounded object-contain"
            />
          ) : (
            <div className="h-9 w-9 animate-pulse rounded bg-slate-200" />
          )}
          <div>
            <h1 className="text-base font-semibold leading-tight text-slate-900">
              {config.data?.name ?? "Loading…"}
            </h1>
            <p className="text-xs text-slate-500">Speed-to-lead agent</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <p className="hidden text-xs text-slate-500 lg:block">
            {config.data &&
              `${config.data.appointment_kind} · ${config.data.offices.length} offices · pings ${config.data.slack_channel}`}
          </p>
          <button
            type="button"
            role="switch"
            aria-checked={dev}
            aria-label="Dev mode"
            onClick={toggleDev}
            className="flex items-center gap-2 text-xs font-medium text-slate-600"
          >
            Dev
            <span
              className={`relative h-5 w-9 rounded-full transition ${dev ? "bg-slate-800" : "bg-slate-300"}`}
              aria-hidden
            >
              <span
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${dev ? "left-[18px]" : "left-0.5"}`}
              />
            </span>
          </button>
        </div>
      </header>

      {apiDown ? (
        <div className="flex-1">
          <ErrorState
            title="Can't reach the API"
            message={`${companies.error?.message ?? "Request failed"} Start it with "make demo" or "python run.py --company <slug>".`}
            onRetry={() => companies.refetch()}
          />
        </div>
      ) : (
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 xl:grid-cols-[400px_minmax(0,1fr)_420px] xl:overflow-hidden">
          <Panel
            title="Lead Simulator"
            subtitle="Send a lead, watch the conversation"
            actions={<GhostButton onClick={resetInteraction}>Reset interaction</GhostButton>}
            className="max-xl:h-[720px]"
          >
            {config.isLoading ? (
              <Skeleton lines={6} />
            ) : (
              <LeadSimulator
                key={resetCount}
                companySlug={activeSlug}
                timeZone={config.data?.timezone}
                detail={detail}
                hasLead={!!leadId}
                typing={working}
                submitting={submit.isPending}
                submitError={submit.error?.message}
                onSubmit={submitLead}
                onReply={(text) => reply.mutate(text)}
                replying={reply.isPending}
                scenarios={scenarios.data?.scenarios}
                scenariosLoading={scenarios.isLoading}
                scenariosError={scenarios.error?.message}
                onPlayScenario={(id) =>
                  replay.mutate(id, { onSuccess: (r) => startLead(r.lead_id) })
                }
                playing={replay.isPending}
              />
            )}
          </Panel>

          <Panel
            title="Representative View"
            subtitle="What the sales rep sees"
            className="max-xl:h-[900px]"
          >
            <RepView
              detail={detail}
              config={config.data}
              loading={config.isLoading || (!!leadId && lead.isLoading)}
              error={lead.error?.message ?? config.error?.message ?? null}
              onRetry={() =>
                qc.invalidateQueries({ queryKey: keys.lead(leadId ?? "") })
              }
              onTakeover={() => takeover.mutate()}
              onHumanMessage={(text) => human.mutate(text)}
              onResume={() => resume.mutate()}
              actionPending={takeover.isPending || resume.isPending}
              actionError={
                takeover.error?.message ?? resume.error?.message ?? null
              }
            />
          </Panel>

          <Panel
            title="Agent Trace"
            subtitle={
              stream.connected
                ? "Live"
                : leadId
                  ? "Connecting…"
                  : "Waiting for a lead"
            }
            className="max-xl:h-[720px]"
            bodyClassName="flex flex-col"
          >
            <div className="border-b border-slate-200 p-3">
              <FirstResponseTimer
                phase={timer.phase}
                startedAtMs={
                  startedAt ??
                  (detail ? Date.parse(detail.lead.created_at) : null)
                }
                seconds={timer.seconds}
                queuedUntil={timer.queuedUntil}
                timeZone={config.data?.timezone}
              />
            </div>
            <div className="min-h-0 flex-1">
              <AgentTrace
                toolCalls={detail?.tool_calls ?? []}
                guardrailEvents={guardrails}
                loading={!!leadId && lead.isLoading}
                error={lead.error?.message ?? null}
                onRetry={() =>
                  qc.invalidateQueries({ queryKey: keys.lead(leadId ?? "") })
                }
                working={working}
              />
            </div>
          </Panel>
        </main>
      )}
    </div>
  );
}
