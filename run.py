"""Entry point: python run.py --company <slug>

Validates the company config and prints a summary. The API server is wired in phase 4.
"""

from __future__ import annotations

import argparse
import sys

from leadagent.config import ConfigError, list_companies, load_company


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Speed-to-lead agent")
    parser.add_argument("--company", required=True, help="folder name under companies/")
    args = parser.parse_args(argv)

    try:
        bundle = load_company(args.company)
    except ConfigError as e:
        print(e, file=sys.stderr)
        print(f"Available companies: {', '.join(list_companies()) or 'none'}", file=sys.stderr)
        return 2

    offices = bundle.routing.offices
    reps = sum(len(o.reps) for o in offices)
    print(
        f"Loaded '{bundle.company.name}': {len(offices)} offices, {reps} reps, "
        f"{len(bundle.qualification.required_fields)} qualification fields, "
        f"{len(bundle.knowledge)} knowledge docs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
