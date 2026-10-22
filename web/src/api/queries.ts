import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { LeadDetail, LeadIn } from "../types";
import { api, unwrap } from "./client";

export const keys = {
  companies: ["companies"] as const,
  config: (slug: string) => ["config", slug] as const,
  lead: (id: string) => ["lead", id] as const,
  scenarios: (slug: string) => ["scenarios", slug] as const,
  clock: ["clock"] as const,
  health: ["health"] as const,
};

export const useHealth = () =>
  useQuery({
    queryKey: keys.health,
    queryFn: () => unwrap(api.GET("/api/health")),
    refetchInterval: 15000,
  });

export const useCompanies = () =>
  useQuery({ queryKey: keys.companies, queryFn: () => unwrap(api.GET("/api/companies")) });

export const useCompanyConfig = (slug: string | undefined) =>
  useQuery({
    queryKey: keys.config(slug ?? ""),
    enabled: !!slug,
    queryFn: () =>
      unwrap(api.GET("/api/companies/{slug}/config", { params: { path: { slug: slug! } } })),
  });

export const useLead = (id: string | null) =>
  useQuery({
    queryKey: keys.lead(id ?? ""),
    enabled: !!id,
    queryFn: () => unwrap(api.GET("/api/leads/{lead_id}", { params: { path: { lead_id: id! } } })),
  });

export const useScenarios = (company: string | undefined) =>
  useQuery({
    queryKey: keys.scenarios(company ?? ""),
    enabled: !!company,
    queryFn: () => unwrap(api.GET("/api/scenarios", { params: { query: { company } } })),
  });

export const useClock = () =>
  useQuery({
    queryKey: keys.clock,
    queryFn: () => unwrap(api.GET("/api/clock")),
    refetchInterval: 10000,
  });

export function useSubmitLead() {
  return useMutation({
    mutationFn: (body: LeadIn) => unwrap(api.POST("/api/leads", { body })),
  });
}

export function useReplayScenario() {
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/scenarios/{scenario_id}/replay", { params: { path: { scenario_id: id } } }),
      ),
  });
}

export function useReply(leadId: string | null) {
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(
        api.POST("/api/leads/{lead_id}/messages", {
          params: { path: { lead_id: leadId! } },
          body: { text },
        }),
      ),
  });
}

export function useTakeover(leadId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/leads/{lead_id}/takeover", { params: { path: { lead_id: leadId! } } })),
    onSuccess: (summary) => {
      qc.setQueryData<LeadDetail | undefined>(keys.lead(leadId!), (d) => d && { ...d, summary });
      qc.invalidateQueries({ queryKey: keys.lead(leadId!) });
    },
  });
}

export function useResume(leadId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/leads/{lead_id}/resume", { params: { path: { lead_id: leadId! } } })),
    onSuccess: (summary) => {
      qc.setQueryData<LeadDetail | undefined>(keys.lead(leadId!), (d) => d && { ...d, summary });
      qc.invalidateQueries({ queryKey: keys.lead(leadId!) });
    },
  });
}

export function useHumanMessage(leadId: string | null) {
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(
        api.POST("/api/leads/{lead_id}/human-message", {
          params: { path: { lead_id: leadId! } },
          body: { text },
        }),
      ),
  });
}

export function useSetClock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { preset: "business_hours" | "after_hours" | "real"; company?: string }) =>
      unwrap(api.PUT("/api/clock", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.clock }),
  });
}

export type { LeadDetail };
