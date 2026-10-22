"""python -m leadagent.evals --company <slug> | --all"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from leadagent.config import ConfigError, list_companies, load_company
from leadagent.config.loader import REPO_ROOT
from leadagent.evals.judge import Judge
from leadagent.evals.metrics import aggregate
from leadagent.evals.report import format_metrics, format_table, write_results
from leadagent.evals.runner import ScenarioResult, run_scenario
from leadagent.llm import LLM, AnthropicLLM
from leadagent.scenarios import Scenario, load_scenarios

# Exit non-zero if the pass rate falls below this, or if there is any guardrail violation.
DEFAULT_MIN_PASS_RATE = 1.0


def run_company(
    slug: str,
    llm: LLM,
    judge: Any,
    *,
    only: set[str] | None,
    repeat: int,
    concurrency: int,
    scenarios_dir: Path | None = None,
    log: Any = sys.stderr,
) -> tuple[list[ScenarioResult], dict[str, Any]]:
    bundle = load_company(slug)
    scenarios: list[Scenario] = load_scenarios(slug, base=scenarios_dir)
    if only:
        scenarios = [s for s in scenarios if s.id in only]
    jobs = [(s, r) for s in scenarios for r in range(repeat)]

    def work(job: tuple[Scenario, int]) -> ScenarioResult:
        s, r = job
        res = run_scenario(bundle, s, llm, judge=judge, run=r)
        mark = "PASS" if res.passed else "FAIL"
        print(f"  [{slug}] {mark} {s.id} ({res.duration_s}s)", file=log, flush=True)
        return res

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(work, jobs))
    return results, aggregate(results)


def main(argv: list[str] | None = None, *, llm: LLM | None = None, judge: Any = None) -> int:
    p = argparse.ArgumentParser(prog="python -m leadagent.evals", description="Run the agent evals")
    p.add_argument("--company", action="append", help="company slug (repeatable)")
    p.add_argument("--all", action="store_true", help="every company that has scenarios")
    p.add_argument("--only", help="comma-separated scenario ids")
    p.add_argument("--repeat", type=int, default=1, help="runs per scenario (model variance)")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--no-judge", action="store_true", help="deterministic assertions only")
    p.add_argument("--min-pass-rate", type=float, default=DEFAULT_MIN_PASS_RATE)
    p.add_argument("--out-dir", type=Path, default=None)
    p.add_argument("--scenarios-dir", type=Path, default=None)
    args = p.parse_args(argv)

    load_dotenv(REPO_ROOT / ".env")
    slugs = args.company or []
    if args.all:
        slugs = [c for c in list_companies() if load_scenarios(c, base=args.scenarios_dir)]
    if not slugs:
        print("Nothing to run. Use --company <slug> or --all.", file=sys.stderr)
        return 2

    if llm is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set. Add it to .env to run the evals.", file=sys.stderr)
            return 2
        llm = AnthropicLLM()
    if judge is None and not args.no_judge:
        judge = Judge()
    only = set(args.only.split(",")) if args.only else None

    payload: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "model": getattr(llm, "model", type(llm).__name__),
        "judge_model": getattr(judge, "model", None),
        "repeat": args.repeat,
        "companies": {},
    }
    failed = False
    api_errors = 0
    started = time.time()
    for slug in slugs:
        print(f"\n=== {slug} ===", file=sys.stderr)
        try:
            results, metrics = run_company(
                slug,
                llm,
                judge,
                only=only,
                repeat=args.repeat,
                concurrency=args.concurrency,
                scenarios_dir=args.scenarios_dir,
            )
        except ConfigError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"\n{slug}\n")
        print(format_table(results))
        print("\nMetrics")
        print(format_metrics(metrics))
        if judge is not None and metrics["judge_checks"]:
            print("  (LLM-judge checks are the only non-deterministic assertions.)")
        payload["companies"][slug] = {"metrics": metrics, "results": [r.to_dict() for r in results]}
        pass_rate = metrics["pass_rate"] or 0.0
        if metrics["api_errors"]:
            api_errors += metrics["api_errors"]
        if metrics["guardrail_violations"] > 0 or pass_rate < args.min_pass_rate:
            failed = True

    payload["duration_s"] = round(time.time() - started, 1)
    path = write_results(payload, args.out_dir)
    print(f"\nSaved {path}")
    if api_errors:
        print(
            f"\nEVAL INVALID: the model API failed in {api_errors} run(s), for example a "
            "billing, rate-limit or network problem. Those runs say nothing about the agent. "
            "Fix the API problem and run again.",
            file=sys.stderr,
        )
        return 3
    if failed:
        print("EVAL FAILED: a guardrail was violated or too few scenarios passed.", file=sys.stderr)
    return 1 if failed else 0
