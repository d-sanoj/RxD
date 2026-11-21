"""Chat about the selected patient. The patient is chosen in the UI, so the message never has to name them.

- A message that names a supported drug goes to the dosing pipeline (rules decide, the model explains).
- Anything else is answered from the patient's saved record, retrieved with the same hybrid search.
- If the model is down, the reply shows the retrieved record text instead of failing.
"""

import logging
import re
from dataclasses import asdict
from datetime import date
from time import perf_counter

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.logging import log_event
from app.models.chunking import format_medications, intake_chunk_id
from app.models.container import Container
from app.models.kidney import assess
from app.models.llm import ModelUnavailable
from app.models.prompts import kidney_block
from app.models.repositories import AuditRepo, IntakeRepo, PatientRepo
from app.models.retrieval import SourceChunk, retrieve_patient
from app.models.router import DRUG_TERMS, find_drug
from app.models.rxd_service import RxdService

logger = logging.getLogger("rxd.chat")

NO_RECORD = "There is nothing saved for this patient yet. Fill in the intake form and save it, then ask again."
NAME_A_DRUG = ("I can check kidney-safe doses for " + ", ".join(DRUG_TERMS) + ". "
               "Name one of those drugs in your question and I will check it against this patient's kidney function.")
_DOSE_WORDS = re.compile(r"\b(dose|doses|dosing|dosage|how much|mg)\b", re.IGNORECASE)
_CITATION = re.compile(r"\[(PT-[A-Za-z0-9._-]+)\]")

RECORD_SYSTEM = (
    "You are RxD, an assistant for clinicians. Answer ONLY from the KIDNEY line and the RECORD excerpts you are given. "
    "If the answer is not there, say you cannot find it in the saved record. Never suggest a drug dose; if asked about "
    "dosing, tell the clinician to name the drug. Be brief and plain (under 120 words). "
    "Cite the excerpt you used like [PT-P001-intake-1]. Never invent patient details, lab values or sources."
)


class ChatService:
    def __init__(self, db: Session, container: Container) -> None:
        self.db = db
        self.c = container

    def reply(self, *, patient_id: str, message: str, history: list[dict], actor: str) -> dict:
        started = perf_counter()
        patient = PatientRepo(self.db).get(patient_id)
        if patient is None:
            raise NotFoundError("Patient not found.")
        intake = IntakeRepo(self.db).latest(patient_id)

        if intake is None:
            return self._info(NO_RECORD, started)

        if find_drug(message):
            suggestion = RxdService(self.db, self.c).create_suggestion(
                patient_id=patient_id, question=message, actor=actor)
            return {
                "kind": "dosing",
                "answer": suggestion.final_output["rationale"],
                "sources": suggestion.sources,
                "suggestion": suggestion,
                "offline": suggestion.status == "fallback",
                "model_name": suggestion.model_name,
                "latency_ms": suggestion.latency_ms,
            }

        if _DOSE_WORDS.search(message):
            return self._info(NAME_A_DRUG, started)

        today = date.today()
        kidney = assess(age=patient.age, sex=patient.sex, weight_kg=intake.weight_kg,
                        scr=intake.serum_creatinine_mg_dl, creatinine_date=intake.creatinine_date,
                        on_dialysis=intake.on_dialysis, today=today)
        sources = retrieve_patient(self.db, self.c.vector, patient.id, f"{message} {intake.chief_complaint}",
                                   intake_chunk_id(patient.id, intake.id)).sources
        kidney_text = kidney_block(
            crcl=kidney.crcl, egfr=kidney.egfr, stage=kidney.ckd_stage, scr=intake.serum_creatinine_mg_dl,
            creatinine_date=intake.creatinine_date.isoformat() if intake.creatinine_date else None,
            lab_age_days=kidney.lab_age_days, dialysis=intake.on_dialysis, flags=kidney.flags)

        offline = False
        try:
            answer = self._ask_model(message, history, kidney_text, sources, patient.name)
        except ModelUnavailable:
            log_event(logger, "chat_model_unavailable", level=logging.WARNING)
            answer, offline = None, True
        if not answer:
            offline = True
            answer = self._extract(intake, kidney, sources)
        else:
            answer = self._drop_unknown_citations(answer, sources)

        AuditRepo(self.db).add(actor, "chat.ask", "patient", patient.id, {"kind": "record", "offline": offline},
                               patient_id=patient.id)
        self.db.commit()
        return {
            "kind": "record",
            "answer": answer,
            "sources": [asdict(s) for s in sources],
            "suggestion": None,
            "offline": offline,
            "model_name": self.c.llm.model_name,
            "latency_ms": int(round((perf_counter() - started) * 1000)),
        }

    def _info(self, text: str, started: float) -> dict:
        return {"kind": "info", "answer": text, "sources": [], "suggestion": None, "offline": False,
                "model_name": None, "latency_ms": int(round((perf_counter() - started) * 1000))}

    def _ask_model(self, message: str, history: list[dict], kidney_text: str,
                   sources: list[SourceChunk], patient_name: str) -> str:
        record = "\n".join(f"[{s.chunk_id}] ({s.label}) {s.text}" for s in sources)
        messages = [{"role": "system", "content": RECORD_SYSTEM}]
        messages += [{"role": t["role"], "content": t["content"][:800]} for t in history[-4:]]
        messages.append({
            "role": "user",
            "content": f"PATIENT: {patient_name}\nKIDNEY:\n{kidney_text}\n\nRECORD:\n{record}\n\nQUESTION:\n{message}",
        })
        return self.c.llm.chat(messages, None).strip()

    @staticmethod
    def _extract(intake, kidney, sources: list[SourceChunk]) -> str:
        """A readable summary of the saved record, used when the language model is offline."""
        lines = ["The language model is offline, so here is the saved record:"]
        if kidney.egfr is not None:
            crcl = kidney.crcl if kidney.crcl is not None else "not calculable"
            lines.append(f"• Kidney function: eGFR {kidney.egfr} ({kidney.ckd_stage}), CrCl {crcl}")
        elif kidney.flags:
            lines.append("• Kidney function: not calculable (" + ", ".join(f.replace("_", " ") for f in kidney.flags) + ")")
        lines.append(f"• Visit: {intake.chief_complaint or 'not recorded'}")
        lines.append(f"• Conditions: {', '.join(intake.conditions or []) or 'none recorded'}")
        lines.append(f"• Medications: {format_medications(list(intake.medications or []))}")
        lines.append(f"• Allergies: {', '.join(intake.allergies or []) or 'none known'}")
        if intake.weight_kg is not None:
            lines.append(f"• Weight: {intake.weight_kg:g} kg")
        if intake.serum_creatinine_mg_dl is not None:
            lines.append(f"• Creatinine: {intake.serum_creatinine_mg_dl:g} mg/dL on {intake.creatinine_date}")
        for s in sources:
            if s.label.startswith("Uploaded note"):
                lines.append(f"• {s.label}: {s.text[:300]}")
        return "\n".join(lines)

    @staticmethod
    def _drop_unknown_citations(answer: str, sources: list[SourceChunk]) -> str:
        known = {s.chunk_id for s in sources}
        return _CITATION.sub(lambda m: m.group(0) if m.group(1) in known else "", answer).strip()
