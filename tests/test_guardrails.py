"""Guardrails and fallback: the rule decides, citations must be retrieved, bad JSON is retried, an outage falls back."""

import json

from app.models.dosing_rules import RuleResult
from app.models.guardrails import check_model_output, fallback_output, parse_model_json
from app.models.llm import FakeLLM
from app.models.retrieval import SourceChunk

P001 = "P001"
QUESTION = "Is metformin 1000 mg twice daily still OK?"


def _rule_avoid() -> RuleResult:
    return RuleResult(drug="metformin", action="avoid", dose=None, max_daily=None, measure="eGFR",
                      cite_ids=["LBL-metformin-04"], why="Discontinue below an eGFR of 30.", monitoring="Stop.")


def _sources() -> list[SourceChunk]:
    return [SourceChunk(chunk_id="LBL-metformin-04", label="FDA label · metformin", text="Discontinue if eGFR falls below 30.")]


def _answer(**overrides) -> dict:
    body = {"drug": "metformin", "action": "avoid", "recommended_dose": None, "max_daily_dose": None,
            "kidney_measure_used": "eGFR", "rationale": "Stop metformin.", "monitoring": "Stop.",
            "citations": [{"chunk_id": "LBL-metformin-04", "quote": "Discontinue"}], "confidence": "high"}
    body.update(overrides)
    return body


# ---------- unit: guardrail rules ----------

def test_model_disagreement_is_overwritten_and_needs_review():
    verdict = check_model_output(_answer(action="continue", recommended_dose="1000 mg twice daily"),
                                 _rule_avoid(), _sources(), flags=[])
    assert verdict.final["action"] == "avoid"
    assert verdict.final["recommended_dose"] is None
    assert verdict.model_disagreed is True
    assert verdict.status == "needs_review"


def test_fake_chunk_ids_are_dropped_and_the_rule_citation_is_used_when_none_remain():
    verdict = check_model_output(_answer(citations=[{"chunk_id": "PT-FAKE-1", "quote": "invented"}]),
                                 _rule_avoid(), _sources(), flags=[])
    assert verdict.dropped_citations == 1
    assert [c["chunk_id"] for c in verdict.final["citations"]] == ["LBL-metformin-04"]


def test_real_and_fake_citations_keep_only_the_real_one():
    verdict = check_model_output(
        _answer(citations=[{"chunk_id": "PT-FAKE-1", "quote": "x"}, {"chunk_id": "LBL-metformin-04", "quote": "Discontinue"}]),
        _rule_avoid(), _sources(), flags=[])
    assert [c["chunk_id"] for c in verdict.final["citations"]] == ["LBL-metformin-04"]


def test_malformed_field_types_do_not_crash_the_guardrail():
    odd = _answer(citations=[{"chunk_id": ["not", "a", "string"], "quote": "x"}, "not-a-dict"],
                  confidence=["high"], rationale=None)
    verdict = check_model_output(odd, _rule_avoid(), _sources(), flags=[])
    assert verdict.final["confidence"] == "medium"
    assert verdict.final["rationale"] == _rule_avoid().why
    assert [c["chunk_id"] for c in verdict.final["citations"]] == ["LBL-metformin-04"]


def test_clean_agreement_is_ok():
    verdict = check_model_output(_answer(), _rule_avoid(), _sources(), flags=[])
    assert verdict.model_disagreed is False
    assert verdict.status == "ok"


def test_any_flag_needs_review_even_when_the_model_agrees():
    verdict = check_model_output(_answer(), _rule_avoid(), _sources(), flags=["dialysis"])
    assert verdict.status == "needs_review"


def test_parse_handles_code_fences_and_rejects_non_objects():
    assert parse_model_json("```json\n{\"action\": \"avoid\"}\n```") == {"action": "avoid"}
    assert parse_model_json("not json") is None
    assert parse_model_json("[1, 2]") is None


def test_fallback_is_built_from_the_rule_alone():
    final = fallback_output(_rule_avoid(), _sources(), intake_chunk_id=None)
    assert final["action"] == "avoid"
    assert final["rationale"] == "Discontinue below an eGFR of 30."
    assert final["citations"][0]["chunk_id"] == "LBL-metformin-04"


# ---------- API: the model in the loop ----------

def test_model_that_disagrees_is_overwritten_end_to_end(client, clinician, llm: FakeLLM):
    llm.replies = [json.dumps(_answer(action="continue", recommended_dose="1000 mg twice daily"))]
    body = client.post("/api/v1/suggestions", headers=clinician, json={"patient_id": P001, "question": QUESTION}).json()
    assert body["final_output"]["action"] == "avoid"
    assert body["status"] == "needs_review"
    assert body["model_output"]["model_disagreed"] is True


def test_invalid_json_is_retried_once_then_accepted(client, clinician, llm: FakeLLM):
    llm.replies = ["this is not json", json.dumps(_answer())]
    body = client.post("/api/v1/suggestions", headers=clinician, json={"patient_id": P001, "question": QUESTION}).json()
    assert body["status"] == "ok"
    assert body["model_output"]["json_attempts"] == 2


def test_invalid_json_twice_falls_back(client, clinician, llm: FakeLLM):
    llm.replies = ["still not json", "nor this"]
    body = client.post("/api/v1/suggestions", headers=clinician, json={"patient_id": P001, "question": QUESTION}).json()
    assert body["status"] == "fallback"
    assert body["final_output"]["action"] == "avoid"
    assert len(llm.calls) == 2


def test_model_down_still_answers_with_the_same_action(client, clinician, llm: FakeLLM):
    llm.unavailable = True
    body = client.post("/api/v1/suggestions", headers=clinician, json={"patient_id": P001, "question": QUESTION}).json()
    assert body["status"] == "fallback"
    assert body["final_output"]["action"] == "avoid"
    assert body["model_output"] is None
    assert body["final_output"]["citations"]


def test_retrieval_still_works_without_vectors(client, clinician, llm: FakeLLM):
    llm.unavailable = True
    body = client.post("/api/v1/suggestions", headers=clinician, json={"patient_id": P001, "question": QUESTION}).json()
    assert any(s["label"].startswith("Visit intake") for s in body["sources"])


def test_when_the_model_disagrees_its_rationale_is_replaced_by_the_rules():
    verdict = check_model_output(_answer(action="continue", rationale="Within the maximum daily dose."),
                                 _rule_avoid(), _sources(), flags=[])
    assert verdict.final["rationale"] == _rule_avoid().why
