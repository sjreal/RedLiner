const state = { dealId: null, deal: null };

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

function message(text, error = false) {
  const box = $("deal-message");
  box.hidden = false;
  box.textContent = text;
  box.className = "deal-message" + (error ? " error" : " success");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.message || "Request failed");
  return data;
}

async function loadDeals() {
  const box = $("deal-list");
  try {
    const data = await api("/api/deals");
    const deals = data.deals || [];
    if (!deals.length) {
      box.innerHTML = '<p class="deal-empty">No deals yet. Send a contract through the webhook or Gmail poller.</p>';
      return;
    }
    box.innerHTML = deals.map((deal) => `
      <button class="deal-row ${deal.deal_id === state.dealId ? "active" : ""}" data-deal="${esc(deal.deal_id)}">
        <span class="deal-row-main">
          <strong>${esc(deal.deal_id)}</strong>
          <small>${esc(deal.vendor_name || "Unknown vendor")} · ${esc(deal.risk_tier || "UNKNOWN")}</small>
        </span>
        <span class="deal-row-meta">
          <span class="status-chip ${statusClass(deal.status)}">${esc(deal.status)}</span>
          <small>iter ${esc(deal.iteration)}/${esc(deal.max_iterations)} · util ${Number(deal.utility || 0).toFixed(2)}</small>
          ${deal.llm_tokens ? `<small>${esc(deal.llm_tokens)} tokens${deal.llm_cost ? ` · $${Number(deal.llm_cost).toFixed(4)}` : ""}</small>` : ""}
        </span>
      </button>
    `).join("");
    box.querySelectorAll("[data-deal]").forEach((button) => {
      button.addEventListener("click", () => openDeal(button.dataset.deal));
    });
  } catch (error) {
    box.innerHTML = `<p class="deal-empty error-text">${esc(error.message)}</p>`;
  }
}

function statusClass(status) {
  const value = String(status || "").toUpperCase();
  if (value.includes("APPROVED") || value.includes("CONVERGED")) return "success";
  if (value.includes("AWAITING") || value.includes("MAX")) return "warning";
  if (value.includes("ERROR") || value.includes("BLOCKED")) return "danger";
  return "";
}

async function openDeal(dealId) {
  state.dealId = dealId;
  $("deal-detail").hidden = false;
  $("deal-title").textContent = "Loading…";
  $("deal-subtitle").textContent = dealId;
  $("deal-status").textContent = "LOADING";
  $("deal-status").className = "status-chip";
  try {
    const deal = await api(`/api/deals/${encodeURIComponent(dealId)}`);
    state.deal = deal;
    $("deal-detail").hidden = false;
    $("deal-title").textContent = deal.deal_id;
    $("deal-subtitle").textContent = `${deal.source_contract_filename || "Contract"} · iteration ${deal.iteration}/${deal.max_iterations}`;
    $("deal-status").textContent = deal.run_status || "UNKNOWN";
    $("deal-status").className = `status-chip ${statusClass(deal.run_status)}`;
    $("btn-deal-report").href = `/api/deals/${encodeURIComponent(dealId)}/report?format=markdown`;
    const docx = deal.counter_proposal_email?.redlined_docx_filename || deal.redline_result?.output_docx_filename;
    $("btn-deal-docx").href = docx ? `/api/redliner/download/${encodeURIComponent(docx)}` : "#";
    $("btn-deal-docx").style.display = docx ? "" : "none";
    $("deal-trace-link").href = deal.langfuse_trace_url || "#";
    $("deal-trace-link").textContent = deal.langfuse_trace_url || "Not recorded";
    $("dispatch-recipient").value = deal.counter_proposal_email?.recipient_email || "";
    $("edited-clauses").value = deal.manual_edits?.length ? JSON.stringify(deal.manual_edits, null, 2) : "";
    $("deal-vendor").textContent = deal.vendor_profile?.company_name || "—";
    $("deal-risk").textContent = deal.vendor_profile?.risk_tier || "—";
    $("deal-iteration").textContent = `${deal.iteration}/${deal.max_iterations}`;
    $("deal-utility").textContent = Number(deal.normalized_utility_score || 0).toFixed(2);
    $("deal-summary").textContent = deal.human_review_summary?.summary_text || deal.convergence_reason || "No summary generated.";
    $("deal-counteroffer").textContent = deal.counteroffer && Object.keys(deal.counteroffer).length
      ? `Counteroffer: ${JSON.stringify(deal.counteroffer)}`
      : "No vendor counteroffer recorded.";
    $("deal-email-subject").textContent = deal.counter_proposal_email?.subject || "No draft email.";
    $("deal-email-body").textContent = deal.counter_proposal_email?.counter_proposal_body || "No draft body.";
    $("review-notes").value = deal.review_feedback || "";

    const clauses = deal.parsed_clauses || [];
    $("deal-clauses").innerHTML = clauses.length
      ? clauses.map((clause) => `
          <tr>
            <td>${esc(clause.clause_type)}</td>
            <td>${esc(clause.heading)}</td>
            <td>${esc((clause.text || "").slice(0, 500))}</td>
          </tr>`).join("")
      : '<tr><td colspan="3" class="deal-empty">No parsed clauses.</td></tr>';

    const redlines = deal.redline_actions || [];
    $("deal-redlines").innerHTML = redlines.length
      ? redlines.map((action) => `
          <tr>
            <td><span class="severity ${esc((action.severity || "").toLowerCase())}">${esc(action.severity)}</span></td>
            <td>${esc(action.clause_type)}</td>
            <td>${esc(action.rule_name)}</td>
            <td>${esc(action.replacement_text)}</td>
          </tr>`).join("")
      : '<tr><td colspan="4" class="deal-empty">No redlines.</td></tr>';

    const history = await api(`/api/deals/${encodeURIComponent(dealId)}/history`);
    $("deal-history").innerHTML = (history.history || []).map((item) => `
      <div class="history-item">
        <strong>Iteration ${esc(item.iteration)}</strong>
        <span class="status-chip ${statusClass(item.status)}">${esc(item.status)}</span>
        <small>${esc(item.created_at)}</small>
      </div>
    `).join("") || "No snapshots yet.";
    await loadDeals();
  } catch (error) {
    message(error.message, true);
  }
}

