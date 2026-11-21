"""
Generate the RxD POC data kit:
  data/dosing_rules.json            verified renal dosing rules (from FDA labels via openFDA, retrieved 2026-11-21)
  data/label_excerpts.json          the same label text as retrievable chunks (seed for the RAG store)
  data/patients/synthetic_patients.json   30 synthetic patients with intake notes
  data/finetune/{train,valid,test}.jsonl  chat-format fine-tuning examples
  data/finetune/summary.csv         readable overview of every example
  data/test_set.jsonl               evaluation cases for the API
All patients are synthetic. Not for clinical use.
"""
import csv, json, random
from datetime import date, timedelta
from pathlib import Path

random.seed(505)
OUT = Path(__file__).resolve().parent.parent / "data"
TODAY = date(2026, 11, 21)

# ---------------------------------------------------------------- kidney math
def egfr_ckd_epi_2021(scr, age, sex):
    f = sex == "F"
    k, a = (0.7, -0.241) if f else (0.9, -0.302)
    e = 142 * min(scr / k, 1) ** a * max(scr / k, 1) ** -1.200 * 0.9938 ** age
    return round(e * (1.012 if f else 1), 1)

def crcl_cockcroft_gault(scr, age, weight, sex):
    if weight is None:
        return None
    c = (140 - age) * weight / (72 * scr)
    return round(c * (0.85 if sex == "F" else 1), 1)

def stage(e):
    return "G1" if e >= 90 else "G2" if e >= 60 else "G3a" if e >= 45 else "G3b" if e >= 30 else "G4" if e >= 15 else "G5"

