# InternLoop AI (v0.1)

## Run
    cd backend && pip install -r requirements.txt
    DEMO_MODE=true SECRET_KEY=local uvicorn app.main:app --reload
    curl -X POST localhost:8000/api/dev/seed      # demo users: admin|mentor|intern@demo.test / demo-pass
Open http://localhost:8000 (UI) and http://localhost:8000/docs (API). Tests: `cd backend && pytest`.

## Implemented and tested (4 tests pass)
Token auth with role checks, task state machine, findings that need written evidence to close, deterministic completion
evaluator (mandatory tasks, findings, required tests, docs, final approval; optional tasks ignored), completion
revocation on reopen, idempotent notification outbox (previews only), CSV validation, audit log.

## NOT implemented
GitHub App/webhooks, PR review pipeline and LLM, sandboxed test execution, Gmail, Calendar/Meet, Google OAuth,
real-time voice, Excel (.xlsx) parsing, Alembic migrations, Celery/Redis, reports, rate limiting.
The `frontend/` UI is still the demo-mode page: it runs on its own in-browser data and is NOT yet wired to this API.
Docker files are untested. Change the demo password hashing salt and use per-user salts before real use.
