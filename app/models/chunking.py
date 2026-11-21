"""Turns intakes and uploaded notes into retrievable text chunks."""

import io

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
UPLOAD_CHUNK_CHARS = 800
UPLOAD_OVERLAP_CHARS = 120


def intake_chunk_id(patient_id: str, intake_id: int) -> str:
    return f"PT-{patient_id}-intake-{intake_id}"


def document_chunk_id(patient_id: str, document_id: int, n: int) -> str:
    return f"PT-{patient_id}-doc-{document_id}-{n}"


def format_medications(medications: list[dict]) -> str:
    parts = []
    for med in medications:
        text = " ".join(str(med.get(key) or "") for key in ("name", "dose", "frequency")).strip()
        if text:
            parts.append(" ".join(text.split()))
    return ", ".join(parts) if parts else "none recorded"


def intake_text(
    *,
    visit_date,
    patient_name: str,
    age: int,
    sex: str,
    chief_complaint: str,
    symptoms: str,
    history: str,
    conditions: list[str],
    medications: list[dict],
    allergies: list[str],
    weight_kg: float | None,
    scr: float | None,
    creatinine_date,
    on_dialysis: bool,
    notes: str,
) -> str:
    sex_word = {"F": "female", "M": "male"}.get(sex or "", "")
    who = " ".join(x for x in (str(age) if age is not None else "", sex_word) if x)
    weight = f"{weight_kg:g} kg" if weight_kg is not None else "not recorded"
    if scr is not None:
        scr_txt = f"Serum creatinine {scr:g} mg/dL on {creatinine_date}"
    else:
        scr_txt = "Serum creatinine not recorded"
    return (
        f"Visit intake {visit_date} for {patient_name}" + (f", {who}" if who else "") + ". "
        f"Chief complaint: {chief_complaint or 'not recorded'}. Symptoms: {symptoms or 'none recorded'}.\n"
        f"History: {history or 'none recorded'}. Conditions: {', '.join(conditions) or 'none recorded'}. "
        f"Current medications: {format_medications(medications)}. "
        f"Allergies: {', '.join(allergies) or 'none known'}.\n"
        f"Weight: {weight}. {scr_txt}. Dialysis: {'yes' if on_dialysis else 'no'}. Notes: {notes or 'none'}"
    )


def chunk_text(text: str, size: int = UPLOAD_CHUNK_CHARS, overlap: int = UPLOAD_OVERLAP_CHARS) -> list[str]:
    normalised = " ".join(text.split())
    if not normalised:
        return []
    step = size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(normalised):
        chunks.append(normalised[start:start + size])
        if start + size >= len(normalised):
            break
        start += step
    return chunks


def extract_text(extension: str, data: bytes) -> str:
    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if extension == ".docx":
        import docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    return data.decode("utf-8", errors="replace")
