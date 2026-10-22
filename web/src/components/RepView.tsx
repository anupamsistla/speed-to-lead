import {
  formatDateTime,
  formatClock,
  humanize,
  STATUS_LABEL,
  TIER_STYLE,
  handoffNotices,
} from "../lib";
import type { CompanyConfig, LeadDetail, Notification } from "../types";
import { ChatThread } from "./ChatThread";
import { Badge, EmptyState, ErrorState, GhostButton, Skeleton } from "./ui";

function Card({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`card p-4 ${className}`} aria-label={title}>
      <h3 className="label mb-2">{title}</h3>
      {children}
    </section>
  );
}

export function ScoreCard({
  detail,
  config,
}: {
  detail: LeadDetail;
  config: CompanyConfig;
}) {
  const score = detail.score;
  if (!score) {
    return (
      <Card title="Lead score">
        <p className="text-sm text-slate-500">
          Not scored yet. The agent scores once it knows enough.
        </p>
      </Card>
    );
  }
  const tier = TIER_STYLE[score.tier];
  const max = Math.max(1, ...score.breakdown.map((b) => Math.abs(b.points)));
  return (
    <Card title="Lead score">
      <div className="flex items-end justify-between">
        <div className="flex items-baseline gap-1">
          <span
            data-testid="score-value"
            className="text-5xl font-semibold tabular-nums"
          >
            {score.tier === "disqualified" ? "n/a" : score.score}
          </span>
          {score.tier !== "disqualified" && (
            <span className="text-sm text-slate-500">/ 100</span>
          )}
        </div>
        <Badge className={tier.cls}>{tier.label}</Badge>
      </div>

      {score.tier !== "disqualified" && (
        <div
          className="relative mt-3 h-2 rounded-full bg-slate-100"
          aria-hidden
        >
          <div
            className="h-2 rounded-full bg-brand"
            style={{ width: `${Math.min(100, score.score)}%` }}
          />
          {[config.warm_lead_threshold, config.hot_lead_threshold].map((t) => (
            <span
              key={t}
              className="absolute top-[-3px] h-3.5 w-px bg-slate-400"
              style={{ left: `${t}%` }}
            />
          ))}
        </div>
      )}
      {score.tier !== "disqualified" && (
        <p className="mt-1 text-[11px] text-slate-500">
          Warm from {config.warm_lead_threshold}, hot from{" "}
          {config.hot_lead_threshold}
          {!score.complete && " · provisional until all answers are in"}
        </p>
      )}

      {score.disqualified_reason && (
        <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">
          {score.disqualified_reason}{" "}
          <span className="text-slate-500">Not booked.</span>
        </p>
      )}

      {score.breakdown.length > 0 && (
        <ul className="mt-3 space-y-1.5" aria-label="Score breakdown">
          {score.breakdown.map((b) => (
            <li key={b.rule} className="text-xs">
              <div className="flex justify-between">
                <span className="text-slate-700">{humanize(b.rule)}</span>
                <span className="font-mono tabular-nums text-slate-900">
                  +{b.points}
                </span>
              </div>
              <div className="mt-0.5 h-1 rounded bg-slate-100">
                <div
                  className="h-1 rounded bg-brand/60"
                  style={{ width: `${(Math.abs(b.points) / max) * 100}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function QualificationCard({
  detail,
  config,
}: {
  detail: LeadDetail;
  config: CompanyConfig;
}) {
  return (
    <Card title="Qualification answers">
      <ul className="space-y-2">
        {config.fields.map((f) => {
          const answer = detail.answers[f.key];
          return (
            <li
              key={f.key}
              className="flex items-start justify-between gap-3 text-sm"
            >
              <span className="min-w-0">
                <span className="block text-slate-800">{humanize(f.key)}</span>
                <span
                  className="block truncate text-[11px] text-slate-400"
                  title={f.question}
                >
                  {f.question}
                </span>
              </span>
              {answer === undefined ? (
                <Badge className="bg-amber-50 text-amber-700 ring-amber-200">
                  Missing
                </Badge>
              ) : (
                <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-800">
                  {typeof answer === "number"
                    ? answer.toLocaleString()
                    : humanize(String(answer))}
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
          <p className="text-sm font-semibold text-slate-900">
            {r.office_name}
          </p>
          <p className="text-sm text-slate-700">Rep: {r.rep_name}</p>
          {r.reason && (
            <p className="mt-1 text-xs text-slate-500">{r.reason}</p>
          )}
        </>
      ) : (
        <p className="text-sm text-slate-500">
          {r.reason ?? "Not routed yet. Needs a zip code."}
        </p>
      )}
    </Card>
  );
}

export function BookingCard({
  detail,
  timeZone,
}: {
  detail: LeadDetail;
  timeZone: string;
}) {
  const b = detail.booking;
  return (
    <Card title="Appointment">
      {b ? (
        <div data-testid="booking">
          <Badge className="bg-emerald-100 text-emerald-800 ring-emerald-200">
            Booked
          </Badge>
          <p className="mt-2 text-base font-semibold text-slate-900">
            {formatDateTime(b.start, timeZone)}
          </p>
          <p className="text-sm text-slate-700">{b.kind}</p>
          <p className="text-xs text-slate-500">
            {b.rep_name} · {b.office_name}
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-500">
          {detail.summary.status === "closed" ||
          detail.score?.tier === "disqualified"
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
          <span className="font-semibold text-slate-900">
            {crm.stage ?? "not created yet"}
          </span>
        </p>
        <Badge
          className={
            crm.synced
              ? "bg-emerald-100 text-emerald-800 ring-emerald-200"
              : "bg-slate-100 text-slate-600 ring-slate-200"
          }
        >
          {crm.synced
            ? `Written${crm.contact_id ? ` · ${crm.contact_id}` : ""}`
            : "Preview"}
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

/** One message, laid out like Slack posts a bot message: bold headline, then "key: value" lines. */
export function SlackCard({
  n,
  timeZone,
  appName,
}: {
  n: Notification;
  timeZone: string;
  appName: string;
}) {
  const fields = Object.entries(n.fields);
  return (
    <div
      data-testid="slack-card"
      data-priority={n.priority}
      className="group flex gap-2 px-5 py-1.5 font-[Lato,Inter,system-ui,sans-serif] hover:bg-[#f8f8f8]"
    >
      <span
        aria-hidden
        className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[6px] bg-brand text-[13px] font-bold text-brand-fg"
      >
        {appName.slice(0, 2).toUpperCase()}
      </span>
      <div className="min-w-0 flex-1 text-[15px] leading-[1.46] text-[#1d1c1d]">
        <div className="flex items-baseline gap-1.5">
          <span className="font-black hover:underline">Lead Agent</span>
          <span className="rounded-[3px] bg-[#e8e8e8] px-1 text-[10px] font-bold uppercase leading-[14px] text-[#616061]">
            App
          </span>
          <span className="text-xs text-[#616061] hover:underline">
            {formatClock(n.created_at, timeZone)}
          </span>
          <span className="ml-auto text-[11px] text-[#616061] opacity-0 group-hover:opacity-100">
            {n.channel}
          </span>
        </div>
        <p className="break-words font-bold">
          {n.priority === "urgent" && (
            <span role="img" aria-label="urgent" className="mr-1">
              🚨
            </span>
          )}
          {n.mention && (
            <span className="mr-1 rounded-[3px] bg-[#1d9bd11a] px-[3px] font-normal text-[#1264a3]">
              @{n.mention}
            </span>
          )}
          {n.title}
        </p>
        {fields.length > 0 && (
          <div className="break-words">
            {fields.map(([k, v]) => (
              <p key={k}>
                <strong>{k}:</strong> {v}
              </p>
            ))}
          </div>
        )}
        {n.note && <p className="break-words italic">{n.note}</p>}
      </div>
    </div>
  );
}

/** A mock Slack window: workspace bar, channel header, day divider, messages, and a (disabled) composer. */
export function SlackPanel({
  notifications,
  channel,
  workspace,
  timeZone,
}: {
  notifications: Notification[];
  channel: string;
  workspace: string;
  timeZone: string;
}) {
  const name = channel.replace(/^#/, "");
  return (
    <section
      aria-label="Slack notifications"
      className="overflow-hidden rounded-lg border border-[#dddddd] bg-white font-[Lato,Inter,system-ui,sans-serif] shadow-sm"
    >
      <div className="flex items-center gap-2 bg-[#3f0e40] px-4 py-1.5 text-[13px] font-bold text-white">
        <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden>
          <path
            fill="#36c5f0"
            d="M9 3a2 2 0 1 1 0 4H7V5a2 2 0 0 1 2-2Zm0 5a2 2 0 1 1 0 4H4a2 2 0 1 1 0-4h5Z"
          />
          <path
            fill="#2eb67d"
            d="M21 9a2 2 0 1 1-4 0V7a2 2 0 1 1 4 0v2Zm-5 0a2 2 0 1 1-4 0V4a2 2 0 1 1 4 0v5Z"
          />
          <path
            fill="#ecb22e"
            d="M15 21a2 2 0 1 1 0-4h2v2a2 2 0 0 1-2 2Zm0-5a2 2 0 1 1 0-4h5a2 2 0 1 1 0 4h-5Z"
          />
          <path
            fill="#e01e5a"
            d="M3 15a2 2 0 1 1 4 0v2a2 2 0 1 1-4 0v-2Zm5 0a2 2 0 1 1 4 0v5a2 2 0 1 1-4 0v-5Z"
          />
        </svg>
        <span className="truncate">{workspace}</span>
      </div>
      <div className="flex items-center gap-2 border-b border-[#dddddd] px-5 py-2">
        <h3 className="text-[15px] font-black text-[#1d1c1d]">
          <span className="mr-0.5 font-normal text-[#616061]">#</span>
          {name}
        </h3>
        <span className="text-[#616061]" aria-hidden>
          ☆
        </span>
      </div>
      <div className="relative py-2">
        <div className="relative my-2 flex items-center px-5" aria-hidden>
          <div className="absolute inset-x-0 top-1/2 border-t border-[#dddddd]" />
          <span className="relative mx-auto rounded-full border border-[#dddddd] bg-white px-3 py-0.5 text-xs font-bold text-[#1d1c1d]">
            Today
          </span>
        </div>
        {notifications.length === 0 ? (
          <p className="px-5 py-3 text-sm text-[#616061]">
            No one has been pinged yet.
          </p>
        ) : (
          notifications.map((n, i) => (
            <SlackCard
              key={`${n.kind}-${i}`}
              n={n}
              timeZone={timeZone}
              appName={workspace}
            />
          ))
        )}
      </div>
      <div className="px-5 pb-4">
        <div
          className="rounded-lg border border-[#868686] px-3 py-2.5 text-[15px] text-[#616061]"
          aria-hidden
        >
          Message #{name}
        </div>
      </div>
    </section>
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
  onResume?: () => void;
  /** Message from a failed take over or hand back. */
  actionError?: string | null;
  actionPending?: boolean;
}

export function RepView({
  detail,
  config,
  loading,
  error,
  onRetry,
  onTakeover,
  onHumanMessage,
  onResume,
  actionPending,
  actionError,
}: Props) {
  if (error)
    return (
      <ErrorState
        message={error}
        onRetry={onRetry}
        title="Can't load this lead"
      />
    );
  if (loading || !config) return <Skeleton lines={8} />;
  if (!detail) {
    return (
      <EmptyState
        title="No lead selected"
        hint="Submit a lead or play a scenario to see what the rep sees."
      />
    );
  }

  const { summary, lead } = detail;
  const human = summary.status === "human";

  return (
    <div className="h-full space-y-3 overflow-y-auto p-4">
      <div className="card flex items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="truncate text-lg font-semibold text-slate-900">
            {lead.name ?? lead.phone ?? lead.email ?? "Unknown lead"}
          </p>
          <p className="truncate text-xs text-slate-500">
            {[lead.phone, lead.email].filter(Boolean).join(" · ")}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge>{humanize(lead.source)}</Badge>
            <Badge
              className={
                human
                  ? "bg-indigo-50 text-indigo-800 ring-indigo-200"
                  : "bg-brand-soft text-brand-strong ring-brand/30"
              }
            >
              {STATUS_LABEL[summary.status]}
            </Badge>
            <Badge>SMS: {humanize(summary.consent)}</Badge>
          </div>
        </div>
        {onTakeover && !human && (
          <GhostButton onClick={onTakeover} disabled={actionPending}>
            Take over
          </GhostButton>
        )}
        {onResume && human && (
          <GhostButton onClick={onResume} disabled={actionPending}>
            Hand back to agent
          </GhostButton>
        )}
      </div>

      {actionError && (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800"
        >
          {actionError}
        </p>
      )}

      {human && (
        <section
          aria-label="Lead conversation"
          className="card overflow-hidden"
        >
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
            <h3 className="truncate text-sm font-medium text-slate-800">
              {detail.routing.rep_name ?? "Representative's Name"}
            </h3>
            <span className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700">
              Staff
            </span>
          </div>
          <div className="h-96">
            <ChatThread
              label="Live messages"
              messages={detail.messages}
              deferred={detail.deferred}
              notices={handoffNotices(detail)}
              timeZone={config.timezone}
              onSend={onHumanMessage}
              inputLabel="Message as rep"
              placeholder="Message the lead as the rep…"
              sendLabel="Send"
            />
          </div>
        </section>
      )}

      <div className="grid grid-cols-2 gap-3">
        <ScoreCard detail={detail} config={config} />
        <QualificationCard detail={detail} config={config} />
        <RoutingCard detail={detail} />
        <BookingCard detail={detail} timeZone={config.timezone} />
        <CrmCard detail={detail} />
      </div>

      <SlackPanel
        notifications={detail.notifications}
        channel={config.slack_channel}
        workspace={config.name}
        timeZone={config.timezone}
      />

      {detail.flags.length > 0 && (
        <section aria-label="Flags" className="card p-4">
          <h3 className="label mb-2">Flags</h3>
          <div className="flex flex-wrap gap-1.5">
            {detail.flags.map((f) => (
              <Badge
                key={f}
                className="bg-amber-50 text-amber-800 ring-amber-200"
              >
                {f}
              </Badge>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
