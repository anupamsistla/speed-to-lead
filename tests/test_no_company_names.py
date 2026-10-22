"""Engine plus config rule: no company slug or name may appear in engine code.

If you need `if company == ...`, the logic belongs in companies/<slug>/ config.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from leadagent.config import list_companies
from leadagent.config.loader import REPO_ROOT, companies_dir

SCANNED_DIRS = [REPO_ROOT / "src", REPO_ROOT / "web" / "src"]
SKIP_DIRS = {"node_modules", "__pycache__", "dist", ".venv"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".ico", ".woff", ".woff2"}


def forbidden_terms() -> set[str]:
    terms: set[str] = set()
    for slug in list_companies():
        terms.update({slug, slug.replace("_", "-"), slug.replace("_", " ")})
        data = yaml.safe_load((companies_dir() / slug / "company.yaml").read_text())
        name = str(data.get("name", "")).strip()
        if name:
            terms.add(name)
    return {t.lower() for t in terms if t}


def scanned_files():
    for base in SCANNED_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix in SKIP_SUFFIXES:
                continue
            if SKIP_DIRS & set(path.parts):
                continue
            yield path


def test_there_are_companies_to_check_against():
    assert list_companies(), "no companies found, the test would pass vacuously"


def test_engine_code_never_mentions_a_company():
    terms = forbidden_terms()
    pattern = re.compile("|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)))
    hits: list[str] = []
    for path in scanned_files():
        try:
            text = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            m = pattern.search(line)
            if m:
                hits.append(f"{Path(path).relative_to(REPO_ROOT)}:{n}: '{m.group(0)}'")
    assert not hits, "Company names found in engine code (move to config):\n" + "\n".join(hits)


def test_detector_actually_detects(tmp_path, monkeypatch):
    """Guard against the scan silently matching nothing."""
    terms = forbidden_terms()
    sample = next(iter(terms))
    pattern = re.compile("|".join(re.escape(t) for t in terms))
    assert pattern.search(f"if company == '{sample}':")
