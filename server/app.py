import base64
import os
import secrets
import shutil
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.models import (
    ParsedDocument,
    RedlineResult,
    VendorProfile,
    InboundEmailWebhook,
    OutboundEmailRequest,
    PlaybookRule,
    ClauseType,
    SeverityLevel,
)
from agents.orchestrator import MainOrchestrator
from agents.legal_redliner import LegalRedlinerAgent
from agents.vendor_intelligence import VendorIntelligenceAgent
from agents.email_writer import EmailWriterAgent
from subgraphs.document_parser import DocumentParserSubgraph
from subgraphs.human_approval import FeedbackAgent
from subgraphs.vendor_information.osint_collectors import OSINTCollector
from Helpers.logger import get_recent_logs
from core.env import load_app_env
from core.report import build_deal_report, report_to_markdown

load_app_env()

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "data" / "uploads"
OUTPUTS_DIR = BASE_DIR / "data" / "outputs"
SAMPLE_DIR = BASE_DIR / "data" / "sample_contracts"
DASHBOARD_DIR = BASE_DIR / "dashboard"
PLAYBOOKS_DIR = BASE_DIR / "playbooks"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    from services.inbox_worker import start_worker_from_env, stop_worker

    start_worker_from_env()
    try:
        yield
    finally:
        stop_worker()


