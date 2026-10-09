from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path
import json, re, time, uuid, threading, traceback

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
STATE_PATH = DATA / "state.json"
LOCK = threading.Lock()

COMPANY_DOCS = {
    "finance_policy.md": """# Finance policy
- Every vendor invoice must match a purchase order and have a named business owner.
- Payments over USD 500 require Finance Lead approval.
- All payments require an explicit human approval in this prototype before submission.
- Never submit a payment based only on an email request; verify invoice ID, amount, vendor, and PO.
- If invoice or PO evidence is missing, stop and ask the requester. Do not invent details.
""",
    "vendor_acme.md": """# Vendor: Acme Supplies
- Vendor ID: VEN-014
- Approved status: Active
- Default business owner: Priya Shah (Operations)
- Payment terms: Net 30
""",
    "runbook.md": """# Invoice review runbook
1. Find the invoice record.
2. Confirm vendor is active.
3. Match the invoice's PO to the purchase-order register.
4. Check amount against finance policy.
5. Create a payment request draft with evidence links.
6. Stop for human approval. Never submit automatically.
7. Verify the draft exists and all required fields are present.
"""
}
INVOICES = {
    "INV-1042": {"invoice_id":"INV-1042","vendor":"Acme Supplies","vendor_id":"VEN-014","amount":420.00,"currency":"USD","po":"PO-7781","business_owner":"Priya Shah","status":"unpaid","invoice_file":"sample_invoice_INV-1042.pdf"},
    "INV-1043": {"invoice_id":"INV-1043","vendor":"Acme Supplies","vendor_id":"VEN-014","amount":875.00,"currency":"USD","po":"PO-7782","business_owner":"Priya Shah","status":"unpaid","invoice_file":"sample_invoice_INV-1043.pdf"},
    "INV-1044": {"invoice_id":"INV-1044","vendor":"Northstar Office","vendor_id":"VEN-999","amount":215.00,"currency":"USD","po":"PO-MISSING","business_owner":"Unknown","status":"unpaid","invoice_file":"sample_invoice_INV-1044.pdf"}
}
PURCHASE_ORDERS = {"PO-7781":{"po":"PO-7781","vendor_id":"VEN-014","approved":True,"amount":420.00},"PO-7782":{"po":"PO-7782","vendor_id":"VEN-014","approved":True,"amount":875.00}}

def initial_state():
    return {"tasks": [], "audit": [], "memory": {"facts": ["All payments require explicit human approval in this prototype.", "Do not invent missing invoice or purchase-order data."]}, "drafts": [], "next_id": 1}

def load_state():
    if STATE_PATH.exists():
        try: return json.loads(STATE_PATH.read_text())
        except Exception: pass
    s = initial_state(); save_state(s); return s

def save_state(s):
    STATE_PATH.write_text(json.dumps(s, indent=2))

STATE = load_state()

def audit(event, task_id=None, detail=None):
    STATE["audit"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "task_id": task_id, "event": event, "detail": detail or {}})
    save_state(STATE)

def tool_search_company_memory(query):
    q = query.lower()
    results = []
    for name, content in COMPANY_DOCS.items():
        if any(w in content.lower() for w in re.findall(r"[a-z0-9-]+", q) if len(w) > 3) or any(k in q for k in ["policy","invoice","vendor","payment","runbook","finance"]):
            results.append({"source": name, "excerpt": content[:700]})
    return results

def tool_get_invoice(invoice_id):
    return INVOICES.get(invoice_id.upper())

def tool_get_purchase_order(po_id):
    return PURCHASE_ORDERS.get(po_id.upper())

def tool_check_vendor(vendor_id):
    if vendor_id == "VEN-014":
        return {"vendor_id": vendor_id, "name":"Acme Supplies", "status":"Active"}
    if vendor_id == "VEN-999":
        return {"vendor_id": vendor_id, "name":"Northstar Office", "status":"Unknown / not in approved vendor register"}
    return {"vendor_id":vendor_id, "status":"Not found"}

def tool_create_payment_draft(invoice, po, vendor, policy):
    draft = {
        "draft_id": "PAY-" + uuid.uuid4().hex[:8].upper(),
        "invoice_id": invoice["invoice_id"], "vendor": invoice["vendor"],
        "amount": invoice["amount"], "currency": invoice["currency"],
        "po": invoice["po"], "business_owner": invoice["business_owner"],
        "vendor_status": vendor["status"], "po_verified": bool(po and po["approved"]),
        "approval_required": True,
        "finance_lead_approval_required": invoice["amount"] > 500,
        "status": "PENDING_HUMAN_APPROVAL",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "evidence": ["finance_policy.md", "runbook.md", invoice["invoice_file"], invoice["po"]]
    }
    STATE["drafts"].append(draft)
    return draft

