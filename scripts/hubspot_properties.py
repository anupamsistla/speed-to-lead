"""List, and optionally create, the HubSpot contact properties a company's CRM mapping needs.

    python scripts/hubspot_properties.py --company <slug>            # list (no token needed)
    python scripts/hubspot_properties.py --company <slug> --create   # needs HUBSPOT_TOKEN

The pipeline and its stages are not created for you. They must already exist as a deal pipeline
in HubSpot with the exact names in crm_mapping.yaml.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from leadagent.adapters.hubspot import (  # noqa: E402
    BASE_URL,
    HubSpotError,
    ensure_properties,
    required_properties,
)  # noqa: E402
from leadagent.config import ConfigError, load_company  # noqa: E402


def main(argv: list[str] | None = None, *, client: httpx.Client | None = None) -> int:
    p = argparse.ArgumentParser(description="HubSpot contact properties for a company")
    p.add_argument("--company", required=True)
    p.add_argument("--create", action="store_true", help="create the missing properties")
    args = p.parse_args(argv)
    load_dotenv(ROOT / ".env")

    try:
        bundle = load_company(args.company)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    wanted = required_properties(bundle)
    m = bundle.crm_mapping
    print(f"{bundle.company.name}: {len(wanted)} contact properties are written.")
    stages = f"'{m.stage_on_create}' and '{m.stage_on_booked}'"
    print(f"Deal pipeline '{m.pipeline}' needs the stages {stages}.\n")
    if not args.create:
        for name, spec in wanted.items():
            print(f"  {name:<32} {spec['type']}")
        print("\nRun again with --create (and HUBSPOT_TOKEN set) to create the missing ones.")
        return 0

    token = os.environ.get("HUBSPOT_TOKEN", "")
    if not token:
        print("HUBSPOT_TOKEN is not set. Add it to .env first.", file=sys.stderr)
        return 2
    client = client or httpx.Client(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=15
    )
    try:
        result = ensure_properties(client, wanted)
    except HubSpotError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Already there: {len(result['existing'])}. Created: {len(result['created'])}.")
    for name in result["created"]:
        print(f"  + {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
