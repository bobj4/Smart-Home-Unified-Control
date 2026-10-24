# Smart home control tasks

Tasks marked (owner) are done by the owner, not the local model.

## Current phase: Phase 0, local model and workflow setup

- [ ] 0.1 (owner) Confirm the laptop operating system, install Hermes Agent,
  and decide whether the agent's commands run in an isolated terminal backend.
- [ ] 0.2 (owner) Download the shortlisted models and start `llama-server` as
  described in `docs/LOCAL_MODEL.md`. Confirm Hermes accepts the 64K context.
- [ ] 0.3 (owner) Run bake-off tasks B1 to B5 on each model and record the
  results in `docs/LOCAL_MODEL.md`.
- [ ] 0.4 (owner) Choose the model. Record the decision and the final settings.
- [ ] 0.5 (owner) Create the repository with the project documents and make the
  first commit. Start Hermes from the repository root and confirm it loads
  `AGENTS.md` without reporting it as blocked.
- [ ] 0.6 Run one trivial task through build, task report, security review, and
  fixes.
- [ ] 0.7 (owner) Answer the Phase 0 questions in `SPEC.md`.

## Next phase: Phase 1, secure backend foundation

- [x] 1.1 Scaffold `backend/` with a FastAPI app and `GET /health`. Tests pass.
- [x] 1.2 Pin the development tools in a requirements file with hashes (SEC-70)
  and create `scripts/check.py`, which runs lint, types, tests, security lint,
  and dependency audit and exits non-zero on any failure.
- [ ] 1.3 Load configuration from environment variables with validation. The
  app refuses to start on an invalid combination, such as no login method
  enabled (SEC-02).
- [ ] 1.4 Add the data layer: SQLAlchemy models for home, user, session, and
  audit event, plus the first Alembic migration. Tests pass.
- [ ] 1.5 Add Argon2id password hashing and a command to create the first
  owner (SEC-01).
- [ ] 1.6 Add login and logout with server-side sessions, secure cookies,
  request-forgery protection, and rate limiting that uses the trusted client
  address (SEC-03 to SEC-05, SEC-26). Tests cover each.
- [ ] 1.7 Add TOTP enrollment and verification, code-reuse prevention, and
  single-use recovery codes (SEC-06, SEC-07). Tests pass.
- [ ] 1.8 Add the authorization dependency: deny by default, with home scoping.
  Add the cross-home access test for homes (SEC-10, SEC-11).
- [ ] 1.9 Add the audit log writer. Tests show secrets never appear in it
  (SEC-32, SEC-80).
- [ ] 1.10 Add the device model, the `DeviceIntegration` interface, and a
  simulated integration used by tests.
- [ ] 1.11 Add security headers and an origin allow-list with no origins
  allowed by default (SEC-14, SEC-24). Tests pass.
- [ ] 1.12 Add a non-root container file for the backend and deployment notes.
  The container is not exposed outside the node (SEC-52).
- [ ] 1.13 Request security review 1 against SEC-01 to SEC-07, SEC-10 to
  SEC-12, SEC-14, SEC-20 to SEC-22, SEC-24, SEC-26, SEC-30, SEC-32, SEC-52,
  and SEC-70.

## Completion rule

Move current-phase tasks to completed only after their acceptance criteria and
required checks pass. Keep manual hardware tests and external settings pending
until the owner confirms them in a task report.