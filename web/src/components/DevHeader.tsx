import { formatDateTime } from "../lib";
import type { CompanyBrief, Health } from "../types";

interface Props {
  companies: CompanyBrief[];
  current: string | undefined;
  onCompany: (slug: string) => void;
  clock?: { now: string; simulated: boolean };
  onPreset: (preset: "business_hours" | "after_hours" | "real") => void;
  health?: Health;
  timeZone?: string;
}

/** Developer-only controls: switch company and pretend it is a different time. */
export function DevHeader({ companies, current, onCompany, clock, onPreset, health, timeZone }: Props) {
  const btn = "rounded border border-slate-600 px-2 py-0.5 text-xs text-slate-200 hover:bg-slate-700";
  return (
    <div
      data-testid="dev-header"
      className="flex items-center gap-4 bg-slate-900 px-4 py-1.5 text-xs text-slate-300"
    >
      <span className="rounded bg-amber-400 px-1.5 py-0.5 font-bold uppercase tracking-wide text-slate-900">Dev</span>
      <label className="flex items-center gap-2">
        Company
        <select
          aria-label="Company"
          value={current ?? ""}
          onChange={(e) => onCompany(e.target.value)}
          className="rounded border border-slate-600 bg-slate-800 px-2 py-0.5 text-slate-100"
        >
          {companies.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <span className="flex items-center gap-2">
        Clock
        <button type="button" className={btn} onClick={() => onPreset("business_hours")}>
          Business hours
        </button>
        <button type="button" className={btn} onClick={() => onPreset("after_hours")}>
          After hours
        </button>
        <button type="button" className={btn} onClick={() => onPreset("real")}>
          Real time
        </button>
        {clock && (
          <span className={clock.simulated ? "text-amber-300" : "text-slate-400"}>
            {clock.simulated ? "simulated " : "real "}
            {formatDateTime(clock.now, timeZone)}
          </span>
        )}
      </span>
      <span className="ml-auto flex items-center gap-3">
        {health && (
          <>
            <span className={health.llm === "ready" ? "text-emerald-400" : "text-rose-400"}>
              {health.llm === "ready" ? `Model: ${health.model}` : "No API key"}
            </span>
            <span className="text-slate-400">
              {Object.entries(health.adapters)
                .map(([k, v]) => `${k}:${v}`)
                .join(" ")}
            </span>
          </>
        )}
      </span>
    </div>
  );
}
