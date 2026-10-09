# Operator — AI Company Runtime PoC

A runnable, local proof of concept for the core **Goal → Understand → Plan → Execute → Observe → Adapt → Verify → Human approval** loop.

## What works

- Browser UI for submitting a business outcome and inspecting the execution trace.
- Tool registry implemented as Python functions: company-memory search, invoice lookup, vendor check, purchase-order lookup, payment-draft creation.
- Company memory via three policy/runbook/vendor documents; relevant documents are retrieved during a run.
- Planning based on the user's goal, including asking for missing invoice context.
- Real branching: a valid invoice creates a draft; missing/unapproved vendor or PO blocks the workflow; unknown invoice asks for input.
- Six verification checks before a draft reaches the approval gate.
- Human approve/reject controls.
- Persistent tasks, drafts, runtime memory facts, and audit events in `data/state.json`.
- Sample tasks for happy path, high-value approval, missing evidence, and missing user input.

## Run

Requires Python 3.10+ and no third-party packages.

```bash
python app.py
```

Open <http://127.0.0.1:8000>.

## Try these cases

1. **Happy path:** `Review invoice INV-1042 and prepare a payment request`
2. **Extra approval threshold:** `Review invoice INV-1043 and prepare a payment request` (USD 875; Finance Lead approval flag)
3. **Safe failure:** `Review invoice INV-1044 and prepare a payment request` (unknown vendor and missing PO; no draft)
4. **Clarification:** `Prepare a payment request` (no invoice ID; asks for missing context)
5. **Unknown source:** `Review invoice INV-9999` (not found; no draft)

## Architecture

- `app.py`: HTTP server, task runtime, planner, tool functions, policy checks, verification, approval handler, audit log.
- `index.html`: self-contained UI.
- `data/state.json`: persistent local task/audit/draft state (created on first run).

The planner is deterministic by design so the PoC is reproducible without API keys. To make it LLM-driven, replace `make_plan()` with a structured-output planner, then validate its proposed steps against a tool allowlist and policy engine. Keep the executor, approval gate, and verification independent of the model.

## Safety and limitations

- Uses synthetic sample records and a local JSON state file.
- Approve/reject records the human decision only; **it never submits a payment or transfers money**.
- Not a production-ready multi-user service: no authentication, tenant isolation, database, secrets manager, real connectors, sandboxed computer use, or distributed queue.
- For production, add a durable queue (e.g. PostgreSQL-backed jobs), tenant-scoped memory, signed tool permissions, idempotency keys, bounded retries, secret isolation, model/provider adapters, real connector integrations, and end-to-end verification.
