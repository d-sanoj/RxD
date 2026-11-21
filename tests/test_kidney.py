"""Kidney calculations against the reference values in the handoff (tolerance ±0.2)."""

from datetime import date, timedelta

import pytest

from app.models.kidney import assess, ckd_stage, crcl_cockcroft_gault, egfr_ckd_epi_2021

TODAY = date(2026, 11, 21)


@pytest.mark.parametrize(
    "sex, age, scr, expected",
    [("M", 60, 1.0, 86.2), ("F", 50, 0.7, 105.3), ("F", 72, 2.0, 26.1)],
)
def test_egfr_reference_values(sex, age, scr, expected):
    assert egfr_ckd_epi_2021(scr, age, sex) == pytest.approx(expected, abs=0.2)


@pytest.mark.parametrize(
    "sex, age, weight, scr, expected",
    [("F", 72, 60, 2.0, 24.1), ("M", 45, 85, 1.2, 93.5)],
)
def test_crcl_reference_values(sex, age, weight, scr, expected):
    assert crcl_cockcroft_gault(scr, age, weight, sex) == pytest.approx(expected, abs=0.2)


@pytest.mark.parametrize(
    "egfr, stage",
    [(90, "G1"), (89.9, "G2"), (60, "G2"), (59.9, "G3a"), (45, "G3a"), (44.9, "G3b"),
     (30, "G3b"), (29.9, "G4"), (15, "G4"), (14.9, "G5")],
)
def test_stage_boundaries(egfr, stage):
    assert ckd_stage(egfr) == stage


def test_p001_demo_patient_matches_milestone_two():
    result = assess(age=72, sex="F", weight_kg=60, scr=2.0, creatinine_date=TODAY - timedelta(days=12),
                    on_dialysis=False, today=TODAY)
    assert result.egfr == pytest.approx(26.1, abs=0.2)
    assert result.crcl == pytest.approx(24.1, abs=0.2)
    assert result.ckd_stage == "G4"
    assert result.flags == []


def test_missing_weight_flags_and_no_crcl():
    result = assess(age=62, sex="F", weight_kg=None, scr=2.2, creatinine_date=TODAY, on_dialysis=False, today=TODAY)
    assert result.crcl is None
    assert "missing_weight" in result.flags


def test_stale_creatinine_is_flagged_after_90_days():
    old = TODAY - timedelta(days=91)
    result = assess(age=68, sex="M", weight_kg=84, scr=1.8, creatinine_date=old, on_dialysis=False, today=TODAY)
    assert "stale_lab" in result.flags
    assert result.lab_age_days == 91


def test_creatinine_exactly_90_days_old_is_not_stale():
    result = assess(age=68, sex="M", weight_kg=84, scr=1.8, creatinine_date=TODAY - timedelta(days=90),
                    on_dialysis=False, today=TODAY)
    assert "stale_lab" not in result.flags


def test_dialysis_flag_and_missing_creatinine():
    result = assess(age=65, sex="M", weight_kg=76, scr=None, creatinine_date=None, on_dialysis=True, today=TODAY)
    assert result.egfr is None and result.crcl is None
    assert "missing_creatinine" in result.flags and "dialysis" in result.flags


def test_missing_age_or_sex_flags_instead_of_failing():
    result = assess(age=None, sex="F", weight_kg=70, scr=1.0, creatinine_date=TODAY, on_dialysis=False, today=TODAY)
    assert result.egfr is None and result.crcl is None
    assert "missing_age_or_sex" in result.flags
