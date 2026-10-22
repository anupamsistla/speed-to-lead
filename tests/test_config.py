from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from leadagent.clock import FixedClock
from leadagent.config import ConfigError, find_todos, list_companies, load_company
from leadagent.config.loader import companies_dir
from leadagent.config.schemas import expand_zips

SLUG = "sunrise_solar"


@pytest.fixture
def copy_company(tmp_path: Path):
    """Copy the fixture company into tmp so tests can break it freely."""
    dest = tmp_path / "acme"
    shutil.copytree(companies_dir() / SLUG, dest)
    return tmp_path, dest


def edit_yaml(path: Path, fn) -> None:
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_fixture_company_loads():
    b = load_company(SLUG)
    assert b.company.name == "Sunrise Solar"
    assert len(b.routing.offices) == 3
    assert sum(len(o.reps) for o in b.routing.offices) == 12
    assert {d.source for d in b.knowledge} >= {"knowledge/faq.md", "knowledge/financing.md"}


def test_list_companies_includes_fixture():
    assert SLUG in list_companies()


def test_unknown_company_lists_available():
    with pytest.raises(ConfigError) as e:
        load_company("nope")
    assert SLUG in str(e.value)


def test_zip_ranges_expand_and_dedupe():
    assert expand_zips(["80202-80204", "80203"]) == ["80202", "80203", "80204"]
    with pytest.raises(ValueError):
        expand_zips(["8020"])
    with pytest.raises(ValueError):
        expand_zips(["80210-80205"])


def test_refuses_todos(copy_company):
    base, root = copy_company
    faq = root / "knowledge" / "faq.md"
    faq.write_text(faq.read_text() + "\nWarranty is 10 years. <!-- TODO verify with owner -->\n")
    (root / "company.yaml").write_text(
        (root / "company.yaml").read_text().replace("Sunrise Solar Team", "TODO signature")
    )
    with pytest.raises(ConfigError) as e:
        load_company("acme", base=base)
    msg = str(e.value)
    assert "unresolved TODO" in msg
    assert "company.yaml:" in msg and "knowledge/faq.md:" in msg
    assert len(find_todos(root)) == 2


def test_allow_todos_for_drafts(copy_company):
    base, root = copy_company
    (root / "knowledge" / "faq.md").write_text("# FAQ\nTODO fill in\n")
    assert load_company("acme", base=base, allow_todos=True).slug == "acme"


def test_missing_file_reported(copy_company):
    base, root = copy_company
    (root / "routing.yaml").unlink()
    with pytest.raises(ConfigError) as e:
        load_company("acme", base=base)
    assert "routing.yaml: file is missing" in str(e.value)


def test_collects_multiple_errors(copy_company):
    base, root = copy_company
    edit_yaml(root / "company.yaml", lambda d: d.update(brand_color="orange", timezone="Mars/Base"))
    with pytest.raises(ConfigError) as e:
        load_company("acme", base=base)
    assert any("brand_color" in p for p in e.value.problems)
    assert any("timezone" in p for p in e.value.problems)


def test_extra_keys_rejected(copy_company):
    base, root = copy_company
    edit_yaml(root / "company.yaml", lambda d: d.update(colour="x"))
    with pytest.raises(ConfigError, match="colour"):
        load_company("acme", base=base)


def test_unquoted_time_gives_helpful_error(copy_company):
    base, root = copy_company
    text = (root / "company.yaml").read_text().replace('start: "21:00"', "start: 21:00")
    (root / "company.yaml").write_text(text)
    with pytest.raises(ConfigError, match="quoted"):
        load_company("acme", base=base)


def test_rule_referencing_unknown_field(copy_company):
    base, root = copy_company

    def bad(d):
        d["disqualify_if"][0]["when"][0]["field"] = "no_such_field"

    edit_yaml(root / "qualification.yaml", bad)
    with pytest.raises(ConfigError, match="no_such_field"):
        load_company("acme", base=base)


def test_hot_threshold_must_be_achievable(copy_company):
    base, root = copy_company
    edit_yaml(root / "qualification.yaml", lambda d: d.update(hot_lead_threshold=500))
    with pytest.raises(ConfigError, match="maximum achievable"):
        load_company("acme", base=base)


def test_zip_field_required(copy_company):
    base, root = copy_company

    def drop(d):
        d["required_fields"] = [f for f in d["required_fields"] if f["key"] != "zip"]

    edit_yaml(root / "qualification.yaml", drop)
    with pytest.raises(ConfigError, match='key "zip"'):
        load_company("acme", base=base)


