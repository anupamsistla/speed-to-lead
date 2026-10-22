import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { keys } from "../api/queries";
import { reduceEvent, reduceProcessing } from "../api/events";
import { STREAM_EVENT_TYPES, type LeadDetail, type StreamEvent } from "../types";

export interface EventSourceLike {
  addEventListener(type: string, listener: (e: MessageEvent) => void): void;
  close(): void;
  onerror: ((e: Event) => void) | null;
  onopen: ((e: Event) => void) | null;
}
export type EventSourceFactory = (url: string) => EventSourceLike;

const defaultFactory: EventSourceFactory = (url) => new EventSource(url) as EventSourceLike;

export interface LeadStream {
  connected: boolean;
  /** The agent is mid-turn (drives the typing indicator). */
  processing: boolean;
  lastEvent: StreamEvent | null;
}

/**
 * Subscribe to a lead's Server-Sent Events. Patches the cached lead detail as events arrive
 * and refetches it (debounced) on `state`, so server-computed fields stay authoritative.
 * The browser reconnects by itself and resumes from Last-Event-ID.
 */
export function useLeadStream(
  leadId: string | null,
  factory: EventSourceFactory = defaultFactory,
): LeadStream {
  const qc = useQueryClient();
  const [state, setState] = useState<LeadStream>({ connected: false, processing: false, lastEvent: null });
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    setState({ connected: false, processing: false, lastEvent: null });
    if (!leadId) return;
    const es = factory(`/api/leads/${leadId}/events`);
    es.onopen = () => setState((s) => ({ ...s, connected: true }));
    es.onerror = () => setState((s) => ({ ...s, connected: false }));

    const refetch = () => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => qc.invalidateQueries({ queryKey: keys.lead(leadId) }), 120);
    };

    for (const type of STREAM_EVENT_TYPES) {
      es.addEventListener(type, (e) => {
        let ev: StreamEvent;
        try {
          ev = JSON.parse(e.data) as StreamEvent;
        } catch {
          return;
        }
        qc.setQueryData<LeadDetail | undefined>(keys.lead(leadId), (d) => reduceEvent(d, ev));
        setState((s) => ({
          connected: true,
          processing: reduceProcessing(s.processing, ev),
          lastEvent: ev,
        }));
        if (type === "state" || type === "turn_done" || type === "error") refetch();
      });
    }
    return () => {
      clearTimeout(timer.current);
      es.close();
    };
  }, [leadId, factory, qc]);

  return state;
}