# ---------------------------------------------------------------- label chunks (verbatim label text)
LABELS = {
    "metformin": {
        "product": "Metformin Hydrochloride Tablets, USP (Granules Pharmaceuticals Inc.)",
        "measure": "eGFR",
        "chunks": {
            "LBL-metformin-01": "Dosage and Administration: Do not use in patients with eGFR below 30 mL/minute/1.73 m2.",
            "LBL-metformin-02": "Dosage and Administration: Initiation is not recommended in patients with eGFR between 30 to 45 mL/minute/1.73 m2.",
            "LBL-metformin-03": "Dosage and Administration: Assess risk/benefit of continuing if eGFR falls below 45 mL/minute/1.73 m2.",
            "LBL-metformin-04": "Dosage and Administration: Discontinue if eGFR falls below 30 mL/minute/1.73 m2. Assess renal function prior to initiation of metformin hydrochloride tablets and periodically thereafter.",
            "LBL-metformin-05": "Dosage and Administration: Adults: up to a maximum dose of 2550 mg per day, given in divided doses.",
            "LBL-metformin-06": "Contraindications: Severe renal impairment (eGFR below 30 mL/min/1.73 m2).",
        },
    },
    "sitagliptin": {
        "product": "JANUVIA (sitagliptin) tablets",
        "measure": "eGFR",
        "chunks": {
            "LBL-sitagliptin-01": "Dosage and Administration: The recommended dose of JANUVIA is 100 mg once daily.",
            "LBL-sitagliptin-02": "Dosage and Administration: Dosage adjustment is recommended for patients with eGFR less than 45 mL/min/1.73 m2. Assess renal function prior to initiation of JANUVIA and periodically thereafter.",
            "LBL-sitagliptin-03": "Dosage and Administration: For patients with moderate renal impairment (eGFR 30 to less than 45 mL/min/1.73 m2), the dose of JANUVIA is 50 mg once daily.",
            "LBL-sitagliptin-04": "Dosage and Administration: For patients with severe renal impairment (eGFR less than 30 mL/min/1.73 m2) or with end-stage renal disease requiring hemodialysis or peritoneal dialysis, the dose of JANUVIA is 25 mg once daily. JANUVIA may be administered without regard to the timing of dialysis.",
        },
    },
    "gabapentin": {
        "product": "Gabapentin capsules/tablets (Table 1: Gabapentin Dosage Based on Renal Function)",
        "measure": "CrCl",
        "chunks": {
            "LBL-gabapentin-01": "Dosage and Administration: Dosage adjustment in patients 12 years of age and older with renal impairment or undergoing hemodialysis is recommended.",
            "LBL-gabapentin-02": "Table 1: Creatinine clearance 60 mL/min or more: total daily dose 900 to 3600 mg/day; regimens 300 TID, 400 TID, 600 TID, 800 TID, 1200 TID.",
            "LBL-gabapentin-03": "Table 1: Creatinine clearance above 30 to 59 mL/min: total daily dose 400 to 1400 mg/day; regimens 200 BID, 300 BID, 400 BID, 500 BID, 700 BID.",
            "LBL-gabapentin-04": "Table 1: Creatinine clearance above 15 to 29 mL/min: total daily dose 200 to 700 mg/day; regimens 200 QD, 300 QD, 400 QD, 500 QD, 700 QD.",
            "LBL-gabapentin-05": "Table 1: Creatinine clearance 15 mL/min: total daily dose 100 to 300 mg/day; regimens 100 QD, 125 QD, 150 QD, 200 QD, 300 QD. For patients with creatinine clearance <15 mL/min, reduce daily dose in proportion to creatinine clearance.",
            "LBL-gabapentin-06": "Table 1: Patients on hemodialysis should receive maintenance doses based on estimates of creatinine clearance, plus a supplemental post-hemodialysis dose administered after each 4 hours of hemodialysis: 125, 150, 200, 250 or 350 mg.",
        },
    },
    "nitrofurantoin": {
        "product": "Nitrofurantoin (set_id 04af8b73-7e15-7da8-e063-6294a90af284)",
        "measure": "CrCl",
        "chunks": {
            "LBL-nitrofurantoin-01": "Contraindications: Nitrofurantoin is contraindicated in patients who have anuria, oliguria, or significant impairment of renal function (creatinine clearance under 60 mL per minute or clinically significant elevated serum creatinine).",
            "LBL-nitrofurantoin-02": "Warnings and Precautions (Neuropathy): Conditions such as renal impairment (creatinine clearance under 60 mL per minute or clinically significant elevated serum creatinine) may enhance the occurrence of peripheral neuropathy. Monitor patients receiving long-term therapy periodically for changes in renal function.",
        },
    },
    "levofloxacin": {
        "product": "Levofloxacin tablets (Table 3: Dosage Adjustment in Adult Patients with Renal Impairment)",
        "measure": "CrCl",
        "chunks": {
            "LBL-levofloxacin-01": "Dosage and Administration: In patients with renal impairment (creatinine clearance less than 50 mL/min), adjustment of the dosage regimen is necessary. No adjustment is necessary for patients with a creatinine clearance greater than or equal to 50 mL/minute.",
            "LBL-levofloxacin-02": "Table 3: Usual regimen 750 mg every 24 hours. CrCl 20 to 49 mL/min: 750 mg every 48 hours. CrCl 10 to 19 mL/min: 750 mg initial dose, then 500 mg every 48 hours. Hemodialysis or CAPD: 750 mg initial dose, then 500 mg every 48 hours.",
            "LBL-levofloxacin-03": "Table 3: Usual regimen 500 mg every 24 hours. CrCl 20 to 49 mL/min: 500 mg initial dose, then 250 mg every 24 hours. CrCl 10 to 19 mL/min: 500 mg initial dose, then 250 mg every 48 hours. Hemodialysis or CAPD: 500 mg initial dose, then 250 mg every 48 hours.",
        },
    },
    "famotidine": {
        "product": "Famotidine Tablets, USP 20 mg and 40 mg",
        "measure": "CrCl",
        "chunks": {
            "LBL-famotidine-01": "Dosage and Administration: Dosage adjustments of famotidine tablets are recommended for patients with moderate to severe renal impairment (creatinine clearance less than 60 mL/min). Use the lowest effective dose.",
            "LBL-famotidine-02": "Table 1: Symptomatic nonerosive GERD: 20 mg twice daily, up to 6 weeks.",
            "LBL-famotidine-03": "Table 2 (maximum dosage in renal impairment): Symptomatic nonerosive GERD: creatinine clearance 30 to 60 mL/minute: 20 mg once daily; creatinine clearance less than 30 mL/minute: 20 mg every other day. An alternate dosage regimen is 10 mg once daily, using an alternate famotidine formulation.",
            "LBL-famotidine-04": "Use in Specific Populations: No dosage adjustment is needed in patients with mild renal impairment (creatinine clearance greater than or equal to 60 mL/minute).",
        },
    },
}

