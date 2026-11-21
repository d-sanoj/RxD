"""Kidney function: Cockcroft-Gault creatinine clearance, CKD-EPI 2021 eGFR, CKD stage and flags."""

from dataclasses import dataclass
from datetime import date

STALE_LAB_DAYS = 90


@dataclass(frozen=True)
class KidneyResult:
    egfr: float | None
    crcl: float | None
    ckd_stage: str | None
    lab_age_days: int | None
    flags: list[str]


def egfr_ckd_epi_2021(scr: float, age: int, sex: str) -> float:
    female = sex == "F"
    kappa, alpha = (0.7, -0.241) if female else (0.9, -0.302)
    value = 142 * min(scr / kappa, 1) ** alpha * max(scr / kappa, 1) ** -1.200 * 0.9938**age
    return round(value * (1.012 if female else 1), 1)


def crcl_cockcroft_gault(scr: float, age: int, weight_kg: float, sex: str) -> float:
    value = (140 - age) * weight_kg / (72 * scr)
    return round(value * (0.85 if sex == "F" else 1), 1)


def ckd_stage(egfr: float) -> str:
    if egfr >= 90:
        return "G1"
    if egfr >= 60:
        return "G2"
    if egfr >= 45:
        return "G3a"
    if egfr >= 30:
        return "G3b"
    if egfr >= 15:
        return "G4"
    return "G5"


def assess(
    *,
    age: int | None,
    sex: str | None,
    weight_kg: float | None,
    scr: float | None,
    creatinine_date: date | None,
    on_dialysis: bool,
    today: date,
) -> KidneyResult:
    """Everything is optional. Values that cannot be calculated are None and a flag says why."""
    flags: list[str] = []
    egfr = crcl = stage = lab_age = None
    can_calculate = age is not None and sex in ("F", "M")
    if scr is None:
        flags.append("missing_creatinine")
    else:
        if creatinine_date is not None:
            lab_age = (today - creatinine_date).days
            if lab_age > STALE_LAB_DAYS:
                flags.append("stale_lab")
        if can_calculate:
            egfr = egfr_ckd_epi_2021(scr, age, sex)
            stage = ckd_stage(egfr)
        else:
            flags.append("missing_age_or_sex")
    if weight_kg is None:
        flags.append("missing_weight")
    elif scr is not None and can_calculate:
        crcl = crcl_cockcroft_gault(scr, age, weight_kg, sex)
    if on_dialysis:
        flags.append("dialysis")
    return KidneyResult(egfr=egfr, crcl=crcl, ckd_stage=stage, lab_age_days=lab_age, flags=flags)
