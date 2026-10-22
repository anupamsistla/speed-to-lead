/** Shared domain types, taken straight from the generated OpenAPI schema (src/api/schema.d.ts)
 *  so the UI and the API cannot drift. Regenerate with `npm run gen:api`. */
import type { components } from "./api/schema";

type S = components["schemas"];

export type Lead = S["Lead"];
export type Message = S["Message"];
export type ToolCall = S["ToolCall"];
export type Score = S["Score"];
export type ScoreItem = S["ScoreItem"];
export type Booking = S["Booking"];
export type Notification = S["Notification"];

export type LeadDetail = S["LeadDetail"];
export type LeadSummary = S["LeadSummary"];
export type LeadIn = S["LeadIn"];
export type LeadStatus = LeadSummary["status"];
export type LeadSource = LeadIn["source"] & string;
export type StreamEvent = S["StreamEvent"];
export type StreamEventType = StreamEvent["type"];
export type CompanyConfig = S["CompanyPublicConfig"];
export type CompanyBrief = S["CompanyBrief"];
export type ScenarioBrief = S["ScenarioBrief"];
export type Deferred = S["DeferredView"];
export type CRMPreview = S["CRMPreview"];
export type RoutingView = S["RoutingView"];
export type Health = S["Health"];

export const STREAM_EVENT_TYPES: StreamEventType[] = [
  "lead_created",
  "message",
  "deferred",
  "tool_call",
  "state",
  "notification",
  "first_response",
  "turn_done",
  "error",
];