async function decide(decision) {
  if (!state.dealId) return;
  let editedClauses = null;
  const rawEdits = $("edited-clauses").value.trim();
  if (rawEdits) {
    try {
      editedClauses = JSON.parse(rawEdits);
      if (!Array.isArray(editedClauses)) throw new Error("Manual edits must be a JSON array.");
    } catch (error) {
      message(`Invalid manual-edit JSON: ${error.message}`, true);
      return;
    }
  }
  try {
    const updated = await api(`/api/deals/${encodeURIComponent(state.dealId)}/decision`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        reviewer: "workbench",
        notes: $("review-notes").value.trim(),
        edited_clauses: editedClauses,
      }),
    });
    message(`${decision} recorded. Status: ${updated.run_status}`);
    await openDeal(state.dealId);
  } catch (error) {
    message(error.message, true);
  }
}

async function applyCounteroffer() {
  if (!state.dealId) return;
  const price = Number($("counter-offer-price").value);
  if (!price || price <= 0) {
    message("Enter a positive offered price.", true);
    return;
  }
  try {
    const updated = await api(`/api/deals/${encodeURIComponent(state.dealId)}/counteroffer`, {
      method: "POST",
      body: JSON.stringify({
        offered_price: price,
        target_price: Number($("counter-target-price").value) || null,
        notes: $("review-notes").value.trim(),
      }),
    });
    message(`Counteroffer applied. Iteration ${updated.iteration}, status ${updated.run_status}.`);
    $("counter-offer-price").value = "";
    $("counter-target-price").value = "";
    await openDeal(state.dealId);
  } catch (error) {
    message(error.message, true);
  }
}

async function dispatchEmail() {
  if (!state.dealId || !state.deal) return;
  const recipient = $("dispatch-recipient").value.trim();
  const filename =
    state.deal.counter_proposal_email?.redlined_docx_filename ||
    state.deal.redline_result?.output_docx_filename;
  if (!recipient || !filename) {
    message("A recipient and redlined document are required.", true);
    return;
  }
  try {
    const result = await api("/api/email/dispatch-counter-proposal", {
      method: "POST",
      body: JSON.stringify({
        contract_filename: filename,
        vendor_name: state.deal.vendor_profile?.company_name || "Vendor",
        recipient_email: recipient,
        recipient_name: "Vendor Legal Counsel",
        deal_id: state.dealId,
      }),
    });
    const receipt = result.dispatch_receipt || {};
    message(`Dispatch: ${result.status} · real delivery: ${receipt.is_real_delivery === true}`);
    await openDeal(state.dealId);
  } catch (error) {
    message(error.message, true);
  }
}

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    $("settings-summary").innerHTML = `
      <span>Model <strong>${esc(settings.model)}</strong></span>
      <span>Email <strong>${esc(settings.email_provider)}</strong></span>
      <span>Database <strong>${esc(settings.database)}</strong></span>
      <span>MCP <strong>${settings.mcp_enabled ? "on" : "off"}</strong></span>
      <span>Live OSINT <strong>${settings.live_osint_enabled ? "on" : "off"}</strong></span>
      <span>Guardrails <strong>${settings.llm_guardrails_enabled ? "on" : "off"}</strong></span>
      <span>Langfuse <strong>${settings.langfuse_enabled ? "on" : "off"}</strong></span>
      <span>A2A <strong>${settings.a2a_enabled ? "on" : "off"}</strong></span>
      <span>Gmail poller <strong>${settings.gmail_poll_enabled ? "on" : "off"}</strong></span>
      <span>Demo auth <strong>${settings.demo_auth_enabled ? "on" : "off"}</strong></span>`;
  } catch (error) {
    $("settings-summary").innerHTML = `<span class="error-text">${esc(error.message)}</span>`;
  }
}

$("btn-refresh-deals").addEventListener("click", loadDeals);
$("btn-approve").addEventListener("click", () => decide("APPROVE"));
$("btn-reject").addEventListener("click", () => decide("REJECT"));
$("btn-manual").addEventListener("click", () => decide("MANUAL_EDIT"));
$("btn-counteroffer").addEventListener("click", applyCounteroffer);
$("btn-dispatch-deal").addEventListener("click", dispatchEmail);

const requestedDeal = new URLSearchParams(window.location.search).get("deal");
loadDeals();
loadSettings();
if (requestedDeal) openDeal(requestedDeal);
