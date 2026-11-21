/* RxD UI: one screen. Pick a patient, fill the intake, chat. Everything goes through the REST API under /api/v1
   (the signed-in cookie is sent automatically). Server text is written with textContent, never innerHTML. */
(() => {
  "use strict";

  const VERDICT = {
    continue: ["✓", "Continue"], adjust_dose: ["↓", "Adjust dose"], caution: ["!", "Caution"],
    avoid: ["✕", "Avoid"], insufficient_information: ["?", "Need more information"],
  };
  const STATUS = {
    ok: ["✓", "Ready to review"], needs_review: ["!", "Needs review"],
    fallback: ["i", "Answered from the rules only (model offline)"], blocked: ["✕", "Blocked"],
  };
  const DRUGS = ["metformin", "sitagliptin", "gabapentin", "nitrofurantoin", "levofloxacin", "famotidine"];
  const GENERAL = ["Summarize this patient", "What is their kidney function?", "What medications are they on?"];

  const $ = (s, r = document) => r.querySelector(s);
  const role = document.body.dataset.role;
  const cap = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : "");
  const when = (iso) => (iso ? new Date(iso + "Z").toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");

  function h(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  async function request(method, path, body, isForm) {
    const opts = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    const res = await fetch(path, opts);
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Signed out."); }
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (_) { /* no body */ }
      throw new Error((data && data.error && data.error.message) || `Something went wrong (${res.status}).`);
    }
    return res.status === 204 ? null : res.json();
  }
  const api = (m, p, b) => request(m, p, b, false);

  function toast(message, error) {
    const item = h("div", { class: "toast" + (error ? " error" : "") }, message);
    $("#toasts").append(item);
    setTimeout(() => item.remove(), 4200);
  }

  // Same formulas as app/models/kidney.py. A preview only: the saved value is the official one.
  function preview(age, sex, weight, scr) {
    if (!(scr > 0) || !(age >= 0) || !["F", "M"].includes(sex)) return null;
    const f = sex === "F";
    const kappa = f ? 0.7 : 0.9, alpha = f ? -0.241 : -0.302;
    let e = 142 * Math.pow(Math.min(scr / kappa, 1), alpha) * Math.pow(Math.max(scr / kappa, 1), -1.2) * Math.pow(0.9938, age);
    if (f) e *= 1.012;
    e = Math.round(e * 10) / 10;
    let c = null;
    if (weight > 0) { c = ((140 - age) * weight) / (72 * scr); if (f) c *= 0.85; c = Math.round(c * 10) / 10; }
    const stage = e >= 90 ? "G1" : e >= 60 ? "G2" : e >= 45 ? "G3a" : e >= 30 ? "G3b" : e >= 15 ? "G4" : "G5";
    return { egfr: e, crcl: c, stage };
  }

  // ---------- sign in ----------
  function initLogin() {
    document.querySelectorAll("[data-fill-user]").forEach((b) => b.addEventListener("click", () => {
      $("#username").value = b.dataset.fillUser;
      $("#password").value = b.dataset.fillPass || "";
      $("#password").focus();
    }));
  }

  // ---------- the screen ----------
  const state = { patients: [], selected: "", detail: null, threads: {} };
  const form = () => $("#intake-form");
  const canWrite = role === "clinician";
  const canChat = role === "clinician" || role === "pharmacist";

  async function loadPatients(keep) {
    const page = await api("GET", "/api/v1/patients?limit=100");
    state.patients = page.items.sort((a, b) => a.name.localeCompare(b.name));
    const sel = $("#patient");
    const options = state.patients.map((p) => h("option", { value: p.id }, p.name.replace(" (synthetic)", ""), p.egfr !== null ? `  ·  eGFR ${p.egfr}` : ""));
    if (canWrite) options.unshift(h("option", { value: "" }, "➕ New patient"));
    sel.replaceChildren(...options);
    sel.value = keep !== undefined ? keep : state.selected;
  }

  async function choose(id) {
    state.selected = id;
    $("#patient").value = id;
    if (!id) { state.detail = null; fillForm(null); renderKidney(null); renderChat(); renderNotes(); return; }
    state.detail = await api("GET", `/api/v1/patients/${id}`);
    fillForm(state.detail);
    renderKidney(state.detail);
    renderChat();
    renderNotes();
  }

  function renderKidney(d) {
    const box = $("#kidney-strip");
    if (!d || !d.kidney) { box.replaceChildren(d ? h("span", { class: "pill" }, "No intake saved yet") : null); return; }
    const k = d.kidney;
    const pills = [];
    if (k.egfr !== null) pills.push(h("span", { class: `pill big s-${(k.ckd_stage || "").toLowerCase()}` }, `eGFR ${k.egfr} · ${k.ckd_stage}`));
    pills.push(h("span", { class: "pill big" }, `CrCl ${k.crcl ?? "—"}`));
    (k.flags || []).forEach((f) => pills.push(h("span", { class: "pill warn" }, f.replace(/_/g, " "))));
    box.replaceChildren(...pills);
  }

  // ----- intake form -----
  function fillForm(d) {
    const f = form();
    f.reset();
    $("#intake-err").hidden = true;
    const existing = !!d;
    for (const n of ["name", "age", "sex"]) f[n].disabled = existing;
    $("#save").textContent = existing ? "Save as a new visit" : "Save patient and intake";
    $("#intake-help").textContent = existing
      ? "Update what changed and save. It becomes a new visit and is added to the assistant's knowledge."
      : "Only the name is required. Saving adds everything to the assistant's knowledge.";
    if (existing) {
      f.name.value = d.name; f.age.value = d.age ?? ""; f.sex.value = d.sex || "";
      const i = d.latest_intake;
      if (i) {
        f.conditions.value = i.conditions.join(", ");
        f.medications.value = i.medications.map((m) => [m.name, m.dose, m.frequency].filter(Boolean).join(" ")).join("\n");
        f.allergies.value = i.allergies.join(", ");
        f.weight_kg.value = i.weight_kg ?? ""; f.serum_creatinine_mg_dl.value = i.serum_creatinine_mg_dl ?? "";
        f.creatinine_date.value = i.creatinine_date || ""; f.on_dialysis.checked = i.on_dialysis;
      } else f.allergies.value = (d.allergies || []).join(", ");
    }
    updatePreview();
  }

  function updatePreview() {
    const f = form();
    const age = f.age.value === "" ? NaN : Number(f.age.value);
    const r = preview(age, f.sex.value, Number(f.weight_kg.value), Number(f.serum_creatinine_mg_dl.value));
    $("#preview").textContent = r
      ? `Preview: eGFR ${r.egfr} · stage ${r.stage} · CrCl ${r.crcl ?? "needs a weight"}  (the saved value is the official one)`
      : "Enter age, sex and creatinine to see a kidney preview.";
  }

  const splitList = (t) => t.split(",").map((s) => s.trim()).filter(Boolean);
  function parseMed(line) {
    const m = line.trim().match(/^(.+?)\s+(\d[\d.]*\s*(?:mg|mcg|g|ml|units?))\s*(.*)$/i);
    return m ? { name: m[1].trim(), dose: m[2].trim(), frequency: m[3].trim() } : { name: line.trim(), dose: "", frequency: "" };
  }

  async function saveIntake(e) {
    e.preventDefault();
    const f = form(); const err = $("#intake-err"); err.hidden = true;
    const num = (n) => (f[n].value === "" ? null : Number(f[n].value));
    const intake = {
      chief_complaint: f.chief_complaint.value.trim(), symptoms: f.symptoms.value.trim(), history: f.history.value.trim(),
      conditions: splitList(f.conditions.value),
      medications: f.medications.value.split("\n").filter((l) => l.trim()).map(parseMed),
      allergies: splitList(f.allergies.value),
      weight_kg: num("weight_kg"), serum_creatinine_mg_dl: num("serum_creatinine_mg_dl"),
      creatinine_date: f.creatinine_date.value || null, on_dialysis: f.on_dialysis.checked, notes: f.notes.value.trim(),
    };
    $("#save").disabled = true;
    try {
      let id = state.selected;
      if (!id) {
        const name = f.name.value.trim();
        if (!name) { err.textContent = "Enter the patient's name."; err.hidden = false; f.name.focus(); return; }
        const created = await api("POST", "/api/v1/patients", { name, age: num("age"), sex: f.sex.value || null, allergies: intake.allergies });
        id = created.id;
      }
      await api("POST", `/api/v1/patients/${id}/intakes`, intake);
      toast("Saved. The assistant now knows this patient.");
      await loadPatients(id);
      await choose(id);
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
    finally { $("#save").disabled = false; }
  }

  // ----- notes -----
  function renderNotes() {
    const box = $("#notes-box"); const d = state.detail;
    box.hidden = !d || !canChat;
    if (!d) return;
    $("#docs").replaceChildren(...(d.documents.length ? d.documents.map((doc) => h("li", {},
      h("span", {}, doc.filename), h("span", { class: "sub small" }, `${doc.chunk_count} parts`),
      h("button", { class: "ghost small danger", type: "button", style: "margin-left:auto", onclick: async () => {
        try { await api("DELETE", `/api/v1/documents/${doc.id}`); toast("Note removed."); await choose(d.id); }
        catch (err) { toast(err.message, true); }
      } }, "Remove"))) : [h("li", { class: "sub" }, "No notes attached.")]));
  }

  // ----- chat -----
  const thread = () => state.threads[state.selected || ""] || (state.threads[state.selected || ""] = []);

  function renderChat() {
    const d = state.detail; const box = $("#thread");
    $("#chat-about").textContent = d ? `about ${d.name.replace(" (synthetic)", "")}` : "";
    const ready = !!d && canChat;
    $("#msg").disabled = !ready; $("#send").disabled = !ready;
    $("#msg").placeholder = ready ? "Ask about this patient…" : "Select a patient to chat";
    const q = $("#quick");
    q.replaceChildren(...(ready && d.latest_intake ? [...GENERAL, ...DRUGS.map((n) => `Check ${n}`)].map((t) => h("button", { type: "button", onclick: () => send(
      t.startsWith("Check ") ? `Can I give ${t.slice(6)}? What dose fits this patient?` : t) }, t)) : []));
    if (!d) { box.replaceChildren(bubble("bot", canWrite ? "Pick a patient above, or fill in the form and save a new one. Then ask me anything about them." : "Pick a patient above to start.")); return; }
    if (!canChat) { box.replaceChildren(bubble("bot", "Your role can review rules and the audit trail. Questions are asked by clinicians and pharmacists.")); return; }
    const msgs = thread();
    if (!msgs.length) {
      msgs.push({ role: "bot", text: d.latest_intake
        ? `Hi. I'm answering about ${d.name.replace(" (synthetic)", "")}, so you don't need to say who. Ask about their record or kidney function, or name a drug to check its dose.`
        : "There is nothing saved for this patient yet. Fill in the intake form and save it, then ask me anything." });
    }
    box.replaceChildren(...msgs.map(renderMessage));
    box.scrollTop = box.scrollHeight;
  }

  const bubble = (who, ...content) => h("div", { class: `bubble ${who}` }, ...content);

  function renderMessage(m) {
    if (m.role === "user") return bubble("user", m.text);
    if (m.reply && m.reply.kind === "dosing" && m.reply.suggestion) return h("div", { class: "bubble bot wide" }, resultCard(m.reply.suggestion));
    const kids = [h("div", { class: "text" }, m.text)];
    if (m.reply && m.reply.sources && m.reply.sources.length) {
      kids.push(h("details", { class: "sources" }, h("summary", {}, `Sources (${m.reply.sources.length})`),
        m.reply.sources.map((s) => h("details", {}, h("summary", {}, `${s.label} · ${s.chunk_id}`), h("p", {}, s.text)))));
    }
    return bubble("bot", ...kids);
  }

  async function send(text) {
    const d = state.detail;
    if (!d || !text.trim()) return;
    const msgs = thread();
    const history = msgs.filter((m) => m.text).slice(-6).map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.text.slice(0, 1500) }));
    msgs.push({ role: "user", text });
    $("#msg").value = "";
    renderChat();
    const box = $("#thread");
    const t0 = Date.now();
    const typing = bubble("bot", h("span", { class: "spin" }), "Thinking… ", h("span", { id: "secs" }, "0 s"));
    box.append(typing); box.scrollTop = box.scrollHeight;
    const timer = setInterval(() => { const s = $("#secs"); if (s) s.textContent = `${Math.floor((Date.now() - t0) / 1000)} s`; }, 500);
    try {
      const reply = await api("POST", "/api/v1/chat", { patient_id: d.id, message: text, history });
      msgs.push({ role: "bot", text: reply.answer, reply });
    } catch (err) {
      msgs.push({ role: "bot", text: `Sorry, that did not work: ${err.message}` });
    } finally { clearInterval(timer); }
    if (state.detail && state.detail.id === d.id) renderChat();
  }

  function resultCard(s) {
    const f = s.final_output; const a = f.action;
    const [ic, word] = VERDICT[a] || ["?", a];
    const [sIc, sWord] = STATUS[s.status] || STATUS.needs_review;
    const lines = [];
    if (f.recommended_dose) lines.push(`Dose: ${f.recommended_dose}`);
    if (f.max_daily_dose) lines.push(`Maximum: ${f.max_daily_dose}`);
    const decided = (s.decisions || []).slice(-1)[0];
    return h("article", { class: "result" },
      h("div", { class: `verdict v-${a}` }, h("span", { class: "ic", "aria-hidden": "true" }, ic),
        h("div", {}, h("h3", {}, `${cap(f.drug && f.drug !== "unknown" ? f.drug : "This drug")} · ${word}`),
          lines.length ? h("p", { class: "dose" }, lines.join(" · ")) : null)),
      h("div", { class: "body" },
        h("p", { class: `status st-${s.status}` }, h("span", { "aria-hidden": "true" }, sIc), sWord),
        h("p", {}, f.rationale),
        f.monitoring ? h("p", {}, h("strong", {}, "Monitoring: "), f.monitoring) : null,
        f.kidney_measure_used ? h("p", { class: "fine" }, `Based on ${f.kidney_measure_used}.`) : null,
        h("details", { class: "sources" }, h("summary", {}, `Sources (${s.sources.length})`),
          s.sources.map((src) => h("details", {}, h("summary", {}, `${src.label} · ${src.chunk_id}`), h("p", {}, src.text)))),
        h("p", { class: "fine" }, `Model ${s.model_name || "none"} · ${s.latency_ms} ms · #${s.id}`),
        decided ? h("div", { class: "decide" }, h("span", { class: "pill" }, `${cap(decided.decision)} by ${decided.decided_by}`))
          : role === "clinician" ? decideBox(s) : null));
  }

  function decideBox(s) {
    const box = h("div", { class: "decide" });
    const send2 = async (payload) => {
      try {
        const d = await api("POST", `/api/v1/suggestions/${s.id}/decision`, payload);
        box.replaceChildren(h("span", { class: "pill" }, `${cap(d.decision)} by ${d.decided_by}`)); toast("Saved.");
      } catch (err) { toast(err.message, true); }
    };
    const buttons = () => [
      h("button", { class: "primary small", type: "button", onclick: () => send2({ decision: "accept" }) }, "Accept"),
      h("button", { class: "small", type: "button", onclick: () => edit("edit") }, "Edit"),
      h("button", { class: "small danger", type: "button", onclick: () => edit("reject") }, "Reject"),
    ];
    const edit = (kind) => {
      const area = h("textarea", { rows: 2, placeholder: kind === "edit" ? "Write your edited suggestion" : "Why are you rejecting it?", style: "width:100%" });
      box.replaceChildren(h("div", { style: "width:100%" }, area,
        h("div", { style: "display:flex;gap:.5rem" },
          h("button", { class: "small", type: "button", onclick: () => box.replaceChildren(...buttons()) }, "Back"),
          h("button", { class: "small primary", type: "button", onclick: () => {
            const v = area.value.trim();
            if (!v) { toast(kind === "edit" ? "Write the edit first." : "A reason is required.", true); return; }
            send2(kind === "edit" ? { decision: "edit", edited_text: v } : { decision: "reject", reason: v });
          } }, "Save"))));
      area.focus();
    };
    box.append(...buttons());
    return box;
  }

  // ----- rules and audit pop-ups (pharmacist and admin) -----
  function initInfoDialogs() {
    const dlg = $("#dlg-info");
    dlg.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dlg.close()));
    const rules = $("#open-rules"), audit = $("#open-audit");
    if (rules) rules.addEventListener("click", async () => {
      try {
        const data = await api("GET", "/api/v1/rules");
        $("#info-title").textContent = "Dosing rules";
        $("#info-body").replaceChildren(...data.items.map((r) => h("details", {},
          h("summary", {}, cap(r.drug), " ", h("span", { class: "tag " + (r.verified ? "yes" : "no") }, r.verified ? `✓ Verified by ${r.verified_by}` : "! Not yet verified by a pharmacist")),
          h("p", {}, `${r.product} · measured by ${r.measure}`),
          h("ul", {}, r.chunks.map((c) => h("li", {}, h("code", {}, c.chunk_id), " ", c.text))))));
        dlg.showModal();
      } catch (err) { toast(err.message, true); }
    });
    if (audit) audit.addEventListener("click", async () => {
      try {
        const data = await api("GET", "/api/v1/audit?limit=50");
        $("#info-title").textContent = "Audit trail (latest 50)";
        $("#info-body").replaceChildren(h("table", {}, h("thead", {}, h("tr", {}, ["When", "User", "Action", "Patient"].map((t) => h("th", {}, t)))),
          h("tbody", {}, data.items.map((e) => h("tr", {}, h("td", {}, when(e.at)), h("td", {}, e.user_name), h("td", {}, e.action), h("td", {}, e.patient_id || "—"))))));
        dlg.showModal();
      } catch (err) { toast(err.message, true); }
    });
  }

  async function initApp() {
    initInfoDialogs();
    const f = form();
    if (!canWrite) { f.hidden = true; $("#intake-help").textContent = "Only clinicians can record intakes."; }
    ["age", "sex", "weight_kg", "serum_creatinine_mg_dl"].forEach((n) => f[n].addEventListener("input", updatePreview));
    f.addEventListener("submit", saveIntake);
    $("#patient").addEventListener("change", (e) => choose(e.target.value).catch((err) => toast(err.message, true)));
    $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); send($("#msg").value); });
    $("#file").addEventListener("change", async (e) => {
      const file = e.target.files[0]; if (!file || !state.detail) return;
      const fd = new FormData(); fd.append("file", file, file.name);
      try { await request("POST", `/api/v1/patients/${state.detail.id}/documents`, fd, true); toast("Note attached and added to the knowledge."); await choose(state.detail.id); }
      catch (err) { toast(err.message, true); }
      e.target.value = "";
    });
    try {
      await loadPatients("");
      const first = state.patients.find((p) => p.id === "P001") || state.patients[0];
      await choose(first ? first.id : "");
    } catch (err) { toast(err.message, true); }
  }

  const page = document.body.dataset.page;
  if (page === "login") initLogin();
  if (page === "app") initApp();
})();