# ---------------------------------------------------------------- rule engine (mirrors the labels)
GABA_TID = [300, 400, 600, 800, 1200]
GABA_BID = [200, 300, 400, 500, 700]
GABA_QD_LOW = [200, 300, 400, 500, 700]
GABA_QD_MIN = [100, 125, 150, 200, 300]
GABA_HD_SUPP = [125, 150, 200, 250, 350]

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

# ---------------------------------------------------------------- clinical scenarios (symptoms -> drug the clinician is considering)
SCENARIOS = {
    "diabetes_new": dict(condition="Type 2 diabetes", complaint="Increased thirst and frequent urination for 3 weeks; fasting glucose 182 mg/dL, HbA1c 8.4%.",
                         drug="metformin", plan=dict(new_start=True, regimen="500 mg twice daily with meals"),
                         q="New type 2 diabetes. Can I start metformin 500 mg twice daily?"),
    "diabetes_cont": dict(condition="Type 2 diabetes on metformin", complaint="Routine diabetes follow-up; HbA1c 7.6%. No new symptoms.",
                          drug="metformin", plan=dict(new_start=False, regimen="1000 mg twice daily"),
                          q="Is metformin 1000 mg twice daily still OK for this patient's kidneys?"),
    "diabetes_dpp4": dict(condition="Type 2 diabetes", complaint="HbA1c 8.1% despite diet; wants a once-daily tablet.",
                          drug="sitagliptin", plan=dict(), q="What dose of sitagliptin should I use?"),
    "neuropathy_300": dict(condition="Diabetic peripheral neuropathy", complaint="Burning pain and numbness in both feet, worse at night, for 2 months.",
                           drug="gabapentin", plan=dict(tid_mg=300), q="I'd like to start gabapentin 300 mg three times daily. What dose fits this patient's kidneys?"),
    "neuropathy_600": dict(condition="Post-herpetic neuralgia", complaint="Persistent shooting pain along the left chest wall 3 months after shingles.",
                           drug="gabapentin", plan=dict(tid_mg=600), q="Planning gabapentin 600 mg three times daily. Does it need adjusting?"),
    "uti": dict(condition="Suspected uncomplicated cystitis", complaint="Painful urination, urgency and frequency for 2 days; no fever or flank pain.",
                drug="nitrofurantoin", plan=dict(), q="Can I treat this UTI with nitrofurantoin?"),
    "pneumonia_750": dict(condition="Community-acquired pneumonia", complaint="Productive cough, fever of 38.6 C and right lower lobe crackles for 3 days.",
                          drug="levofloxacin", plan=dict(mg=750), q="Planning levofloxacin 750 mg every 24 hours. What regimen for this patient?"),
    "pneumonia_500": dict(condition="Acute bacterial sinusitis, penicillin allergy", complaint="Facial pain and purulent nasal discharge for 12 days.",
                          drug="levofloxacin", plan=dict(mg=500), q="Levofloxacin 500 mg every 24 hours: does it need a renal adjustment?"),
    "gerd": dict(condition="Heartburn (symptomatic nonerosive GERD)", complaint="Burning chest discomfort after meals, worse lying down, for 4 weeks; no alarm symptoms.",
                 drug="famotidine", plan=dict(), q="Starting famotidine 20 mg twice daily for heartburn. What is the right dose here?"),
}

# ---------------------------------------------------------------- synthetic patients
FIRST_F = ["Maria", "Aisha", "Grace", "Linda", "Mei", "Fatima", "Rosa", "Helen", "Priya", "Joan", "Carmen", "Nadia", "Ruth", "Elena", "Tanya"]
FIRST_M = ["James", "Omar", "Victor", "Daniel", "Raj", "Samuel", "Luis", "George", "Kofi", "Peter", "Hiro", "Ahmed", "Frank", "Mateo", "Ivan"]
LAST = ["Lopez", "Okafor", "Nguyen", "Patel", "Kim", "Haddad", "Silva", "Brown", "Iyer", "Walsh", "Moreno", "Rahman", "Cohen", "Novak", "Mensah",
        "Tanaka", "Garcia", "Ali", "Fischer", "Reyes", "Osei", "Singh", "Dubois", "Kowalski", "Hassan", "Rossi", "Bauer", "Chen", "Mwangi", "Popov"]

