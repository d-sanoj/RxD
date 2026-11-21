"""Finds the drug in a question, parses a stated regimen and picks the persona."""

import re
from dataclasses import dataclass, field

DRUG_TERMS: dict[str, list[str]] = {
    "metformin": ["metformin", "glucophage"],
    "sitagliptin": ["sitagliptin", "januvia"],
    "gabapentin": ["gabapentin", "neurontin"],
    "nitrofurantoin": ["nitrofurantoin", "macrobid", "macrodantin"],
    "levofloxacin": ["levofloxacin", "levaquin"],
    "famotidine": ["famotidine", "pepcid"],
}
PERSONA = {
    "metformin": "diabetes",
    "sitagliptin": "diabetes",
    "nitrofurantoin": "anti_infective",
    "levofloxacin": "anti_infective",
}
_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg)\b", re.IGNORECASE)
_FREQUENCY = re.compile(
    r"\b(once daily|twice daily|three times daily|two times daily|every \d+ hours|every day|once a day"
    r"|twice a day|three times|twice|daily)\b",
    re.IGNORECASE,
)


@dataclass
class RoutedRequest:
    drug: str | None
    persona: str
    plan: dict = field(default_factory=dict)
    regimen: str | None = None


def find_drug(question: str) -> str | None:
    text = question.lower()
    best: tuple[int, str] | None = None
    for drug, terms in DRUG_TERMS.items():
        for term in terms:
            match = re.search(rf"\b{re.escape(term)}\b", text)
            if match and (best is None or match.start() < best[0]):
                best = (match.start(), drug)
    return best[1] if best else None


def route(question: str, medications: list[dict]) -> RoutedRequest:
    drug = find_drug(question)
    if drug is None:
        return RoutedRequest(drug=None, persona="general")

    dose_match = _DOSE.search(question)
    amount = float(dose_match.group(1)) if dose_match else None
    unit = dose_match.group(2).lower() if dose_match else None
    freq = None
    if dose_match:
        nearby = question[dose_match.end(): dose_match.end() + 40]
        freq_match = _FREQUENCY.search(nearby)
        freq = freq_match.group(1).lower() if freq_match else None
    regimen = None
    if amount is not None:
        regimen = f"{amount:g} {unit}" + (f" {freq}" if freq else "")

    unsupported = None
    if drug == "metformin":
        on_metformin = any("metformin" in (m.get("name") or "").lower() for m in medications)
        plan = {"new_start": not on_metformin, "regimen": regimen or "dose not stated in the question"}
    elif drug == "gabapentin":
        if freq and "three times" not in freq:
            unsupported = ("The label's gabapentin table is for three-times-daily regimens, and the stated "
                           "frequency is different. Check the dose with a pharmacist.")
        tid = int(amount) if amount is not None and unit == "mg" else 300
        plan = {"tid_mg": tid}
    elif drug == "levofloxacin":
        if freq and freq not in {"every 24 hours", "once daily", "daily", "once a day", "every day"}:
            unsupported = ("The label's levofloxacin table is for every-24-hour regimens, and the stated "
                           "frequency is different. Check the dose with a pharmacist.")
        mg = int(amount) if amount is not None and unit == "mg" else 750
        plan = {"mg": mg}
    else:
        plan = {}

    if unsupported:
        plan["unsupported"] = unsupported
    return RoutedRequest(drug=drug, persona=PERSONA.get(drug, "general"), plan=plan, regimen=regimen)
