"""Draft a new company's config from its public website.

    python scripts/draft_company.py --url https://example.com --slug acme_roofing

Scrapes the public site (respecting robots.txt), has Claude extract claims, verifies every claim
against the page text, and writes companies/<slug>/ with a TODO on every guess and every gap.
The engine refuses to run that company until every TODO is resolved.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from leadagent.onboarding import draft_company  # noqa: E402
from leadagent.onboarding.extract import AnthropicExtractor  # noqa: E402


def main(argv: list[str] | None = None, *, extractor=None, client=None, resolver=None) -> int:
    p = argparse.ArgumentParser(description="Draft a company config from its website")
    p.add_argument("--url", required=True, help="the company's public website")
    p.add_argument("--slug", required=True, help="folder name under companies/, e.g. acme_roofing")
    p.add_argument("--max-pages", type=int, default=12)
    p.add_argument("--force", action="store_true", help="overwrite an existing folder")
    p.add_argument(
        "--allow-private", action="store_true", help="allow localhost or private-network URLs"
    )
    p.add_argument(
        "--out", type=Path, default=None, help="companies directory (default: companies/)"
    )
    args = p.parse_args(argv)

    load_dotenv(ROOT / ".env")
    if extractor is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "ANTHROPIC_API_KEY is not set. Add it to .env to draft a company.", file=sys.stderr
            )
            return 2
        extractor = AnthropicExtractor()

    try:
        r = draft_company(
            args.url,
            args.slug,
            extractor=extractor,
            out_root=args.out,
            client=client,
            force=args.force,
            max_pages=args.max_pages,
            allow_private=args.allow_private,
            resolver=resolver,
            log=lambda m: print(m, file=sys.stderr),
        )
    except (ValueError, FileExistsError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print(f"\nDrafted {r.out_dir} from {len(r.pages)} pages.")
    print("\nVerified against the website:")
    for k, n in r.verified.items():
        print(f"  {k:<22} {n}")
    if r.dropped:
        print(f"\nLeft out because the model's claim could not be verified ({len(r.dropped)}):")
        for d in r.dropped:
            print(f"  - {d}")
    if r.skipped:
        print(f"\nPages not read ({len(r.skipped)}): see DRAFT_NOTES.txt")
    print(f"\n{r.todos} TODO markers need a human. Nothing will run until they are resolved:")
    print(f"  grep -rn TODO {r.out_dir}")
    print(f"  python run.py --company {args.slug} --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
