/* Vouch demo · invoice creator — single-page operator UI (vanilla JS, no build step). */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const FORMATS = [["pdf", "PDF"], ["xlsx", "Excel"], ["csv", "CSV"], ["png", "Image"], ["body", "Email text"]];
  const FORMAT_NAMES = Object.fromEntries(FORMATS);
  const TONES = { a: "good", f: "good", b: "bad", e: "bad", c: "warn", d: "warn" };

  const state = {
    config: null,
    allPresets: [], // every story, as served by /api/presets
    presets: [], // the active story's presets, in demo order (hidden follow-ups included)
    story: null,
    presetKey: null,
    senderKind: "custom",
    format: "pdf",
    delivery: "smtp",
    invoice: {
      vendor_name: "", vendor_email: "", invoice_number: "", currency: "USD", amount: 0,
      invoice_date: today(0), due_date: today(14), po_number: "", description: "", line_items: [],
      bank: { bank_name: "", account_label: "Account Number", account_number: "", routing_label: "Routing Number", routing_number: "" },
      remit_to: { address: "", phone: "", tax_id_label: "Tax ID", tax_id: "", contact_name: "" },
      notes: "", bill_to_name: "", bill_to_address: "",
    },
    sender: {
      from_name: "", from_addr: "", reply_to: "", envelope_from: "", subject: "", body: "", add_received_header: true,
      auth: { enabled: true, spf: "pass", dkim: "pass", dmarc: "pass", dkim_domain: "" },
    },
  };

  function today(offsetDays) {
    const d = new Date();
    d.setDate(d.getDate() + offsetDays);
    return d.toISOString().slice(0, 10);
  }
  const getPath = (obj, path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
  function setPath(obj, path, value) {
    const ks = path.split(".");
    let o = obj;
    for (let i = 0; i < ks.length - 1; i++) { if (o[ks[i]] == null) o[ks[i]] = {}; o = o[ks[i]]; }
    o[ks[ks.length - 1]] = value;
  }
  const money = (n, cur) => {
    const v = Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (cur || "USD") === "USD" ? `$${v}` : `${cur} ${v}`;
  };
  const qty = (q) => (Number.isInteger(Number(q)) ? Number(q).toLocaleString("en-US") : Number(q).toFixed(2));

  // ---------------------------------------------------------------- bindings ----
  function readInput(el) {
    let v;
    if (el.type === "checkbox") v = el.checked;
    else if (el.type === "number") v = el.value === "" ? 0 : parseFloat(el.value);
    else v = el.value;
    setPath(state, el.dataset.bind, v);
  }
  function writeInputs() {
    document.querySelectorAll("[data-bind]").forEach((el) => {
      const v = getPath(state, el.dataset.bind);
      if (el.type === "checkbox") el.checked = !!v;
      else el.value = v == null ? "" : v;
    });
    $("#currency-prefix").textContent = state.invoice.currency === "USD" ? "$" : state.invoice.currency;
    $("#auth-fields").style.opacity = state.sender.auth.enabled ? "1" : "0.45";
  }
  document.querySelectorAll("[data-bind]").forEach((el) => {
    const handler = () => {
      readInput(el);
      if (el.dataset.bind.startsWith("sender.from") || el.dataset.bind === "sender.reply_to") {
        state.senderKind = detectSenderKind();
        renderSenderKind();
      }
      onChange();
    };
    el.addEventListener("input", handler);
    el.addEventListener("change", handler);
  });

  // -------------------------------------------------------------- line items ----
  function renderItems() {
    const tbody = $("#items-body");
    tbody.innerHTML = "";
    state.invoice.line_items.forEach((li, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><input aria-label="Item ${i + 1} description" data-item="${i}" data-field="description" value="${esc(li.description)}" /></td>
        <td class="num"><input aria-label="Item ${i + 1} quantity" data-item="${i}" data-field="quantity" type="number" step="any" min="0" value="${esc(li.quantity)}" /></td>
        <td class="num"><input aria-label="Item ${i + 1} unit price" data-item="${i}" data-field="unit_price" type="number" step="0.01" min="0" value="${esc(li.unit_price)}" /></td>
        <td class="num amount">${money(li.quantity * li.unit_price, state.invoice.currency)}</td>
        <td><button type="button" class="icon-btn" data-remove="${i}" aria-label="Remove item ${i + 1}">✕</button></td>`;
      tbody.appendChild(tr);
    });
    const total = lineTotal();
    $("#items-total").textContent = state.invoice.line_items.length ? `Lines add up to ${money(total, state.invoice.currency)}` : "No line items";
  }
  const lineTotal = () => state.invoice.line_items.reduce((s, li) => s + Number(li.quantity || 0) * Number(li.unit_price || 0), 0);
  $("#items-body").addEventListener("input", (e) => {
    const el = e.target;
    if (!el.dataset.item) return;
    const li = state.invoice.line_items[Number(el.dataset.item)];
    li[el.dataset.field] = el.type === "number" ? (el.value === "" ? 0 : parseFloat(el.value)) : el.value;
    state.invoice.amount = Math.round(lineTotal() * 100) / 100;
    el.closest("tr").querySelector(".amount").textContent = money(li.quantity * li.unit_price, state.invoice.currency);
    $("#items-total").textContent = `Lines add up to ${money(lineTotal(), state.invoice.currency)}`;
    writeInputs();
    onChange();
  });
  $("#items-body").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove]");
    if (!btn) return;
    state.invoice.line_items.splice(Number(btn.dataset.remove), 1);
    if (state.invoice.line_items.length) state.invoice.amount = Math.round(lineTotal() * 100) / 100;
    renderItems(); writeInputs(); onChange();
  });
  $("#add-item").addEventListener("click", () => {
    state.invoice.line_items.push({ description: "", quantity: 1, unit_price: 0 });
    renderItems();
    $("#items-body tr:last-child input").focus();
  });

  // ----------------------------------------------------------------- stories ----
  const storyOf = (key) => ((state.config && state.config.stories) || []).find((s) => s.key === key);
  function renderStories() {
    const seg = $("#story-seg");
    seg.innerHTML = "";
    ((state.config && state.config.stories) || []).forEach((s) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(s.key === state.story));
      b.dataset.story = s.key;
      b.textContent = s.title;
      b.title = s.summary;
      b.addEventListener("click", () => selectStory(s.key));
      seg.appendChild(b);
    });
    const s = storyOf(state.story);
    $("#story-summary").textContent = s ? s.summary : "";
    const n = state.presets.length;
    $("#send-all-btn").textContent = `Send all ${n}`;
    $("#send-all-detail").textContent = `Sends all ${n} invoices, one after the other (about ${Math.max(5, Math.round(n * 1.3))} seconds).`;
  }
  function selectStory(key, firstPreset) {
    state.story = key;
    state.presets = state.allPresets.filter((p) => p.story === key);
    renderStories(); renderPresets();
    const first = firstPreset || (state.presets.find((p) => !p.hidden) || {}).key;
    if (first) applyPreset(first);
  }

  // ----------------------------------------------------------------- presets ----
  function renderPresets() {
    const grid = $("#preset-grid");
    grid.innerHTML = "";
    state.presets.filter((p) => !p.hidden).forEach((p) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `preset tone-${TONES[p.group] || "warn"}`;
      b.setAttribute("aria-pressed", String(p.key === state.presetKey));
      b.dataset.key = p.key;
      b.innerHTML = `<span class="letter" aria-hidden="true">${esc(p.group)}</span><span><span class="t">${esc(p.title)}</span><br/><span class="v">${esc(p.vendor)}</span></span>`;
      b.addEventListener("click", () => applyPreset(p.key));
      grid.appendChild(b);
    });
  }
  function applyPreset(key) {
    const p = state.presets.find((x) => x.key === key);
    if (!p) return;
    state.presetKey = key;
    state.invoice = JSON.parse(JSON.stringify(p.invoice));
    state.sender = JSON.parse(JSON.stringify(p.sender));
    state.format = p.format;
    state.senderKind = detectSenderKind();
    document.querySelectorAll(".preset").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === key || b.dataset.key === parentOf(key))));
    const card = $("#scenario-card");
    card.hidden = false;
    $("#scenario-title").textContent = p.title;
    $("#scenario-group").textContent = `invoice ${p.group}`;
    $("#scenario-summary").textContent = p.summary;
    $("#scenario-expected").textContent = p.expected;
    const hint = $("#scenario-hint");
    hint.hidden = !p.hint; hint.textContent = p.hint || "";
    const fu = $("#follow-up-btn");
    fu.hidden = !p.follow_up;
    if (p.follow_up) { fu.textContent = p.follow_up_label || "Load the next step"; fu.onclick = () => applyPreset(p.follow_up); }
    renderItems(); writeInputs(); renderSenderKind(); renderFormat(); onChange();
    setStatus(`Loaded: ${p.title}.`, "");
  }
  const parentOf = (key) => (state.presets.find((x) => x.follow_up === key) || {}).key;
  function currentPreset() { return state.presets.find((x) => x.key === state.presetKey); }

  // --------------------------------------------------------- sender identity ----
  function detectSenderKind() {
    const p = currentPreset();
    if (!p) return "custom";
    const m = p.sender_options.find((o) => o.from_addr === state.sender.from_addr);
    return m ? m.kind : "custom";
  }
  function renderSenderKind() {
    const seg = $("#sender-kind");
    seg.innerHTML = "";
    const p = currentPreset();
    const opts = (p ? p.sender_options : []).map((o) => ({ ...o })).concat([{ kind: "custom", label: "Custom" }]);
    opts.forEach((o) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(o.kind === state.senderKind));
      b.textContent = o.kind === "custom" ? o.label : `${o.label} · ${o.from_addr}`;
      b.addEventListener("click", () => {
        state.senderKind = o.kind;
        if (o.kind !== "custom") { state.sender.from_name = o.from_name; state.sender.from_addr = o.from_addr; state.sender.reply_to = o.reply_to || ""; }
        writeInputs(); renderSenderKind(); onChange();
      });
      seg.appendChild(b);
    });
  }
  document.querySelectorAll("[data-auth]").forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.auth;
    state.sender.auth.enabled = true;
    state.sender.auth.spf = v; state.sender.auth.dkim = v; state.sender.auth.dmarc = v;
    writeInputs(); onChange();
  }));

  // ------------------------------------------------------------------ format ----
  function renderFormat() {
    const seg = $("#format-seg");
    seg.innerHTML = "";
    FORMATS.forEach(([id, label]) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String(id === state.format));
      b.textContent = label;
      b.addEventListener("click", () => { state.format = id; renderFormat(); onChange(); });
      seg.appendChild(b);
    });
    $("#preview-format").textContent = state.format === "body" ? "typed into the email" : `${FORMAT_NAMES[state.format] || state.format.toUpperCase()} file`;
    $("#open-attachment").disabled = state.format === "body";
  }

  // ---------------------------------------------------------------- delivery ----
  function renderDelivery() {
    const sel = $("#delivery");
    sel.innerHTML = "";
    state.config.deliveries.forEach((d) => {
      const o = document.createElement("option");
      o.value = d.id; o.textContent = d.label; o.dataset.detail = d.detail;
      sel.appendChild(o);
    });
    sel.value = state.delivery;
    $("#delivery-detail").textContent = (state.config.deliveries.find((d) => d.id === state.delivery) || {}).detail || "";
    sel.addEventListener("change", () => {
      state.delivery = sel.value;
      $("#delivery-detail").textContent = (state.config.deliveries.find((d) => d.id === state.delivery) || {}).detail || "";
    });
  }

  // ------------------------------------------------------------ paper preview ----
  // Mirrors render.account_line(): labels the backend parser knows stay; others print as "Bank account".
  const PARSEABLE_ACCOUNT_LABELS = new Set(["iban", "account number", "account no", "account no.", "account #", "acct", "acct."]);
  const accountLabel = (label) => (PARSEABLE_ACCOUNT_LABELS.has(String(label || "").trim().toLowerCase()) ? label : "Bank account");
  // Mirrors render.bill_to(): the invoice's own bill-to wins, else the operator's configured owner.
  function billTo(inv, c) {
    const name = (inv.bill_to_name || "").trim();
    const address = name ? (inv.bill_to_address || "").trim() : (c.owner_address || "");
    const who = name || c.owner_name || "";
    return who ? (address ? `${who}, ${address}` : who) : "";
  }
  function renderPaper() {
    const inv = state.invoice, c = state.config || {};
    const cur = inv.currency || "USD";
    const rows = inv.line_items.map((li) => `<tr><td>${esc(li.description)}</td><td class="num">${qty(li.quantity)}</td><td class="num">${money(li.unit_price, cur)}</td><td class="num">${money(li.quantity * li.unit_price, cur)}</td></tr>`).join("");
    const subtotal = inv.line_items.length ? lineTotal() : inv.amount;
    const contact = [inv.vendor_email && `Email: ${esc(inv.vendor_email)}`, inv.remit_to.phone && `Phone: ${esc(inv.remit_to.phone)}`].filter(Boolean).join(" &nbsp;&nbsp;&nbsp; ");
    $("#paper").innerHTML = `
      ${state.format === "body" ? '<div class="body-only">This invoice is typed into the email instead of attached.</div>' : ""}
      <h3>${esc(inv.vendor_name) || "<span style='color:#999'>Vendor name</span>"}</h3>
      <div class="addr muted">From: ${esc(inv.vendor_name)}</div>
      <div class="addr">${esc(inv.remit_to.address)}</div>
      <div class="addr">${contact}</div>
      ${inv.remit_to.tax_id ? `<div class="addr">${esc(inv.remit_to.tax_id_label)}: ${esc(inv.remit_to.tax_id)}</div>` : ""}
      <hr/>
      <div class="title">INVOICE</div>
      <div class="kv"><b>Invoice No:</b> ${esc(inv.invoice_number)}</div>
      <div class="kv"><b>Invoice Date:</b> ${esc(inv.invoice_date)}</div>
      <div class="kv"><b>Due Date:</b> ${esc(inv.due_date)}</div>
      ${inv.po_number ? `<div class="kv"><b>PO Number:</b> ${esc(inv.po_number)}</div>` : ""}
      ${billTo(inv, c) ? `<div class="kv"><b>Bill To:</b> ${esc(billTo(inv, c))}</div>` : ""}
      ${inv.description ? `<div class="kv"><b>Description:</b> ${esc(inv.description)}</div>` : ""}
      ${rows ? `<table><thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Unit Price</th><th class="num">Amount</th></tr></thead><tbody>${rows}</tbody></table>` : ""}
      <div class="kv">Subtotal: ${money(subtotal, cur)}</div>
      <div class="total">Total Due: ${money(inv.amount, cur)} ${cur === "USD" ? "USD" : ""}</div>
      <hr/>
      <div class="title" style="font-size:14px">Payment Details</div>
      ${inv.bank.bank_name ? `<div class="kv"><b>Bank Name:</b> ${esc(inv.bank.bank_name)}</div>` : ""}
      ${inv.bank.account_number ? `<div class="kv"><b>${esc(accountLabel(inv.bank.account_label))}:</b> <span class="mono">${esc(inv.bank.account_number)}</span>${accountLabel(inv.bank.account_label) === "Bank account" ? ` <span class="muted">(${esc(inv.bank.account_label)})</span>` : ""}</div>` : ""}
      ${inv.bank.routing_number ? `<div class="kv"><b>${esc(inv.bank.routing_label)}:</b> <span class="mono">${esc(inv.bank.routing_number)}</span></div>` : ""}
      ${inv.remit_to.contact_name ? `<div class="kv"><b>Contact:</b> ${esc(inv.remit_to.contact_name)}</div>` : ""}
      ${inv.notes ? `<div class="notes"><b>Notes:</b> ${esc(inv.notes)}</div>` : ""}
      <div class="foot">DEMO — synthetic data (Vouch demo-tools)</div>`;
  }

  // ---------------------------------------------------------- message preview ----
  let previewTimer = null;
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(previewMessage, 350);
  }
  function payload() {
    const p = currentPreset();
    return { invoice: state.invoice, sender: state.sender, format: state.format, delivery: state.delivery, scenario: state.presetKey || "", label: p ? p.title : "custom" };
  }
  async function previewMessage() {
    if (!valid(false)) return;
    try {
      const r = await fetch("/api/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()) });
      if (!r.ok) throw new Error(await r.text());
      const m = await r.json();
      const SIM = new Set(["received", "authentication-results", "x-vouch-demo", "x-vouch-demo-scenario"]);
      $("#headers-pre").innerHTML = m.headers.map(([k, v]) => `<span class="hn">${esc(k)}:</span> <span class="${SIM.has(k.toLowerCase()) ? "sim" : ""}">${esc(v)}</span>`).join("\n");
      $("#body-pre").textContent = m.body_text;
      $("#intake-pre").textContent = JSON.stringify(m.intake_json_preview, null, 2);
      $("#message-meta").textContent = m.attachment_name ? `${m.attachment_name} · ${(m.attachment_size / 1024).toFixed(1)} KB` : "no attachment";
    } catch (err) {
      $("#headers-pre").textContent = `preview failed: ${err.message}`;
    }
  }

  // -------------------------------------------------------------------- send ----
  function valid(report) {
    const inv = state.invoice, s = state.sender;
    const problems = [];
    if (!inv.vendor_name.trim()) problems.push("vendor name");
    if (!inv.invoice_number.trim()) problems.push("invoice number");
    if (!(Number(inv.amount) > 0)) problems.push("amount");
    if (!inv.invoice_date || !inv.due_date) problems.push("dates");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s.from_addr)) problems.push("from address");
    if (problems.length && report) setStatus(`Missing: ${problems.join(", ")}.`, "bad");
    return problems.length === 0;
  }
  function setStatus(text, tone) {
    const el = $("#send-status");
    el.textContent = text; el.className = `status ${tone || ""}`;
  }
  $("#send-btn").addEventListener("click", async () => {
    if (!valid(true)) return;
    const btn = $("#send-btn");
    btn.disabled = true; setStatus("Sending…", "");
    try {
      const r = await fetch("/api/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()) });
      if (!r.ok) throw new Error(await r.text());
      const e = await r.json();
      prependLog(e);
      setStatus(e.status === "failed" ? `Not sent: ${e.detail}` : e.status === "built" ? `Saved ${e.invoice_number} (not sent).` : `Sent ${e.invoice_number}. Watch it arrive in Vouch.`, e.status === "failed" ? "bad" : "ok");
      setTimeout(refreshReceiver, 1500);
    } catch (err) {
      setStatus(`Send failed: ${err.message}`, "bad");
    } finally {
      btn.disabled = false;
    }
  });
  $("#download-eml").addEventListener("click", async () => {
    if (!valid(true)) return;
    const r = await fetch("/api/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()) });
    if (!r.ok) { setStatus(`Could not build the email: ${await r.text()}`, "bad"); return; }
    const m = await r.json();
    const a = document.createElement("a");
    a.href = m.eml_url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
    setStatus(`Downloading the email file.`, "ok");
  });
  $("#open-attachment").addEventListener("click", async () => {
    if (!valid(true) || state.format === "body") return;
    const r = await fetch("/api/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ invoice: state.invoice, format: state.format }) });
    if (!r.ok) { setStatus(`Could not make the file: ${await r.text()}`, "bad"); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    if (state.format === "pdf" || state.format === "png") window.open(url, "_blank", "noopener");
    else { const a = document.createElement("a"); a.href = url; a.download = `${state.invoice.invoice_number}.${state.format}`; document.body.appendChild(a); a.click(); a.remove(); }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  });

  // --------------------------------------------------------------------- log ----
  function backendCell(e) {
    if (e.status !== "sent") return `<span class="muted">—</span>`;
    if (e.delivery === "backend") return `<span class="st st-delivered">yes</span><div class="detail">sent straight to Vouch</div>`;
    if (!e.receiver_message_id) return `<span class="st st-pending">unknown</span><div class="detail">mailbox gave no id</div>`;
    return `<span class="st st-pending">checking…</span><div class="detail mono">${esc(e.receiver_message_id)}</div>`;
  }
  function logRow(e) {
    const when = new Date(e.at).toLocaleTimeString();
    const via = { smtp: "email", receiver_http: "mailbox (HTTP)", backend: "Vouch (HTTP)", none: "not sent" }[e.delivery] || e.delivery;
    return `<tr data-log-id="${esc(e.id)}" data-receiver-id="${esc(e.receiver_message_id || "")}">
      <td>${esc(when)}</td>
      <td class="wrap">${esc(e.label || e.scenario || "custom")}</td>
      <td><span class="mono">${esc(e.invoice_number)}</span><br/><span class="muted">${esc(e.vendor_name)}</span></td>
      <td class="num mono">${money(e.amount, e.currency)}</td>
      <td>${esc(e.format)}</td>
      <td class="mono wrap">${esc(e.from_addr)}${e.reply_to ? `<br/><span class="muted">reply-to ${esc(e.reply_to)}</span>` : ""}<br/>→ ${esc(e.to)}</td>
      <td class="mono wrap">${esc(e.auth_summary)}</td>
      <td>${esc(via)}</td>
      <td><span class="st st-${esc(e.status)}">${esc(e.status)}</span><div class="detail">${esc(e.detail)}</div></td>
      <td class="backend">${backendCell(e)}</td>
      <td><a href="${esc(e.eml_url)}" download>.eml</a></td>
    </tr>`;
  }
  function prependLog(e) {
    $("#log-body").insertAdjacentHTML("afterbegin", logRow(e));
    $("#log-empty").hidden = true;
    trackBackend(e, 0);
  }
  async function loadLog() {
    const r = await fetch("/api/log");
    const entries = await r.json();
    $("#log-body").innerHTML = entries.map(logRow).join("");
    $("#log-empty").hidden = entries.length > 0;
    entries.slice(0, 25).forEach((e) => trackBackend(e, 0));
  }
  $("#clear-log").addEventListener("click", async () => {
    await fetch("/api/log", { method: "DELETE" });
    loadLog();
  });

  // ---------------------------------------------- receiver → backend tracking ----
  // After a send, follow the message through the receiver (/recent/{id} via the same-origin
  // proxy) until its forward to the backend reaches a terminal state.
  const TERMINAL = new Set(["delivered", "dead_letter", "stored", "missing"]);
  const TRACK_DELAYS_MS = [600, 1200, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000, 30000, 30000];
  function paintBackend(row, status, detail, extra) {
    const cell = row.querySelector("td.backend");
    if (!cell) return;
    const label = { delivered: "yes", dead_letter: "failed", stored: "stored only", retrying: "retrying", queued: "waiting", received: "received", missing: "missing", pending: "checking" }[status] || status;
    cell.innerHTML = `<span class="st st-${esc(status)}">${esc(label)}</span><div class="detail">${esc(detail || "")}${extra ? `<br/>${esc(extra)}` : ""}</div>`;
  }
  async function trackBackend(e, step) {
    if (e.status !== "sent" || e.delivery === "backend" || !e.receiver_message_id) return;
    const row = document.querySelector(`tr[data-log-id="${CSS.escape(e.id)}"]`);
    if (!row) return;
    let info;
    try {
      const r = await fetch(`/api/receiver/messages/${encodeURIComponent(e.receiver_message_id)}`);
      info = await r.json();
    } catch (_err) {
      info = { reachable: false };
    }
    if (!info.reachable) { paintBackend(row, "pending", "mailbox not reachable"); }
    else if (!info.found) { paintBackend(row, "pending", "mailbox does not know this email"); return; }
    else {
      const d = info.delivery || {};
      const attempts = d.attempts ? `attempt ${d.attempts}` : "";
      const dropped = info.attachments_dropped ? `${info.attachments_dropped} attachment(s) dropped by allowlist` : "";
      // "HTTP 200 {...backend json...}" → keep the status line, not the backend's payload
      const last = (d.last_detail || "").split("{")[0].trim().slice(0, 140);
      const detail = [attempts, last].filter(Boolean).join(" · ");
      paintBackend(row, d.status || "received", detail, dropped);
      if (TERMINAL.has(d.status)) { refreshReceiver(); return; }
    }
    if (step < TRACK_DELAYS_MS.length) setTimeout(() => trackBackend(e, step + 1), TRACK_DELAYS_MS[step]);
  }

  // ------------------------------------------------------ receiver status pill ----
  async function refreshReceiver() {
    const pill = $("#receiver-pill");
    let info;
    try { info = await (await fetch("/api/receiver/health")).json(); } catch (_err) { info = { reachable: false }; }
    pill.classList.remove("ok", "degraded", "down");
    if (!info.reachable) {
      pill.classList.add("down");
      pill.textContent = `mailbox offline (${(info.url || "").replace(/^https?:\/\//, "")})`;
      pill.title = `No answer from the Vouch mailbox at ${info.url || "?"}: ${info.error || ""}`;
      return;
    }
    const h = info.health;
    pill.classList.add(h.status === "ok" ? "ok" : h.status === "degraded" ? "degraded" : "ok");
    const dead = h.dead_letter_count ? ` · ${h.dead_letter_count} failed` : "";
    pill.textContent = `mailbox ${h.status === "ok" ? "online" : h.status} · ${h.received_total} received · ${h.delivered_total} passed to Vouch${dead}`;
    const last = h.last_delivery ? `last forward ${h.last_delivery.ok ? "ok" : "FAILED"} at ${new Date(h.last_delivery.at).toLocaleTimeString()} — ${(h.last_delivery.detail || "").split("{")[0].trim()}` : "no forwards yet";
    pill.title = `${info.url} · ${h.config && h.config.backend_intake_url ? "backend " + h.config.backend_intake_url : "store-only (no BACKEND_INTAKE_URL)"} · ${last}`;
  }

  // --------------------------------------------------------- demo sequence ----
  $("#send-all-btn").addEventListener("click", async () => {
    const btn = $("#send-all-btn");
    const sequence = state.presets; // API order is the demo order; hidden follow-ups included
    btn.disabled = true;
    let sent = 0, failed = 0;
    for (const p of sequence) {
      sent += 1;
      setStatus(`Sending ${sent} of ${sequence.length}: ${p.title}…`, "");
      try {
        const body = { invoice: p.invoice, sender: p.sender, format: p.format, delivery: state.delivery, scenario: p.key, label: p.title };
        const r = await fetch("/api/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error(await r.text());
        const e = await r.json();
        prependLog(e);
        if (e.status === "failed") failed += 1;
      } catch (err) {
        failed += 1;
        setStatus(`${p.title} was not sent: ${err.message}`, "bad");
      }
      await new Promise((res) => setTimeout(res, 900));
    }
    btn.disabled = false;
    setStatus(failed ? `Done: ${sequence.length - failed} sent, ${failed} not sent.` : `Done: all ${sequence.length} sent. Watch them arrive in Vouch.`, failed ? "bad" : "ok");
    refreshReceiver();
  });

  // -------------------------------------------------------------------- boot ----
  function onChange() { renderPaper(); schedulePreview(); }

  async function boot() {
    const [cfg, presets] = await Promise.all([fetch("/api/config").then((r) => r.json()), fetch("/api/presets").then((r) => r.json())]);
    state.config = cfg; state.allPresets = presets;
    $("#target-pill").textContent = `to ${cfg.mail_to}`;
    $("#version").textContent = `invoice-creator v${cfg.version}`;
    $("#bill-to-name").placeholder = cfg.owner_name || "";
    $("#bill-to-address").placeholder = cfg.owner_address || "";
    renderDelivery(); renderFormat(); renderSenderKind(); renderItems(); writeInputs();
    await loadLog();
    const wanted = new URLSearchParams(location.search).get("story");
    selectStory(storyOf(wanted) ? wanted : cfg.default_story || (presets[0] || {}).story);
    refreshReceiver();
    setInterval(refreshReceiver, 10000);
  }
  boot().catch((err) => { $("#target-pill").textContent = "offline"; setStatus(`Could not load: ${err.message}`, "bad"); });
})();
