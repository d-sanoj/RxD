"""Drug detection and regimen parsing, checked against the 30 evaluation questions."""

import json
from pathlib import Path

import pytest

from app.models.router import DRUG_TERMS, route

DATA = Path(__file__).resolve().parents[1] / "data"
TEST_SET = [json.loads(line) for line in (DATA / "test_set.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


SUPPORTED = set(DRUG_TERMS)


@pytest.mark.parametrize("case", TEST_SET, ids=[c["id"] for c in TEST_SET])
def test_test_set_questions_route_to_the_expected_drug(case):
    routed = route(case["question"], medications=[])
    if case["drug"] in SUPPORTED:
        assert routed.drug == case["drug"]
    else:
        # Drugs outside the approved sources (e.g. apixaban) must not be matched to any rule.
        assert routed.drug is None


def test_brand_names_are_recognised():
    assert route("Can I use Januvia for this patient?", []).drug == "sitagliptin"
    assert route("Is Neurontin safe here?", []).drug == "gabapentin"
    assert route("Macrobid for the cystitis?", []).drug == "nitrofurantoin"
    assert route("Levaquin 750 mg?", []).drug == "levofloxacin"
    assert route("Pepcid 20 mg?", []).drug == "famotidine"
    assert route("Glucophage 500 mg twice daily?", []).drug == "metformin"


def test_metformin_new_start_depends_on_the_medication_list():
    new = route("Can I start metformin 500 mg twice daily?", medications=[{"name": "lisinopril"}])
    assert new.plan == {"new_start": True, "regimen": "500 mg twice daily"}
    continuing = route("Is metformin 1000 mg twice daily still OK?", medications=[{"name": "metformin", "dose": "1000 mg"}])
    assert continuing.plan == {"new_start": False, "regimen": "1000 mg twice daily"}


def test_gabapentin_regimen_is_parsed_and_defaults_to_300_three_times_daily():
    assert route("Planning gabapentin 600 mg three times daily.", []).plan == {"tid_mg": 600}
    assert route("Check gabapentin for this patient.", []).plan == {"tid_mg": 300}


def test_gabapentin_with_another_frequency_is_not_guessed():
    routed = route("Gabapentin 300 mg twice daily?", [])
    assert "unsupported" in routed.plan


def test_levofloxacin_regimen_is_parsed():
    assert route("Levofloxacin 500 mg every 24 hours: renal adjustment?", []).plan == {"mg": 500}
    assert route("Check levofloxacin for this patient.", []).plan == {"mg": 750}


def test_persona_is_chosen_by_drug():
    assert route("metformin?", []).persona == "diabetes"
    assert route("nitrofurantoin?", []).persona == "anti_infective"
    assert route("famotidine?", []).persona == "general"
