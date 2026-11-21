"""Renal dosing rules. The rules engine decides the dose; the model only explains it.

decide() is ported unchanged from tools/generate_dataset.py, which produced the
124 labelled examples in data/finetune/. evaluate() adds the data-quality checks
that the generator applied before calling decide(), in the same order.
"""

from dataclasses import asdict, dataclass, field

STALE_LAB_DAYS = 90

RULE_MEASURE = {
    "metformin": "eGFR",
    "sitagliptin": "eGFR",
    "gabapentin": "CrCl",
    "nitrofurantoin": "CrCl",
    "levofloxacin": "CrCl",
    "famotidine": "CrCl",
}

GABA_TID = [300, 400, 600, 800, 1200]
GABA_BID = [200, 300, 400, 500, 700]
GABA_QD_LOW = [200, 300, 400, 500, 700]
GABA_QD_MIN = [100, 125, 150, 200, 300]
GABA_HD_SUPP = [125, 150, 200, 250, 350]


@dataclass(frozen=True)
class KidneyFacts:
    egfr: float | None
    crcl: float | None
    dialysis: bool
    scr: float | None
    lab_age_days: int | None


@dataclass
class RuleResult:
    drug: str
    action: str
    dose: str | None
    max_daily: str | None
    measure: str | None
    cite_ids: list[str] = field(default_factory=list)
    why: str = ""
    monitoring: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def decide(drug, plan, k):
    """Return dict(action, dose, max_daily, measure, cites, why, monitoring). k = kidney dict."""
    e, c, dialysis = k["egfr"], k["crcl"], k["dialysis"]
    if drug == "metformin":
        if (dialysis or e < 30) and not plan["new_start"]:
            return dict(action="avoid", dose=None, max_daily=None, measure="eGFR", cites=["LBL-metformin-04", "LBL-metformin-06"],
                        why=f"The patient already takes metformin and eGFR is {e}, below 30. The label says to discontinue metformin if eGFR falls below 30; severe renal impairment is a contraindication.",
                        monitoring="Stop metformin and agree an alternative glucose-lowering plan suited to kidney function.")
        if dialysis or e < 30:
            return dict(action="avoid", dose=None, max_daily=None, measure="eGFR", cites=["LBL-metformin-01", "LBL-metformin-06"],
                        why=f"eGFR is {e}, below 30. The label says do not use metformin below an eGFR of 30, and lists severe renal impairment as a contraindication.",
                        monitoring="Discuss an alternative glucose-lowering plan suited to the patient's kidney function.")
        if e < 45:
            if plan["new_start"]:
                return dict(action="avoid", dose=None, max_daily=None, measure="eGFR", cites=["LBL-metformin-02"],
                            why=f"eGFR is {e}. The label says starting metformin is not recommended at an eGFR between 30 and 45.",
                            monitoring="Consider an alternative; recheck eGFR.")
            return dict(action="caution", dose=None, max_daily="2550 mg per day", measure="eGFR", cites=["LBL-metformin-03", "LBL-metformin-04"],
                        why=f"The patient already takes metformin and eGFR is {e}, below 45. The label says to assess the risk and benefit of continuing, and to stop if eGFR falls below 30.",
                        monitoring="Recheck eGFR regularly; stop if it falls below 30.")
        return dict(action="continue", dose=plan["regimen"], max_daily="2550 mg per day", measure="eGFR", cites=["LBL-metformin-05", "LBL-metformin-04"],
                    why=f"eGFR is {e}, which is 45 or above, so the label's kidney limits do not apply. The planned dose is within the 2550 mg daily maximum.",
                    monitoring="Assess renal function periodically.")
    if drug == "sitagliptin":
        if dialysis or e < 30:
            return dict(action="adjust_dose", dose="25 mg once daily", max_daily="25 mg", measure="eGFR", cites=["LBL-sitagliptin-04"],
                        why=("The patient is on dialysis; " if dialysis else f"eGFR is {e}, below 30; ") + "the label dose is 25 mg once daily, given without regard to dialysis timing.",
                        monitoring="Assess renal function periodically.")
        if e < 45:
            return dict(action="adjust_dose", dose="50 mg once daily", max_daily="50 mg", measure="eGFR", cites=["LBL-sitagliptin-03", "LBL-sitagliptin-02"],
                        why=f"eGFR is {e}, between 30 and 45. The label dose for moderate renal impairment is 50 mg once daily instead of 100 mg.",
                        monitoring="Assess renal function periodically.")
        return dict(action="continue", dose="100 mg once daily", max_daily="100 mg", measure="eGFR", cites=["LBL-sitagliptin-01", "LBL-sitagliptin-02"],
                    why=f"eGFR is {e}, 45 or above, so the usual label dose of 100 mg once daily applies.",
                    monitoring="Assess renal function periodically.")
    if drug == "gabapentin":
        i = GABA_TID.index(plan["tid_mg"])
        if dialysis:
            return dict(action="adjust_dose", dose=f"{GABA_QD_MIN[i]} mg once daily, plus {GABA_HD_SUPP[i]} mg after each 4 hours of hemodialysis",
                        max_daily="100 to 300 mg/day maintenance", measure="CrCl", cites=["LBL-gabapentin-06", "LBL-gabapentin-05"],
                        why=f"The patient is on hemodialysis. The label bases the maintenance dose on creatinine clearance and adds a supplemental dose after each 4 hours of dialysis; the equivalent of {plan['tid_mg']} mg three times daily is {GABA_QD_MIN[i]} mg once daily plus {GABA_HD_SUPP[i]} mg post-dialysis.",
                        monitoring="Watch for sedation and dizziness.")
        if c >= 60:
            return dict(action="continue", dose=f"{plan['tid_mg']} mg three times daily", max_daily="3600 mg/day", measure="CrCl", cites=["LBL-gabapentin-02"],
                        why=f"CrCl is {c} mL/min, 60 or above, so the full-dose row applies (900 to 3600 mg/day).",
                        monitoring="Watch for sedation and dizziness.")
        if c > 30:
            return dict(action="adjust_dose", dose=f"{GABA_BID[i]} mg twice daily", max_daily="1400 mg/day", measure="CrCl", cites=["LBL-gabapentin-03", "LBL-gabapentin-01"],
                        why=f"CrCl is {c} mL/min, in the above-30-to-59 band (400 to 1400 mg/day). The label's equivalent of {plan['tid_mg']} mg three times daily is {GABA_BID[i]} mg twice daily.",
                        monitoring="Watch for sedation and dizziness; recheck kidney function.")
        if c > 15:
            return dict(action="adjust_dose", dose=f"{GABA_QD_LOW[i]} mg once daily", max_daily="700 mg/day", measure="CrCl", cites=["LBL-gabapentin-04", "LBL-gabapentin-01"],
                        why=f"CrCl is {c} mL/min, in the above-15-to-29 band (200 to 700 mg/day). The label's equivalent of {plan['tid_mg']} mg three times daily is {GABA_QD_LOW[i]} mg once daily.",
                        monitoring="Watch for sedation and dizziness; recheck kidney function.")
        return dict(action="adjust_dose", dose=f"{GABA_QD_MIN[i]} mg once daily, reduced further in proportion to CrCl if below 15",
                    max_daily="300 mg/day", measure="CrCl", cites=["LBL-gabapentin-05"],
                    why=f"CrCl is {c} mL/min, in the lowest band (100 to 300 mg/day). Below 15 mL/min the label says to reduce the daily dose in proportion to creatinine clearance.",
                    monitoring="Watch for sedation and dizziness; recheck kidney function.")
    if drug == "nitrofurantoin":
        if dialysis or c < 60:
            return dict(action="avoid", dose=None, max_daily=None, measure="CrCl", cites=["LBL-nitrofurantoin-01", "LBL-nitrofurantoin-02"],
                        why=("The patient is on dialysis. " if dialysis else f"CrCl is {c} mL/min, under 60. ") + "The label lists significant renal impairment (CrCl under 60 mL/min) as a contraindication, and renal impairment raises the risk of neuropathy.",
                        monitoring="Choose an alternative antibiotic suited to kidney function; RxD can check its dose.")
        return dict(action="continue", dose="Usual labeled dose (no renal adjustment)", max_daily=None, measure="CrCl", cites=["LBL-nitrofurantoin-01"],
                    why=f"CrCl is {c} mL/min, 60 or above, so the label's renal contraindication does not apply.",
                    monitoring="Monitor renal function if therapy is long-term.")
    if drug == "levofloxacin":
        mg = plan["mg"]
        chunk = "LBL-levofloxacin-02" if mg == 750 else "LBL-levofloxacin-03"
        table = {
            750: {"20-49": "750 mg every 48 hours", "10-19": "750 mg initial dose, then 500 mg every 48 hours", "HD": "750 mg initial dose, then 500 mg every 48 hours"},
            500: {"20-49": "500 mg initial dose, then 250 mg every 24 hours", "10-19": "500 mg initial dose, then 250 mg every 48 hours", "HD": "500 mg initial dose, then 250 mg every 48 hours"},
        }[mg]
        if dialysis:
            return dict(action="adjust_dose", dose=table["HD"], max_daily=None, measure="CrCl", cites=[chunk],
                        why=f"The patient is on hemodialysis. For a usual regimen of {mg} mg every 24 hours, the label gives {table['HD']}.",
                        monitoring="Monitor for tendon pain, confusion and blood sugar changes.")
        if c >= 50:
            return dict(action="continue", dose=f"{mg} mg every 24 hours", max_daily=None, measure="CrCl", cites=["LBL-levofloxacin-01"],
                        why=f"CrCl is {c} mL/min, 50 or above, so the label says no adjustment is necessary.",
                        monitoring="Monitor for tendon pain, confusion and blood sugar changes.")
        if c >= 20:
            return dict(action="adjust_dose", dose=table["20-49"], max_daily=None, measure="CrCl", cites=[chunk, "LBL-levofloxacin-01"],
                        why=f"CrCl is {c} mL/min, in the 20 to 49 band. For {mg} mg every 24 hours, the label gives {table['20-49']}.",
                        monitoring="Monitor for tendon pain, confusion and blood sugar changes.")
        if c >= 10:
            return dict(action="adjust_dose", dose=table["10-19"], max_daily=None, measure="CrCl", cites=[chunk, "LBL-levofloxacin-01"],
                        why=f"CrCl is {c} mL/min, in the 10 to 19 band. For {mg} mg every 24 hours, the label gives {table['10-19']}.",
                        monitoring="Monitor for tendon pain, confusion and blood sugar changes.")
        return dict(action="insufficient_information", dose=None, max_daily=None, measure="CrCl", cites=["LBL-levofloxacin-01"],
                    why=f"CrCl is {c} mL/min, below 10, and the patient is not on dialysis. The label table does not give a regimen for this level.",
                    monitoring="Pharmacist or nephrology review before prescribing.")
    if drug == "famotidine":
        if dialysis or c < 30:
            return dict(action="adjust_dose", dose="20 mg every other day (or 10 mg once daily using another formulation)", max_daily="20 mg every other day",
                        measure="CrCl", cites=["LBL-famotidine-03", "LBL-famotidine-01"],
                        why=("The patient is on dialysis. " if dialysis else f"CrCl is {c} mL/min, below 30. ") + "For symptomatic GERD the label maximum is 20 mg every other day, or 10 mg once daily as an alternative.",
                        monitoring="Use the lowest effective dose; watch for confusion in older adults.")
        if c < 60:
            return dict(action="adjust_dose", dose="20 mg once daily", max_daily="20 mg/day", measure="CrCl", cites=["LBL-famotidine-03", "LBL-famotidine-01"],
                        why=f"CrCl is {c} mL/min, between 30 and 60. For symptomatic GERD the label maximum is 20 mg once daily instead of 20 mg twice daily.",
                        monitoring="Use the lowest effective dose.")
        return dict(action="continue", dose="20 mg twice daily, up to 6 weeks", max_daily="40 mg/day", measure="CrCl", cites=["LBL-famotidine-02", "LBL-famotidine-04"],
                    why=f"CrCl is {c} mL/min, 60 or above, so no renal adjustment is needed; the usual GERD dose applies.",
                    monitoring="Reassess symptoms after the course.")
    raise ValueError(drug)


