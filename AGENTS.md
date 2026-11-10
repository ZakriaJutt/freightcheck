# AGENTS.md — FreightCheck

Canonical instructions for any agent working in this repository. [CLAUDE.md](CLAUDE.md) adds product guidance and defers to this file.

**State of the repository:** build milestone B1 on branch `feat/b1-foundation` (owner authorised implementation on 2026-11-11, before the Phase 0 gate; recorded in [verification-report-fixing.md](verification-report-fixing.md#9-build-milestone-b1-2026-11-11)). Present: the pure core engine, the B1 subset of the schema with forced row-level security, a minimal API for the core path, and a worker. Not present: sign-in (T-2.2.3), intake and extraction, any real provider, any UI. Commands marked **exists** in section 8 were run; all others stay **proposed**; do not report a proposed command as run.

## 1. Reading order

1. [Decision.md](Decision.md) — why, for whom, economics, go-to-market, sources, label legend.
2. [PRD.md](PRD.md) — must-haves MH-01 to MH-15, check catalogue, metrics.
3. [execution-plan.md](execution-plan.md) — phases, tasks, tests. Phase 0 comes first and needs no code.
4. [TRD.md](TRD.md), [schema.md](schema.md), [App-flow.md](App-flow.md), [design.md](design.md) — how.
5. [verification-report-fixing.md](verification-report-fixing.md) — matrix, risks R-01 to R-22, findings, outstanding items.

## 2. Sources of truth

| Topic | File |
|---|---|
| Offer, prices, funnel, stop rule, sources, labels | Decision.md |
| Requirements, roles, checks, metrics | PRD.md |
| Architecture decisions, API, jobs, security | TRD.md |
| Screens, routes, states | App-flow.md |
| Layout, copy, accessibility map | design.md |
| Tables, permissions, retention, migrations | schema.md |
| Tasks, estimates, tests, proposed commands | execution-plan.md |
| Risks, traceability, findings, self-check | verification-report-fixing.md |

State a fact once, in its home, and cite it by ID elsewhere. Never restate a risk outside the register.

## 3. Product boundaries

- No build task before the week-10 gate (T-0.5.2).
- Non-goals in PRD section 9 are binding. A new feature needs an MH and a pilot reason first (R-21).
- FreightCheck never contacts a carrier and never decides that a carrier is wrong on class, weight or accessorial support.
- Not a law firm: deadlines are shown with their source; no advice.

## 4. Architecture conventions

- Layout: `apps/web`, `apps/api`, `apps/worker`, `packages/core`, `packages/db`, `packages/platform`.
- `packages/core` is pure: no database, network, clock or environment access. Dates and "today" are passed in.
- Money is integer cents; never floats. Rounding lives only in `packages/core`.
- Checks are independent functions returning `pass`, `variance`, `exception` or `not_applicable`. An exception is never a pass and never stops another check.
- The model extracts fields and does nothing else.
- Configuration, logging, correlation, tenant context, storage keys and queue access come from `packages/platform` only.

## 5. Reuse

Before writing a helper, search `packages/core` and `packages/platform`. If it exists, use it; if it nearly fits, extend it there. Do not copy modules into the worker (R-03, R-06).

Utilities index (B1):

| Need | Use |
|---|---|
| Cents rounding, percent of cents, dollars to cents | `fc_core.money` (`round_half_up_cents`, `percent_of_cents`, `dollars_to_cents`) |
| Governing document for an invoice | `fc_core.resolver.resolve`, `resolve_linehaul` |
| Run checks, invoice roll-up, rule-parameter validation | `fc_core.checks.run_checks`, `roll_up`, `validate_rule_params` |
| Contest-by date, days left, deadline sweep | `fc_core.deadline.compute_deadline`, `days_left`, `deadline_sweep` |
| Claim status, approval guard, withdrawal note, fee lines, NSV | `fc_core.ledger.derive`, `evaluate_approval`, `withdrawal_note`, `fee_lines`, `net_settled_value` |
| Settings | `fc_platform.settings.get_settings` (unknown or missing `FC_*` keys stop startup) |
| Logging with correlation ID | `fc_platform.logging.configure_logging`, `log`, `correlation_id` |
| Tenant context | `fc_platform.tenant.tenant_transaction`, `set_tenant` |
| Storage key, signed URL, fake storage and scanner | `fc_platform.storage` |
| Today's date in apps | `fc_platform.clock.today` (never in `fc_core`) |
| Row by id under RLS, rows to core types | `fc_db.repo.get_row`, `load_invoice`, `load_context` |
| Audit row, enqueue job, check run, recompute, mark dependent claims, claim state, fee statement | `fc_db.ops` |
| Request transaction, roles, idempotency, error body | `fc_api.core` (`tenant_ctx`, `Ctx.require`, `idempotent`, `ApiError`) |
| Worker loop | `fc_worker.main.process_one`, `run_until_idle` |

## 6. Tenant safety

- Every query runs with the tenant context set; never bypass row-level security with the migration role.
- IDs from another tenant return 404. Storage keys come from the key function, never from user input.
- Operator access needs a live grant and is audited.
- Fixtures and examples are synthetic. No customer file, rate or name enters the repository, a prompt, a log or an issue.

## 7. Migrations

Single linear head; expand then contract; concurrent index builds; resumable backfills; model parity checked in CI. Details in schema.md section 9. Never edit a merged migration.

## 8. Tests

- A change to a check needs a unit test with worked arithmetic in the test name or docstring.
- A change to permissions needs IT-01 or IT-02 extended.
- A change to a screen needs the end-to-end test that covers its route.
- Commands. **Exists** (run in B1): `make venv`, `make env`, `make dev` (no Docker: migrates `freightcheck_dev`, seeds a synthetic tenant, starts the API on 8102 and the worker, waits for `/readyz`), `make migrate`, `make test-db` (drops and re-migrates `freightcheck_test`), `make test-unit`, `make test-int`, `make test`, `make lint`, `make typecheck`, `make check-boundaries`, `make check`. **Proposed**: `make db-repair`, `make backfill`, `make deploy`, `make restore`, `make fixtures`, and the Compose stack.
- Integration tests and the app connect as the non-superuser role `freightcheck_app` (NOSUPERUSER NOBYPASSRLS); the owner role is used only for migrations and to seed or truncate test fixtures.

## 9. Git hygiene

- Branch from `main` as `T-x.y.z-short-name`; one task per branch; delete after merge.
- No credentials, tokens, real customer data or generated framework files in commits.
- Do not rewrite shared history. Do not delete a branch with unmerged work without its owner's note.

## 10. Which documents to update

| When this changes | Update |
|---|---|
| A requirement | PRD (MH row, metric), traceability matrix, affected task and test in the execution plan |
| A screen or route | App-flow inventory and diagram, design section 5 and accessibility map, matrix |
| A permission or role | schema section 4, TRD API table, PRD roles, IT-02 |
| A table, field, index or constraint | schema dictionary and index table, migration task, matrix if an MH relies on it |
| A check or reason code | PRD check catalogue, schema `exception_code` and `reason_code` lists, unit test |
| A deadline or receipt rule | Decision section 4, PRD MH-09, schema `receipt_basis` and `deadline_basis`, UT-07 |
| An operating assumption (price, rate, hours, conversion) | Decision sections 7, 8, 9 and 12 together, the PRD metric targets, and the hour totals in the execution plan, with the arithmetic re-run |
| An architecture decision | TRD section 4 with date and reason; risk register if a risk moves |
| A legal rule or source | Decision sections 4 and 13 with the date consulted |

## 11. Completion reporting

Report only what was verified. Say "not run" for any test not executed, "proposed" for any command not implemented, and "unverified" for any claim with no source opened. Never mark a finding fixed; record the fix and leave the retest to the reviewer.
