import { earliestDeliver } from "./lib";
import type { TimerPhase } from "./components/FirstResponseTimer";
import type { LeadDetail } from "./types";

export interface TimerState {
  phase: TimerPhase;
  seconds: number | null;
  queuedUntil: string | null;
}

/** Decide what the first-response timer should show for the current lead. */
export function deriveTimer(detail: LeadDetail | undefined, working: boolean): TimerState {
  if (!detail) return { phase: "idle", seconds: null, queuedUntil: null };
  const fr = detail.summary.first_response_seconds;
  if (fr != null) return { phase: "done", seconds: fr, queuedUntil: null };
  if (detail.deferred.length > 0) {
    return { phase: "queued", seconds: null, queuedUntil: earliestDeliver(detail.deferred) };
  }
  const closedSilently = ["spam", "closed", "escalated", "human"].includes(detail.summary.status);
  if (!working && closedSilently) return { phase: "silent", seconds: null, queuedUntil: null };
  return { phase: "running", seconds: null, queuedUntil: null };
}
