import { useState } from "react";
import { formatDateTime, formatClock, humanize, STATUS_LABEL, TIER_STYLE } from "../lib";
import type { CompanyConfig, LeadDetail, Notification } from "../types";
import { Badge, EmptyState, ErrorState, GhostButton, Skeleton } from "./ui";

function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card p-4 ${className}`} aria-label={title}>
      <h3 className="label mb-2">{title}</h3>
      {children}
    </section>
  );
}

export function ScoreCard({ detail, config }: { detail: LeadDetail; config: CompanyConfig }) {
  const score = detail.score;
  if (!score) {
    return (
      <Card title="Lead score">
        <p className="text-sm text-slate-500">Not scored yet. The agent scores once it knows enough.</p>
      </Card>
    );
  }
  const tier = TIER_STYLE[score.tier];
  const max = Math.max(1, ...score.breakdown.map((b) => Math.abs(b.points)));
  return (
    <Card title="Lead score">
      <div className="flex items-end justify-between">
        <div className="flex items-baseline gap-1">
          <span data-testid="score-value" className="text-5xl font-semibold tabular-nums">
            {score.tier === "disqualified" ? "—" : score.score}
          </span>
          {score.tier !== "disqualified" && <span className="text-sm text-slate-500">/ 100</span>}
        </div>
        <Badge className={tier.cls}>{tier.label}</Badge>
      </div>

      {score.tier !== "disqualified" && (
        <div className="relative mt-3 h-2 rounded-full bg-slate-100" aria-hidden>
          <div className="h-2 rounded-full bg-brand" style={{ width: `${Math.min(100, score.score)}%` }} />
          {[config.warm_lead_threshold, config.hot_lead_threshold].map((t) => (
            <span key={t} className="absolute top-[-3px] h-3.5 w-px bg-slate-400" style={{ left: `${t}%` }} />
          ))}
        </div>
      )}
      {score.tier !== "disqualified" && (
        <p className="mt-1 text-[11px] text-slate-500">
          Warm from {config.warm_lead_threshold}, hot from {config.hot_lead_threshold}
          {!score.complete && " · provisional until all answers are in"}
        </p>
      )}

      {score.disqualified_reason && (
        <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">
          {score.disqualified_reason} <span className="text-slate-500">Not booked.</span>
        </p>
      )}

      {score.breakdown.length > 0 && (
        <ul className="mt-3 space-y-1.5" aria-label="Score breakdown">
          {score.breakdown.map((b) => (
            <li key={b.rule} className="text-xs">
              <div className="flex justify-between">
                <span className="text-slate-700">{humanize(b.rule)}</span>
                <span className="font-mono tabular-nums text-slate-900">+{b.points}</span>
              </div>
              <div className="mt-0.5 h-1 rounded bg-slate-100">
                <div className="h-1 rounded bg-brand/60" style={{ width: `${(Math.abs(b.points) / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function QualificationCard({ detail, config }: { detail: LeadDetail; config: CompanyConfig }) {
  return (
    <Card title="Qualification answers">
      <ul className="space-y-2">
        {config.fields.map((f) => {
          const answer = detail.answers[f.key];
          return (
            <li key={f.key} className="flex items-start justify-between gap-3 text-sm">
              <span className="min-w-0">
                <span className="block text-slate-800">{humanize(f.key)}</span>
                <span className="block truncate text-[11px] text-slate-400" title={f.question}>
                  {f.question}
                </span>
              </span>
              {answer === undefined ? (
                <Badge className="bg-amber-50 text-amber-700 ring-amber-200">Missing</Badge>
              ) : (
                <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-800">
                  {typeof answer === "number" ? answer.toLocaleString() : humanize(String(answer))}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function RoutingCard({ detail }: { detail: LeadDetail }) {
  const r = detail.routing;
  return (
    <Card title="Routing">
      {r.office_name ? (
        <>
          <p className="text-sm font-semibold text-slate-900">{r.office_name}</p>
          <p className="text-sm text-slate-700">Rep: {r.rep_name}</p>
          {r.reason && <p className="mt-1 text-xs text-slate-500">{r.reason}</p>}
        </>
      ) : (
        <p className="text-sm text-slate-500">{r.reason ?? "Not routed yet. Needs a zip code."}</p>
      )}
    </Card>
  );
}

export function BookingCard({ detail, timeZone }: { detail: LeadDetail; timeZone: string }) {
  const b = detail.booking;
  return (
    <Card title="Appointment">
      {b ? (
        <div data-testid="booking">
          <Badge className="bg-emerald-100 text-emerald-800 ring-emerald-200">Booked</Badge>
          <p className="mt-2 text-base font-semibold text-slate-900">{formatDateTime(b.start, timeZone)}</p>
          <p className="text-sm text-slate-700">{b.kind}</p>
          <p className="text-xs text-slate-500">
            {b.rep_name} · {b.office_name}
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-500">
          {detail.summary.status === "closed" || detail.score?.tier === "disqualified"
            ? "No appointment. This lead was closed, not booked."
            : "No appointment yet."}
        </p>
      )}
    </Card>
  );
}

export function CrmCard({ detail }: { detail: LeadDetail }) {
  const crm = detail.crm;
  const rows = Object.entries(crm.properties);
  return (
    <Card title="CRM record" className="col-span-2">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs text-slate-600">
          {crm.pipeline} <span className="text-slate-400">›</span>{" "}
          <span className="font-semibold text-slate-900">{crm.stage ?? "not created yet"}</span>
        </p>
        <Badge className={crm.synced ? "bg-emerald-100 text-emerald-800 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200"}>
          {crm.synced ? `Written${crm.contact_id ? ` · ${crm.contact_id}` : ""}` : "Preview"}
        </Badge>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing to write yet.</p>
      ) : (
        <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1 text-xs">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="truncate font-mono text-slate-500">{k}</dt>
              <dd className="break-words text-slate-900">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}

export function SlackCard({ n, timeZone, appName }: { n: Notification; timeZone: string; appName: string }) {
  return (
    <div
      data-testid="slack-card"
      className={`rounded-lg border bg-white p-3 ${n.priority === "urgent" ? "border-l-4 border-l-rose-500 border-slate-200" : "border-slate-200"}`}
    >
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded bg-brand text-[11px] font-bold text-brand-fg">
          {appName.slice(0, 2).toUpperCase()}
        </span>
        <span className="text-sm font-bold text-slate-900">Lead Agent</span>
        <span className="rounded bg-slate-200 px-1 text-[10px] font-semibold text-slate-600">APP</span>
        <span className="text-[11px] text-slate-400">{formatClock(n.created_at, timeZone)}</span>
        <span className="ml-auto text-[11px] text-slate-500">{n.channel}</span>
      </div>
      <p className="mt-2 text-sm text-slate-900">
        {n.mention && <span className="mr-1 rounded bg-sky-100 px-1 font-medium text-sky-800">@{n.mention}</span>}
        <span className="font-semibold">{n.title}</span>
      </p>
      {Object.keys(n.fields).length > 0 && (
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {Object.entries(n.fields).map(([k, v]) => (
            <div key={k}>
              <dt className="text-slate-500">{k}</dt>
              <dd className="font-medium text-slate-900">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {n.note && <p className="mt-2 text-xs italic text-slate-600">{n.note}</p>}
    </div>
  );
}

interface Props {
  detail: LeadDetail | undefined;
  config: CompanyConfig | undefined;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onTakeover?: () => void;
  onHumanMessage?: (text: string) => void;
  actionPending?: boolean;
}

export function RepView({ detail, config, loading, error, onRetry, onTakeover, onHumanMessage, actionPending }: Props) {
  const [draft, setDraft] = useState("");

  if (error) return <ErrorState message={error} onRetry={onRetry} title="Can't load this lead" />;
  if (loading || !config) return <Skeleton lines={8} />;
  if (!detail) {
    return <EmptyState title="No lead selected" hint="Submit a lead or play a scenario to see what the rep sees." />;
  }

  const { summary, lead } = detail;
  const human = summary.status === "human";

  return (
    <div className="h-full space-y-3 overflow-y-auto p-4">
      <div className="card flex items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="truncate text-lg font-semibold text-slate-900">{lead.name ?? lead.phone ?? lead.email ?? "Unknown lead"}</p>
          <p className="truncate text-xs text-slate-500">
            {[lead.phone, lead.email].filter(Boolean).join(" · ")}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge>{humanize(lead.source)}</Badge>
            <Badge className="bg-brand-soft text-brand-strong ring-brand/30">{STATUS_LABEL[summary.status]}</Badge>
            <Badge>SMS: {humanize(summary.consent)}</Badge>
          </div>
        </div>
        {onTakeover && !human && (
          <GhostButton onClick={onTakeover} disabled={actionPending}>
            Take over
          </GhostButton>
        )}
      </div>

      {human && onHumanMessage && (
        <form
          className="card flex gap-2 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) {
              onHumanMessage(draft.trim());
              setDraft("");
            }
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Message as rep"
            placeholder="Message the lead as the rep…"
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <button className="rounded-lg bg-slate-800 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={!draft.trim()}>
            Send
          </button>
        </form>
      )}

      <div className="grid grid-cols-2 gap-3">
        <ScoreCard detail={detail} config={config} />
        <QualificationCard detail={detail} config={config} />
        <RoutingCard detail={detail} />
        <BookingCard detail={detail} timeZone={config.timezone} />
        <CrmCard detail={detail} />
      </div>

      <section aria-label="Slack notifications" className="card p-4">
        <h3 className="label mb-2">Slack notifications</h3>
        {detail.notifications.length === 0 ? (
          <p className="text-sm text-slate-500">No one has been pinged yet.</p>
        ) : (
          <div className="space-y-2">
            {detail.notifications.map((n, i) => (
              <SlackCard key={`${n.kind}-${i}`} n={n} timeZone={config.timezone} appName={config.name} />
            ))}
          </div>
        )}
      </section>

      {detail.flags.length > 0 && (
        <section aria-label="Flags" className="card p-4">
          <h3 className="label mb-2">Flags</h3>
          <div className="flex flex-wrap gap-1.5">
            {detail.flags.map((f) => (
              <Badge key={f} className="bg-amber-50 text-amber-800 ring-amber-200">
                {f}
              </Badge>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
