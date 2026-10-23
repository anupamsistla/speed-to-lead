import { useState } from "react";
import { handoffNotices } from "../lib";
import type { LeadDetail, LeadIn, ScenarioBrief } from "../types";
import { ChatThread } from "./ChatThread";
import { ScenarioReplay } from "./ScenarioReplay";
import { GhostButton, PrimaryButton } from "./ui";

export type LeadFormValues = {
  source: "web_form" | "missed_call" | "text";
  name: string;
  phone: string;
  email: string;
  message: string;
  consent: boolean;
};

export const EMPTY_FORM: LeadFormValues = {
  source: "web_form",
  name: "",
  phone: "",
  email: "",
  message: "",
  consent: false,
};

const SOURCES: { id: LeadFormValues["source"]; label: string; hint: string }[] = [
  { id: "web_form", label: "Web form", hint: "A visitor fills in the contact form." },
  { id: "missed_call", label: "Missed call", hint: "The agent texts the caller back." },
  { id: "text", label: "Inbound text", hint: "The lead texts the business number." },
];

/** Pure validation, mirrored from the API's rules so errors show before the round trip. */
export function validateLead(v: LeadFormValues): Partial<Record<keyof LeadFormValues, string>> {
  const errors: Partial<Record<keyof LeadFormValues, string>> = {};
  const needsPhone = v.source === "missed_call" || v.source === "text";
  if (needsPhone && !v.phone.trim()) errors.phone = "A phone number is required for this source.";
  if (!v.phone.trim() && !v.email.trim()) errors.phone = "Add a phone number or an email address.";
  if (v.email.trim() && !/^\S+@\S+\.\S+$/.test(v.email.trim())) errors.email = "That email doesn't look right.";
  if (v.source === "text" && !v.message.trim()) errors.message = "A text lead needs a message.";
  return errors;
}

export function toLeadIn(v: LeadFormValues, company: string | undefined): LeadIn {
  return {
    company,
    source: v.source,
    name: v.name.trim() || null,
    phone: v.phone.trim() || null,
    email: v.email.trim() || null,
    message: v.source === "missed_call" ? "" : v.message.trim(),
    consent: v.consent ? true : null,
  };
}

interface Props {
  companySlug: string | undefined;
  timeZone?: string;
  detail: LeadDetail | undefined;
  hasLead: boolean;
  typing: boolean;
  submitting: boolean;
  submitError?: string | null;
  onSubmit: (lead: LeadIn) => void;
  onReply: (text: string) => void;
  replying?: boolean;
  onNewLead: () => void;
  scenarios: ScenarioBrief[] | undefined;
  scenariosLoading?: boolean;
  scenariosError?: string | null;
  onPlayScenario: (id: string) => void;
  playing?: boolean;
}

const QUICK_REPLIES = ["The first one works", "I want to talk to a real person", "STOP"];

export function LeadSimulator(p: Props) {
  const [values, setValues] = useState<LeadFormValues>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);
  const errors = validateLead(values);
  const set = <K extends keyof LeadFormValues>(k: K, v: LeadFormValues[K]) =>
    setValues((s) => ({ ...s, [k]: v }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(errors).length) return;
    p.onSubmit(toLeadIn(values, p.companySlug));
  };

  const input =
    "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-3 border-b border-slate-200 p-3">
        <ScenarioReplay
          scenarios={p.scenarios}
          loading={p.scenariosLoading}
          error={p.scenariosError}
          playing={p.playing}
          onPlay={p.onPlayScenario}
        />
      </div>

      {!p.hasLead ? (
        <form onSubmit={submit} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4" aria-label="Submit a lead" noValidate>
          <div role="radiogroup" aria-label="Lead source" className="grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1">
            {SOURCES.map((s) => (
              <button
                key={s.id}
                type="button"
                role="radio"
                aria-checked={values.source === s.id}
                onClick={() => set("source", s.id)}
                className={`rounded-md px-2 py-1.5 text-xs font-medium transition ${
                  values.source === s.id ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
          <p className="-mt-1 text-xs text-slate-500">{SOURCES.find((s) => s.id === values.source)?.hint}</p>

          <label className="block text-xs font-medium text-slate-700">
            Name
            <input className={`${input} mt-1`} value={values.name} onChange={(e) => set("name", e.target.value)} autoComplete="off" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs font-medium text-slate-700">
              Phone
              <input className={`${input} mt-1`} value={values.phone} onChange={(e) => set("phone", e.target.value)} inputMode="tel" autoComplete="off" aria-invalid={touched && !!errors.phone} />
            </label>
            <label className="block text-xs font-medium text-slate-700">
              Email
              <input className={`${input} mt-1`} value={values.email} onChange={(e) => set("email", e.target.value)} inputMode="email" autoComplete="off" aria-invalid={touched && !!errors.email} />
            </label>
          </div>
          {touched && (errors.phone || errors.email) && (
            <p role="alert" className="text-xs text-rose-700">
              {errors.phone ?? errors.email}
            </p>
          )}

          {values.source !== "missed_call" && (
            <label className="block text-xs font-medium text-slate-700">
              Message
              <textarea
                className={`${input} mt-1 min-h-[96px] resize-y`}
                value={values.message}
                onChange={(e) => set("message", e.target.value)}
                placeholder="What is the lead asking for?"
                aria-invalid={touched && !!errors.message}
              />
            </label>
          )}
          {touched && errors.message && (
            <p role="alert" className="text-xs text-rose-700">
              {errors.message}
            </p>
          )}

          <label className="flex items-start gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={values.consent} onChange={(e) => set("consent", e.target.checked)} className="mt-0.5" />
            The lead agreed to receive text messages
          </label>

          {p.submitError && (
            <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800">
              {p.submitError}
            </p>
          )}
          <div className="flex gap-2">
            <PrimaryButton type="submit" className="flex-1" disabled={p.submitting}>
              {p.submitting ? "Sending…" : "Send lead"}
            </PrimaryButton>
            <GhostButton type="button" onClick={p.onNewLead} disabled={p.submitting}>
              Reset interaction
            </GhostButton>
          </div>
        </form>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
            <p className="truncate text-sm font-medium text-slate-800">
              {p.detail?.lead.name ?? p.detail?.lead.phone ?? "New lead"}
            </p>
            <GhostButton onClick={p.onNewLead}>Reset interaction</GhostButton>
          </div>
          <div className="min-h-0 flex-1">
            <ChatThread
              messages={p.detail?.messages ?? []}
              deferred={p.detail?.deferred}
              notices={handoffNotices(p.detail)}
              typing={p.typing}
              timeZone={p.timeZone}
              onSend={p.onReply}
              sending={p.replying}
              quickReplies={QUICK_REPLIES}
            />
          </div>
        </div>
      )}
    </div>
  );
}