def parse_invoice_id(goal):
    m = re.search(r"\bINV[- ]?(\d{4,})\b", goal, re.I)
    return "INV-" + m.group(1) if m else None

def make_plan(goal):
    invoice_id = parse_invoice_id(goal)
    if not invoice_id:
        return {"intent":"clarify_invoice", "steps":["Search company memory for the invoice review procedure", "Ask the requester for an invoice ID"], "invoice_id":None}
    return {"intent":"review_invoice_and_prepare_payment", "invoice_id":invoice_id, "steps":[
        "Retrieve the invoice record",
        "Read company finance policy and invoice runbook",
        "Check vendor approval status",
        "Match purchase order and invoice amount",
        "Create a payment request draft only if evidence checks pass",
        "Verify draft fields and stop for human approval"
    ]}

def execute_task(task):
    tid = task["id"]; goal = task["goal"]
    task["status"] = "RUNNING"; task["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    task["events"].append({"type":"understand","message":"Interpreted goal: "+goal})
    task["plan"] = make_plan(goal)
    audit("task_started", tid, {"goal":goal,"intent":task["plan"]["intent"]})
    if task["plan"]["intent"] == "clarify_invoice":
        mem = tool_search_company_memory("invoice policy runbook")
        task["events"].append({"type":"observe","message":"Loaded invoice runbook and finance policy from company memory."})
        task["status"] = "NEEDS_INPUT"
        task["result"] = {"message":"I need an invoice ID (for example INV-1042) before I can safely prepare a payment request.", "memory_sources":[x["source"] for x in mem]}
        audit("needs_input", tid, task["result"])
        return
    invoice_id = task["plan"]["invoice_id"]
    task["events"].append({"type":"tool","tool":"get_invoice","message":"Looking up "+invoice_id})
    invoice = tool_get_invoice(invoice_id)
    if not invoice:
        task["status"]="NEEDS_INPUT"; task["result"]={"message":f"Invoice {invoice_id} was not found. No payment draft was created."}
        task["events"].append({"type":"recovery","message":"Stopped safely because the source record is missing."})
        audit("source_missing",tid,task["result"]); return
    task["evidence"] = {"invoice":invoice}
    task["events"].append({"type":"observe","message":f"Invoice found: {invoice['vendor']} · {invoice['currency']} {invoice['amount']:.2f} · PO {invoice['po']}"})
    memory = tool_search_company_memory("invoice payment finance policy")
    task["evidence"]["memory_sources"] = [{"source":x["source"],"excerpt":x["excerpt"]} for x in memory]
    task["events"].append({"type":"tool","tool":"search_company_memory","message":"Retrieved finance policy and invoice runbook."})
    vendor = tool_check_vendor(invoice["vendor_id"])
    task["evidence"]["vendor"] = vendor
    task["events"].append({"type":"tool","tool":"check_vendor","message":f"Vendor status: {vendor['status']}"})
    po = tool_get_purchase_order(invoice["po"])
    task["evidence"]["purchase_order"] = po
    if po:
        task["events"].append({"type":"tool","tool":"get_purchase_order","message":f"PO {po['po']} found; approved={po['approved']}; amount={po['amount']:.2f}"})
    else:
        task["events"].append({"type":"recovery","message":f"PO {invoice['po']} not found. Stopping rather than guessing."})
    problems = []
    if vendor["status"] != "Active": problems.append("Vendor is not confirmed active in the vendor register.")
    if not po or not po.get("approved"): problems.append("Purchase order is missing or not approved.")
    if po and (po["vendor_id"] != invoice["vendor_id"] or abs(po["amount"]-invoice["amount"]) > 0.009): problems.append("Purchase order does not match invoice vendor or amount.")
    if problems:
        task["status"]="BLOCKED"
        task["result"]={"message":"No payment draft created because one or more verification checks failed.", "blockers":problems}
        task["events"].append({"type":"verify","message":"Preconditions failed; execution stopped safely."})
        audit("task_blocked",tid,task["result"]); return
    policy = next((x["excerpt"] for x in memory if x["source"]=="finance_policy.md"), "")
    draft = tool_create_payment_draft(invoice, po, vendor, policy)
    task["events"].append({"type":"tool","tool":"create_payment_draft","message":f"Created draft {draft['draft_id']} (not submitted)."})
    checks = {
        "invoice_id_present": bool(draft.get("invoice_id")),
        "amount_positive": draft.get("amount",0) > 0,
        "po_verified": draft.get("po_verified") is True,
        "vendor_active": draft.get("vendor_status") == "Active",
        "human_approval_required": draft.get("approval_required") is True,
        "draft_not_submitted": draft.get("status") == "PENDING_HUMAN_APPROVAL"
    }
    task["evidence"]["draft"] = draft
    task["evidence"]["verification"] = checks
    if all(checks.values()):
        task["status"]="WAITING_APPROVAL"
        task["result"]={"message":"Payment request prepared and verified. It has NOT been submitted; human approval is required.", "draft_id":draft["draft_id"], "amount":f"{draft['currency']} {draft['amount']:.2f}", "finance_lead_approval_required":draft["finance_lead_approval_required"]}
        task["events"].append({"type":"verify","message":"All six verification checks passed. Waiting for human decision."})
        audit("draft_verified_waiting_approval",tid,{"draft_id":draft["draft_id"],"checks":checks})
    else:
        task["status"]="FAILED_VERIFICATION"; task["result"]={"message":"Draft verification failed; do not approve.", "checks":checks}
        task["events"].append({"type":"verify","message":"Verification failed."})
        audit("verification_failed",tid,{"draft_id":draft["draft_id"],"checks":checks})

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send_json(self, data, code=200):
        b=json.dumps(data).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/":
            data=(ROOT/"index.html").read_bytes(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif path=="/api/state":
            with LOCK: self.send_json(STATE)
        elif path=="/api/docs":
            self.send_json({"docs":COMPANY_DOCS,"invoices":INVOICES,"purchase_orders":PURCHASE_ORDERS})
        else: self.send_json({"error":"not found"},404)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            n=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(n) or b"{}")
            with LOCK:
                if path=="/api/run":
                    goal=(body.get("goal") or "").strip()
                    if not goal: return self.send_json({"error":"Enter a goal."},400)
                    task={"id":STATE["next_id"],"goal":goal,"status":"QUEUED","created_at":time.strftime("%Y-%m-%d %H:%M:%S"),"events":[],"plan":None,"result":None,"evidence":{}}
                    STATE["next_id"]+=1; STATE["tasks"].insert(0,task); audit("task_queued",task["id"],{"goal":goal})
                    execute_task(task); save_state(STATE); return self.send_json({"task":task,"state":STATE})
                if path in ("/api/approve","/api/reject"):
                    tid=body.get("task_id")
                    task=next((t for t in STATE["tasks"] if t["id"]==tid),None)
                    if not task: return self.send_json({"error":"Task not found"},404)
                    if task["status"]!="WAITING_APPROVAL": return self.send_json({"error":"Task is not awaiting approval"},409)
                    if path=="/api/approve":
                        draft_id=task["result"]["draft_id"]
                        draft=next((d for d in STATE["drafts"] if d["draft_id"]==draft_id),None)
                        # Approval records the decision; this local PoC intentionally does not move money or call external systems.
                        draft["status"]="APPROVED_FOR_HANDOFF"
                        task["status"]="APPROVED"
                        task["result"]["message"]="Human approval recorded. This prototype does not submit or transfer money."
                        audit("human_approved",tid,{"draft_id":draft_id,"action":"approval_recorded_only"})
                        task["events"].append({"type":"human","message":"Human approved the draft. No external payment was submitted."})
                    else:
                        draft_id=task["result"]["draft_id"]
                        draft=next((d for d in STATE["drafts"] if d["draft_id"]==draft_id),None)
                        draft["status"]="REJECTED"
                        task["status"]="REJECTED"
                        task["result"]["message"]="Human rejected the payment draft. No payment was submitted."
                        audit("human_rejected",tid,{"draft_id":draft_id})
                        task["events"].append({"type":"human","message":"Human rejected the draft; no payment was submitted."})
                    save_state(STATE); return self.send_json({"task":task,"state":STATE})
                if path=="/api/reset":
                    STATE.clear(); STATE.update(initial_state()); save_state(STATE); return self.send_json(STATE)
            self.send_json({"error":"not found"},404)
        except Exception as e:
            traceback.print_exc(); self.send_json({"error":str(e)},500)

if __name__=="__main__":
    port=int(__import__("os").environ.get("PORT","8000"))
    print(f"Company Operator PoC running at http://127.0.0.1:{port}")
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
