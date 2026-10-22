"""Console table and JSON results file."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from leadagent.config.loader import REPO_ROOT
from leadagent.evals.runner import ScenarioResult

METRIC_LABELS = [
    ("pass_rate", "Scenarios passed", "{:.0%}"),
    ("first_response_median_s", "First response, median", "{:.1f}s"),
    ("first_response_p95_s", "First response, p95", "{:.1f}s"),
    ("qualification_accuracy", "Qualification accuracy", "{:.0%}"),
    ("routing_accuracy", "Routing accuracy", "{:.0%}"),
    ("booking_rate", "Booking rate (where expected)", "{:.0%}"),
    ("guardrail_violations", "Guardrail violations", "{}"),
    ("judge_pass_rate", "LLM-judge pass rate", "{:.0%}"),
    ("backstops_used", "Safety-net rescues (info)", "{}"),
]


def _cell(v: Any) -> str:
    return "-" if v is None else ("yes" if v is True else "no" if v is False else str(v))


def format_table(results: list[ScenarioResult]) -> str:
    multi = len({r.run for r in results}) > 1
    rows = [("scenario", "result", "tier", "office", "booked", "1st reply", "notes")]
    for r in results:
        o = r.outcome
        name = f"{r.id}#{r.run + 1}" if multi else r.id
        fr = f"{r.first_response_seconds:.1f}s" if r.first_response_seconds is not None else "-"
        notes = "; ".join(r.violations + r.failures)
        if r.passed and r.backstops:
            notes = f"rescued: {', '.join(b.removeprefix('backstop:') for b in r.backstops)}"
        rows.append(
            (
                name,
                "PASS" if r.passed else "FAIL",
                _cell(o.get("tier")),
                _cell(o.get("office")),
                _cell(o.get("booked")),
                fr,
                notes[:110],
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    lines = []
    for n, row in enumerate(rows):
        cells = [c.ljust(w) for c, w in zip(row[:-1], widths, strict=True)]
        lines.append("  ".join(cells) + "  " + row[-1])
        if n == 0:
            lines.append("  ".join("-" * w for w in widths) + "  " + "-" * 5)
    return "\n".join(lines)


def format_metrics(metrics: dict[str, Any]) -> str:
    lines = []
    for key, label, fmt in METRIC_LABELS:
        v = metrics.get(key)
        lines.append(f"  {label:<34} {fmt.format(v) if v is not None else 'n/a'}")
    return "\n".join(lines)


def write_results(payload: dict[str, Any], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or REPO_ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path
