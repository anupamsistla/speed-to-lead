import { useEffect, useState } from "react";
import type { ScenarioBrief } from "../types";
import { PrimaryButton } from "./ui";

interface Props {
  scenarios: ScenarioBrief[] | undefined;
  loading?: boolean;
  error?: string | null;
  playing?: boolean;
  onPlay: (id: string) => void;
}

/** Loads a saved scenario from evals/scenarios and plays it through, so demos are repeatable. */
export function ScenarioReplay({ scenarios, loading, error, playing, onPlay }: Props) {
  const [selected, setSelected] = useState("");

  useEffect(() => {
    if (scenarios?.length && !scenarios.some((s) => s.id === selected)) setSelected(scenarios[0].id);
  }, [scenarios, selected]);

  const current = scenarios?.find((s) => s.id === selected);

  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-3" aria-label="Scenario replay">
      <p className="label mb-1.5">Replay a saved scenario</p>
      {error ? (
        <p role="alert" className="text-xs text-rose-700">
          Couldn't load scenarios: {error}
        </p>
      ) : loading ? (
        <div role="status" aria-label="Loading scenarios" className="h-8 animate-pulse rounded bg-slate-200" />
      ) : !scenarios?.length ? (
        <p className="text-xs text-slate-500">No saved scenarios for this company yet.</p>
      ) : (
        <>
          <div className="flex gap-2">
            <select
              aria-label="Scenario"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
            >
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
            <PrimaryButton type="button" disabled={playing || !selected} onClick={() => onPlay(selected)}>
              {playing ? "Starting…" : "Play"}
            </PrimaryButton>
          </div>
          {current?.description && <p className="mt-1.5 text-xs text-slate-500">{current.description}</p>}
        </>
      )}
    </div>
  );
}
