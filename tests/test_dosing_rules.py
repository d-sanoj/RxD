"""Dataset parity: the app's rules engine must give the same answer as the 124 labelled examples in data/finetune/."""

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.models.dosing_rules import RULE_MEASURE, KidneyFacts, evaluate
from app.models.kidney import assess
from app.models.router import find_drug
from tests.fixtures.scenarios import SCENARIO_PLANS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TODAY = date(2026, 11, 21)  # the dataset was built on this date; lab ages in the CSV are relative to it


def _rows() -> list[dict]:
    with (DATA / "finetune" / "summary.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


ROWS = _rows()


def test_dataset_has_124_examples():
    assert len(ROWS) == 124


@pytest.mark.parametrize("row", ROWS, ids=[r["example_id"] for r in ROWS])
def test_rule_matches_dataset(row):
    expected_dose = row["recommended_dose"] or None
    if row["drug"] == "apixaban":
        # Not in RxD's approved sources: the router must not find a drug, and the answer is a refusal.
        assert row["expected_action"] == "insufficient_information"
        return
    scenario = SCENARIO_PLANS[row["scenario"]]
    assert scenario["drug"] == row["drug"]
    facts = KidneyFacts(
        egfr=float(row["egfr"]),
        crcl=float(row["crcl"]) if row["crcl"] else None,
        dialysis=row["dialysis"] == "yes",
        scr=float(row["scr_mg_dl"]),
        lab_age_days=int(row["lab_age_days"]),
    )
    result = evaluate(row["drug"], scenario["plan"], facts)
    assert result.action == row["expected_action"]
    assert result.dose == expected_dose


@pytest.mark.parametrize("row", [r for r in ROWS if r["drug"] != "apixaban"],
                         ids=[r["example_id"] for r in ROWS if r["drug"] != "apixaban"])
def test_kidney_values_match_dataset(row):
    creatinine_date = TODAY - timedelta(days=int(row["lab_age_days"]))
    result = assess(
        age=int(row["age"]),
        sex=row["sex"],
        weight_kg=float(row["weight_kg"]) if row["weight_kg"] else None,
        scr=float(row["scr_mg_dl"]),
        creatinine_date=creatinine_date,
        on_dialysis=row["dialysis"] == "yes",
        today=TODAY,
    )
    assert result.egfr == pytest.approx(float(row["egfr"]), abs=0.2)
    if row["crcl"]:
        assert result.crcl == pytest.approx(float(row["crcl"]), abs=0.2)
    else:
        assert result.crcl is None


def test_rule_measures_agree_with_the_provided_rules_file():
    rules = json.loads((DATA / "dosing_rules.json").read_text(encoding="utf-8"))
    assert {drug: meta["measure"] for drug, meta in rules.items()} == RULE_MEASURE


def test_apixaban_is_not_a_supported_drug():
    assert find_drug("What apixaban dose should this patient take?") is None
