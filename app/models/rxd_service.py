"""The suggestion pipeline: kidney -> route -> retrieve -> rule -> model -> guardrail -> fallback -> persist.

The rules engine decides the dose. The model only explains it, and its output is checked against the rule.
"""

import logging
from dataclasses import asdict
from datetime import date
from time import perf_counter

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.logging import log_event
from app.models.chunking import intake_chunk_id
from app.models.container import Container
from app.models.dosing_rules import KidneyFacts, RuleResult, evaluate
from app.models.entities import Decision, Intake, Patient, Suggestion
from app.models.guardrails import check_model_output, fallback_output, parse_model_json
from app.models.kidney import KidneyResult, assess
from app.models.llm import ModelUnavailable
from app.models.prompts import (
    ANSWER_SCHEMA,
    build_user_message,
    kidney_block,
    patient_block,
    rule_block,
    sources_block,
    system_prompt,
)
from app.models.repositories import AuditRepo, DecisionRepo, IntakeRepo, PatientRepo, SuggestionRepo
from app.models.retrieval import SourceChunk, retrieve_labels, retrieve_patient
from app.models.router import RoutedRequest, route

logger = logging.getLogger("rxd.suggestions")


def _medication_text(medications: list[dict]) -> list[str]:
    return [" ".join(str(m.get(k) or "") for k in ("name", "dose", "frequency")).strip() for m in medications]


