"""Load and validate companies/<slug>/ into a CompanyBundle.

Validation refuses to run while any TODO marker remains in the company folder, so a draft
produced by scripts/draft_company.py can never reach production half-finished.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from leadagent.config.schemas import (
    CompanyBundle,
    CompanyConfig,
    CRMMapping,
    KnowledgeDoc,
    QualificationConfig,
    RoutingConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TODO_RE = re.compile(r"\bTODO\b")
TEXT_SUFFIXES = {".yaml", ".yml", ".md"}

CONFIG_FILES = {
    "company.yaml": CompanyConfig,
    "qualification.yaml": QualificationConfig,
    "routing.yaml": RoutingConfig,
    "crm_mapping.yaml": CRMMapping,
}


class ConfigError(Exception):
    """Raised with every problem found, so the author can fix them in one pass."""

    def __init__(self, slug: str, problems: list[str]):
        self.slug = slug
        self.problems = problems
        lines = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"Config for company '{slug}' is invalid:\n{lines}")


@dataclass(frozen=True)
class TodoMarker:
    file: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.text.strip()}"


def companies_dir() -> Path:
    return Path(os.environ.get("COMPANIES_DIR", REPO_ROOT / "companies"))


def list_companies(base: Path | None = None) -> list[str]:
    base = base or companies_dir()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "company.yaml").exists())


def find_todos(root: Path) -> list[TodoMarker]:
    found: list[TodoMarker] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        rel = str(path.relative_to(root))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if TODO_RE.search(line):
                found.append(TodoMarker(rel, n, line))
    return found


def _format_validation(file: str, err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        out.append(f"{file}: {loc}: {e['msg']}")
    return out


def load_company(
    slug: str, *, base: Path | None = None, allow_todos: bool = False
) -> CompanyBundle:
    base = base or companies_dir()
    root = base / slug
    if not root.is_dir():
        available = ", ".join(list_companies(base)) or "none"
        raise ConfigError(slug, [f"no folder {root}. Available companies: {available}"])

    if not allow_todos:
        todos = find_todos(root)
        if todos:
            raise ConfigError(
                slug,
                [f"unresolved TODO (replace with a real value or remove): {t}" for t in todos],
            )

    problems: list[str] = []
    parsed: dict[str, object] = {}
    for filename, model in CONFIG_FILES.items():
        path = root / filename
        if not path.exists():
            problems.append(f"{filename}: file is missing")
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            problems.append(f"{filename}: invalid YAML: {e}")
            continue
        if not isinstance(raw, dict):
            problems.append(f"{filename}: top level must be a mapping")
            continue
        # Top-level keys starting with "x_" are scratch space for YAML anchors.
        raw = {k: v for k, v in raw.items() if not str(k).startswith("x_")}
        try:
            parsed[filename] = model.model_validate(raw)
        except ValidationError as e:
            problems.extend(_format_validation(filename, e))

    knowledge = [
        KnowledgeDoc(source=str(p.relative_to(root)), text=p.read_text(encoding="utf-8"))
        for p in sorted((root / "knowledge").glob("*.md"))
    ]
    if not knowledge:
        problems.append("knowledge/: needs at least one .md file")

    if "company.yaml" in parsed:
        logo = parsed["company.yaml"].logo  # type: ignore[attr-defined]
        if not logo.startswith(("http://", "https://")) and not (root / logo).is_file():
            problems.append(f"company.yaml: logo: file '{logo}' not found in {root}")

    if problems:
        raise ConfigError(slug, problems)

    try:
        return CompanyBundle(
            slug=slug,
            root=str(root),
            company=parsed["company.yaml"],  # type: ignore[arg-type]
            qualification=parsed["qualification.yaml"],  # type: ignore[arg-type]
            routing=parsed["routing.yaml"],  # type: ignore[arg-type]
            crm_mapping=parsed["crm_mapping.yaml"],  # type: ignore[arg-type]
            knowledge=knowledge,
        )
    except ValidationError as e:
        raise ConfigError(slug, _format_validation("(cross-file)", e)) from e
