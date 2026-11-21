"""Guardrails. The rule decides; the model may only explain. Every citation must have been retrieved."""

import json
import re
from dataclasses import dataclass

from app.models.dosing_rules import RuleResult
from app.models.retrieval import SourceChunk

QUOTE_CHARS = 160
CONFIDENCE_LEVELS = {"high", "medium", "low"}


@dataclass(frozen=True)
class Verdict:
    final: dict
    status: str
    model_disagreed: bool
    dropped_citations: int


def parse_model_json(raw: str) -> dict | None:
    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _norm(value) -> str | None:
    return None if value is None else str(value).strip().lower()


def _rule_citations(rule: RuleResult, sources: list[SourceChunk]) -> list[dict]:
    by_id = {s.chunk_id: s for s in sources}
    return [{"chunk_id": cid, "quote": by_id[cid].text[:QUOTE_CHARS]} for cid in rule.cite_ids if cid in by_id]


def check_model_output(parsed: dict, rule: RuleResult, sources: list[SourceChunk], flags: list[str]) -> Verdict:
    retrieved = {s.chunk_id: s for s in sources}
    disagreed = (
        _norm(parsed.get("action")) != _norm(rule.action)
        or _norm(parsed.get("recommended_dose")) != _norm(rule.dose)
        or _norm(parsed.get("max_daily_dose")) != _norm(rule.max_daily)
    )

    kept: list[dict] = []
    dropped = 0
    for citation in parsed.get("citations") or []:
        chunk_id = citation.get("chunk_id") if isinstance(citation, dict) else None
        if isinstance(chunk_id, str) and chunk_id in retrieved:
            quote = str(citation.get("quote") or retrieved[chunk_id].text[:QUOTE_CHARS])
            kept.append({"chunk_id": chunk_id, "quote": quote})
        else:
            dropped += 1
    if not kept:
        kept = _rule_citations(rule, sources)

    rationale = parsed.get("rationale")
    monitoring = parsed.get("monitoring")
    confidence = parsed.get("confidence")
    final = {
        "drug": rule.drug,
        "action": rule.action,
        "recommended_dose": rule.dose,
        "max_daily_dose": rule.max_daily,
        "kidney_measure_used": rule.measure,
        # If the model disagreed with the rule, its explanation may contradict the verdict, so use the rule's.
        "rationale": rationale if isinstance(rationale, str) and rationale.strip() and not disagreed else rule.why,
        "monitoring": monitoring if isinstance(monitoring, str) else rule.monitoring,
        "citations": kept,
        "confidence": confidence if isinstance(confidence, str) and confidence in CONFIDENCE_LEVELS else "medium",
    }
    needs_review = disagreed or rule.action == "insufficient_information" or bool(flags)
    return Verdict(final=final, status="needs_review" if needs_review else "ok",
                   model_disagreed=disagreed, dropped_citations=dropped)


def fallback_output(rule: RuleResult, sources: list[SourceChunk], intake_chunk_id: str | None) -> dict:
    """Deterministic answer built straight from the rule, used when the model is unavailable or fails."""
    citations = _rule_citations(rule, sources)
    if intake_chunk_id:
        citations += [
            {"chunk_id": s.chunk_id, "quote": s.text[:QUOTE_CHARS]} for s in sources if s.chunk_id == intake_chunk_id
        ]
    return {
        "drug": rule.drug,
        "action": rule.action,
        "recommended_dose": rule.dose,
        "max_daily_dose": rule.max_daily,
        "kidney_measure_used": rule.measure,
        "rationale": rule.why,
        "monitoring": rule.monitoring,
        "citations": citations,
        "confidence": "medium" if rule.action == "insufficient_information" else "high",
    }