def test_overlapping_office_zips(copy_company):
    base, root = copy_company

    def overlap(d):
        d["offices"][1]["zips"] = ["80202"]

    edit_yaml(root / "routing.yaml", overlap)
    with pytest.raises(ConfigError, match="80202"):
        load_company("acme", base=base)


def test_office_zip_outside_service_area(copy_company):
    base, root = copy_company

    def outside(d):
        d["offices"][0]["zips"].append("99999")

    edit_yaml(root / "routing.yaml", outside)
    with pytest.raises(ConfigError, match="outside company.service_area_zips"):
        load_company("acme", base=base)


def test_uncovered_service_zip_needs_default_office(copy_company):
    base, root = copy_company
    edit_yaml(
        root / "company.yaml",
        lambda d: d["service_area_zips"].append("80301"),
    )
    with pytest.raises(ConfigError, match="default_office"):
        load_company("acme", base=base)


def test_crm_mapping_must_cover_required_fields(copy_company):
    base, root = copy_company
    edit_yaml(root / "crm_mapping.yaml", lambda d: d["field_map"].pop("roof_type"))
    with pytest.raises(ConfigError, match="roof_type"):
        load_company("acme", base=base)


def test_missing_logo(copy_company):
    base, root = copy_company
    (root / "logo.svg").unlink()
    with pytest.raises(ConfigError, match="logo"):
        load_company("acme", base=base)


def test_run_py_reports_errors(capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_entry", Path(__file__).resolve().parents[1] / "run.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--company", SLUG, "--check"]) == 0
    assert mod.main(["--company", "nope"]) == 2
    assert "Available companies" in capsys.readouterr().err


def test_choice_options_must_be_snake_case(copy_company):
    base, root = copy_company
    edit_yaml(
        root / "qualification.yaml",
        lambda d: d["required_fields"][1].update(options=["Owner", "rent er"]),
    )
    with pytest.raises(ConfigError, match="snake_case"):
        load_company("acme", base=base)


def test_rules_must_use_values_the_field_can_hold(copy_company):
    base, root = copy_company

    def typo(d):
        d["disqualify_if"][0]["when"][0]["value"] = "tenant"

    edit_yaml(root / "qualification.yaml", typo)
    with pytest.raises(ConfigError, match="not among its options"):
        load_company("acme", base=base)


def test_boolean_fields_need_real_booleans_in_rules(copy_company):
    base, root = copy_company

    def make_bool(d):
        d["required_fields"][1] = {"key": "homeowner", "type": "boolean", "question": "Own it?"}
        d["disqualify_if"][0]["when"][0].update(field="homeowner", value="false")
        d["score_weights"][0]["when"][0].update(field="homeowner", value=True)

    edit_yaml(root / "qualification.yaml", make_bool)
    with pytest.raises(ConfigError, match="Use true or false without quotes"):
        load_company("acme", base=base)


def test_a_copied_env_example_with_empty_values_still_uses_the_defaults(monkeypatch):
    """.env.example ships COMPANIES_DIR= and SCENARIOS_DIR= empty. Empty must mean unset."""
    from leadagent.scenarios import load_scenarios, scenarios_dir

    monkeypatch.setenv("COMPANIES_DIR", "")
    monkeypatch.setenv("SCENARIOS_DIR", "")
    assert SLUG in list_companies()
    assert companies_dir().name == "companies"
    assert scenarios_dir().name == "scenarios" and load_scenarios()


def test_every_variable_in_env_example_is_safe_when_left_blank(monkeypatch, tmp_path):
    from dotenv import dotenv_values

    from leadagent.adapters import build_adapters
    from leadagent.server import Settings

    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example")
    blank = {k: (v or "") for k, v in values.items() if k != "DATABASE_PATH"}
    assert {"ANTHROPIC_API_KEY", "COMPANIES_DIR", "WEBHOOK_SECRET", "DEFAULT_COMPANY"} <= set(blank)
    for k, v in blank.items():
        monkeypatch.setenv(k, v)
    settings = Settings.from_env()
    assert settings.webhook_secret is None and settings.default_company is None
    assert settings.cors_origins  # falls back to the Vite dev origins
    bundle = load_company(SLUG)
    adapters = build_adapters(
        bundle,
        FixedClock(
            __import__("datetime").datetime(
                2026, 10, 27, 10, tzinfo=__import__("zoneinfo").ZoneInfo("America/Denver")
            )
        ),
        env=blank,
    )
    assert (
        type(adapters.crm).__name__ == "MockCRM"
        and type(adapters.notifier).__name__ == "MockNotifier"
    )
