# AGENTS.md — FreightCheck

Canonical instructions for any agent working in this repository. [CLAUDE.md](CLAUDE.md) adds product guidance and defers to this file.

**State of the repository:** planning documents only. No application, script, migration or environment exists. Every command below is **proposed** until an implementation lands; do not report a proposed command as run.

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
- Proposed commands: `make dev`, `make test`, `make check-boundaries`, `make migrate`. All proposed.

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
