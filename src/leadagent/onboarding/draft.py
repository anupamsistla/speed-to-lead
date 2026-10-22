"""Orchestrate: scrape, extract, verify, render, write."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from leadagent.config.loader import companies_dir, find_todos
from leadagent.onboarding import render
from leadagent.onboarding.extract import SYSTEM, Extractor, Verified, build_prompt, verify
from leadagent.onboarding.scrape import USER_AGENT, Site, fetch_site

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/webp": "webp"}
MAX_LOGO_BYTES = 1_500_000


@dataclass
class DraftResult:
    out_dir: Path
    files: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    verified: dict[str, int] = field(default_factory=dict)
    todos: int = 0
    logo: str | None = None


def pick_brand_color(site: Site) -> tuple[str, str] | None:
    for page in site.pages:
        if page.theme_colors:
            return page.theme_colors[0], page.url
    return None


def download_logo(client: httpx.Client, site: Site, dest: Path) -> tuple[str, str] | None:
    seen: list[str] = []
    for page in site.pages:
        for c in page.logo_candidates:
            if c not in seen:
                seen.append(c)
    for url in seen[:8]:
        try:
            r = client.get(url)
        except (httpx.HTTPError, Exception):  # a blocked or broken image is simply skipped
            continue
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = IMAGE_EXT.get(ctype)
        if r.status_code == 200 and ext and 0 < len(r.content) <= MAX_LOGO_BYTES:
            name = f"logo.{ext}"
            (dest / name).write_bytes(r.content)
            return name, url
    return None


def draft_company(
    url: str,
    slug: str,
    *,
    extractor: Extractor,
    out_root: Path | None = None,
    client: httpx.Client | None = None,
    force: bool = False,
    max_pages: int = 12,
    allow_private: bool = False,
    delay: float = 0.3,
    resolver: Callable[..., list] | None = None,
    today: date | None = None,
    log: Callable[[str], None] = lambda s: None,
) -> DraftResult:
    if not SLUG_RE.match(slug):
        raise ValueError(
            "slug must be lowercase letters, digits and underscores, e.g. acme_roofing"
        )
    out_dir = (out_root or companies_dir()) / slug
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise FileExistsError(
            f"{out_dir} already exists and is not empty. Use --force to overwrite."
        )
    today = today or date.today()

    own = client is None
    client = client or httpx.Client(
        follow_redirects=True, timeout=15, headers={"User-Agent": USER_AGENT}
    )
    kwargs: dict[str, Any] = {"resolver": resolver} if resolver else {}
    try:
        log(f"Fetching {url}")
        site = fetch_site(
            url,
            client=client,
            max_pages=max_pages,
            delay=delay,
            allow_private=allow_private,
            **kwargs,
        )
        if not site.pages:
            reasons = "; ".join(site.skipped) or "no pages could be read"
            raise RuntimeError(f"Could not read {url}: {reasons}")
        log(f"Read {len(site.pages)} pages. Asking the model to extract claims.")
        extraction = extractor.extract(SYSTEM, build_prompt(site))
        v: Verified = verify(extraction, site)

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "knowledge").mkdir(exist_ok=True)
        logo = download_logo(client, site, out_dir)
        brand = pick_brand_color(site)
    finally:
        if own:
            client.close()

    files = {
        "company.yaml": render.render_company(url, v, today, brand, logo),
        "routing.yaml": render.render_routing(url, v, today),
        "qualification.yaml": render.render_qualification(url, v, today),
        "crm_mapping.yaml": render.render_crm(url, v, today),
        **render.render_knowledge(v, url),
    }
    for name, content in files.items():
        (out_dir / name).write_text(content, encoding="utf-8")
    (out_dir / "DRAFT_NOTES.txt").write_text(_notes(url, site, v), encoding="utf-8")

    return DraftResult(
        out_dir=out_dir,
        files=sorted(files),
        pages=[p.url for p in site.pages],
        skipped=site.skipped,
        dropped=v.dropped,
        verified={
            "company name": int(v.company_name is not None),
            "description": int(v.description is not None),
            "phone/email": int(v.phone is not None) + int(v.email is not None),
            "hours (days)": len(v.hours),
            "offices": len(v.offices),
            "zip codes": len({z.value for z in v.zips} | {z for o in v.offices for z in o.zips}),
            "knowledge statements": len(v.knowledge),
        },
        todos=len(find_todos(out_dir)),
        logo=logo[0] if logo else None,
    )


def _notes(url: str, site: Site, v: Verified) -> str:
    lines = [f"Draft for {url}", "", "Pages read:", *[f"  {p.url}" for p in site.pages]]
    if site.skipped:
        lines += ["", "Pages not read:", *[f"  {s}" for s in site.skipped]]
    if v.phone:
        lines += ["", f"Phone on the site: {v.phone.value}"]
    if v.email:
        lines += [f"Email on the site: {v.email.value}"]
    if v.dropped:
        lines += [
            "",
            "Claims the model made that could not be verified and were left out:",
            *[f"  {d}" for d in v.dropped],
        ]
    lines += [
        "",
        "Next: resolve every TODO (grep -rn TODO .), then run:",
        "  python run.py --company <slug> --check",
    ]
    return "\n".join(lines) + "\n"


def parse_host(url: str) -> str:
    return urlparse(url).hostname or ""