app = FastAPI(
    title="RedLiner — B2B Autonomous Contract Negotiation & Redlining",
    description="Agentic contract orchestration with subagents and subgraphs matching the project synopsis architecture.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def demo_basic_auth(request: Request, call_next):
    """One shared demo login; no user table, roles or RLS for the college demo."""
    password = os.environ.get("DEMO_PASSWORD", "").strip()
    if not password or request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path == "/api/health" or request.url.path.startswith("/api/webhook/"):
        return await call_next(request)

    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() == "basic" and encoded:
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, _, supplied = decoded.partition(":")
        except (ValueError, UnicodeDecodeError):
            username, supplied = "", ""
        expected_user = os.environ.get("DEMO_USER", "demo")
        if secrets.compare_digest(username, expected_user) and secrets.compare_digest(
            supplied, password
        ):
            return await call_next(request)

    return Response(
        content="RedLiner demo login required.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="RedLiner Demo"'},
    )


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.endswith((".js", ".html", ".css")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Core Supervisor & Specialized Agents / Subgraphs
orchestrator = MainOrchestrator()
doc_parser = DocumentParserSubgraph()
legal_redliner = LegalRedlinerAgent()
vendor_intelligence = VendorIntelligenceAgent()
email_writer = EmailWriterAgent()


@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "service": "RedLiner Core Orchestration System",
        "agents": [
            "MainOrchestrator",
            "CrewAI Procurement Negotiator",
            "CrewAI Finance Compliance Reviewer",
            "CrewAI Email Writer",
            "ADK Document Parser",
            "ADK Legal Review",
            "ADK Vendor Intelligence",
            "ADK Tradeoff Engine",
            "ADK Approval Gate"
        ],
        "subgraphs": [
            "DocumentParserSubgraph",
            "PlaybookMatcherSubgraph",
            "VendorInformationSubgraph",
            "TradeoffEngineSubgraph",
            "HumanApprovalSubgraph"
        ],
        "frameworks": ["CrewAI", "Google ADK"],
        "runtime": "CrewAI + Google ADK",
        "mcp_enabled": os.environ.get("MCP_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        "a2a_enabled": os.environ.get("A2A_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
        "persistence": "postgres" if os.environ.get("DATABASE_URL") else "sqlite",
    }


@app.get("/api/settings")
def get_settings():
    """Non-secret effective demo settings for the workbench."""
    email_config = email_writer.service.get_config(mask_secret=True)
    return {
        "model": os.environ.get("OPENCODE_MODEL", "glm-5.3-flash"),
        "email_provider": email_config.get("provider", "sandbox"),
        "smtp_user": email_config.get("smtp_user", ""),
        "mcp_enabled": os.environ.get("MCP_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        "live_osint_enabled": os.environ.get("LIVE_OSINT_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        "llm_guardrails_enabled": os.environ.get("LLM_GUARDRAILS_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        "langfuse_enabled": os.environ.get("LANGFUSE_TRACING_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"}
        and bool(os.environ.get("LANGFUSE_PUBLIC_KEY")),
        "a2a_enabled": os.environ.get("A2A_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
        "database": "postgres" if os.environ.get("DATABASE_URL") else "sqlite",
        "demo_auth_enabled": bool(os.environ.get("DEMO_PASSWORD")),
        "gmail_poll_enabled": os.environ.get("GMAIL_POLL_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
    }


@app.post("/api/parser/parse")
async def parse_document(file: Optional[UploadFile] = File(None), sample_name: Optional[str] = Form(None)):
    """Executes DocumentParserSubgraph on uploaded .docx/.pdf or sample file."""
    target_path: Optional[Path] = None

    if sample_name:
        sample_path = SAMPLE_DIR / sample_name
        if not sample_path.exists():
            raise HTTPException(status_code=404, detail=f"Sample '{sample_name}' not found.")
        target_path = sample_path
    elif file:
        safe_name = Path(file.filename).name
        target_path = UPLOADS_DIR / safe_name
        with open(target_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    else:
        target_path = SAMPLE_DIR / "vendor_saas_agreement.docx"

    try:
        return doc_parser.execute(target_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document parsing error: {str(e)}")


class RedlineRequest(BaseModel):
    filename: str


@app.post("/api/redliner/redline")
def run_redline(req: RedlineRequest):
    """Executes LegalRedlinerAgent and PlaybookMatcherSubgraph to produce native Word tracked changes."""
    source_path = SAMPLE_DIR / req.filename
    if not source_path.exists():
        source_path = UPLOADS_DIR / req.filename
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Contract '{req.filename}' not found.")

    try:
        parsed_doc = doc_parser.execute(source_path)
        output_filename = f"{source_path.stem}_redlined.docx"
        output_path = OUTPUTS_DIR / output_filename

        actual_source = source_path
        if source_path.suffix.lower() == ".pdf":
            import docx
            temp_docx = OUTPUTS_DIR / f"temp_{source_path.stem}.docx"
            doc = docx.Document()
            doc.add_heading(source_path.stem.replace("_", " ").title(), 0)
            for c in parsed_doc.clauses:
                doc.add_heading(c.heading, level=1)
                doc.add_paragraph(c.text)
            doc.save(str(temp_docx))
            actual_source = temp_docx

        redline_result = legal_redliner.generate_redlined_docx(
            source_docx_path=actual_source,
            output_docx_path=output_path,
            clauses=parsed_doc.clauses,
            contract_name=source_path.stem,
        )

        return redline_result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redline error: {str(e)}")


@app.get("/api/redliner/download/{filename}")
def download_redlined_file(filename: str):
    file_path = OUTPUTS_DIR / filename
    if not file_path.exists():
        file_path = SAMPLE_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found.")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


# ---------------------------------------------------------------------------
# VENDOR INTELLIGENCE & OSINT ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/api/vendor/stats")
def get_vendor_stats():
    """Returns dynamic statistics on screened counterparties from the SQLite database."""
    return OSINTCollector.get_database_stats()


@app.get("/api/vendor/search")
def search_vendors(q: str = "", limit: int = 50):
    """Executes VendorInformationSubgraph search with persistence."""
    return vendor_intelligence.search_vendors(q, limit)


@app.get("/api/vendor/assess")
def assess_vendor(name: str):
    """Executes dynamic OSINT risk assessment on a vendor and permanently stores into SQLite."""
    if not name.strip():
        raise HTTPException(status_code=400, detail="Vendor name or domain is required.")
    return vendor_intelligence.evaluate_counterparty(name)


# ---------------------------------------------------------------------------
# CORPORATE LEGAL PLAYBOOK ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/api/playbook")
def get_active_playbook():
    """Returns the currently active corporate legal playbook configuration and all rules."""
    return legal_redliner.subgraph.comparator.to_dict()


@app.post("/api/playbook/upload")
async def upload_playbook(file: UploadFile = File(...)):
    """Uploads an updated YAML or JSON playbook file and immediately activates it across agents."""
    playbook_file = PLAYBOOKS_DIR / "enterprise_playbook.yaml"
    temp_file = PLAYBOOKS_DIR / f"temp_{file.filename}"
    content = await file.read()
    try:
        parsed = yaml.safe_load(content)
        if isinstance(parsed, list):
            parsed = {
                "name": f"Custom Corporate Playbook ({file.filename})",
                "version": "2026.upload",
                "description": "User uploaded corporate rules",
                "author": "Enterprise Legal Operations",
                "rules": parsed
            }
        elif isinstance(parsed, dict):
            if "rules" not in parsed:
                for alt in ["policies", "clauses", "playbook", "items"]:
                    if alt in parsed and isinstance(parsed[alt], list):
                        parsed["rules"] = parsed[alt]
                        break
            if "rules" not in parsed:
                raise ValueError("Playbook must contain a list of 'rules'.")
        else:
            raise ValueError("Playbook must be a YAML or JSON object with a 'rules' list.")

        # Test write to temp file first
        with open(temp_file, "w", encoding="utf-8") as f:
            yaml.dump(parsed, f, sort_keys=False, allow_unicode=True)

        from subgraphs.playbook_matcher.policy_comparator import PolicyComparator
        test_comp = PolicyComparator(temp_file)
        if len(test_comp.rules) == 0:
            raise ValueError("Uploaded playbook contained 0 valid rules.")

        # Atomically replace active file
        shutil.move(temp_file, playbook_file)

        # Reload comparator in memory across agents
        legal_redliner.reload_playbook(playbook_file)
        orchestrator.reload_playbook(playbook_file)

        return {
            "status": "SUCCESS",
            "message": f"Active Playbook updated with {len(test_comp.rules)} verified rules.",
            "playbook": legal_redliner.subgraph.comparator.to_dict()
        }
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink()
        raise HTTPException(status_code=400, detail=f"Invalid playbook format: {str(e)}")


class RawPlaybookPayload(BaseModel):
    content: str


@app.post("/api/playbook/raw")
def save_raw_playbook(payload: RawPlaybookPayload):
    """Directly updates the active playbook via pasted YAML or JSON text."""
    playbook_file = PLAYBOOKS_DIR / "enterprise_playbook.yaml"
    temp_file = PLAYBOOKS_DIR / "temp_raw_upload.yaml"
    try:
        parsed = yaml.safe_load(payload.content)
        if isinstance(parsed, list):
            parsed = {
                "name": "Custom Corporate Legal Playbook",
                "version": "2026.custom",
                "description": "Custom edited legal guardrails",
                "author": "Corporate Counsel",
                "rules": parsed
            }
        elif isinstance(parsed, dict):
            if "rules" not in parsed:
                for alt in ["policies", "clauses", "playbook", "items"]:
                    if alt in parsed and isinstance(parsed[alt], list):
                        parsed["rules"] = parsed[alt]
                        break
            if "rules" not in parsed:
                raise ValueError("Playbook must contain a list of 'rules'.")
        else:
            raise ValueError("Playbook content must be a YAML or JSON object with a 'rules' list.")

        with open(temp_file, "w", encoding="utf-8") as f:
            yaml.dump(parsed, f, sort_keys=False, allow_unicode=True)

        from subgraphs.playbook_matcher.policy_comparator import PolicyComparator
        test_comp = PolicyComparator(temp_file)
        if len(test_comp.rules) == 0:
            raise ValueError("Provided playbook contained 0 valid rules.")

        shutil.move(temp_file, playbook_file)
        legal_redliner.reload_playbook(playbook_file)
        orchestrator.reload_playbook(playbook_file)

        return {
            "status": "SUCCESS",
            "message": f"Playbook updated with {len(test_comp.rules)} active rules.",
            "playbook": legal_redliner.subgraph.comparator.to_dict()
        }
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink()
        raise HTTPException(status_code=400, detail=f"Failed to update playbook: {str(e)}")


class PlaybookRulePayload(BaseModel):
    id: str
    name: str
    target_clause_type: str
    severity: str
    pattern_triggers: List[str] = Field(default_factory=list)
    forbidden_terms: List[str] = Field(default_factory=list)
    required_terms: List[str] = Field(default_factory=list)
    preferred_fallback_text: str
    comment_explanation: str
    guidance_note: Optional[str] = None


@app.post("/api/playbook/rule")
def add_or_update_rule(payload: PlaybookRulePayload):
    """Adds a new custom policy rule or updates an existing rule in the active corporate playbook."""
    try:
        from subgraphs.playbook_matcher.policy_comparator import normalize_clause_type, normalize_severity
        rule = PlaybookRule(
            id=payload.id,
            name=payload.name,
            target_clause_type=normalize_clause_type(payload.target_clause_type),
            severity=normalize_severity(payload.severity),
            pattern_triggers=payload.pattern_triggers,
            forbidden_terms=payload.forbidden_terms,
            required_terms=payload.required_terms,
            preferred_fallback_text=payload.preferred_fallback_text,
            comment_explanation=payload.comment_explanation,
            guidance_note=payload.guidance_note,
        )
        legal_redliner.subgraph.comparator.add_or_update_rule(rule)
        orchestrator.reload_playbook()
        return {
            "status": "SUCCESS",
            "message": f"Rule '{payload.name}' saved and activated.",
            "playbook": legal_redliner.subgraph.comparator.to_dict()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save rule: {str(e)}")


@app.post("/api/playbook/reset")
def reset_playbook():
    """Resets the corporate playbook to standard default Fortune 500 SaaS v2026.1 rules."""
    legal_redliner.subgraph.comparator.reset_to_default()
    orchestrator.reload_playbook()
    return {
        "status": "SUCCESS",
        "message": "Playbook successfully reset to default Enterprise SaaS v2026.1 baseline.",
        "playbook": legal_redliner.subgraph.comparator.to_dict()
    }


# ---------------------------------------------------------------------------
# EMAIL DISPATCH & CONFIGURATION ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/api/email/config")
def get_email_config():
    """Returns current email dispatch configuration with masked passwords."""
    return email_writer.service.get_config(mask_secret=True)


class EmailConfigUpdate(BaseModel):
    provider: str
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""
    smtp_use_tls: Optional[bool] = True
    from_email: Optional[str] = "procurement@redliner.ai"
    from_name: Optional[str] = "RedLiner Enterprise Procurement"
    resend_api_key: Optional[str] = ""


@app.post("/api/email/config")
def update_email_config(cfg: EmailConfigUpdate):
    """Updates SMTP or Resend credentials for live outbound email dispatch."""
    updated = email_writer.service.update_config(cfg.dict(exclude_unset=True))
    return {"status": "SUCCESS", "message": "Email configuration saved successfully.", "config": updated}


class SendTestEmailRequest(BaseModel):
    target_email: str


@app.post("/api/email/send-test")
def send_test_email(req: SendTestEmailRequest):
    """Sends a verification email to ensure direct SMTP or Resend connection is healthy."""
    try:
        res = email_writer.service.send_test_email(req.target_email)
        return {"status": "SUCCESS", "result": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Test email failed: {str(e)}")


@app.post("/api/webhook/email")
def inbound_email_webhook(
    payload: InboundEmailWebhook,
    auto_process: bool = True,
    offered_price: Optional[float] = None,
    target_price: Optional[float] = None,
    x_redliner_webhook_token: Optional[str] = Header(default=None),
):
    """
    Inbound Cloudflare Email Routing Webhook receiver.
    Extracts vendor .docx/.pdf attachments, runs OSINT screening, executes legal redlining,
    and drafts a structured counter-proposal email.
    """
    expected_token = os.environ.get("REDLINER_WEBHOOK_TOKEN", "").strip()
    if expected_token and (
        not x_redliner_webhook_token
        or not secrets.compare_digest(expected_token, x_redliner_webhook_token)
    ):
        raise HTTPException(status_code=401, detail="Invalid RedLiner webhook token.")

    inbound_res = email_writer.service.process_inbound_webhook(payload)
    saved_attachments = [
        filename
        for filename in inbound_res.get("saved_attachments", [])
        if Path(filename).suffix.lower() in {".docx", ".pdf"}
    ]

    headers = {str(k).lower(): str(v) for k, v in (payload.headers or {}).items()}
    references = payload.references or [
        item for item in headers.get("references", "").split() if item
    ]
    in_reply_to = payload.in_reply_to or headers.get("in-reply-to")
    matched_deal = orchestrator.find_deal_for_reply(
        in_reply_to=in_reply_to,
        references=references,
        thread_id=headers.get("x-gm-thrid"),
        deal_reference=headers.get("x-redliner-deal"),
    )
    if matched_deal:
        reply_text = "\n".join(
            part for part in (payload.subject, payload.text_content, payload.html_content) if part
        )
        reply_state = orchestrator.handle_vendor_reply(
            matched_deal,
            reply_text[:100000],
            subject=payload.subject,
        )
        return {
            "status": (
                "COUNTEROFFER_APPLIED"
                if reply_state.counteroffer.get("status") == "APPLIED"
                else "COUNTEROFFER_NEEDS_REVIEW"
            ),
            "deal_id": matched_deal,
            "iteration": reply_state.iteration,
            "run_status": reply_state.run_status,
            "convergence_reason": reply_state.convergence_reason,
            "counteroffer": reply_state.counteroffer,
            "requires_human_approval": reply_state.requires_human_approval,
            "inbound_info": inbound_res,
        }

    if not auto_process or not saved_attachments:
        return {
            "status": "RECEIVED",
            "inbound_info": inbound_res,
            "message": "Email received; no supported .docx or .pdf contract attachment was found."
        }

    contract_file_path = Path(saved_attachments[0])
    
    # Infer vendor name from sender email domain or sender name
    from_domain = payload.from_email.split("@")[-1] if "@" in payload.from_email else "vendor"
    vendor_query = payload.from_name if payload.from_name and payload.from_name != payload.from_email else from_domain
    if vendor_query.lower() in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"]:
        vendor_query = "Vendor Counterparty"

    deal_id = f"DEAL-EMAIL-{payload.message_id[:12]}"

    deal_state = orchestrator.process_incoming_deal(
        deal_id=deal_id,
        contract_path=contract_file_path,
        vendor_name=vendor_query,
        output_dir=OUTPUTS_DIR,
        email_context="\n".join((payload.subject or "", payload.text_content or "", payload.html_content or ""))[:100000],
        offered_price=offered_price,
        target_price=target_price,
    )

    return {
        "status": "PROCESSED_AUTOMATICALLY",
        "message_id": payload.message_id,
        "deal_id": deal_id,
        "vendor_screened": deal_state.vendor_profile.company_name if deal_state.vendor_profile else vendor_query,
        "vendor_risk_tier": deal_state.vendor_profile.risk_tier.value if deal_state.vendor_profile else "UNKNOWN",
        "violations_detected": len(deal_state.redline_actions),
        "requires_human_approval": deal_state.requires_human_approval,
        "run_status": deal_state.run_status,
        "security_status": deal_state.security_status,
        "security_flags": deal_state.security_flags,
        "guardrail_flags": deal_state.guardrail_flags,
        "llm_status": deal_state.llm_status,
        "llm_usage": deal_state.llm_usage,
        "trace_id": deal_state.trace_id,
        "langfuse_trace_url": deal_state.langfuse_trace_url,
        "human_review_summary": deal_state.human_review_summary,
        "procurement_plan": deal_state.procurement_plan,
        "finance_analysis": deal_state.finance_analysis,
        "crew_finance_review": deal_state.crew_finance_review,
        "tradeoff_proposal": deal_state.tradeoff_proposal,
        "runtime_frameworks": deal_state.runtime_frameworks,
        "crew_status": deal_state.crew_status,
        "crew_error": deal_state.crew_error,
        "adk_event_count": deal_state.adk_event_count,
        "pipeline_error": deal_state.pipeline_error,
        "mcp_tools_used": deal_state.mcp_tools_used,
        "mcp_errors": deal_state.mcp_errors,
        "iteration": deal_state.iteration,
        "convergence_reason": deal_state.convergence_reason,
        "redlined_docx_filename": deal_state.redline_result.output_docx_filename if deal_state.redline_result else None,
        "counter_proposal_email": deal_state.counter_proposal_email,
        "inbound_info": inbound_res,
    }


class DispatchProposalRequest(BaseModel):
    contract_filename: str = Field(examples=["vendor_saas_agreement_redlined.docx"])
    vendor_name: str = Field(examples=["ApexCloud Enterprise Ltd"])
    recipient_email: str = Field(examples=["counsel@example.com"])
    recipient_name: str = Field(default="Vendor Legal Counsel")
    deal_id: Optional[str] = Field(default=None, examples=["DEAL-2026-001"])
    thread_id: Optional[str] = None


@app.post("/api/email/dispatch-counter-proposal")
def dispatch_counter_proposal(req: DispatchProposalRequest):
    """Executes EmailWriterAgent to dispatch counter-proposal email with native redlined Word document."""
    requested_name = Path(req.contract_filename).name
    # Accept an already generated redlined filename directly, which is useful
    # for the Gmail poller where the output name includes a deal/message prefix.
    direct_output = OUTPUTS_DIR / requested_name
    output_filename = f"{Path(requested_name).stem}_redlined.docx"
    redlined_path = (
        direct_output
        if direct_output.exists() and direct_output.suffix.lower() == ".docx"
        else OUTPUTS_DIR / output_filename
    )

    if not redlined_path.exists():
        sample_output = SAMPLE_DIR / output_filename
        if sample_output.exists():
            redlined_path = sample_output

    if not redlined_path.exists():
        source_path = SAMPLE_DIR / requested_name
        if not source_path.exists():
            source_path = UPLOADS_DIR / requested_name
        if not source_path.exists():
            raise HTTPException(status_code=404, detail=f"Source contract '{req.contract_filename}' not found.")
        parsed = doc_parser.execute(source_path)
        redline_result = legal_redliner.generate_redlined_docx(source_path, redlined_path, parsed.clauses)
    else:
        parsed = doc_parser.execute(redlined_path)
        actions = legal_redliner.review_clauses(parsed.clauses)
        redline_result = RedlineResult(
            contract_name=Path(req.contract_filename).stem,
            total_clauses=len(parsed.clauses),
            violations_detected=len(actions),
            critical_count=sum(1 for a in actions if a.severity.value == "CRITICAL"),
            actions=actions,
            output_docx_filename=redlined_path.name,
            output_docx_path=str(redlined_path),
            summary="Existing redline package retrieved.",
        )

    vendor = vendor_intelligence.evaluate_counterparty(req.vendor_name)
    counter_email = email_writer.compose_counter_proposal(
        redline_result=redline_result,
        vendor=vendor,
        recipient_email=req.recipient_email,
        recipient_name=req.recipient_name,
        deal_id=req.deal_id,
    )

    dispatch_result = email_writer.dispatch_email(counter_email, redlined_path)
    if req.deal_id:
        try:
            orchestrator.record_outbound(
                counter_email,
                {**dispatch_result, "thread_id": req.thread_id},
            )
        except Exception as exc:
            # The email may already be delivered; never turn a persistence
            # failure into a false delivery failure.
            print(f"[dispatch] Could not persist outbound message: {exc}")

    return {
        "status": "DISPATCHED",
        "email_details": counter_email,
        "dispatch_receipt": dispatch_result,
    }


class HumanDecisionRequest(BaseModel):
    decision: str = Field(examples=["APPROVE"])
    reviewer: str = Field(default="", examples=["reviewer@example.com"])
    notes: str = Field(default="", examples=["Approved for dispatch."])
    edited_clauses: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        examples=[[{"clause_id": "CL-1", "text": "Revised clause"}]],
    )


class CounterofferRequest(BaseModel):
    offered_price: float = Field(examples=[110000])
    target_price: Optional[float] = Field(default=None, examples=[100000])
    notes: str = Field(default="", examples=["Vendor moved $10k."])


@app.get("/api/deals")
def list_deals(limit: int = 50):
    """List persisted deals, newest first."""
    return {"deals": orchestrator.list_deals(limit)}


@app.get("/api/deals/{deal_id}")
def get_deal(deal_id: str):
    """Return the persisted state for one deal."""
    state = orchestrator.get_deal(deal_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Deal not found: {deal_id}")
    return state.model_dump(mode="json")


@app.get("/api/deals/{deal_id}/report")
def get_deal_report(deal_id: str, format: str = "json"):
    """Return a structured JSON report or a Markdown export."""
    state = orchestrator.get_deal(deal_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Deal not found: {deal_id}")
    report = build_deal_report(
        state,
        events=orchestrator.repository.events(deal_id, 200),
        history=orchestrator.repository.history(deal_id, 100),
    )
    if format.lower() == "markdown":
        return Response(
            content=report_to_markdown(report),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{deal_id}-report.md"'},
        )
    return report.model_dump(mode="json")


@app.get("/api/deals/{deal_id}/events")
def get_deal_events(deal_id: str, limit: int = 100):
    state = orchestrator.get_deal(deal_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Deal not found: {deal_id}")
    return {"events": orchestrator.repository.events(deal_id, limit)}


@app.get("/api/deals/{deal_id}/history")
def get_deal_history(deal_id: str, limit: int = 50):
    state = orchestrator.get_deal(deal_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Deal not found: {deal_id}")
    return {"history": orchestrator.repository.history(deal_id, limit)}


@app.post("/api/deals/{deal_id}/decision")
def decide_deal(deal_id: str, req: HumanDecisionRequest):
    """Approve, reject or request manual edits for a paused deal."""
    try:
        state = orchestrator.decide(
            deal_id,
            decision=req.decision,
            reviewer=req.reviewer,
            notes=req.notes,
            edited_clauses=req.edited_clauses,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.model_dump(mode="json")


@app.post("/api/deals/{deal_id}/counteroffer")
def counteroffer_deal(deal_id: str, req: CounterofferRequest):
    """Apply a vendor counteroffer and run the next bounded iteration."""
    try:
        state = orchestrator.apply_counteroffer(
            deal_id,
            offered_price=req.offered_price,
            target_price=req.target_price,
            notes=req.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.model_dump(mode="json")


@app.get("/api/helpers/logs")
def get_helpers_logs(log_type: str = "all", limit: int = 50):
    """Reads logs directly from the Helpers directory."""
    return get_recent_logs(log_type, limit)


# Mount static Dashboard
if DASHBOARD_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")
