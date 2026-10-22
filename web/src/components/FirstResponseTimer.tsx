import { useEffect, useState } from "react";
import { formatClock, formatSeconds } from "../lib";

export type TimerPhase = "idle" | "running" | "done" | "queued" | "silent";

export const TARGET_SECONDS = 60;

/** Seconds elapsed since `startedAtMs`, ticking while `running`. `now` is injectable for tests. */
export function useElapsedSeconds(
  startedAtMs: number | null | undefined,
  running: boolean,
  now: () => number = Date.now,
  tickMs = 100,
): number {
  const read = () => (startedAtMs == null ? 0 : Math.max(0, (now() - startedAtMs) / 1000));
  const [elapsed, setElapsed] = useState(read);
  useEffect(() => {
    setElapsed(read());
    if (!running || startedAtMs == null) return;
    const id = setInterval(() => setElapsed(read()), tickMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, startedAtMs, tickMs]);
  return elapsed;
}

interface Props {
  phase: TimerPhase;
  /** Client time (ms) when the lead was submitted. Drives the running count-up. */
  startedAtMs?: number | null;
  /** Authoritative first_response_seconds from the server, once the first reply went out. */
  seconds?: number | null;
  /** When a reply held for quiet hours will go out. */
  queuedUntil?: string | null;
  timeZone?: string;
  now?: () => number;
}

export function FirstResponseTimer({ phase, startedAtMs, seconds, queuedUntil, timeZone, now }: Props) {
  const elapsed = useElapsedSeconds(startedAtMs, phase === "running", now);
  const shown = phase === "done" && seconds != null ? seconds : elapsed;
  const withinTarget = phase === "done" && seconds != null && seconds < TARGET_SECONDS;

  const tone =
    phase === "done"
      ? withinTarget
        ? "text-emerald-600"
        : "text-amber-600"
      : phase === "running"
        ? "text-brand"
        : "text-slate-400";

  return (
    <div
      role="timer"
      aria-label="First response time"
      data-phase={phase}
      className="rounded-xl border border-slate-200 bg-white px-4 py-3"
    >
      <div className="flex items-center justify-between">
        <span className="label">First response</span>
        {phase === "running" && (
          <span className="flex items-center gap-1 text-[11px] font-medium text-brand">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" /> Live
          </span>
        )}
        {phase === "done" && (
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
              withinTarget ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
            }`}
          >
            {withinTarget ? `Under ${TARGET_SECONDS}s target` : `Over ${TARGET_SECONDS}s target`}
          </span>
        )}
      </div>

      <div className={`mt-1 font-mono text-5xl font-semibold tabular-nums leading-none ${tone}`}>
        {phase === "idle" && "--"}
        {(phase === "running" || phase === "done") && formatSeconds(shown)}
        {phase === "queued" && <span className="text-3xl">Queued</span>}
        {phase === "silent" && <span className="text-3xl">No reply</span>}
      </div>

      <p className="mt-2 text-xs text-slate-500">
        {phase === "idle" && "Starts when a lead is submitted."}
        {phase === "running" && "Counting from the moment the lead was submitted."}
        {phase === "done" && "From lead submitted to the first message sent."}
        {phase === "queued" &&
          (queuedUntil
            ? `Quiet hours. The reply goes out at ${formatClock(queuedUntil, timeZone)}.`
            : "Quiet hours. The reply is held until morning.")}
        {phase === "silent" && "This lead was closed without sending a message."}
      </p>
    </div>
  );
}