# (sex, age, weight_kg, scr, dialysis, flags)  chosen to spread across kidney stages
PROFILES = [
    ("F", 72, 60, 2.0, False, []),          # P001 Maria Lopez: eGFR ~26, CrCl ~24 (pitch deck patient)
    ("M", 58, 92, 0.9, False, []), ("F", 45, 70, 0.7, False, []), ("M", 66, 80, 1.1, False, []), ("F", 61, 74, 0.9, False, []),
    ("M", 70, 85, 1.3, False, []), ("F", 68, 66, 1.1, False, []), ("M", 77, 72, 1.5, False, []), ("F", 74, 58, 1.3, False, []),
    ("M", 63, 95, 1.7, False, []), ("F", 80, 55, 1.4, False, []), ("M", 71, 78, 1.9, False, []), ("F", 59, 82, 1.6, False, []),
    ("M", 82, 64, 2.1, False, []), ("F", 76, 52, 1.9, False, []), ("M", 69, 88, 2.6, False, []), ("F", 67, 61, 2.4, False, []),
    ("M", 74, 70, 3.2, False, []), ("F", 79, 57, 2.9, False, []), ("M", 60, 101, 3.8, False, []), ("F", 71, 63, 4.5, False, []),
    ("M", 65, 76, 6.8, True, ["hemodialysis"]), ("F", 58, 68, 7.4, True, ["hemodialysis"]), ("M", 73, 81, 8.1, True, ["hemodialysis"]),
    ("M", 55, None, 1.4, False, ["missing_weight"]), ("F", 62, None, 2.2, False, ["missing_weight"]),
    ("M", 68, 84, 1.8, False, ["stale_lab"]), ("F", 75, 59, 1.6, False, ["stale_lab"]),
    ("M", 50, 110, 1.0, False, []), ("F", 84, 49, 1.2, False, []),
]

def kidney(p):
    e = egfr_ckd_epi_2021(p["scr"], p["age"], p["sex"])
    c = crcl_cockcroft_gault(p["scr"], p["age"], p["weight_kg"], p["sex"])
    return dict(egfr=e, crcl=c, stage=stage(e), dialysis=p["dialysis"],
                lab_age_days=(TODAY - date.fromisoformat(p["scr_date"])).days)

patients = []
used = set()
for i, (sex, age, wt, scr, dial, flags) in enumerate(PROFILES):
    pid = f"P{i+1:03d}"
    if i == 0:
        first, last = "Maria", "Lopez"
    else:
        while True:
            first = random.choice(FIRST_F if sex == "F" else FIRST_M); last = random.choice(LAST)
            if (first, last) not in used and (first, last) != ("Maria", "Lopez"):
                break
    used.add((first, last))
    lab_date = TODAY - timedelta(days=random.randint(200, 400) if "stale_lab" in flags else random.randint(3, 60))
    p = dict(id=pid, name=f"{first} {last} (synthetic)", sex=sex, age=age, weight_kg=wt, height_cm=random.randint(150, 175) if sex == "F" else random.randint(163, 190),
             scr=scr, scr_date=lab_date.isoformat(), dialysis=dial, flags=flags, allergies=random.choice([[], [], ["penicillin"], ["sulfa drugs"], ["codeine"]]))
    patients.append(p)

