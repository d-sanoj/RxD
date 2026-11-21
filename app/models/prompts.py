"""Prompt building. The message layout matches data/finetune/ exactly: PATIENT / KIDNEY / RULE / SOURCES / QUESTION."""

from pathlib import Path

from app.models.dosing_rules import RuleResult
from app.models.retrieval import SourceChunk

PERSONA_LINES = {
    "diabetes": "Mention hypoglycemia or lactic-acidosis wording when the sources include it.",
    "anti_infective": "Note when kidney function makes a drug unsuitable, not only the dose.",
    "general": None,
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "drug": {"type": "string"},
        "action": {"type": "string", "enum": ["continue", "adjust_dose", "caution", "avoid", "insufficient_information"]},
        "recommended_dose": {"type": ["string", "null"]},
        "max_daily_dose": {"type": ["string", "null"]},
        "kidney_measure_used": {"type": ["string", "null"], "enum": ["CrCl", "eGFR", None]},
        "rationale": {"type": "string"},
        "monitoring": {"type": ["string", "null"]},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["chunk_id", "quote"],
            },
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": [
        "drug", "action", "recommended_dose", "max_daily_dose", "kidney_measure_used",
        "rationale", "monitoring", "citations", "confidence",
    ],
}


def load_master_prompt(data_dir: Path) -> str:
    return (data_dir / "prompts" / "master_prompt.txt").read_text(encoding="utf-8").strip()


def system_prompt(master: str, persona: str) -> str:
    line = PERSONA_LINES.get(persona)
    return f"{master}\n\n{line}" if line else master


def patient_block(*, name: str, age: int, sex: str, weight_kg: float | None, conditions: list[str],
                  medications: list[str], allergies: list[str], visit_date: str, complaint: str) -> str:
    weight = f"{weight_kg:g} kg" if weight_kg is not None else "not recorded"
    sex_word = {"F": "female", "M": "male"}.get(sex or "", "")
    who = " ".join(x for x in (str(age) if age is not None else "", sex_word) if x) or "age and sex not recorded"
    return (
        f"{name}, {who}, weight {weight}. "
        f"Conditions: {', '.join(conditions) or 'none recorded'}. "
        f"Medications: {', '.join(medications) or 'none recorded'}. "
        f"Allergies: {', '.join(allergies) or 'none known'}.\n"
        f"Visit intake ({visit_date}): {complaint or 'not recorded'}"
    )


def kidney_block(*, crcl: float | None, egfr: float | None, stage: str | None, scr: float | None,
                 creatinine_date: str | None, lab_age_days: int | None, dialysis: bool, flags: list[str]) -> str:
    crcl_txt = f"{crcl:g} mL/min" if crcl is not None else "not calculable (weight missing)"
    egfr_txt = f"{egfr:g} mL/min/1.73m2" if egfr is not None else "not calculable"
    if scr is not None:
        lab_txt = f"Creatinine {scr:g} mg/dL on {creatinine_date} ({lab_age_days} days old)"
    else:
        lab_txt = "Creatinine not recorded"
    return (
        f"CrCl (Cockcroft-Gault): {crcl_txt} | eGFR (CKD-EPI 2021): {egfr_txt} | Stage: {stage or 'unknown'} | "
        f"{lab_txt} | Dialysis: {'yes' if dialysis else 'no'} | Flags: {', '.join(flags) if flags else 'none'}"
    )


def rule_block(rule: RuleResult | None) -> str:
    if rule is None:
        return "No rule found for this drug at this kidney function."
    return (
        f"{rule.drug}: action={rule.action}; dose={rule.dose or 'none'}; max daily={rule.max_daily or 'n/a'}; "
        f"measure={rule.measure or 'n/a'}; source chunks={', '.join(rule.cite_ids) or 'none'}"
    )


def sources_block(sources: list[SourceChunk]) -> str:
    return "\n".join(f"[{s.chunk_id}] ({s.label}) {s.text}" for s in sources)


def build_user_message(*, patient: str, kidney: str, rule: str, sources: str, question: str) -> str:
    return (
        f"PATIENT:\n{patient}\n\nKIDNEY:\n{kidney}\n\nRULE:\n{rule}\n\n"
        f"SOURCES:\n{sources}\n\nQUESTION:\n{question}"
    )
