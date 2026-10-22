"""Entry point: python run.py --company <slug>

Validates the company config, then serves the API (and the built web app, if present).
Use --check to validate only. Other companies stay selectable from the UI without a restart.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))  # works without install

from leadagent.config import ConfigError, list_companies, load_company  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Speed-to-lead agent")
    parser.add_argument("--company", required=True, help="folder name under companies/")
    parser.add_argument("--check", action="store_true", help="validate the config and exit")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
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
    if args.check:
        return 0

    import uvicorn

    from leadagent.server import Settings, create_app

    app = create_app(Settings.from_env(default_company=args.company))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