# Assign scenarios to patients (2 to 5 visits each), keeping P001 = diabetes on metformin
conds_pool = list(SCENARIOS.keys())
for i, p in enumerate(patients):
    if i == 0:
        picks = ["diabetes_cont", "neuropathy_300", "uti", "gerd"]
    else:
        picks = random.sample(conds_pool, k=random.randint(3, 5))
        if "diabetes_new" in picks and "diabetes_cont" in picks:
            picks.remove("diabetes_new")
    p["scenarios"] = picks
    conds = sorted({SCENARIOS[s]["condition"] for s in picks})
    base_conds = ["Hypertension"] + (["Chronic kidney disease"] if kidney(p)["egfr"] < 60 else [])
    if p["dialysis"]:
        base_conds.append("End-stage kidney disease on hemodialysis three times weekly")
    p["conditions"] = base_conds + conds
    meds = ["lisinopril 10 mg once daily", "atorvastatin 20 mg once daily"]
    if "diabetes_cont" in picks:
        meds.append("metformin 1000 mg twice daily")
    p["medications"] = meds
    k = kidney(p)
    p["kidney"] = {"egfr": k["egfr"], "crcl": k["crcl"], "stage": k["stage"]}
    wt_txt = f"{p['weight_kg']} kg" if p["weight_kg"] else "not recorded"
    p["background"] = (
        f"{p['name']} is a {p['age']}-year-old {'woman' if sex == 'F' else 'man'} seen in primary care. "
        f"Known conditions: {', '.join(p['conditions'])}. Current medications: {', '.join(p['medications'])}. "
        f"Allergies: {', '.join(p['allergies']) if p['allergies'] else 'none known'}. Weight {wt_txt}. "
        f"Most recent serum creatinine {p['scr']} mg/dL on {p['scr_date']}"
        + (" (more than 90 days ago; repeat labs are due)." if "stale_lab" in flags else ".")
        + (" Receives hemodialysis three times weekly." if p["dialysis"] else "")
        + " Lives independently and manages own medications."
    )

# ---------------------------------------------------------------- prompts (kept identical to the app's master prompt)
MASTER_PROMPT = (OUT / "prompts" / "master_prompt.txt").read_text().strip()

def patient_summary(p, visit):
    wt = f"{p['weight_kg']} kg" if p["weight_kg"] else "not recorded"
    return (f"{p['name']}, {p['age']} {('female' if p['sex']=='F' else 'male')}, weight {wt}. "
            f"Conditions: {', '.join(p['conditions'])}. Medications: {', '.join(p['medications'])}. "
            f"Allergies: {', '.join(p['allergies']) if p['allergies'] else 'none known'}.\n"
            f"Visit intake ({TODAY.isoformat()}): {visit['complaint']}")

def kidney_line(p, k):
    flags = list(p["flags"])
    if k["lab_age_days"] > 90 and "stale_lab" not in flags:
        flags.append("stale_lab")
    crcl = "not calculable (weight missing)" if k["crcl"] is None else f"{k['crcl']} mL/min"
    return (f"CrCl (Cockcroft-Gault): {crcl} | eGFR (CKD-EPI 2021): {k['egfr']} mL/min/1.73m2 | Stage: {k['stage']} | "
            f"Creatinine {p['scr']} mg/dL on {p['scr_date']} ({k['lab_age_days']} days old) | Dialysis: {'yes' if k['dialysis'] else 'no'} | "
            f"Flags: {', '.join(flags) if flags else 'none'}")

def rule_text(drug, d):
    if d is None:
        return "No rule found for this drug at this kidney function."
    dose = d["dose"] or "none"
    return f"{drug}: action={d['action']}; dose={dose}; max daily={d['max_daily'] or 'n/a'}; measure={d['measure']}; source chunks={', '.join(d['cites'])}"

def sources_block(drug, p, visit_id):
    lines = [f"[PT-{p['id']}-intake] (Patient intake, {TODAY.isoformat()}) {p['background']}"]
    if drug in LABELS:
        for cid, txt in LABELS[drug]["chunks"].items():
            lines.append(f"[{cid}] ({LABELS[drug]['product']}) {txt}")
    return "\n".join(lines)

