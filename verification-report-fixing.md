# Verification, findings and fixes — FreightCheck carrier invoice audit

## 1. Status summary

| Item | Status |
|---|---|
| Documents | Ten files written by Author A on 2026-11-10 |
| Application | Build milestone B1 on branch `feat/b1-foundation` (2026-11-11), not pushed, not independently reviewed. Results in [section 9](#9-build-milestone-b1-2026-11-11); every check not listed there as passed stays `Not run` |
| Independent review | Round 1 done on 2026-11-10: 17 findings (0 blocker, 12 major, 5 minor). Fixes recorded in section 6. Retest on 2026-11-10 (`freightcheck-round2.md`): 13 closed, 0 still open, 4 open by design (F-004, F-005, F-009, F-017), no new findings; verdicts transcribed into section 6 by the lead |
| Customer evidence | None. No interview, audit, message or payment |
| Highest-consequence failure | **Wrong-basis dispute sent** ([PRD.md](PRD.md#11-highest-cost-user-mistakes)) |

## 2. Checks performed on the documents (author self-check)

Done by the author with a scratch script kept outside the repository, and by reading. These are document checks only. Results are in the [self-check log](#7-author-self-check-log).

| Check | Method |
|---|---|
| Exactly ten required files, no others | Directory listing |
| Relative links and heading anchors resolve | Script |
| Every `MH-`, `T-`, `S-`, `AD-`, `UT-`, `IT-`, `E2E-`, `R-`, `SRC-`, `C-` ID that is cited is defined | Script |
| Every MH appears in the traceability matrix | Script |
| 22 risk rows, numbered as the specification, each with an existing task ID | Script |
| Screens, routes, tables, API paths and tasks agree across files | Script for IDs; reading for content |
| Economics, funnel, binomial figures, ramp table, hour totals, fixture arithmetic, contrast ratios | Recomputed by script |
| Brief figures quoted exactly; departures recorded | Reading against the brief |
| Mermaid blocks parse by inspection; commands labelled proposed; no credentials; synthetic names only | Reading and pattern search |

## 3. Application checks planned for future implementation

Definitions: [execution-plan.md](execution-plan.md#7-test-catalogue). B1 results per ID are in [section 9](#9-build-milestone-b1-2026-11-11).

| Group | IDs | Status |
|---|---|---|
| Unit | UT-01 to UT-15 | B1: UT-01 to UT-11, UT-13, UT-15 passed; UT-12, UT-14 Not run |
| Integration | IT-01 to IT-22 | B1: IT-01, IT-06, IT-07, IT-08, IT-13, IT-16, IT-19, IT-20 passed; IT-17 partly (single head only); others Not run |
| End-to-end | E2E-01 to E2E-08 | Not run in a browser. E2E-02 passed in an API-level form only |
| Manual accessibility checks | [design.md](design.md#7-accessibility-map) | Not run |
| Security checks against the ASVS list | [TRD.md](TRD.md#84-security-controls-and-accepted-gaps) | Not run |
| Quality targets | [TRD.md](TRD.md#10-quality-requirements) | Not run |

## 4. Traceability matrix

| MH | Screen or API | Design decision | Schema or permission | Task | Planned test |
|---|---|---|---|---|---|
| MH-01 | S-06; POST `/hooks/inbound-email`, `/files` | AD-05 | `intake_message`, `source_file` uniqueness | T-3.1.1, T-3.1.2 | IT-03, IT-04, IT-05 |
| MH-02 | S-08; PATCH `/invoices/{id}/fields` | AD-02 | `extraction`, `field_revision`, `invoice.fields_confirmed` | T-3.2.1, T-3.2.2 | UT-12, E2E-08 |
| MH-03 | S-03, S-04, S-17; `/rate-documents`, `/rate-documents/{id}/confirm`, `/rate-documents/{id}/revise` | AD-01 | `rate_document` exclusion constraint, `date_basis`, `revision`; confirm is Approver-only | T-4.1.1, T-5.2.5 | UT-02, IT-02 |
| MH-04 | S-07, S-08; POST `/invoices/{id}/rerun` | AD-01, AD-08 | `check_result`, `invoice.status` | T-4.2.1, T-4.2.2, T-4.2.4, T-4.2.6 | UT-01, UT-04, UT-06, UT-08, UT-11 |
| MH-05 | S-08 | AD-01 | `invoice` and `ap_payment` duplicate indexes | T-4.2.5 | UT-05 |
| MH-06 | S-05, S-08; `/fuel-index`, `/fuel-index/{id}/confirm` | AD-01 | `rate_rule` fuel types, `fuel_index_price` status and revision | T-4.1.2, T-4.2.3 | UT-03, IT-20 |
| MH-07 | S-09; POST `/findings/{id}/decision` | AD-01 | `finding`, tenant thresholds | T-5.1.1 | E2E-01, E2E-04 |
| MH-08 | S-10; POST `/claims/{id}/approve`, `/claims/{id}/sent` | AD-03, AD-04 | `claim.basis_snapshot`, `stale_basis`, `basis_changed_after_send`, `late_override_reason`; approve is Approver-only | T-5.1.2, T-5.1.3 | UT-14, IT-06, IT-16, IT-19, IT-20, E2E-02 |
| MH-09 | S-03, S-08, S-10, S-11 | AD-01 | `invoice.receipt_date`, `receipt_basis`, `contest_by`, `deadline_basis`; `carrier_account.dispute_window_*`; `notification` | T-4.2.7, T-5.1.3 | UT-07, UT-15, IT-19 |
| MH-10 | S-11, S-12; `/claims/{id}/events`, `/claims/{id}/settlements` | AD-09 | `claim` with `origin`, `claim_event` with `reason_code`, `settlement` evidence constraint | T-5.1.4, T-5.1.5 | UT-09, IT-07, IT-20, E2E-01 |
| MH-11 | S-13; `/time-entries` | AD-08 | `time_entry`, `tenant.hourly_rate_cents` | T-5.2.1 | UT-10 |
| MH-12 | S-14; GET `/reports/nsv` | AD-08 | `settlement` window index; `claim.origin` | T-5.2.2 | UT-10, E2E-01 |
| MH-13 | S-01, S-15, S-16; `/auth/*`, `/users`, `/tenant/settings`, `/audit-events`, `/operator-grants` | AD-06, AD-07 | RLS; permission table; `user_session`, `auth_token`, `recovery_code`, `audit_event` | T-2.2.2, T-2.2.3, T-2.2.4 | IT-01, IT-02, IT-15, IT-22, E2E-06 |
| MH-14 | S-15; POST `/exports`, `/deletion-requests` | AD-10 | `data_request`; retention table | T-5.2.4, T-3.2.3 | IT-10 |
| MH-15 | S-14, S-18; GET `/fee-statements`, `/reconciliation` | AD-08 | `fee_statement`, `fee_statement_line`, `ap_payment.reconcile_state`, `settlement.ap_payment_id` | T-5.2.3 | UT-10, IT-07, IT-21 |

## 5. Production risk register

Single home of the register. Numbering follows the specification.

| ID | Impact on this buyer and data | Prevention | Detection signal | Test and expected outcome | Task |
|---|---|---|---|---|---|
| R-01 | A re-delivered inbound email or a late-entered carrier acknowledgment moves a claim back from "partly accepted" to "acknowledged", or re-runs extraction over fields a clerk already confirmed | Status derived from events (AD-09); versioned job transitions | Count of refused transitions | UT-09: late event does not regress; IT-03: one message from duplicate deliveries B1 2026-11-11: UT-09 passed (late acknowledgment and duplicate decision do not regress); IT-03 Not run. | T-3.1.3 |
| R-02 | Approve or upload times out at the proxy while the server finishes; the Approver clicks again and the carrier ledger shows two approvals or two invoices | `Idempotency-Key` on every creating POST; stored results | Idempotent replays per day | IT-04: retry returns the first result, one file | T-3.1.3 |
| R-03 | A second rounding or deadline helper outside `packages/core` makes the ledger total differ from the report by cents and a contest-by date differ between screens | Core owns money, dates, NSV; boundary lint | Lint failure; search for decimal rounding outside core | `make check-boundaries` (proposed) fails on a planted duplicate helper | T-2.1.1 |
| R-04 | Web or worker imports API internals, so a change to authorization code breaks the packet job unnoticed | Enforced import rules (AD-11) | Lint failure | Planted forbidden import fails CI B1 2026-11-11: `tools/test_check_boundaries.py` passed (planted forbidden imports reported); `make check-boundaries` 0 violations. Not yet wired into CI. | T-2.1.1 |
| R-05 | One shipper's contract rates or invoices are readable by another shipper through an API ID, a worker job or a file link | RLS plus one tenant context module; tenant-prefixed keys (AD-06) | Failed-authorization log entries; RLS-empty anomalies | IT-01: 404 or no rows on every path B1 2026-11-11: IT-01 passed (API 404 on 12 foreign-id requests, worker job fails closed, signed link bound to key, zero rows without tenant context, cross-tenant insert refused by RLS). | T-2.2.2 |
| R-06 | Worker runs with its own copy of tolerance or public URL settings, so checks disagree with what the screen says | One settings module in `packages/platform` | Settings hash logged at start by api and worker differs | IT-13: hashes equal | T-2.1.4 |
| R-07 | Worker crashes at start on a web-only import; intake stalls silently while 180-day windows run | Worker image without web packages; shared logger | Worker heartbeat missing; queue age alert | IT-13: worker starts and runs a job B1 2026-11-11: IT-13 passed with web modules blocked at import, not with a separate image. | T-2.1.4 |
| R-08 | The no-overlap constraint on rate documents exists in a migration but not in the models; a rebuilt environment accepts two governing versions and produces a wrong-basis claim | Parity check in CI | Parity job fails | IT-08: no drift B1 2026-11-11: IT-08 passed (no column/index/FK drift; check and exclusion constraints and forced RLS match the models). | T-2.2.1 |
| R-09 | A backfill of contest-by dates stops halfway; half the invoices show no deadline | Resumable backfills with a progress row | Progress row not complete | IT-09: restart completes, no row twice | T-2.2.1 |
| R-10 | Two branches add migrations; deploy order differs between staging and production and the claim tables diverge | Single linear head enforced | CI two-heads failure | IT-17: fails on two heads B1 2026-11-11: single-head assertion passed; the two-branch CI case of IT-17 Not run. | T-2.2.1 |
| R-11 | Building an index on `invoice` or `check_result` locks intake during a deploy in business hours | Concurrent builds, lock timeout, `NOT VALID` then validate | Lock-wait metrics during deploy | IT-17: plain index on a populated table fails CI | T-2.2.1 |
| R-12 | A wrong claim cannot be traced back to its extraction and rule because the correlation ID stops at the queue; or contract rates appear in logs | ID carried in job rows and provider calls; logs hold IDs only | Log lines without correlation ID; pattern scan for amounts | IT-13: ID present end to end, no amounts B1 2026-11-11: IT-13 passed (request correlation ID on the worker's job lines; no amount fields in logs). | T-2.1.4 |
| R-13 | Two shippers upload `invoice.pdf`; one overwrites the other and a dispute packet carries another shipper's invoice | Generated keys with tenant, purpose, source and UUID; unique `storage_key` | Unique violation count | UT-13: keys differ and contain no user filename B1 2026-11-11: UT-13 passed. | T-2.2.5 |
| R-14 | Lookback files from a prospect that never signed remain after the promised 30 days, in Phase 0 in the founder's data room and later in the application | Phase 0: data-handling sheet and weekly deletion check (T-0.1.6, T-0.3.5). Application: `expires_at` and retention sweep | Sheet rows past their delete-by date; count of rows past expiry | Phase 0: deletion log matches the sheet. IT-10: expired objects and rows gone | T-3.2.3 |
| R-15 | Recreating the database container on the single VPS loses every claim, decision and settlement record | Named volume; WAL archive; restore drill | Backup-missing alert; volume check at start | IT-18: rows survive recreation; IT-12: restore within target | T-2.1.2 |
| R-16 | Evidence links in a packet or export point at `localhost` or a container name and fail for the Approver | `PUBLIC_BASE_URL` in one builder | Link host check in smoke test | IT-11: host equals the public URL | T-2.2.5 |
| R-17 | A developer starts api without worker or scanner; uploads sit unprocessed and are mistaken for extraction bugs | `make dev` with health checks | Readiness endpoint lists dependencies | IT-18: one command, all healthy | T-2.1.2 |
| R-18 | An Auditor loses twenty corrected fields on refresh, or Back re-submits an approval | State in URL and server; per-user drafts; POST then redirect | Client error reports on navigation | E2E-03: state kept, no re-submit | T-3.2.2 |
| R-19 | A 90-day batch silently skips unreadable invoices, so the audit looks cleaner than it is, or a retry duplicates the invoices that succeeded | Per-file results and summary; retry failures only; file hash uniqueness | Batch counts not summing to files received | IT-05: 18 done, 2 failed, retry touches 2 | T-3.1.4 |
| R-20 | "Accepted" is read as "Settled" and the Owner believes money has arrived; or a stale route shows an old ledger | Money triple with fixed labels; route crawl | Support questions; dead-link crawl | E2E-07: no dead route; T-1.1.3 walkthrough completed unaided | T-1.1.3 |
| R-21 | Effort goes into a TMS, model-written disputes or integrations nobody paid for while the settlement ledger is unfinished | Non-goals; every task links an MH or risk; scope cut list | Tasks without a linked need | Document check: every task row names an MH, risk or operational need | T-1.1.1 |
| R-22 | A branch named `fix` or a stale release branch hides which code runs in the pilot, or unmerged rule changes are deleted | Branch naming by task ID; protected `main`; stale report | Weekly stale-branch report | Push of a non-conforming branch name fails the CI check; report lists branches older than 14 days | T-2.1.3 |

None of the 22 is inapplicable. R-15 and R-16 would shrink if hosting moved to managed services; R-05 would grow if a shared cache or search index were added.

## 6. Findings register

Findings by the independent reviewer, round 1 (2026-11-10). Authors record fixes; reviewers record retest results.

| Issue ID | Severity | File and location | Evidence | Impact | Owner | Fix | Retest result |
|---|---|---|---|---|---|---|---|
| F-001 | major | Decision 2, 3, 12.7 | Warp's pages claim audit against shipper-loaded rate tables, fuel, reweigh, reclass, duplicates, dispute queue | Gap overstated | Author A | Both pages re-read. Warp row, counterargument, remaining-gap table and objection 1 restated; decision now says little checking gap remains and what is left; new discovery question 6 and disqualifier | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-002 | major | schema, PRD MH-09, plan UT-07 | Inbox time could serve as receipt of the bill | Out-of-time dispute | Author A | Receipt defined as the shipper's receipt; evidence order (carrier transmission, AP stamp, user entry with note), else invoice-date proxy; inbox time never used; approval past contest-by refused unless overridden; daily sweep, reminders, expiry; UT-07 cases (e) and (f), UT-15, IT-19 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-003 | major | TRD 6.2, 5.1, 12; schema; UT-03 | Six holes in the wrong-basis guard | Wrong rate or fuel week enters | Author A | (a) `date_basis` on every rate document, `GOVERNING_DATE_MISSING`; (b) confirmation per document, `revision` separate from `version`; (c) `basis_changed_after_send`, IT-20; (d) index values confirmed by an Approver, revisions, `INDEX_PRICE_UNCONFIRMED`, correction marks claims; (e) UT-03 tests the week rule; (f) `reason_code` on events; TRD 6.2 redrawn to match E2E-02 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-004 | major | Decision 9; plan 1 | Clause C reads after the build | Decisive question cannot stop the build | Author A | Clause C0 at end of W16 gates Phase 5 and outreach (T-0.5.4); Decision 9 states that the build starts before any settled credit and shows hours and money at risk before C0 and before C; alternative left to the founder (open decision 7) | Open by design: Phases 1-4 (252-392 h) are committed on clauses A and B' before any settled credit; disclosed with money at risk; needs the founder's choice and the C0 and C readings (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead). Open by design: Phases 1-4 are still committed on clauses A and B′ |
| F-005 | major | Decision 5.2; PRD 10; T-0.4.4 | Hand-run pilots hide the shipper's work | NSV describes a done-for-you service | Author A | Hand-run adjustment: founder minutes on field confirmation and queue review added to T at the shipper's rate; self-serve NSV used for clause C; total founder hours reported; bias stated | Open by design: self-serve NSV rests on a hand-run adjustment until one pilot month runs on the software (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead). Evidence needed: one pilot month on the software |
| F-006 | major | Decision 7.3-7.5, 8, 12.8; PRD 10 | Ramp carried every pilot forward | Headline held only at 100% conversion | Author A | Pilot to recurring 75% in PRD target, funnel, CAC and ramp; refunds to leavers in the ramp; sensitivity at 100% and 50%; support cost flagged as unreconciled. Numbers that moved are in SC-12 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-007 | major | Decision 5.1, 5.2; PRD 10 | Lookback claims had no scope, fee or count | Oldest invoices outside every rule | Author A | Decision 5.1 paragraph: ten drafts free at readout, rest for signers, no fee on flat, 20% on gainshare, non-signers keep drafts and data is deleted; `claim.origin`; MH-10 and MH-12 criteria; NSV split; refund test and clause C on pilot-period claims | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-008 | major | Decision 5.2; MH-15; schema | Fee base self-reported | Fee leakage | Author A | Order-form duty to supply monthly AP credit export through the 120-day tail, fallback fee on accepted amounts; reconciliation screen S-18, `ap_payment.kind` and `reconcile_state`, IT-21; hand version in T-0.4.4 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-009 | major | PRD 8.1; verification 8; UT-02 | Base tariff the shipper may not hold | Main check may not run | Author A | SMC3 page opened (SRC-11); Decision 4 row; `BASE_TARIFF_UNAVAILABLE` with discount and minimum still checked; discovery question 7 and disqualifier; T-0.3.4 metric and PRD metric; outstanding item | Open by design: share of LTL invoices with a resolvable base rate is unknown until T-0.3.4 measures it (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead). Evidence needed: share of invoices with a resolvable base rate |
| F-010 | major | plan Phase 0; Decision 12.4 | Real rate data in an undefined shared folder | Confidentiality promise unbacked | Author A | T-0.1.6 data room before any file (region, access, second factor, no email, sheet) and T-0.3.5 deletion log; R-14 extended; Decision 12.4 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-011 | major | TRD 5.1, 8.1; schema; App-flow | Missing identity and settings contracts | MH-13 not buildable | Author A | Endpoints for invitations, members, roles, settings, reset, enrolment, recovery codes, factor reset; tables `user_session`, `auth_token`, `recovery_code`, `idempotency_record`, `notification`, `totp_last_step`; lost-factor process stated and V6.4.4 listed as not met; IT-22 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-012 | major | design 7, 8 | Read-only below 768 px contradicted reflow intent | Core screens unusable at 200% zoom | Author A | One rule: every screen operable to 320 px with stacked panes; read-only rule removed; manual check at 1280 px and 200% | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-013 | minor | TRD 3, 8.5 | "No tenant names" in page images | Overclaim | Author A | Reworded: images show the shipper's name and rates; terms required; exposure accepted and disclosed | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-014 | minor | TRD 8.4, 8.5 | No email authentication, CSRF, missing "security notes" | Spoofed intake or send record | Author A | DMARC-aligned check for intake and BCC; anti-forgery header (V3.5.1); lockout policy written in TRD 8.1; IT-22 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-015 | minor | Decision 3.1; T-0.2.2 | Unsourced range; questions missing | Unlabelled number | Author A | Range marked pure assumption with its origin stated; seven discovery questions listed in Decision 12.4; demo script and referral offer noted as not carried | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-016 | minor | plan 4, M1.1, M0.5; design 6; Decision 5.2 | Four inconsistencies | Ambiguity | Author A | Phase 1 entry aligned on a signed pilot; "v2" in design; pilot covers 5 carriers in full and the rest for duplicates and arithmetic; rule for fewer than 5 audits at W10 | Closed (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead) |
| F-017 | minor | Decision 4, 12.5 | Board framing; subject line | Deadline wording; subject accuracy | Author A | Decision 4 row states the framing and what was not researched; T-0.1.1 carries the questions; subject line now matches the lookback scope | Open by design: what act contests a bill under 49 U.S.C. 13710(a)(3) and how the bar is applied await the lawyer (T-0.1.1) (independent reviewer retest, 2026-11-10, `freightcheck-round2.md`; verdict transcribed by the lead). Open until the lawyer answers |

Nothing in the reviewer's findings is disputed.

## 7. Author self-check log

Not a substitute for independent review.

| ID | Check | Result |
|---|---|---|
| SC-01 | Ten required files present, no others | Pass |
| SC-02 | Relative links and anchors | Pass |
| SC-03 | Every cited ID is defined; every MH in the matrix; 22 risk rows with existing tasks | Pass, re-run after fix round 1 |
| SC-04 | Unit economics, break-even, funnel, CAC, binomial figures recomputed | Pass, re-run after fix round 1. Brief's model reproduces with CAC 600; plan uses 555.56 per recurring account |
| SC-05 | Ramp table and troughs recomputed from the stated rules | Pass |
| SC-06 | Go-to-market checkpoints, hours and accounts equal the funnel: 500 → 20 → 9 → 5.4 → 1.8 pilots → 1.35 recurring | Pass |
| SC-07 | Hour totals in the estimate summary equal the sum of task rows | Pass: Phase 0 313-408, build 421-653, phases 1-4 252-392 |
| SC-08 | Fixture arithmetic (UT-01, UT-03, UT-07, UT-10, UT-11) and contrast ratios recomputed | Pass |
| SC-09 | Sources opened today match what is written; blocked sources named | Pass; three pages blocked (403). Fix round 1: both Warp pages re-read, SMC3 page opened (SRC-11) |
| SC-10 | Defects found by the author and corrected before hand-off | Reply-count probability corrected to under 0.1%; objection 2 corrected to state both fee-only and time-inclusive thresholds; ramp break-even account count corrected to 23.80; retention row for fee statements separated; hand pilot delivery hours raised and T-0.4.6 added so Phase 0 hours match 1.8 accounts; Warp TMS row corrected to say the brief did mention a free TMS |
| SC-12 | Numbers that moved in fix round 1 | CAC 416.67 → 555.56; payback 1.78 → 2.37 months; churn × CAC 14.58 → 19.44; break-even counts unchanged at 3 and 23; trough with founder 75,126 at M28 → 108,639 at M48; first positive month M29 → M49; trough without founder 3,599 at M7 → 4,333 at M8; account ceiling 41.1 → 30.9; downside CAC 1,666.67 → 3,333.33 with no break-even by formula; prospects touched by break-even 10,500 → 18,500; build hours 411-639 → 421-653; Phase 0 hours 307-398 → 313-408 |
| SC-11 | Length against the 16,000-20,000 word target | About 22,400 words before fix round 1 and more after it, excluding table punctuation and diagrams; over target, kept for completeness |

## 8. Outstanding items

Items documents cannot close.

| Item | Needed from | Blocks |
|---|---|---|
| Any measured recovery or settlement rate | Phase 0 audits and pilots | The decisive question |
| Count of distinct reachable prospects and the qualifying share | T-0.1.2, T-0.2.2 | Break-even feasibility |
| Legal confirmation: CASL exclusion for US recipients, CAN-SPAM content, directory terms | Lawyer, T-0.1.1 | Any outreach |
| What act "contests" a bill under 49 U.S.C. 13710(a)(3), whether the 180 days run from receipt or bill date in practice, how courts apply the bar (F-017) | Lawyer, T-0.1.1 | MH-09 wording; any contest-by date shown to a buyer |
| Whether broker invoices have any default contest period; effect of contract waivers | Lawyer | MH-09 wording |
| Whether any shipper pays for what Warp's free TMS does not claim: no-TMS intake, lookback, settlement ledger (F-001) | Discovery question 6; pilots | The decision itself |
| Share of LTL invoices priced off a base tariff the shipper does not hold; licence terms of such tariffs (F-009) | T-0.3.4; SMC3 terms | C-02 |
| Settled credits before the build: only clause C0 at W16 and clause C at day 120 measure them (F-004) | Carrier decisions on Phase 0 claims | Phases 5-7; the decisive question |
| Self-serve NSV rests on a hand-run adjustment until a pilot month runs on the software (F-005) | Pilots after release | Clause C confidence |
| Pilot-to-recurring rate; 75% is assumed and under about that level break-even with founder pay never arrives (F-006) | Pilots | Economics |
| Reliability of carrier-date evidence in forwarded mail (F-002) | Pilot mailboxes | Share of invoices on the proxy date |
| NMFC text and carrier rules tariffs not read (licensed or per carrier) | Shipper's documents | C-05, C-06 behaviour |
| Each carrier's fuel index, region and effective-day rule | Shipper's fuel schedules | MH-06 |
| Contingency auditors' actual percentages | Quotes | Comparison in Decision 3.1 |
| Provider prices and no-training terms | T-1.1.4 | Variable cost of 44.39 |
| Region of the founder's VPS | Founder | AD-10 |
| Cross-border invoicing and tax | Accountant | Pilot invoices |
| Founder's agreement to proposals marked `[P]` | Founder | T-0.1.5, T-0.4.1 |
| Blocked sources: Supply Chain 24/7 article, ThomasNet, IMA membership page | Manual browsing | Error-rate claim; list building |
| ASVS items stated as not met: V6.4.4, V13.3.1, V6.3.3 at L3, V8.4.2, V8.2.4 | Later phase | Security posture beyond pilot |
| Page-image viewer has no text alternative for scans | Later phase | Accessibility for blind reviewers |

## 9. Build milestone B1 (2026-11-11)

**Authorisation.** On 2026-11-11 the owner authorised implementation in all ten repositories at once, before this product's Phase 0 sales gate (T-0.5.2, week 10) has passed. The decision text in Decision.md is unchanged; the gate itself is still open.

**Environment.** Python 3.12 venv at `.venv`; PostgreSQL 16 on localhost, databases `freightcheck_dev` and `freightcheck_test`; application role `freightcheck_app` (NOSUPERUSER, NOBYPASSRLS) used by the API, the worker and every isolation test; every tenant table has ENABLE and FORCE ROW LEVEL SECURITY. API port 8102. Redis (index 1 assigned) is not used: the TRD keeps the queue in Postgres (AD-05). No frontend was built (port 3102 unused). Docker is not available, so the Compose stack (T-2.1.2) stays proposed and `make dev` starts the services directly.

**Tasks implemented** (B1 subsets where marked):

| Task | What exists |
|---|---|
| T-2.1.1 | Layout `apps/api`, `apps/worker`, `packages/core`, `packages/db`, `packages/platform`; `tools/check_boundaries.py` with a planted-violation test. CI wiring and code-owners note not done |
| T-2.1.2 (adapted) | `make dev`: role bootstrap, migrate, seed a synthetic tenant, API and worker, wait for `/readyz`; exits non-zero naming the failed service. Compose, MinIO, ClamAV proposed |
| T-2.1.4 | Typed settings (unknown or missing `FC_*` keys stop startup), JSON logs with correlation ID from request to job, worker without web modules |
| T-2.2.1 (subset) | Migration `0001` for 22 tables of schema.md needed by the core; exclusion constraint on confirmed rate documents; parity test. Backfill runner and concurrent-index check not built |
| T-2.2.2 | RLS policies on every tenant table, forced; one tenant context module used by API and worker; `fc_claim_next_job` for the worker |
| T-2.2.4 | Audit rows in the same transaction as the change; rollback test |
| T-2.2.5 | Storage key function, signed URL with `PUBLIC_BASE_URL`, fake local storage and fake scanner |
| T-3.1.3 (subset) | Job table, worker loop, idempotency keys for jobs; `Idempotency-Key` on every API POST with stored replay |
| T-4.1.1, T-4.1.2 (API subset) | Rate documents with date basis, rules, per-document confirmation, revisions, overlap refusal naming the revision, supersede, marking of dependent claims; fuel index values with confirmation and corrections as revisions |
| T-4.1.3 | Governing-rate resolver |
| T-4.2.1 to T-4.2.5 | Check registry and runner, exception codes, invoice roll-up; C-02 with base-tariff case; C-07; C-03; C-04 amount and support question; C-01 against invoice history |
| T-4.2.6 (part) | C-08 late-rebill question only; C-05 and C-06 not built |
| T-4.2.7 (core) | Contest-by calculator with receipt evidence order, proxy, contract term, broker case; sweep logic (UT-15). The daily sweep job and reminder sending are not built |
| T-5.1.3 | Approve with recompute, stale-basis and contest-by guards with override; send record; basis-changed-after-send flag, banner and withdrawal note; redraft. BCC capture not built |
| T-5.1.4 (API subset) | Events with reason codes, settlements with required document, reversal, derived status, claim origin |
| T-5.2.2, T-5.2.3 (core and job only) | NSV and gainshare arithmetic; fee statement job with reversal lines. Report screen, AP-credit reconciliation (IT-21) not built |

**Test results.** All run on 2026-11-11 from a clean test database.

| Command | Result |
|---|---|
| `make test-db` (drops and re-creates schema `public` of `freightcheck_test`, migrates to `0001`) | OK |
| `make test-unit` (`packages/core/tests`, `packages/platform/tests`, `tools`) | 47 passed, 0 failed |
| `make test-int` (`apps/api/tests`, real Postgres, app role, fake providers) | 26 passed, 0 failed |
| `make lint` (ruff check and format check) | Passed |
| `make typecheck` (mypy; `fc_core` strict) | Passed, 29 source files |
| `make check-boundaries` | 0 violations |
| `DEV_SMOKE=1 tools/dev.sh` | API ready on 8102, worker started |

| Test ID | Test (file) | Result |
|---|---|---|
| UT-01 | `test_ut01_*` (`packages/core/tests/test_checks.py`) | Passed: 175.56 expected, 27.72 variance, identical over 1,000 runs |
| UT-02 | `TestUT02Resolver` | Passed |
| UT-03 | `TestUT03Fuel` | Passed: 14 Mar uses 3.78 (50.03, 12.99); 9 Mar uses 3.74 (49.16, 13.86); missing, unconfirmed, no week rule each an exception while linehaul still varies |
| UT-04 | `test_ut04_*` | Passed |
| UT-05 | `test_ut05_*` | Passed |
| UT-06 | `test_ut06_*` (3 tests) | Passed, including a crashing check recorded as `ENGINE_ERROR` |
| UT-07 | `TestUT07Deadlines` (`test_deadline_ledger.py`) | Passed (a)-(f), plus user note and missing invoice date |
| UT-08 | `test_ut08_*` | Passed |
| UT-09 | `test_ut09_*` | Passed |
| UT-10 | `test_ut10_*` | Passed: time 393.33, NSV 1,557.67, fees 30.35, reversal −6.35 |
| UT-11 | `test_ut11_*` | Passed: 226 days; arithmetic 1.00 shown as pass |
| UT-13 | `packages/platform/tests/test_storage_keys.py` | Passed |
| UT-15 | `TestUT15Sweep` | Passed (sweep logic; the job is not built) |
| IT-01 | `apps/api/tests/test_isolation.py` (5 tests) | Passed |
| IT-06 | `test_it06_*` (`test_core_path.py`) | Passed: 409 `STALE_BASIS`, old 12.99 and new 12.11 on the fuel line, nothing approved |
| IT-07 | `test_it07_*` | Passed: refused without document; short-pay refused without acceptance; settled 27.72; reversal gives a −5.54 line in the next statement |
| IT-08 | `test_it08_*` (`test_schema_worker.py`, 2 tests) | Passed |
| IT-13 | `test_it13_*` | Passed with web modules blocked by an import hook (not a separate image) |
| IT-16 | `test_it16_*` | Passed: concurrent approvals give one 200 and one 409 with current state; double-click replays |
| IT-17 | `test_it17_single_migration_head` | Partly: single head only; two-branch CI and non-concurrent index check Not run |
| IT-19 | `test_it19_*` (2 tests) | Passed: 409 `PAST_CONTEST_BY`, override stored, audited, counted |
| IT-20 | `test_it20_*` | Passed: flag with 40.71 to 41.58, withdrawal note, metric 1, draft on the same value stale, withdrawal clears the flag and keeps the metric |
| E2E-02 | `test_e2e02_api_level_*` | API-level form only: stale send blocked with amounts, sent claim flagged with note, re-approval unblocks. The browser test is Not run |

Every other UT, IT and E2E ID stays `Not run`.

**Blocked or not built in B1, and why.**

| Task | Reason |
|---|---|
| T-2.2.3 sign-in, TOTP, invitations, sessions lifecycle; IT-02, IT-15, IT-22 | Not in B1 scope (foundation and core only). Tests seed sessions directly; no sign-in endpoint exists |
| T-3.1.1, T-3.1.2 intake, T-3.2.1 extraction, UT-12 | Need the inbound email and extraction providers (sandbox accounts, no-training terms: T-1.1.4); only interfaces and fakes are allowed in B1 |
| T-3.1.4 AP import, C-01 against AP payments, IT-21 | Not built; C-01 compares invoice history only |
| T-5.1.2 templates and packets, UT-14 | Not built |
| T-5.2.4, T-5.2.5, exports, deletion, operator grants | Not built |
| Deployment, backups, restore (IT-12, IT-18 with Compose) | Out of B1 scope; Docker not available |
| Any legal answer (F-017, broker periods) | Needs a lawyer; the calculator implements MH-09 as written |

**Document changes made from implementation** (not re-reviewed):

| File | Change | Reason |
|---|---|---|
| schema.md | `user_session.active_tenant_id`; `claim.basis_changed_after_send_at`; `fc_claim_next_job` noted on `job`; `check_result.check_code` sub-results and `arithmetic.basis`; `basis_snapshot` written at drafting too | RLS needs the tenant before the membership read; the wrong-basis metric must survive a withdrawal; the worker cannot read jobs before it knows the tenant; marking drafts needs their basis |
| TRD.md 5.1 | Added POST `/invoices` (manual keying), POST `/claims/{id}/redraft`, GET `/reports/basis-metrics`, GET `/files/raw`; contest-by unknown treated as past it at approval | A stale draft had no path to re-approval; IT-19 and IT-20 metrics needed a reader; fail closed when no date exists |
| PRD.md 8.1 | C-02 and C-04 report sub-results `C-02-BASE` and `C-04-SUPPORT` | One result per check and line could not hold both parts |
| AGENTS.md, CLAUDE.md | State lines, utilities index, existing commands | Accuracy |

**Found in the documents.** AGENTS.md section 9 names branches `T-x.y.z-short-name`; the build instruction named `feat/b1-foundation`, which was used. The schema's unique key on `invoice (tenant_id, carrier_account_id, invoice_number, revision_of)` does not stop a second original with the same number (nulls are distinct), which is what lets C-01 see a re-sent invoice; kept as written. The C-03 base when the expected linehaul is unavailable is not specified; B1 uses the billed net linehaul and labels it `base_source: billed_linehaul` in the arithmetic.