def _insufficient(drug: str, measure: str | None, why: str, monitoring: str) -> RuleResult:
    return RuleResult(drug=drug, action="insufficient_information", dose=None, max_daily=None,
                      measure=measure, cite_ids=[], why=why, monitoring=monitoring)


def evaluate(drug: str, plan: dict, k: KidneyFacts) -> RuleResult:
    """Data-quality checks first (same order as the generator), then the label rule."""
    if drug not in RULE_MEASURE:
        raise ValueError(f"No rule for {drug}")
    measure = RULE_MEASURE[drug]

    if plan.get("unsupported"):
        return _insufficient(drug, measure, plan["unsupported"], "Check the regimen with a pharmacist before prescribing.")
    if drug == "gabapentin" and plan.get("tid_mg") not in GABA_TID:
        return _insufficient(drug, measure,
                             f"The label gives gabapentin regimens of 300, 400, 600, 800 or 1200 mg three times daily; {plan.get('tid_mg')} mg is not one of them.",
                             "Check the planned regimen with a pharmacist.")
    if drug == "levofloxacin" and plan.get("mg") not in (750, 500):
        return _insufficient(drug, measure,
                             f"The label gives levofloxacin regimens of 750 mg or 500 mg every 24 hours; {plan.get('mg')} mg is not one of them.",
                             "Check the planned regimen with a pharmacist.")
    if k.scr is None:
        return _insufficient(drug, None,
                             "Serum creatinine is not recorded, so kidney function cannot be calculated. Record a creatinine result before choosing a dose.",
                             "Order a serum creatinine.")
    if k.egfr is None:
        return _insufficient(drug, None,
                             "Age and sex are needed to calculate kidney function, and one of them is missing from the record. Add them, then ask again.",
                             "Record age and sex.")
    if k.lab_age_days is not None and k.lab_age_days > STALE_LAB_DAYS:
        return _insufficient(drug, None,
                             f"The latest creatinine is {k.lab_age_days} days old, so current kidney function is unknown. Repeat serum creatinine before choosing a {drug} dose.",
                             "Order a serum creatinine today.")
    if drug == "nitrofurantoin" and k.crcl is None and k.egfr < 60:
        return RuleResult(drug=drug, action="avoid", dose=None, max_daily=None, measure="eGFR",
                          cite_ids=["LBL-nitrofurantoin-01"],
                          why=f"Weight is missing, so CrCl cannot be calculated, but creatinine is {k.scr} mg/dL (eGFR {k.egfr}). The label contraindicates nitrofurantoin with clinically significant elevated serum creatinine.",
                          monitoring="Choose an alternative antibiotic suited to kidney function; record weight.")
    if measure == "CrCl" and k.crcl is None and not k.dialysis:
        return _insufficient(drug, None,
                             f"The {drug} label doses by creatinine clearance, which needs body weight, and weight is not recorded. Weigh the patient, then recheck.",
                             "Record weight at this visit.")

    d = decide(drug, plan, {"egfr": k.egfr, "crcl": k.crcl, "dialysis": k.dialysis})
    return RuleResult(drug=drug, action=d["action"], dose=d["dose"], max_daily=d["max_daily"],
                      measure=d["measure"], cite_ids=list(d["cites"]), why=d["why"], monitoring=d["monitoring"])