def build_example(p, scen_key, ex_id):
    s = SCENARIOS[scen_key]; drug = s["drug"]; k = kidney(p)
    # data-quality checks come first (mirrors the app's guardrail)
    if k["lab_age_days"] > 90:
        d = None
        out = dict(drug=drug, action="insufficient_information", recommended_dose=None, max_daily_dose=None, kidney_measure_used=None,
                   rationale=f"The latest creatinine is {k['lab_age_days']} days old, so current kidney function is unknown. Repeat serum creatinine before choosing a {drug} dose.",
                   monitoring="Order a serum creatinine today.", citations=[{"chunk_id": f"PT-{p['id']}-intake", "quote": f"Most recent serum creatinine {p['scr']} mg/dL on {p['scr_date']}"}],
                   confidence="high")
    elif drug == "nitrofurantoin" and k["crcl"] is None and k["egfr"] < 60:
        d = None
        out = dict(drug=drug, action="avoid", recommended_dose=None, max_daily_dose=None, kidney_measure_used="eGFR",
                   rationale=f"Weight is missing, so CrCl cannot be calculated, but creatinine is {p['scr']} mg/dL (eGFR {k['egfr']}). The label contraindicates nitrofurantoin with clinically significant elevated serum creatinine.",
                   monitoring="Choose an alternative antibiotic suited to kidney function; record weight.",
                   citations=[{"chunk_id": "LBL-nitrofurantoin-01", "quote": LABELS[drug]["chunks"]["LBL-nitrofurantoin-01"][:160]},
                              {"chunk_id": f"PT-{p['id']}-intake", "quote": f"serum creatinine {p['scr']} mg/dL on {p['scr_date']}"}],
                   confidence="medium")
    elif LABELS[drug]["measure"] == "CrCl" and k["crcl"] is None and not k["dialysis"]:
        d = None
        out = dict(drug=drug, action="insufficient_information", recommended_dose=None, max_daily_dose=None, kidney_measure_used=None,
                   rationale=f"The {drug} label doses by creatinine clearance, which needs body weight, and weight is not recorded. Weigh the patient, then recheck.",
                   monitoring="Record weight at this visit.", citations=[{"chunk_id": f"PT-{p['id']}-intake", "quote": "Weight not recorded"}],
                   confidence="high")
    else:
        d = decide(drug, s["plan"], k)
        cites = [{"chunk_id": cid, "quote": LABELS[drug]["chunks"][cid][:160]} for cid in d["cites"]]
        cites.append({"chunk_id": f"PT-{p['id']}-intake", "quote": f"serum creatinine {p['scr']} mg/dL on {p['scr_date']}"})
        out = dict(drug=drug, action=d["action"], recommended_dose=d["dose"], max_daily_dose=d["max_daily"], kidney_measure_used=d["measure"],
                   rationale=d["why"], monitoring=d["monitoring"], citations=cites,
                   confidence="high" if d["action"] != "insufficient_information" else "medium")
    user = (f"PATIENT:\n{patient_summary(p, s)}\n\nKIDNEY:\n{kidney_line(p, k)}\n\nRULE:\n{rule_text(drug, d)}\n\n"
            f"SOURCES:\n{sources_block(drug, p, ex_id)}\n\nQUESTION:\n{s['q']}")
    return dict(id=ex_id, patient_id=p["id"], scenario=scen_key, messages=[
        {"role": "system", "content": MASTER_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
    ]), out, k

def build_unknown_drug(p, ex_id):
    k = kidney(p)
    q = "What apixaban dose should this patient take?"
    out = dict(drug="apixaban", action="insufficient_information", recommended_dose=None, max_daily_dose=None, kidney_measure_used=None,
               rationale="Apixaban is not in RxD's approved sources yet, so RxD cannot give a dose. Check the current label or ask a pharmacist.",
               monitoring=None, citations=[], confidence="high")
    visit = dict(complaint="Newly diagnosed atrial fibrillation; palpitations for 1 week.")
    user = (f"PATIENT:\n{patient_summary(p, visit)}\n\nKIDNEY:\n{kidney_line(p, k)}\n\nRULE:\nNo rule found for this drug at this kidney function.\n\n"
            f"SOURCES:\n[PT-{p['id']}-intake] (Patient intake) {p['background']}\n\nQUESTION:\n{q}")
    return dict(id=ex_id, patient_id=p["id"], scenario="unknown_drug", messages=[
        {"role": "system", "content": MASTER_PROMPT}, {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}]), out, k

examples, rows, n = [], [], 0
for p in patients:
    for sk in p["scenarios"]:
        n += 1
        ex, out, k = build_example(p, sk, f"EX{n:04d}")
        examples.append(ex)
        rows.append([ex["id"], p["id"], sk, out["drug"], p["age"], p["sex"], p["weight_kg"] or "", p["scr"], k["lab_age_days"], k["egfr"], k["crcl"] if k["crcl"] is not None else "", "yes" if k["dialysis"] else "no", out["action"], out["recommended_dose"] or ""])
for p in random.sample(patients[1:], 6):
    n += 1
    ex, out, k = build_unknown_drug(p, f"EX{n:04d}")
    examples.append(ex)
    rows.append([ex["id"], p["id"], "unknown_drug", "apixaban", p["age"], p["sex"], p["weight_kg"] or "", p["scr"], k["lab_age_days"], k["egfr"], k["crcl"] if k["crcl"] is not None else "", "yes" if k["dialysis"] else "no", out["action"], ""])

# split by patient: P001 always in test (demo patient), others 80/10/10
pids = [p["id"] for p in patients if p["id"] != "P001"]
random.shuffle(pids)
n_valid = 3; n_test = 3
valid_ids = set(pids[:n_valid]); test_ids = set(pids[n_valid:n_valid + n_test]) | {"P001"}
splits = {"train": [], "valid": [], "test": []}
for ex in examples:
    s = "test" if ex["patient_id"] in test_ids else "valid" if ex["patient_id"] in valid_ids else "train"
    splits[s].append(ex)

# ---------------------------------------------------------------- write files
(OUT / "patients").mkdir(parents=True, exist_ok=True)
(OUT / "finetune").mkdir(parents=True, exist_ok=True)

rules_out = {}
for drug, L in LABELS.items():
    rules_out[drug] = {"product": L["product"], "measure": L["measure"], "source": "openFDA drug label API, retrieved 2026-11-21",
                       "chunk_ids": list(L["chunks"].keys()), "verified_by": None}
(OUT / "dosing_rules.json").write_text(json.dumps(rules_out, indent=2))
(OUT / "label_excerpts.json").write_text(json.dumps(
    [{"chunk_id": cid, "drug": drug, "product": L["product"], "text": txt, "source": "openFDA drug label API, retrieved 2026-11-21"}
     for drug, L in LABELS.items() for cid, txt in L["chunks"].items()], indent=2))

pat_out = []
for p in patients:
    q = {k2: v for k2, v in p.items() if k2 not in ("scenarios",)}
    q["visits"] = [{"date": TODAY.isoformat(), "chief_complaint": SCENARIOS[s]["complaint"], "considered_drug": SCENARIOS[s]["drug"]} for s in p["scenarios"]]
    pat_out.append(q)
(OUT / "patients" / "synthetic_patients.json").write_text(json.dumps(pat_out, indent=2))

for name, items in splits.items():
    with open(OUT / "finetune" / f"{name}.jsonl", "w") as f:
        for ex in items:
            f.write(json.dumps({"messages": ex["messages"]}, ensure_ascii=False) + "\n")

with open(OUT / "finetune" / "summary.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["example_id", "patient_id", "scenario", "drug", "age", "sex", "weight_kg", "scr_mg_dl", "lab_age_days", "egfr", "crcl", "dialysis", "expected_action", "recommended_dose"])
    w.writerows(rows)

with open(OUT / "test_set.jsonl", "w") as f:
    for ex in splits["test"] + splits["valid"]:
        out = json.loads(ex["messages"][2]["content"])
        q = ex["messages"][1]["content"].split("QUESTION:\n")[1]
        f.write(json.dumps({"id": ex["id"], "patient_id": ex["patient_id"], "question": q, "drug": out["drug"],
                            "expected_action": out["action"], "expected_dose": out["recommended_dose"]}) + "\n")

print("patients", len(patients), "examples", len(examples), {k2: len(v) for k2, v in splits.items()})
from collections import Counter
print(Counter(r[12] for r in rows))
print(Counter(r[3] for r in rows))
p1 = patients[0]; print("P001", p1["name"], p1["kidney"])
