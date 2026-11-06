# Recruitment LangGraph Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan task-by-task with TDD.

**Goal:** Deliver the first independently usable migration: durable conversation workflow with explicit pending fields, contextual numeric replies, request replay protection and refresh recovery.

**Architecture:** A LangGraph turn/wait loop checkpoints conversation state to SQLite. Existing Luna calls, Pydantic validation and Jev execution remain tools; runtime callbacks hold request-scoped database resources outside checkpoints. SQL business state records the last committed request so checkpoint recovery cannot duplicate an already committed turn.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, LangGraph 1.0.5, langgraph-checkpoint-sqlite 3.0.3, native JavaScript.

**Spec:** `docs/superpowers/specs/2026-11-06-recruitment-agent.md`

## Global Constraints

- Keep Luna for reasoning and Jev for browser decisions; do not add the LangChain application framework.
- Preserve HR-specified values, authentication, tenant isolation and final human submission.
- No main merge; preserve unrelated files in the original checkout.
- This first plan covers the conversation subsystem. Browser execution checkpoints and interactive takeover are separately sequenced follow-up work, not claimed complete here.

## Review Focus

- A bare `5` is headcount only when a specific question is waiting for headcount.
- A salary reference must not become an approved employer salary.
- Other users and tabs cannot resume a task they do not own.
- Replaying the same request cannot create another batch; a different payload with the same ID is rejected.
- After restart or short-term chat expiry, the task remains resumable without restoring expired chatter.

### Task 1: Durable LangGraph conversation runner

**Files:** Create `recruitment/backend/workflow.py`; modify `requirements-recruitment.txt`; test `tests/recruitment_backend/test_workflow.py`.

**Interfaces:** `ConversationWorkflow(path)`; `run(thread_id, message, request_id, handle_turn, initial_memory)` returns `{memory, result}`; `peek(thread_id)` exposes server-owned current state.

- [ ] Write failing tests for interruption, resume, restart and isolation.
- [ ] Run focused tests and confirm failure before implementation.
- [ ] Implement turn/wait graph with native SqliteSaver and request context callbacks.
- [ ] Run focused tests, then commit.

### Task 2: Explicit pending field and contextual evidence

**Files:** Modify `assistant.py`, `memory.py`, `main.py`, `schemas.py`; extend API tests.

**Interfaces:** Planner returns optional `pending_question` with field/title/location; validated memory consumes numeric replies only for that pending field. Existing batch/search/clarify responses remain compatible.

- [ ] Add failing tests for screenshot input followed by `5`, intervening information query and ambiguous/non-headcount replies.
- [ ] Add Luna pending-question structured output and source checks; preserve a deterministic offline equivalent.
- [ ] Wire assistant turns through the graph without serializing SQL sessions, tokens or model clients.
- [ ] Persist a turn receipt atomically with batch writes; verify identical replay and conflicting replay.
- [ ] Verify restart, expiry, clear and existing recruitment API regression cases, then commit.

### Task 3: Browser-refresh conversation recovery

**Files:** Modify `ui/static/recruitment-api.js`, `ui/static/recruitment.js`; add authenticated task-state endpoint and frontend tests.

**Interfaces:** `GET /assistant/task?conversation_id=...` returns owned task summary; `RecruitmentAPI` retains conversation ID in per-tab sessionStorage and changes it for a new intake.

- [ ] Add failing tests for storage-backed ID recovery and fresh-tab isolation.
- [ ] Restore pending question/current batch on reconnect without auto-filling or submitting.
- [ ] Run frontend and backend tests, then commit.

### Task 4: Verification and delivery

- [ ] Run recruitment regression suite and an isolated real-Luna conversation using the screenshot case.
- [ ] Review ownership, transaction boundaries and request replay behavior.
- [ ] Update PR and preview only after checks pass; do not merge main.

## Subsequent plans

1. Stable external job IDs, diff-only updates and persisted browser progress, with read-back reconciliation before retry.
2. Same-page interactive browser takeover with exclusive human/agent control; CAPTCHA/login handoff and explicit resume.

## Execution ledger

- 2026-11-06: User approved the architecture and requested stepwise implementation. First subsystem isolated in managed worktree `recruitment-langgraph`; original checkout untouched. LangGraph 1.0.5 and SqliteSaver 3.0.3 installed for verification.
