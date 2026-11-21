"""The planned regimen for each clinical scenario, copied from SCENARIOS in tools/generate_dataset.py.

Importing that script would regenerate the data files, so the plan values are copied here instead.
"""

SCENARIO_PLANS = {
    "diabetes_new": dict(drug="metformin", plan=dict(new_start=True, regimen="500 mg twice daily with meals")),
    "diabetes_cont": dict(drug="metformin", plan=dict(new_start=False, regimen="1000 mg twice daily")),
    "diabetes_dpp4": dict(drug="sitagliptin", plan=dict()),
    "neuropathy_300": dict(drug="gabapentin", plan=dict(tid_mg=300)),
    "neuropathy_600": dict(drug="gabapentin", plan=dict(tid_mg=600)),
    "uti": dict(drug="nitrofurantoin", plan=dict()),
    "pneumonia_750": dict(drug="levofloxacin", plan=dict(mg=750)),
    "pneumonia_500": dict(drug="levofloxacin", plan=dict(mg=500)),
    "gerd": dict(drug="famotidine", plan=dict()),
}