class RxdService:
    def __init__(self, db: Session, container: Container) -> None:
        self.db = db
        self.c = container

    # ----- suggestions -----
    def create_suggestion(self, *, patient_id: str, question: str, actor: str) -> Suggestion:
        started = perf_counter()
        patient = PatientRepo(self.db).get(patient_id)
        if patient is None:
            raise NotFoundError("Patient not found.")
        intake = IntakeRepo(self.db).latest(patient_id)
        if intake is None:
            raise UnprocessableError("Record a visit intake first.", code="no_intake")

        today = date.today()
        kidney = assess(
            age=patient.age,
            sex=patient.sex,
            weight_kg=intake.weight_kg,
            scr=intake.serum_creatinine_mg_dl,
            creatinine_date=intake.creatinine_date,
            on_dialysis=intake.on_dialysis,
            today=today,
        )
        facts = KidneyFacts(
            egfr=kidney.egfr,
            crcl=kidney.crcl,
            dialysis=intake.on_dialysis,
            scr=intake.serum_creatinine_mg_dl,
            lab_age_days=kidney.lab_age_days,
        )
        routed = route(question, list(intake.medications or []))
        intake_cid = intake_chunk_id(patient.id, intake.id)

        if routed.drug is None:
            rule = RuleResult(
                drug="unknown", action="insufficient_information", dose=None, max_daily=None, measure=None,
                why="This drug is not in RxD's approved sources.",
                monitoring="Check the current label or ask a pharmacist.",
            )
            sources: list[SourceChunk] = []
            final = fallback_output(rule, sources, None)
            status, model_output = "needs_review", None
            model_name = None
        else:
            sources = retrieve_labels(self.db, routed.drug)
            query = f"{question} {intake.chief_complaint}".strip()
            sources = sources + retrieve_patient(self.db, self.c.vector, patient.id, query, intake_cid).sources
            rule = evaluate(routed.drug, routed.plan, facts)
            user_message = self._user_message(patient, intake, kidney, rule, sources, question)
            final, status, model_output = self._generate(routed, rule, sources, user_message, kidney.flags, intake_cid)
            model_name = self.c.llm.model_name

        suggestion = SuggestionRepo(self.db).add(
            Suggestion(
                patient_id=patient.id,
                intake_id=intake.id,
                question=question,
                drug=routed.drug,
                rule_result=rule.as_dict(),
                sources=[asdict(s) for s in sources],
                retrieved_ids=[s.chunk_id for s in sources],
                model_name=model_name,
                model_output=model_output,
                final_output=final,
                status=status,
                latency_ms=int(round((perf_counter() - started) * 1000)),
                created_by=actor,
            )
        )
        AuditRepo(self.db).add(
            actor, "suggestion.create", "suggestion", str(suggestion.id),
            {"drug": routed.drug, "action": final["action"], "status": status}, patient_id=patient.id,
        )
        self.db.commit()
        return suggestion

    def _generate(self, routed: RoutedRequest, rule: RuleResult, sources: list[SourceChunk],
                  user_message: str, flags: list[str], intake_cid: str):
        messages = [
            {"role": "system", "content": system_prompt(self.c.master_prompt, routed.persona)},
            {"role": "user", "content": user_message},
        ]
        parsed = None
        raw = ""
        attempts = 0
        try:
            for attempt in range(2):
                attempts += 1
                attempt_messages = messages if attempt == 0 else messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "Return only valid JSON."},
                ]
                raw = self.c.llm.chat(attempt_messages, ANSWER_SCHEMA)
                parsed = parse_model_json(raw)
                if parsed is not None:
                    break
        except ModelUnavailable:
            log_event(logger, "fallback_model_unavailable", level=logging.WARNING, drug=rule.drug)
            return fallback_output(rule, sources, intake_cid), "fallback", None

        if parsed is None:
            log_event(logger, "fallback_invalid_json", level=logging.WARNING, drug=rule.drug, attempts=attempts)
            return fallback_output(rule, sources, intake_cid), "fallback", {"parsed": None, "json_attempts": attempts}

        verdict = check_model_output(parsed, rule, sources, flags)
        model_output = {
            "parsed": parsed,
            "model_disagreed": verdict.model_disagreed,
            "json_attempts": attempts,
            "dropped_citations": verdict.dropped_citations,
        }
        return verdict.final, verdict.status, model_output

    def _user_message(self, patient: Patient, intake: Intake, kidney: KidneyResult,
                      rule: RuleResult, sources: list[SourceChunk], question: str) -> str:
        patient_text = patient_block(
            name=patient.name,
            age=patient.age,
            sex=patient.sex,
            weight_kg=intake.weight_kg,
            conditions=list(intake.conditions or []),
            medications=_medication_text(list(intake.medications or [])),
            allergies=list(intake.allergies or []),
            visit_date=intake.visit_date.isoformat(),
            complaint=intake.chief_complaint,
        )
        kidney_text = kidney_block(
            crcl=kidney.crcl,
            egfr=kidney.egfr,
            stage=kidney.ckd_stage,
            scr=intake.serum_creatinine_mg_dl,
            creatinine_date=intake.creatinine_date.isoformat() if intake.creatinine_date else None,
            lab_age_days=kidney.lab_age_days,
            dialysis=intake.on_dialysis,
            flags=kidney.flags,
        )
        return build_user_message(
            patient=patient_text,
            kidney=kidney_text,
            rule=rule_block(rule),
            sources=sources_block(sources),
            question=question,
        )

    def get_suggestion(self, suggestion_id: int) -> Suggestion:
        suggestion = SuggestionRepo(self.db).get(suggestion_id)
        if suggestion is None:
            raise NotFoundError("Suggestion not found.")
        return suggestion

    def list_for_patient(self, patient_id: str, limit: int, offset: int) -> tuple[list[Suggestion], int]:
        if PatientRepo(self.db).get(patient_id) is None:
            raise NotFoundError("Patient not found.")
        return SuggestionRepo(self.db).page(limit, offset, patient_id)

    # ----- decisions -----
    def record_decision(self, *, suggestion_id: int, decision: str, edited_text: str | None,
                        reason: str | None, actor: str) -> Decision:
        suggestion = SuggestionRepo(self.db).get(suggestion_id)
        if suggestion is None:
            raise NotFoundError("Suggestion not found.")
        edited = (edited_text or "").strip()
        why = (reason or "").strip()
        if decision == "reject" and not why:
            raise UnprocessableError("A reason is required to reject a suggestion.", code="reason_required")
        if decision == "edit" and not edited:
            raise UnprocessableError("Edited text is required when editing a suggestion.", code="edited_text_required")
        if DecisionRepo(self.db).for_suggestion(suggestion.id):
            raise ConflictError("This suggestion already has a decision.", code="already_decided")

        record = DecisionRepo(self.db).add(
            Decision(
                suggestion_id=suggestion.id,
                decision=decision,
                edited_text=edited or None,
                reason=why or None,
                decided_by=actor,
            )
        )
        AuditRepo(self.db).add(actor, f"suggestion.{decision}", "suggestion", str(suggestion.id),
                               {"decision": decision}, patient_id=suggestion.patient_id)
        self.db.commit()
        return record
