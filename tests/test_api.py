"""End-to-end tests of the REST API, with the fake model and a temporary database."""

import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

PATIENT_P001 = "P001"


def _new_patient(client, clinician, **overrides):
    body = {"name": "Test Patient (synthetic)", "sex": "M", "age": 50, "height_cm": 178, "allergies": []}
    body.update(overrides)
    response = client.post("/api/v1/patients", json=body, headers=clinician)
    assert response.status_code == 201, response.text
    return response.json()


def _intake(**overrides):
    body = {
        "chief_complaint": "Heartburn after meals for 4 weeks.",
        "symptoms": "Burning chest discomfort; no alarm symptoms.",
        "conditions": ["Heartburn (symptomatic nonerosive GERD)"],
        "medications": [],
        "allergies": [],
        "weight_kg": 80,
        "serum_creatinine_mg_dl": 1.0,
        "creatinine_date": date.today().isoformat(),
        "on_dialysis": False,
        "notes": "",
    }
    body.update(overrides)
    return body


# ---------- auth and roles ----------

def test_token_login_returns_bearer_token(client):
    response = client.post("/api/v1/auth/token", data={"username": "dr.evans", "password": "pw-clinician"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json() == {"username": "dr.evans", "role": "clinician"}


def test_wrong_password_is_401_with_error_body(client):
    response = client.post("/api/v1/auth/token", data={"username": "dr.evans", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_no_token_is_401(client):
    response = client.get("/api/v1/patients")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_invalid_token_is_401(client):
    response = client.get("/api/v1/patients", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_pharmacist_cannot_create_a_patient(client, pharmacist):
    response = client.post("/api/v1/patients", headers=pharmacist,
                           json={"name": "X", "sex": "F", "age": 40, "allergies": []})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_clinician_cannot_read_audit(client, clinician):
    assert client.get("/api/v1/audit", headers=clinician).status_code == 403


def test_admin_cannot_ask_about_doses(client, admin):
    response = client.post("/api/v1/suggestions", headers=admin,
                           json={"patient_id": PATIENT_P001, "question": "Is metformin OK?"})
    assert response.status_code == 403


def test_reindex_is_admin_only(client, clinician, admin):
    assert client.post("/api/v1/admin/reindex", headers=clinician).status_code == 403
    response = client.post("/api/v1/admin/reindex", headers=admin)
    assert response.status_code == 202


# ---------- error body, request id, health, docs ----------

def test_error_body_shape_and_request_id(client, clinician):
    response = client.get("/api/v1/patients/P999", headers=clinician)
    assert response.status_code == 404
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_incoming_request_id_is_honoured(client, clinician):
    response = client.get("/api/v1/patients", headers={**clinician, "X-Request-ID": "abcdef1234567890"})
    assert response.headers["X-Request-ID"] == "abcdef1234567890"


def test_validation_errors_use_the_standard_body(client, clinician):
    response = client.post("/api/v1/patients", headers=clinician, json={"name": "", "sex": "X", "age": -1})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["errors"]


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "ok", "checks": {}}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] is True


def test_openapi_has_examples_and_versioned_routes(client):
    spec = client.get("/openapi.json").json()
    assert any(path.startswith("/api/v1/") for path in spec["paths"])
    assert "examples" in json.dumps(spec["components"]["schemas"]) or "example" in json.dumps(spec["components"]["schemas"])
    assert client.get("/docs").status_code == 200


# ---------- patients, paging, kidney values ----------

def test_patients_list_is_paged_and_worst_kidney_function_first(client, clinician):
    response = client.get("/api/v1/patients?limit=5&offset=0", headers=clinician)
    body = response.json()
    assert body["total"] == 30
    assert body["limit"] == 5 and body["offset"] == 0
    assert len(body["items"]) == 5
    egfrs = [item["egfr"] for item in body["items"] if item["egfr"] is not None]
    assert egfrs == sorted(egfrs)


def test_patient_search_by_name(client, clinician):
    body = client.get("/api/v1/patients?q=Maria%20Lopez", headers=clinician).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == PATIENT_P001


def test_p001_shows_milestone_two_kidney_values(client, clinician):
    body = client.get(f"/api/v1/patients/{PATIENT_P001}", headers=clinician).json()
    assert body["kidney"]["egfr"] == 26.1
    assert body["kidney"]["crcl"] == 24.1
    assert body["kidney"]["ckd_stage"] == "G4"
    assert body["latest_intake"]["egfr"] == 26.1


def test_create_patient_returns_201_with_location(client, clinician):
    response = client.post("/api/v1/patients", headers=clinician,
                           json={"name": "New Patient (synthetic)", "sex": "F", "age": 61, "allergies": ["penicillin"]})
    assert response.status_code == 201
    assert response.headers["Location"] == f"/api/v1/patients/{response.json()['id']}"
    assert response.json()["egfr"] is None


# ---------- intakes and the RAG store ----------

def test_intake_computes_kidney_values_and_is_retrieved_immediately(client, clinician):
    patient = _new_patient(client, clinician)
    response = client.post(f"/api/v1/patients/{patient['id']}/intakes", headers=clinician, json=_intake())
    assert response.status_code == 201
    intake = response.json()
    assert intake["egfr"] is not None and intake["crcl"] is not None
    assert intake["ckd_stage"] == "G1" or intake["ckd_stage"] == "G2"

    answer = client.post("/api/v1/suggestions", headers=clinician, json={
        "patient_id": patient["id"],
        "question": "Starting famotidine 20 mg twice daily for heartburn. What is the right dose here?",
    })
    assert answer.status_code == 201
    sources = answer.json()["sources"]
    assert any(s["label"].startswith("Visit intake") for s in sources)


def test_intake_list_is_newest_first(client, clinician):
    patient = _new_patient(client, clinician)
    for complaint in ("First visit", "Second visit"):
        client.post(f"/api/v1/patients/{patient['id']}/intakes", headers=clinician, json=_intake(chief_complaint=complaint))
    body = client.get(f"/api/v1/patients/{patient['id']}/intakes", headers=clinician).json()
    assert body["total"] == 2
    assert body["items"][0]["chief_complaint"] == "Second visit"


def test_intake_accepts_an_empty_form_for_a_name_only_patient(client, clinician):
    created = client.post("/api/v1/patients", headers=clinician, json={"name": "Only A Name"})
    assert created.status_code == 201
    assert created.json()["age"] is None and created.json()["sex"] is None
    pid = created.json()["id"]
    response = client.post(f"/api/v1/patients/{pid}/intakes", headers=clinician, json={})
    assert response.status_code == 201
    intake = response.json()
    assert intake["egfr"] is None and intake["crcl"] is None
    assert "missing_creatinine" in intake["flags"]
    detail = client.get(f"/api/v1/patients/{pid}", headers=clinician).json()
    assert detail["name"] == "Only A Name"


def test_creatinine_without_age_or_sex_cannot_be_calculated_and_dosing_asks_for_it(client, clinician):
    pid = client.post("/api/v1/patients", headers=clinician, json={"name": "No Age"}).json()["id"]
    intake = client.post(f"/api/v1/patients/{pid}/intakes", headers=clinician,
                         json={"serum_creatinine_mg_dl": 1.0, "weight_kg": 70}).json()
    assert intake["egfr"] is None
    assert "missing_age_or_sex" in intake["flags"]
    answer = client.post("/api/v1/chat", headers=clinician, json={"patient_id": pid, "message": "Check metformin"}).json()
    assert answer["kind"] == "dosing"
    assert answer["suggestion"]["final_output"]["action"] == "insufficient_information"


def test_intake_with_old_creatinine_is_flagged_stale(client, clinician):
    patient = _new_patient(client, clinician)
    old = (date.today() - timedelta(days=120)).isoformat()
    response = client.post(f"/api/v1/patients/{patient['id']}/intakes", headers=clinician,
                           json=_intake(creatinine_date=old))
    assert "stale_lab" in response.json()["flags"]


# ---------- uploads ----------

def test_upload_and_delete_a_note(client, clinician, app):
    upload = client.post(
        f"/api/v1/patients/{PATIENT_P001}/documents",
        headers=clinician,
        files={"file": ("discharge-note.txt", b"Patient reports better appetite. Labs repeated at clinic.", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    document = upload.json()
    assert document["chunk_count"] >= 1
    assert upload.headers["Location"] == f"/api/v1/documents/{document['id']}"

    patient = client.get(f"/api/v1/patients/{PATIENT_P001}", headers=clinician).json()
    assert any(d["id"] == document["id"] for d in patient["documents"])

    deleted = client.delete(f"/api/v1/documents/{document['id']}", headers=clinician)
    assert deleted.status_code == 204
    patient = client.get(f"/api/v1/patients/{PATIENT_P001}", headers=clinician).json()
    assert all(d["id"] != document["id"] for d in patient["documents"])


def test_upload_rejects_unsupported_types_and_large_files(client, clinician, settings):
    bad_type = client.post(f"/api/v1/patients/{PATIENT_P001}/documents", headers=clinician,
                           files={"file": ("photo.png", b"\x89PNG", "image/png")})
    assert bad_type.status_code == 422
    assert bad_type.json()["error"]["code"] == "unsupported_file_type"

    too_big = client.post(f"/api/v1/patients/{PATIENT_P001}/documents", headers=clinician,
                          files={"file": ("big.txt", b"a" * (settings.max_upload_bytes + 10), "text/plain")})
    assert too_big.status_code == 422
    assert too_big.json()["error"]["code"] == "file_too_large"


def test_pharmacist_can_upload_but_admin_cannot(client, pharmacist, admin):
    files = {"file": ("note.md", b"# Note\nStable on current regimen.", "text/markdown")}
    assert client.post(f"/api/v1/patients/{PATIENT_P001}/documents", headers=pharmacist, files=files).status_code == 201
    assert client.post(f"/api/v1/patients/{PATIENT_P001}/documents", headers=admin, files=files).status_code == 403


# ---------- suggestions ----------

def test_p001_metformin_is_avoid_with_label_and_intake_citations(client, clinician):
    response = client.post("/api/v1/suggestions", headers=clinician,
                           json={"patient_id": PATIENT_P001, "question": "Is metformin 1000 mg twice daily still OK?"})
    assert response.status_code == 201
    suggestion = response.json()
    final = suggestion["final_output"]
    assert final["action"] == "avoid"
    cited = {c["chunk_id"] for c in final["citations"]}
    assert "LBL-metformin-04" in cited
    retrieved = {s["chunk_id"] for s in suggestion["sources"]}
    assert cited <= retrieved
    assert suggestion["status"] == "ok"
    assert response.headers["Location"] == f"/api/v1/suggestions/{suggestion['id']}"


def test_p001_gabapentin_adjusts_to_200_mg_once_daily(client, clinician):
    response = client.post("/api/v1/suggestions", headers=clinician,
                           json={"patient_id": PATIENT_P001,
                                 "question": "I'd like to start gabapentin 300 mg three times daily. What dose fits this patient's kidneys?"})
    final = response.json()["final_output"]
    assert final["action"] == "adjust_dose"
    assert final["recommended_dose"] == "200 mg once daily"


def test_unknown_drug_is_refused_without_calling_the_model(client, clinician, llm):
    llm.calls.clear()
    response = client.post("/api/v1/suggestions", headers=clinician,
                           json={"patient_id": PATIENT_P001, "question": "What apixaban dose should this patient take?"})
    suggestion = response.json()
    assert suggestion["drug"] is None
    assert suggestion["final_output"]["action"] == "insufficient_information"
    assert suggestion["final_output"]["rationale"] == "This drug is not in RxD's approved sources."
    assert llm.calls == []


def test_suggestion_needs_an_intake_first(client, clinician):
    patient = _new_patient(client, clinician)
    response = client.post("/api/v1/suggestions", headers=clinician,
                           json={"patient_id": patient["id"], "question": "Can I give metformin?"})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Record a visit intake first."


def test_demo_famotidine_continue_for_a_new_patient(client, clinician):
    patient = _new_patient(client, clinician, sex="M", age=50)
    client.post(f"/api/v1/patients/{patient['id']}/intakes", headers=clinician, json=_intake())
    response = client.post("/api/v1/suggestions", headers=clinician, json={
        "patient_id": patient["id"],
        "question": "Starting famotidine 20 mg twice daily for heartburn. What is the right dose?",
    })
    final = response.json()["final_output"]
    assert final["action"] == "continue"
    assert final["recommended_dose"] == "20 mg twice daily, up to 6 weeks"


def test_suggestion_history_is_paged_newest_first(client, clinician):
    for _ in range(3):
        client.post("/api/v1/suggestions", headers=clinician,
                    json={"patient_id": PATIENT_P001, "question": "Check metformin for this patient."})
    body = client.get(f"/api/v1/patients/{PATIENT_P001}/suggestions?limit=2", headers=clinician).json()
    assert body["total"] >= 3
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] > body["items"][1]["id"]


def test_decision_flow(client, clinician):
    suggestion = client.post("/api/v1/suggestions", headers=clinician,
                             json={"patient_id": PATIENT_P001, "question": "Is metformin 1000 mg twice daily still OK?"}).json()
    url = f"/api/v1/suggestions/{suggestion['id']}/decision"

    assert client.post(url, headers=clinician, json={"decision": "reject"}).status_code == 422
    assert client.post(url, headers=clinician, json={"decision": "edit"}).status_code == 422

    accepted = client.post(url, headers=clinician, json={"decision": "accept"})
    assert accepted.status_code == 201
    assert accepted.json()["decided_by"] == "dr.evans"

    again = client.post(url, headers=clinician, json={"decision": "accept"})
    assert again.status_code == 409


def test_pharmacist_cannot_record_a_decision(client, clinician, pharmacist):
    suggestion = client.post("/api/v1/suggestions", headers=clinician,
                             json={"patient_id": PATIENT_P001, "question": "Is metformin OK?"}).json()
    response = client.post(f"/api/v1/suggestions/{suggestion['id']}/decision", headers=pharmacist,
                           json={"decision": "accept"})
    assert response.status_code == 403


# ---------- rules and audit ----------

def test_rules_are_visible_to_pharmacists_with_verification_status(client, pharmacist):
    items = client.get("/api/v1/rules", headers=pharmacist).json()["items"]
    assert {item["drug"] for item in items} == {
        "metformin", "sitagliptin", "gabapentin", "nitrofurantoin", "levofloxacin", "famotidine"}
    assert all(item["verified"] is False for item in items)


def test_audit_records_actions_without_patient_names(client, clinician, pharmacist):
    client.post("/api/v1/suggestions", headers=clinician,
                json={"patient_id": PATIENT_P001, "question": "Is metformin OK?"})
    body = client.get(f"/api/v1/audit?patient_id={PATIENT_P001}", headers=pharmacist).json()
    actions = {event["action"] for event in body["items"]}
    assert "suggestion.create" in actions
    assert all("Maria" not in json.dumps(event["details"]) for event in body["items"])


# ---------- chat about the selected patient ----------

def test_chat_answers_from_the_saved_record_without_naming_the_patient(client, clinician, llm):
    llm.replies = ["Her eGFR is 26.1, stage G4. [PT-P001-intake-1]"]
    response = client.post("/api/v1/chat", headers=clinician,
                           json={"patient_id": PATIENT_P001, "message": "What is her kidney function?"})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "record"
    assert "26.1" in body["answer"]
    assert any(s["chunk_id"] == "PT-P001-intake-1" for s in body["sources"])
    # the model was given the selected patient's record, not another patient's
    sent = llm.calls[-1][-1]["content"]
    assert "Maria Lopez" in sent and "PT-P001-intake-1" in sent


def test_chat_drops_citations_that_were_not_retrieved(client, clinician, llm):
    llm.replies = ["Allergic to penicillin. [PT-P001-intake-1] [PT-P999-intake-9]"]
    body = client.post("/api/v1/chat", headers=clinician,
                       json={"patient_id": PATIENT_P001, "message": "Any allergies?"}).json()
    assert "PT-P999" not in body["answer"] and "PT-P001-intake-1" in body["answer"]


def test_chat_only_retrieves_the_selected_patients_record(client, clinician, llm):
    client.post("/api/v1/chat", headers=clinician, json={"patient_id": PATIENT_P001, "message": "Summarize"})
    sent = llm.calls[-1][-1]["content"]
    assert "PT-P002" not in sent and "PT-P003" not in sent


def test_chat_with_a_drug_name_uses_the_dosing_pipeline(client, clinician):
    body = client.post("/api/v1/chat", headers=clinician,
                       json={"patient_id": PATIENT_P001, "message": "Is metformin 1000 mg twice daily still OK?"}).json()
    assert body["kind"] == "dosing"
    assert body["suggestion"]["final_output"]["action"] == "avoid"


def test_chat_asks_for_a_drug_name_when_the_question_is_about_dose_only(client, clinician, llm):
    llm.calls.clear()
    body = client.post("/api/v1/chat", headers=clinician,
                       json={"patient_id": PATIENT_P001, "message": "What dose should she take?"}).json()
    assert body["kind"] == "info" and "Name one of those drugs" in body["answer"]
    assert llm.calls == []


def test_chat_with_no_saved_intake_says_so(client, clinician):
    pid = client.post("/api/v1/patients", headers=clinician, json={"name": "Empty Chart"}).json()["id"]
    body = client.post("/api/v1/chat", headers=clinician, json={"patient_id": pid, "message": "Summarize"}).json()
    assert body["kind"] == "info" and "nothing saved" in body["answer"]


def test_chat_shows_the_record_when_the_model_is_offline(client, clinician, llm):
    llm.unavailable = True
    body = client.post("/api/v1/chat", headers=clinician,
                       json={"patient_id": PATIENT_P001, "message": "What medications is she on?"}).json()
    assert body["kind"] == "record" and body["offline"] is True
    assert "metformin" in body["answer"]


def test_chat_is_not_open_to_admins_or_anonymous_users(client, admin):
    assert client.post("/api/v1/chat", headers=admin, json={"patient_id": PATIENT_P001, "message": "hi"}).status_code == 403
    assert client.post("/api/v1/chat", json={"patient_id": PATIENT_P001, "message": "hi"}).status_code == 401


def test_chat_for_an_unknown_patient_is_404(client, clinician):
    assert client.post("/api/v1/chat", headers=clinician, json={"patient_id": "P999", "message": "hi"}).status_code == 404


# ---------- the single web screen ----------

def test_login_page_shows_the_banner_and_demo_accounts(client):
    page = client.get("/login")
    assert page.status_code == 200
    assert "Prototype · synthetic data · not for clinical use." in page.text
    assert "dr.evans" in page.text and "rph.aniket" in page.text and "admin.sanoj" in page.text


def test_web_login_sets_an_http_only_cookie_and_shows_the_single_screen(client):
    response = client.post("/login", data={"username": "dr.evans", "password": "pw-clinician"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert "httponly" in response.headers["set-cookie"].lower()
    page = client.get("/")
    assert page.status_code == 200
    assert "Patient intake" in page.text and "Assistant" in page.text
    assert "Prototype · synthetic data" in page.text


def test_the_screen_redirects_to_login_without_a_session(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/login"


def test_only_the_login_and_the_single_screen_exist_as_pages(client):
    client.post("/login", data={"username": "dr.evans", "password": "pw-clinician"})
    for gone in ("/patients", "/rules", "/audit", "/patients/P001"):
        assert client.get(gone).status_code == 404


def test_static_assets_are_served(client: TestClient):
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def _record_section(prompt: str) -> str:
    """The retrieved record text in a chat prompt, without the question."""
    return prompt.split("RECORD:")[1].split("QUESTION:")[0]


def test_attached_note_is_used_only_for_its_own_patient(client, clinician, llm):
    note = b"Social history: the patient keeps pet zebrafinches and works as a lighthouse keeper."
    up = client.post(f"/api/v1/patients/{PATIENT_P001}/documents", headers=clinician,
                     files={"file": ("social.txt", note, "text/plain")})
    assert up.status_code == 201

    llm.replies = ["ok", "ok"]
    own = client.post("/api/v1/chat", headers=clinician,
                      json={"patient_id": PATIENT_P001, "message": "Does she have pets or a job to know about? lighthouse zebrafinches"}).json()
    assert any("lighthouse" in s["text"] for s in own["sources"])
    assert "lighthouse" in _record_section(llm.calls[-1][-1]["content"])

    other = client.post("/api/v1/chat", headers=clinician,
                        json={"patient_id": "P002", "message": "Does he have pets or a job to know about? lighthouse zebrafinches"}).json()
    assert all("lighthouse" not in s["text"] for s in other["sources"])
    assert "lighthouse" not in _record_section(llm.calls[-1][-1]["content"])

    doc_id = client.get(f"/api/v1/patients/{PATIENT_P001}", headers=clinician).json()["documents"][0]["id"]
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=clinician).status_code == 204
    llm.replies = ["ok"]
    after = client.post("/api/v1/chat", headers=clinician,
                        json={"patient_id": PATIENT_P001, "message": "lighthouse zebrafinches"}).json()
    assert all("lighthouse" not in s["text"] for s in after["sources"])
