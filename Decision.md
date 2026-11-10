# Decision — FreightCheck carrier invoice audit

Status: planning document. No customer has been interviewed, no audit has been run, no message has been sent. Nothing here is legal, tax or investment advice.

Decisive pilot question: **do settled carrier credits exceed the shipper's setup, review and dispute costs?** Errors found do not answer it; only credits a carrier has actually granted, net of the fee and the shipper's own time, do.

## 0. How numbers are labelled

| Label | Meaning |
|---|---|
| `[C]` | Stated in the chat or its decision brief. Where the brief marks a figure as research or as output of the site's economics model, that is said. Unit-economics inputs in the brief are assumptions, never findings. |
| `[S: SRC-nn]` | Read by the author at the named source on 2026-11-10 ([section 13](#13-sources-and-assumptions)). |
| `[A]` | Assumption with no source. |
| `[P]` | Proposal by the author; the founder has not agreed to it. |

Computed figures show their inputs. Currency is USD unless marked. Anything the brief does not settle is "not decided in chat".

## 1. Proposed decision

**Test, do not build yet** `[C: research verdict "test"]`. Run Phase 0 of [execution-plan.md](execution-plan.md): 500 first-touch emails over five weeks, hand-run lookback audits, hand-run paid pilots, and the stop rule in [section 9](#9-stop-rule). Build starts only if the rule does not fire.

| Item | Decision | Label |
|---|---|---|
| Launch market | US Midwest: manufacturers and distributors in Illinois, Indiana, Ohio, Wisconsin shipping 100-500 LTL loads a month with 3-10 carriers | `[C]` |
| Daily user | AP clerk or logistics coordinator who approves freight bills | `[C]` |
| Buyer | Logistics manager or controller | `[C]` |
| Budget owner | CFO or VP operations | `[C]` |
| Current workaround | Clerk matches invoice to rate confirmation by eye or pays on trust; some rely on a TMS variance flag; larger shippers outsource | `[C]` |
| Seller | One founder in Vancouver, selling remotely into the Chicago region | `[C]` |
| Product | Forwarding inbox, extraction, deterministic match to the governing rate, dispute draft, claim ledger to settlement | `[C]` plus ledger `[P]` |

## 2. Why the buyer might pay, and why not

**Strongest supporting evidence.** A vendor calculator states typical recovery of 3% to 7% of LTL spend and 1% to 3% of truckload spend, described as "typical industry ranges" with no named study, assuming invoices were never checked `[S: SRC-08]`. This is a vendor-advertised range, not a measured customer outcome. No measured outcome was found.

**Strongest counterargument.** A free alternative already covers most of what FreightCheck would check. Warp's pages say its free TMS lets a shipper register outside carriers "with contracted rate tables", audits outside carriers "against the rate table you load" with contracted discount tiers and minimum charges, checks fuel against the DOE diesel index for the ship week, checks accessorials against what the BOL requested, checks reweigh and reclass against the BOL, holds a PRO billed twice, and offers approval and dispute actions `[S: SRC-10]`. A shipper willing to record its freight in that TMS gets continuing audit at no fee. Separately, a contingency auditor files the claims itself for a percentage of the amount recovered `[S: SRC-13]`, which costs the shipper almost no time. FreightCheck's flat fee only wins if settled credits are large enough and the shipper's own dispute time is small enough; the brief's own commercial risk is that recoverable amounts are "nearer 1% than 3-7%" `[C]`.

Reported but not opened: trade press puts incorrect billing at roughly 5-6% of freight invoices `[C: secondary; page returned 403 again on 2026-11-10]`. It is used below only to size the shipper's review workload.

## 3. Competitor gap: what was read and what was not

Vendor-advertised features only; no customer outcome was measured for any vendor.

| Alternative | What its own page says | Price read | Departure from the brief |
|---|---|---|---|
| Warp savings calculator `[S: SRC-08]` | A calculator; "does not read your invoices" | Free | Brief cited this URL as the free audit tool. It is not one. |
| Warp free invoice audit tool `[S: SRC-09]` | Upload CSV or PDF, no login; re-quotes each shipment at live Warp rates and shows savings "shipping with Warp" | Free | It benchmarks against Warp's price, not the shipper's contract. No dispute step stated. |
| Warp TMS and AI invoice audit `[S: SRC-10]`, re-read for fix round 1 | Free TMS. Shipper registers its carriers "with their contracted rate tables"; outside carriers audited "against the rate table you load", with contracted discount tiers and minimum charges; fuel against the DOE diesel index for the ship week; accessorials against what the BOL requested; billed weight and class against the BOL; a PRO billed twice is held; flagged items go to a dispute queue with documentation (stated for Warp's own invoices; "approval and dispute actions" for the rest); QuickBooks CSV export. Parcel and EDI not live | Free | Brief noted that a free TMS exists but not its audit features. The first version of this document understated them (F-001). |
| AuditFreight `[S: SRC-12]` | AI audit against the negotiated contract. Fee on **identified findings**, "not contingent on carrier dispute outcomes": 20% Starter (up to 5 invoices a month), 15% Growth, 8% Enterprise (by invitation) | % of findings | Brief said 20% of findings, invitation only. Tiers and the 5-invoice cap were not in the brief. It is not recovery-based. |
| Williams & Associates post-audit `[S: SRC-13]` | Files claims in the shipper's name; refunds paid by the carrier to the shipper; fee is "a percentage of the amount recovered"; truck claims limited to 180 days | Percentage not published | Not in the brief. A true recovery-based alternative. |
| Freightview `[S: SRC-14]` | TMS; USD 149 a month for 0-50 shipments, monthly billing; higher bands by phone; no mention of invoice audit | USD 149/month | Matches the brief. |
| Intelligent Audit `[S: SRC-15]` | No price; Catalyst for smaller shippers is free for 90 days and is a parcel product | Not public | Brief said no self-serve plan. A small-shipper entry exists, for parcel, not LTL. |
| Loop `[S: SRC-16]` | No price; demo request only; home page claims "80% of carrier invoices contain errors" and 5-7% spend reduction | Not public | Matches. The claims are vendor claims. |
| Cass `[S: SRC-17]` | No price; USD 37 billion freight spend processed a year | Not public | Matches. |

**Remaining gap after reading** `[P]`. Little of the checking is unique. Against what Warp's pages claim, FreightCheck's planned checks on contract rates, discounts, minimums, fuel week, reweigh, reclass and duplicates are **not** a gap. What the pages do not state, and so what is left:

| Possible gap | Basis | Weight |
|---|---|---|
| Fuel against the carrier's own surcharge schedule and effective-day rule, not only the DOE index | Page names only the DOE index | Small; unverified in the product |
| Accessorial amounts against the carrier's accessorial schedule | Page describes a check against BOL requests only | Small |
| No need to record freight in a TMS; forward invoices only | Warp's audit runs inside its TMS | Real for shippers who will not adopt a TMS |
| A lookback over invoices already paid | Not stated | Unknown |
| A ledger of claimed, accepted and settled amounts, the carrier's 30- and 60-day dates, and net settled value | Not stated; no mention of carrier decisions, credit memos or settlements | The main difference |
| Neutrality: Warp sells freight, so its tools are a lead magnet `[C]` | Brief | Soft |

Silence on a marketing page is not proof of absence; the product was not used. **If a prospect will adopt a free TMS, FreightCheck has little to offer beyond the settlement ledger**, and a ledger alone may not carry USD 199-299 a month. Whether any shipper pays for the remainder is unproven and is the first thing discovery calls must test (section 12.4, question 6).

### 3.1 Like-for-like cost to one shipper

Same shipper, same month, USD. Scenario `[C: brief's modelled assumption]`: USD 1.5M LTL spend a year, 3% recoverable, 60% of disputes won. Identified = 1,500,000 × 3% ÷ 12 = 3,750 a month. Settled = 3,750 × 60% = 2,250 a month. Downside uses 1% recoverable: identified 1,250, settled 750.

Shipper time `[A]`: 400 invoices a month `[C]`; 30 flags reviewed at 5 minutes and 22 claims handled at 20 minutes (22 = 5.5% of 400, from the unopened 5-6% claim); loaded clerk cost USD 40 an hour. (30 × 5 + 22 × 20) ÷ 60 × 40 = **USD 393.33 a month**. One-time setup 6 hours = USD 240.

| Option | Fee basis | Fee, base | Net of fee and time, base | Fee, downside | Net, downside |
|---|---|---|---|---|---|
| FreightCheck Pro flat | 299 a month `[C]` | 299.00 | 2,250 − 299 − 393.33 = **1,557.67** | 299.00 | 750 − 299 − 393.33 = **57.67** |
| FreightCheck gainshare | 20% of credits received `[C]` | 450.00 | 2,250 − 450 − 393.33 = **1,406.67** | 150.00 | **206.67** |
| AuditFreight Growth | 15% of identified `[S: SRC-12]` | 562.50 | 2,250 − 562.50 − 393.33 = **1,294.17** | 187.50 | **169.17** |
| Contingency auditor | 20% to 50% of recovered `[A]`: scenario range only; a guide seen in a search summary gave it without a source and was not opened, and SRC-13 publishes no percentage | 450 to 1,125 | 1,800 to 1,125, shipper time near zero | 150 to 375 | 600 to 375 |
| Warp TMS | 0 `[S: SRC-10]` | 0 | 2,250 − time, only for freight recorded in the TMS with its rate tables loaded; the shipper disputes and tracks credits itself | 0 | 750 − time |

What the table says honestly: with the same win rate, a contingency auditor at 20% beats FreightCheck in both cases because the shipper spends no time; FreightCheck's flat fee wins only against contingency rates above about 31% in the base case (2,250 − 1,557.67 = 692.33; 692.33 ÷ 2,250). In the downside the flat plan leaves USD 57.67 a month and the first month's setup cost erases it. The flat fee equals the gainshare fee at settled credits of 299 ÷ 20% = USD 1,495 a month (1,245 at the pilot price). A shipper who expects less will choose gainshare, so gainshare accounts are adversely selected.

## 4. Rules that shape the product (primary sources)

| Rule | What the source says | Product consequence |
|---|---|---|
| Shipper's contest window | A shipper must contest the original or a subsequent bill within 180 days of **receipt of the bill** "in order to have the right to contest such charges"; the subsection is framed around asking the Board to decide `[S: SRC-01]`. One vendor page read by the author counts from the date of the freight bill instead `[S: SRC-13]`; the reviewer reports a second. What act counts as contesting, and how courts apply the bar, were not researched and go to the lawyer (T-0.1.1) | Receipt means the **shipper's** receipt of the carrier's bill, never the time FreightCheck received a forward. Accepted evidence, earliest wins: the carrier's original transmission date, the shipper's AP received stamp, or a user entry with a note. With none, the invoice date is used as the earliest defensible date and flagged. Approval after the contest-by date is refused unless the Approver overrides with a reason (MH-09). A 90-day lookback fits inside the window only on that basis. |
| Base tariff | Many LTL pricing agreements are a discount off a third-party base rate; SMC3 calls CzarLite "the most widely used neutral LTL base rate for pricing agreements in North America" `[S: SRC-11]`. Its licence terms were not read | If the shipper does not hold the base rates, C-02 cannot recompute linehaul and returns an exception; discount percentage and minimum are still checked against the gross charge printed on the invoice. The share of invoices with a resolvable base rate is unknown and is measured in T-0.3.4 |
| Carrier rebilling | A carrier must issue any bill for additional charges within 180 days of receipt of the original bill `[S: SRC-01]` | Check C-08 flags a later rebill for human review. |
| Overcharge claims | Written claim filed with the collecting carrier, accompanied by the freight bill; acknowledgment within 30 days of receipt; pay, decline or settle within 60 days of receipt unless extended in writing; denial must state reasons `[S: SRC-03]` | Claim ledger shows 30-day and 60-day expected dates. Carriers may lawfully still be deciding at pilot day 60. |
| Court action | Civil action to recover overcharges within 18 months after accrual; accrual is delivery or tender of delivery; extended 6 months from written disallowance `[S: SRC-02]` | Shown as a date only. FreightCheck gives no legal advice. |
| Contract waiver | Carrier and shipper may waive rights and remedies in writing, except registration, insurance and safety `[S: SRC-04]` | A contract term overrides the default only when entered with its source document. |
| Brokers | Sections above address motor carriers. A broker's invoice is governed by the broker contract `[A]` | No default deadline is asserted for a broker invoice; the user is asked for the contract term and other checks still run. |
| NMFC | Published by NMFTA; access through ClassIT+; text not opened `[S: SRC-23]` | Class rules are entered from the shipper's documents. FreightCheck does not reproduce the NMFC. |
| Fuel index | EIA publishes diesel prices weekly `[S: SRC-20]`; which index, region and effective day a carrier uses is in that carrier's schedule, not checked for any carrier | Fuel check takes its basis from the carrier's schedule; a missing basis is an exception. |

## 5. Offer, channel and pilot

Chat, verbatim (Roman Urdu) and translated:

- Offer (owner's chat, translated): a free audit of the last 90 days, then USD 249 a month or 20% of the recovered amount `[C]`.
- Funnel: "400 → 16 → 7 demos → 1-2 customers. Cycle 35 din." `[C]`
- Pilot `[C: research]`: free 90-day lookback, then a 60-day pilot at USD 249 a month or 20% of credits received, customer's choice.

| Item | Value | Label |
|---|---|---|
| Channel | Cold email offering the free lookback; backup: fractional CFO and freight consultant referrals | `[C]` |
| Prospect sources | ThomasNet (IL, IN, OH, WI), Illinois Manufacturers' Association list, LinkedIn Sales Navigator, NASSTRAC and CSCMP Chicago Roundtable | `[C]` |
| Sample inputs | 90 days of carrier invoices, the rate documents that governed them, and an AP payment export | `[C]` plus export `[P]` |
| Pilot duration | 60 days | `[C]` |
| Pilot price | USD 249 a month, or 20% of credits received | `[C]` |
| Sales cycle | 35 days from first touch to signed pilot | `[C]` |

### 5.1 What the free lookback covers `[P]`

A hand audit of every invoice for 90 days is 300 to 1,500 invoices at the target volume, too many for one person. Proposed scope, stated to the buyer in the first message: duplicates across all 90 days from the AP export; every invoice of the latest full calendar month (the "audit month") line by line; in the other two months only invoices with accessorial, reweigh or reclass lines; at most 400 invoices line-audited. "Errors per month" in the stop rule is the audit-month total. Nothing is extrapolated. This narrows the chat's offer and needs the founder's agreement.

**Lookback findings and claims** `[P]`. The report lists every finding with its contest-by date. Dispute drafts for the ten largest findings above USD 25 are handed over at the readout, free, whether or not the shipper signs; a signer gets the rest in pilot week 1. On the flat option lookback claims carry no extra fee. On the gainshare option the 20% applies to lookback settlements too, since the chat's wording is "20% of the recovered amount" `[C]`. A shipper that does not sign keeps the report and drafts, owes nothing, and its files are deleted 30 days after the readout (T-0.3.5). Lookback and pilot-period claims are tagged by origin and reported separately: lookback settlements are a one-time clean-up, pilot-period settlements indicate the recurring value.

### 5.2 What the pilot price buys `[P]`

| Term | Proposal |
|---|---|
| Scope | Every carrier invoice received in 60 days, up to 500 a month. Full checks for up to 5 carriers chosen by spend (the profile has 3-10); for the others only duplicates and arithmetic. Exception list; dispute drafts with evidence; claim ledger covering lookback and pilot claims; reports at day 60 and day 120 |
| Signer and payer | Controller signs, or CFO where the controller lacks authority; the shipper's AP pays by card or ACH |
| Data supplier | Logistics manager supplies rate documents and carrier contacts; AP clerk forwards invoices |
| Flat option | USD 249 invoiced at signing and at day 30, due on receipt |
| Gainshare option | 20% of settlements recorded in the month with carrier evidence, invoiced monthly in arrears; claims drafted in the pilot stay billable for 120 days after it ends. The order form obliges the shipper to supply a monthly AP export of carrier credits and refunds during the term and that 120-day tail; unmatched carrier credits are reconciled to claims before each statement (MH-15). If the export stops, the fee for open claims is computed on amounts the carrier accepted in writing |
| Delivery before software | The founder runs the same checks in a spreadsheet and keeps the ledger by hand (T-0.4.3, T-0.4.4). **Bias:** the founder then does the field confirmation and queue review that the product assigns to the shipper's clerk, so the shipper's logged time is too low. The founder logs minutes on those two activities per account; they are added at the shipper's hourly rate to give the self-serve figure used in clause C ([PRD.md](PRD.md#10-success-metrics)) |
| Pilot ends | Day 60. The report shows claimed, accepted, settled and pending amounts and the shipper's logged time |
| Step to recurring | By day 60 the signer picks a tier by invoice volume or continues gainshare on an order form; first recurring charge on day 61 |

**Refund criterion (flat option)** `[P]`: at day 120 after pilot start, if settlements with carrier evidence on pilot-period claims total less than the USD 498 paid, FreightCheck refunds the difference. It applies only if the buyer decided every flagged claim within 10 business days and sent at least 90% by amount of the claims it approved within 5 business days, both read from the ledger. The test uses carrier documents, so neither side can void it by opinion; a buyer who sends no disputes does not qualify. Lookback settlements are not counted in the test.

## 6. One paying account, one billable unit

- **One paying account** `[P]`: one shipper legal entity with a signed order form, counted from the first month FreightCheck invoices it. All its locations and carriers are one account.
- **One billable unit** `[P]`: flat plans, one account-month within the tier's allowance of audited carrier invoices (a distinct carrier and invoice number run through the checks; duplicates and re-sent copies do not count). Gainshare, one US dollar of settlement with carrier evidence.

Not decided in chat: what separates the tiers. Proposal:

| Tier | Price `[C]` | Allowance `[P]` | Share of accounts `[A]` |
|---|---|---|---|
| Starter | 199 a month | up to 150 invoices | 40% |
| Pro | 299 a month | up to 500 | 55% |
| Business | 699 a month | up to 1,500 | 5% |

Reconciliation: 0.40 × 199 + 0.55 × 299 + 0.05 × 699 = 79.60 + 164.45 + 34.95 = **279.00**, the brief's assumed revenue per account `[C: model]`. This holds only with monthly billing, no 15% annual discount `[C]` and no gainshare accounts. The pilot price of 249 `[C: launch price]` sits between Starter and Pro; each account's first two months bring 30 less than 279, which the ramp subtracts. Usage: the mix implies 0.40 × 100 + 0.55 × 400 + 0.05 × 1,000 = 310 invoices per account; the cost note assumes 400 at 2 cents `[C]` = USD 8, while the brief's AI line is 9. The 9 is used; the 1 dollar gap is not explained in the brief.

## 7. Unit economics

### 7.1 Cost categories

| Category | Value | Label |
|---|---|---|
| Startup cost | CAD 15,000 = 150 hours at CAD 100 `[C: model]`; ÷ 1.38 = USD 10,869.57. The plan's own build estimate is 421 to 653 hours ([execution-plan.md](execution-plan.md#5-estimate-summary)); at the same rate that is CAD 42,100 to 65,300 = USD 30,507.25 to 47,318.84. The brief's figure is not reconciled. | `[C]` / `[P]` |
| Monthly fixed cost, no founder | USD 550 | `[C: model]` |
| Founder compensation | CAD 6,000 a month ÷ 1.38 = USD 4,347.83 | `[C]` |
| Variable cost per account-month | USD 44.39 | `[C: model]` |
| Initial acquisition cost | USD 1.50 per prospect touched (USD 150 per 100 `[C]`) | `[C]` |
| Churn replacement | monthly churn × CAC | derived |

Exchange rate: scenario assumption 1 USD = 1.38 CAD `[C: model]`, direction CAD to USD (divide), scenario date 2026-11-10, not a sourced rate. For reference the Bank of Canada daily rate on 2026-11-09 was 1.4123 `[S: SRC-19]`, which would give 6,000 ÷ 1.4123 = USD 4,248.39. The scenario rate is used everywhere.

### 7.2 Gross profit per account-month, base case

Direct cost `[C: model]`: AI 9 + API 2 + hosting 3 + storage 1 + messaging 1 + support 20 + payment (2.9% × 279 + 0.30 = 8.39) = **44.39**. Gross profit = 279 − 44.39 = **234.61** (84.1%).

### 7.3 CAC: one definition

**CAC = outreach cash cost ÷ recurring paying accounts**, where a recurring account is a pilot that signs the day-61 order form. Founder hours are not in CAC; they are in the founder compensation line and shown as hours in section 12.

The chat's funnel on its own rates `[C]`: 400 × 4% = 16 replies; × 45% = 7.2 calls; × 20% = 1.44 customers. Cost 400 × 1.50 = 600, so 600 ÷ 1.44 = 416.67 per **paid pilot**. The chat does not say what share of pilots stays. This document assumes 75% `[A]`, the same figure as the target in [PRD.md](PRD.md#10-success-metrics): 1.44 × 0.75 = 1.08 recurring accounts, CAC = 600 ÷ 1.08 = **USD 555.56**.

The brief's model uses CAC 600 `[C: model]`. With 600 its outputs reproduce: payback 600 ÷ 234.61 = 2.56 months; LTV 234.61 ÷ 0.035 = 6,703; break-even ceil(550 ÷ 213.61) = 3 and ceil(4,897.83 ÷ 213.61) = 23. The model and the funnel do not reconcile exactly. **This document uses 555.56 everywhere** so that the funnel, the go-to-market plan and the ramp give the same accounts. (The first version used 416.67 and carried every pilot forward; corrected under F-006.)

### 7.4 Base and downside cases

| Input or result | Base | Downside | Label |
|---|---|---|---|
| Reply rate | 4% | 2% | `[C]` / `[A]` |
| Reply to call | 45% | 45% | `[C]` |
| Call to delivered audit | 60% | 60% | `[A]` |
| Audit to paid pilot | 33.33% | 16.67% | `[A]` |
| Call to paid pilot (product of the two rows above) | 20% | 10% | `[C]` / `[A]` |
| Paid pilots per 100 prospects | 100 × 0.04 × 0.45 × 0.20 = 0.36 | 100 × 0.02 × 0.45 × 0.10 = 0.09 | derived |
| Pilot to recurring | 75% | 50% | `[A]` |
| Recurring accounts per 100 prospects | 0.27 | 0.045 | derived |
| CAC | 150 ÷ 0.27 = 555.56 | 150 ÷ 0.045 = 3,333.33 | derived |
| Revenue per account-month | 279 | 199 (all Starter) | `[C]` / `[A]` |
| Support cost | 20 | 40 | `[C]` / `[A]` |
| Payment cost | 8.39 | 2.9% × 199 + 0.30 = 6.07 | derived |
| Direct cost | 44.39 | 16 + 40 + 6.07 = 62.07 | derived |
| Gross profit | 234.61 (84.1%) | 136.93 (68.8%) | derived |
| Monthly churn after conversion | 3.5% | 7% | `[C]` / `[A]` |
| Payback | 555.56 ÷ 234.61 = 2.37 months | 3,333.33 ÷ 136.93 = 24.34 months | derived |
| LTV | 234.61 ÷ 0.035 = 6,703 | 136.93 ÷ 0.07 = 1,956 | derived |
| Churn × CAC | 19.44 | 233.33 | derived |
| Gross profit − churn × CAC | 215.17 | −96.40 | derived |
| Break-even, no founder | 550 ÷ 215.17 = 2.56 → **3** | **none**: replacing a churned account costs more than an account earns | derived |
| Break-even, with founder | 4,897.83 ÷ 215.17 = 22.76 → **23** | **none** | derived |

The split of the chat's 20% into 60% and 33.33% is the author's; it yields 4.32 audits per 400 prospects, close to the brief's four lookbacks in its weekly plan. The break-even formula assumes outreach only replaces churn; the ramp below does not.

### 7.5 Cash required during the ramp

Rules: one model month = 4 weeks (13 blocks a year treated as 12 months; revenue and cost are overstated alike by one twelfth). Outreach runs at 100 first touches a week in weeks 1-5, pauses for weeks 6-16 while one founder audits, decides and builds, and resumes in week 17 if clause C0 passes (section 9). A prospect touched in week w pays for a pilot in week w + 5 (35 days `[C]`). Of each month's new pilots, 25% leave two months later (pilot to recurring 75% `[A]`) and, conservatively, each leaver is refunded the USD 498 two months after that `[A]`. Accounts(m) = accounts(m − 1) × (1 − churn) + new(m) − 0.25 × new(m − 2). Revenue = accounts × 279 − 30 × (new(m) + new(m − 1)) − 498 × 0.25 × new(m − 4). Variable cost = accounts × 44.39. Acquisition = touches × 1.50. Fixed 550; founder 4,347.83. Release is planned for week 21, so week-17 prospects reach their audit on the software. Month 1 is the month outreach starts.

Base case, USD:

| Month | Touches | New pilots | Accounts | Revenue | Variable | Acquisition | Net, no founder | Net, with founder | Cumulative, no founder | Cumulative, with founder |
|---|---|---|---|---|---|---|---|---|---|---|
| M1 | 400 | 0.00 | 0.00 | 0 | 0 | 600 | -1,150 | -5,498 | -1,150 | -5,498 |
| M2 | 100 | 1.08 | 1.08 | 269 | 48 | 150 | -479 | -4,827 | -1,629 | -10,325 |
| M3 | 0 | 0.72 | 1.76 | 438 | 78 | 0 | -191 | -4,538 | -1,820 | -14,863 |
| M4 | 0 | 0.00 | 1.43 | 378 | 64 | 0 | -236 | -4,584 | -2,056 | -19,447 |
| M5 | 400 | 0.00 | 1.20 | 335 | 53 | 600 | -868 | -5,216 | -2,924 | -24,663 |
| M6 | 400 | 1.08 | 2.24 | 458 | 99 | 600 | -792 | -5,140 | -3,716 | -29,803 |
| M7 | 400 | 1.44 | 3.60 | 839 | 160 | 600 | -471 | -4,818 | -4,186 | -34,621 |
| M8 | 400 | 1.44 | 4.64 | 1,209 | 206 | 600 | -147 | -4,495 | -4,333 | -39,116 |
| M9 | 400 | 1.44 | 5.56 | 1,465 | 247 | 600 | 68 | -4,279 | -4,265 | -43,395 |
| M10 | 400 | 1.44 | 6.45 | 1,578 | 286 | 600 | 142 | -4,206 | -4,123 | -47,601 |
| M11 | 400 | 1.44 | 7.30 | 1,771 | 324 | 600 | 297 | -4,051 | -3,826 | -51,652 |
| M12 | 400 | 1.44 | 8.13 | 2,001 | 361 | 600 | 491 | -3,857 | -3,335 | -55,509 |
| M18 | 400 | 1.44 | 12.50 | 3,222 | 555 | 600 | 1,517 | -2,831 | 3,308 | -74,953 |
| M24 | 400 | 1.44 | 16.03 | 4,208 | 712 | 600 | 2,346 | -2,002 | 15,398 | -88,950 |
| M36 | 400 | 1.44 | 21.19 | 5,646 | 941 | 600 | 3,556 | -792 | 51,925 | -104,597 |
| M48 | 400 | 1.44 | 24.55 | 6,585 | 1,090 | 600 | 4,345 | -3 | 100,057 | -108,639 |
| M49 | 400 | 1.44 | 24.77 | 6,646 | 1,100 | 600 | 4,397 | 49 | 104,453 | -108,590 |

- **Cash trough without founder compensation: USD 4,333 at M8**; with the brief's startup cost, 4,333 + 10,869.57 = USD 15,203. Monthly net is positive from M9.
- **Cash trough with founder compensation: USD 108,639 at M48**; with the brief's startup cost, USD 119,509; with the plan's own build estimate, 108,639 + 30,507.25 to 47,318.84 = USD 139,146 to 155,958. Monthly net first turns positive in **M49**, four years after outreach starts, at 24.77 accounts. The ramp needs (5,497.83 + 86.40 + 179.28) ÷ 234.61 = 24.57 accounts, more than the formula's 22.76, because it keeps buying growth (600 a month), carries the pilot discount (30 × 2.88 = 86.40) and refunds leavers (0.25 × 1.44 × 498 = 179.28).
- Accounts can never exceed 1.44 × 0.75 ÷ 0.035 = 30.9 at this outreach volume, so the margin over 24.57 is thin.

Sensitivity to pilot conversion, same rules: at 100% and no refunds (the first version's assumption) the trough is USD 75,126 at M28 and net turns positive in M29; **at 50% the ceiling is 1.44 × 0.5 ÷ 0.035 = 20.6 accounts and break-even with founder compensation never arrives** (cumulative −103,911 at M24, −165,593 at M48).

Downside ramp (0.09 pilots per 100, 50% conversion, churn 7%, 199 revenue, 62.07 direct cost, refunds as above, no pilot discount): accounts 0.27 at M2, 1.34 at M12, 2.05 at M24, limit 0.36 × 0.5 ÷ 0.07 = 2.57. Cumulative −11,418 at M12 and −23,375 at M24 without founder, −63,592 and −127,723 with. **The downside never reaches break-even, with or without founder compensation.**

**Plain reading:** with founder compensation the base case needs four years and more than USD 108,000 of cash, and it survives only if at least about three in four pilots convert. One founder at 100 first touches a week is not a viable path to a founder's salary on these assumptions; the product makes sense only if Phase 0 shows better conversion, a higher price, or a cheaper channel.

Missing inputs: the share of accounts choosing gainshare and the lag from claim to settlement (gainshare revenue arrives at least 30 to 60 days late `[S: SRC-03]`); processing cost of free audits once software exists (about 900 invoices × 0.02 = USD 18 an audit `[A]`, four audits per recurring account, not in the chat's CAC); cross-border tax treatment. **Support is unreconciled:** the model's USD 20 per account-month `[C: model]` does not cover rate-rule entry by an operator (about 4 hours a carrier `[A]`, so 12 to 40 hours for a new account with 3-10 carriers) or the 21 hours an account-month of hand delivery before release; both are founder time inside the compensation line, and at 1.44 new pilots a month they consume roughly 17 to 58 founder hours a month.

## 8. Funnel from distinct reachable prospects

**The number of distinct reachable prospects is unknown.** Upper bound: 22,450 establishments with 20 to 249 employees in manufacturing (14,698) and wholesale trade (7,752) across Illinois, Indiana, Ohio and Wisconsin `[S: SRC-18]`. These are establishments, not firms, and nothing shows what share ships 100-500 LTL loads a month, uses three or more carriers, has no auditor, holds its rate documents and has a reachable named contact. ThomasNet and the IMA membership page returned 403 to the author, so neither list was counted.

| Stage | Rate | Phase 0 cohort | Label |
|---|---|---|---|
| Distinct prospects touched | | 500 | `[P]`: the chat's 400 extended at the same weekly rate so that expected audits reach the 5 the stop rule needs |
| Replies | 4% | 20 | `[C]` |
| Discovery calls | 45% | 9 | `[C]` |
| Lookback audits delivered | 60% | 5.4 | `[A]` |
| Paid pilots | 33.33% | 1.8 | `[A]`; calls to paid pilot = 20% `[C]` |
| Recurring accounts | 75% | 1.35 | `[A]` |

Cost 500 × 1.50 = 750; CAC 750 ÷ 1.35 = 555.56. Even at the assumed rates the chance of at least 5 delivered audits from 500 prospects is 63% (binomial, n = 500, p = 0.0108); from the chat's 400 it is 43%.

**Pool against break-even.** By M49 the base ramp has touched 500 + 45 × 400 = 18,500 prospects, 82% of the upper bound, and holding the accounts needs 4,800 new prospects every year. **The four-state pool cannot carry the base case to break-even with founder compensation** unless almost every establishment is a distinct qualified firm, which it is not; more states or the referral channel would be required.

## 9. Stop rule

Chat (owner's chat, translated): stop if fewer than 2 of 5 audits find errors of more than USD 500 a month `[C]`. The research record adds: "or if no shipper pays after 5 delivered audits" `[C: research]`.

Probability the rule fires when every assumed rate is true. Let p be the chance one qualified audit finds more than USD 500 a month; the chat gives no p.

| p `[A]` | P(fewer than 2 of 5) |
|---|---|
| 0.4 | 33.7% |
| 0.5 | 18.8% |
| 0.6 | 8.7% |
| 0.7 | 3.1% |

At p = 0.6: 0.4^5 + 5 × 0.6 × 0.4^4 = 0.0102 + 0.0768 = 0.0870. No payer in 5 audits at 33.33%: (2/3)^5 = 0.1317. Either clause: 1 − (1 − 0.0870) × (1 − 0.1317) = **20.7%**. One time in five the rule stops a product whose assumptions are all true. It also lets a dead product through: at p = 0.2 it continues 26.3% of the time. And it measures errors found, not credits settled.

**Proposed revision** `[P]` (clause A kept as stated; clause B changed; clauses C0 and C added):

| Clause | Read | Rule | Status |
|---|---|---|---|
| A | Week 10 | Stop if fewer than 2 of the first 5 delivered audits find more than USD 500 of identified error in the audit month | Unchanged from the chat |
| B′ | Week 10, or later if extended | Stop if no shipper has signed and paid after 8 delivered audits | Changed from 5: (2/3)^8 = 3.9% |
| C0 | End of week 16 | Over all lookback and pilot claims sent by the end of week 7 (their 60-day carrier period `[S: SRC-03]` has then run), read accepted and settled amounts with carrier documents. Stop Phase 5 and do not resume outreach if nothing has been accepted or settled. If no claim was sent by week 7, extend the reading four weeks once, then stop | New; first settled-credit evidence |
| C | Day 120 of each paid pilot (weeks 23-27) | Compute self-serve net settled value on pilot-period claims ([PRD.md](PRD.md#10-success-metrics)). Stop further spending if no pilot is above zero | New; measures the decisive question |

A or B′ firing with all rates true: 1 − (1 − 0.0870) × (1 − 0.0390) = **12.3%**. B′ costs up to three more weeks of outreach (8 ÷ 0.0108 = 741 prospects) only when nobody has paid after five audits. Clauses C0 and C rest on a handful of claims from one or two shippers and support no rate estimate; they are floors.

**The build decision comes before the decisive answer.** The week-10 gate rests only on errors found (A) and willingness to pay for a pilot (B′). Neither is a settled credit. What is at risk before each later reading, at the plan's hours and CAD 100 an hour `[C: model rate]`:

| Committed before | Phases | Hours | CAD | USD at 1.38 |
|---|---|---|---|---|
| Clause C0, week 16 | 1-4 | 252 to 392 | 25,200 to 39,200 | 18,260.87 to 28,405.80 |
| Clause C, weeks 23-27 | 1-7 | 421 to 653 | 42,100 to 65,300 | 30,507.25 to 47,318.84 |

The alternative is to hand-deliver until week 27 before building anything; it removes that risk and costs about 17 more weeks of hand delivery at 21 hours an account-month. The founder chooses (open decision 7).

**Fewer than 5 audits at week 10** (37% likely even at the assumed rates): no build starts. Outreach resumes at 100 a week until the fifth audit is delivered or week 14, whichever is first; clause A is then read. Still under 5 at week 14: the channel is dropped (section 12.9). Each extension week moves every later date by a week. The brief's invalidation test is carried unchanged: three or more lookback audits finding under 1% recoverable `[C]`.

Not carried over: the brief's 30-day roadmap builds in week 3 and expects two paying customers in week 4 `[C]`. That contradicts its own 35-day cycle, so the build starts after the week-10 gate.

## 10. What buyer evidence would change the decision

| Evidence | Effect |
|---|---|
| Three audits with settled credits above USD 1,495 a month | Flat pricing is justified; continue |
| Buyers choose gainshare every time | Base revenue of 279 is wrong; re-run section 7 on settlement data |
| Shippers say they would rather hand everything to a contingency auditor | Product should become a done-for-you service or stop |
| Prospects already quote in a free TMS that audits | Segment is closed; narrow to shippers on contract tariffs |
| Carrier contracts forbid sharing rates with a vendor | Add carrier consent step or stop |
| Carriers deny or ignore most claims at day 60 and day 120 | Settled-to-claimed ratio replaces the 60% assumption `[C]` |
| Prospects on the first calls say they would record freight in a free TMS that audits | The remaining gap (section 3) is too thin; stop |
| Most LTL invoices rest on a base tariff the shipper does not hold | C-02 cannot run; product reduces to duplicates, fuel and accessorials; re-price or stop |
| Fewer than three in four pilots convert | Break-even with founder compensation does not arrive (7.5) |

## 11. Open decisions for the founder

1. Accept the narrowed lookback scope (5.1) or staff full 90-day hand audits.
2. Accept the refund criterion (5.2) and the tier allowances (section 6).
3. Accept stop-rule clauses B′, C0 and C.
4. Whether gainshare stays on offer, given adverse selection (3.1).
5. Who builds. One founder sells and delivers, and outreach pauses for 11 weeks. The week-21 release needs about 1.4 full-time builders for ten weeks at the plan's midpoint; a solo builder releases about four weeks later and every ramp month from M5 moves one month.
6. A lawyer's answer on T-0.1.1 before any message is sent, and an accountant's on cross-border invoicing.
7. Build at week 11 on clauses A and B′ with clause C0 as a mid-build gate (the plan as written), or hand-deliver until clause C before building.
8. Whether lookback settlements carry the 20% on the gainshare option (5.1).

## 12. Go-to-market plan

One cohort (500 prospects), one weekly volume (100 new first touches), one founder. Every rate is from section 8.

### 12.1 Ideal customer profile

| Aspect | Profile | Label |
|---|---|---|
| Firm | Manufacturer or distributor, 20-250 employees, USD 0.5M-5M a year LTL and truckload spend, no TMS audit module, AP approves freight bills by hand | `[C]` |
| Region | Greater Chicago first, then the rest of IL, IN, OH, WI | `[C]` |
| Trigger | New controller, carrier general rate increase, a reclass dispute, freight over budget, NMFC classification change | `[C]` |
| Disqualified | Under 100 carrier invoices a month; fewer than 3 carriers; already uses an audit firm; cannot forward 90 days of invoices `[C]`. Added `[P]`: freight bought only on spot quotes with no rate documents; a contract that forbids sharing rates and no carrier consent; any Canadian mailing address; already records freight in a TMS that audits invoices; holds neither per-shipment rates nor the base tariff its discounts apply to |

### 12.2 Named roles

| Role | Part |
|---|---|
| AP clerk or logistics coordinator | Feels the pain; forwards invoices; logs time |
| Logistics or transportation manager | Supplies rate documents; approves disputes; can block over carrier relationships |
| Controller | Signs the pilot; can block over data sharing |
| CFO or VP operations | Budget owner; signs where the controller cannot |
| Carrier sales representative | Outside the firm; decides the claim |

### 12.3 Prospect list

Sources as in section 5. Count: unknown; upper bound 22,450 establishments (section 8). Build (T-0.1.2): 100 firms a week, one named logistics manager or controller each, about 3 minutes a record. Checks: firm appears once across sources (deduplicate by domain); US street address in the four states; address verified by the verification tool; not on the suppression list. Cost USD 150 per 100 `[C]`. The terms of each directory on reuse of listings were not read; T-0.1.1 covers them.

### 12.4 Channel, sequence and weekly volume

Email only for the cohort, so the reply rate has one meaning.

| Day | Step |
|---|---|
| 0 | First-touch email, Tuesday to Thursday, 07:30-09:30 Central |
| +4 business days | One follow-up in the same thread |
| On reply | 30-minute video call offered at 09:00-16:00 Central (07:00-14:00 Pacific); US phone number on the signature |
| After the call | NDA and data authorization, then invoices, rate documents and AP export through an upload link |
| +10 days | Findings report and 30-minute readout; pilot order form sent the same day |

Discovery questions, the brief's five `[C]` and two added `[P]`:

1. How many carrier invoices do you pay each month and across how many carriers?
2. Who approves a freight bill and what do they check it against?
3. When did you last dispute a reweigh or reclass?
4. Where do rate confirmations and tariffs live?
5. What would you need to see to trust an automated flag?
6. Do you record shipments in a TMS, and would you load your carrier rates into a free one that audits invoices?
7. Are your LTL rates per-hundredweight tables you hold, or a discount off a base tariff, and do you hold that tariff?

Not carried from the brief: its five-minute demo script (no product exists to demo) and the referral offer of one free month (kept for the backup channel).

Volume: 100 new prospects a week, at most 200 emails a week with follow-ups. Founder hours a week `[A]`: list 5, sending and replies 2, calls 1.8 × 0.75 = 1.4, audits 1.08 × 24 = 26; about 34 hours.

**Selling from Vancouver into Chicago.** Everything is remote and no trip is budgeted. Calls sit in the founder's morning. Invoices are in USD. A foreign one-person vendor asking for confidential rate agreements is the main trust barrier: answer it with a mutual NDA before any document moves, US-region storage, a written statement that the founder reads the data from Canada, and deletion on request (MH-14). In Phase 0 there is no software, so these promises are kept by the data room of T-0.1.6 and the deletion log of T-0.3.5; no customer file is accepted before T-0.1.6 passes. Proposed and unverified `[A]`: US customers may ask for a W-8BEN-E, and tax treatment of the invoices needs an accountant.

**Outreach law. Not legal advice; sending is gated on T-0.1.1.** The sender's computer is in Canada, so CASL section 6 is engaged by section 12 `[S: SRC-06]`. The plan relies on the exclusion for a message the sender reasonably believes will be accessed in a listed foreign state, where it conforms to that state's law on similar conduct; the United States is listed `[S: SRC-07]`. So every recipient must have a verified US address, and every message must meet CAN-SPAM `[S: SRC-05]`: truthful headers, a subject line that is not deceptive, identification as an ad, the sender's valid postal address, a working opt-out that is processed for at least 30 days after sending and honoured within 10 business days. The FTC states no exception for business-to-business email and a penalty of up to USD 53,088 per email. A Canadian recipient would need consent under CASL section 6; an address found by a tool does not meet implied consent under section 10(9)(b), so none is contacted. The FTC guide addresses email; rules for LinkedIn messages were not checked, so LinkedIn messaging is not used for the cohort (Sales Navigator is used only to build the list).

### 12.5 Messages (synthetic; never sent)

First touch:

> Subject: Free freight bill check: 90 days for duplicates, one month line by line
>
> Hi Dana,
>
> I'm the founder of FreightCheck. This is a sales email. We check carrier invoices against the shipper's own rate sheets, accessorial schedules and fuel tables, and draft the dispute for each overcharge.
>
> Offer: send 90 days of carrier invoices, the rate agreements for those carriers and an AP payment export. Within 10 days you get a list of duplicates across the quarter and a line-by-line check of the latest month. No charge. If it is worth continuing, the pilot is 60 days at USD 249 a month, or 20% of credits your carriers actually issue.
>
> Would a 30-minute call next week suit?
>
> Sam Example, FreightCheck — 100 Example Street, Vancouver BC, Canada — +1 312 555 0100
> Reply "unsubscribe" or use https://freightcheck.example/unsubscribe and I will not write again.

Follow-up (+4 business days):

> Subject: Re: Free freight bill check: 90 days for duplicates, one month line by line
>
> Hi Dana, one more note and then I'll stop. This is a sales email. The check needs three things from you: the invoices, the rate agreements and the payment export. We sign an NDA first. Is this yours, or should I ask your controller?
>
> Sam Example, FreightCheck — 100 Example Street, Vancouver BC, Canada — +1 312 555 0100
> Reply "unsubscribe" or use https://freightcheck.example/unsubscribe.

### 12.6 Pilot offer and the step to a recurring account

As sections 5.1 and 5.2. The buyer gets the lookback and ten drafts free, then 60 days of audit, drafts and ledger; pays USD 249 at signing and at day 30, or 20% of evidenced settlements; supplies invoices, rate documents, the AP export, carrier contacts and one approver. The pilot ends at day 60 with the report. Conversion is the order form for a tier or continued gainshare, first charge day 61. Refund test at day 120.

### 12.7 Three likely objections

| Objection | Honest answer |
|---|---|
| "Our TMS already flags variances", or "Warp's TMS does this free" | It may, and Warp says its free TMS audits outside carriers against the rate tables you load, with fuel, reweigh, reclass and duplicate checks. If you are willing to record your freight there, that is the cheaper choice and we say so. We are for a shipper who will not adopt a TMS, wants past invoices checked, and wants each claim followed to the credit memo. The free lookback shows whether that is worth anything; if not, do not buy. |
| "A contingency auditor does all the work for a percentage" | True, and for a shipper with no clerk time that may be the better deal. At 20% of recovery it beats our flat plan on the modelled numbers (3.1). On fee alone our flat plan is cheaper above about USD 1,500 of credits a month; counting your team's time (692.33 ÷ 20%), only above about USD 3,460. |
| "Disputes hurt carrier relationships, and our rates are confidential" | Disputes cite the carrier's own document and stay above a threshold you set; you approve and send each one, we never write to your carrier. If your contract forbids sharing rates we need the carrier's consent or we cannot work together. |

### 12.8 First 30, 60 and 90 days

Lags per weekly batch of 100: replies in week w + 1 (4), calls w + 2 (1.8), audits delivered w + 4 (1.08), paid w + 5 (0.36). Checkpoints fall on whole weeks.

| Checkpoint | Weekly activity | Sent | Replies | Calls | Audits delivered | Paid pilots | Recurring accounts | Cash | Founder hours, cumulative `[A]` |
|---|---|---|---|---|---|---|---|---|---|
| Day 28 | 100 touches a week; calls from week 3 | 400 | 12 | 3.6 | 0 | 0 | 0 | 600 | 42.7 |
| Day 56 | Last batch in week 5; audits weeks 5-8 | 500 | 20 | 9 | 4.32 | 1.08 | 0 | 750 | 170.8 |
| Day 84 | Audits end week 9; gate week 10; hand pilots; build from week 11 | 500 | 20 | 9 | 5.4 | 1.8 | 0 | 750 | 232.6 |

Hours: setup 12; list 5 per 100; sending 2 a week for six weeks; calls 0.75 each; audits 24 each; hand pilot delivery 5.25 per account-week (21 a month). Day 28: 12 + 20 + 8 + 2.7 = 42.7. Recurring accounts stay at 0 through day 84 because the first pilots end in weeks 14-18; the cohort is expected to yield 1.8 × 75% = 1.35. The brief's 70 founder hours and four lookbacks in the first 30 days `[C]` do not fit a 35-day cycle; these figures replace them. Build hours are excluded.

### 12.9 GTM stop rule

- **Drop the channel** `[P]`: fewer than 8 replies from the 500 (at a true 4% this happens under 0.1% of the time; at 2% it happens 22%), or fewer than 3 delivered audits by week 9 (9.4% at the assumed rates). Try the referral channel once before dropping the product.
- **Drop the product**: section 9, clauses A, B′, C0 and C.
- **Hold spending**: no outreach beyond the 500 until the week-10 gate, except the extensions section 9 calls for (B′, or fewer than 5 audits at week 10); none after week 16 unless clause C0 passes.

## 13. Sources and assumptions

All consulted 2026-11-10 by automated fetch; quotes are short excerpts.

| ID | Source | Jurisdiction | Scope used | Access restriction |
|---|---|---|---|---|
| SRC-01 | 49 U.S.C. 13710(a)(3), law.cornell.edu/uscode/text/49/13710 | US federal | 180-day windows for carrier rebilling and shipper contest | None; unofficial codification |
| SRC-02 | 49 U.S.C. 14705, law.cornell.edu/uscode/text/49/14705 | US federal | 18-month action, accrual, extension | None |
| SRC-03 | 49 CFR Part 378, ecfr.gov, version dated 2026-01-01 | US federal | Overcharge and duplicate payment claims: filing, documents, 30 and 60 days | None |
| SRC-04 | 49 U.S.C. 14101(b), law.cornell.edu/uscode/text/49/14101 | US federal | Contract waiver | None |
| SRC-05 | FTC, CAN-SPAM Act: A Compliance Guide for Business, ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business | US federal | Requirements, B2B, opt-out timing, penalty | None; guidance, not the statute |
| SRC-06 | CASL, S.C. 2010, c. 23, ss. 6, 10(9), 11, 12, laws-lois.justice.gc.ca/eng/acts/E-1.6 | Canada | Application to a sender in Canada; consent; unsubscribe | None |
| SRC-07 | Electronic Commerce Protection Regulations, SOR/2013-221, s. 3(f) and schedule, laws-lois.justice.gc.ca/eng/regulations/SOR-2013-221 | Canada | Foreign-state exclusion; US listed | None |
| SRC-08 | Warp freight audit savings calculator, wearewarp.com/tools/freight-audit-savings-calculator | US vendor | Recovery ranges; what the tool is | None |
| SRC-09 | Warp freight invoice audit tool, wearewarp.com/tools/freight-invoice-audit | US vendor | Inputs, method, price | Tool not run; page text only |
| SRC-10 | Warp TMS, wearewarp.com/tms, and wearewarp.com/ai-freight-invoice-audit; both re-read on 2026-11-10 for fix round 1 | US vendor | Free TMS audit features against shipper-loaded rate tables, and limits | Product not used; marketing pages only |
| SRC-11 | SMC3, CzarLite product page, smc3.com/czarlite.htm | US vendor | Use of a third-party base rate in LTL pricing agreements | Licence terms and price not on the page |
| SRC-12 | AuditFreight, auditfreight.pages.dev | US vendor | Fee basis and tiers | Early-access page; availability unclear |
| SRC-13 | Williams & Associates, waionline.com/freight-post-audit | US vendor | Contingency model, claim filing, 180 days | Percentage not published |
| SRC-14 | Freightview pricing, freightview.com/pricing | US vendor | Price and bands | None |
| SRC-15 | Intelligent Audit, intelligentaudit.com and /products/catalyst-for-smbs | US vendor | No price; Catalyst scope | None |
| SRC-16 | Loop, loop.com | US vendor | No price; claims | /pricing returned 404 |
| SRC-17 | Cass, cassinfo.com/freight-audit-payment | US vendor | No price; scale | None |
| SRC-18 | US Census Bureau, County Business Patterns 2022 state file (cbp22st), NAICS 31-33 and 42, size classes 20-49, 50-99, 100-249, states 17, 18, 39, 55 | US | Establishment counts | 2022 data; establishments, not firms |
| SRC-19 | Bank of Canada Valet, series FXUSDCAD, 2026-11-09 | Canada | Reference rate only | None |
| SRC-20 | US EIA, Gasoline and Diesel Fuel Update, eia.gov/petroleum/gasdiesel | US | Weekly publication of diesel prices | Price values not used |
| SRC-21 | OWASP ASVS 5.0.0, English CSV, github.com/OWASP/ASVS tag v5.0.0 | International | Requirement text cited in [TRD.md](TRD.md#84-security-controls-and-accepted-gaps) | None |
| SRC-22 | W3C WCAG 2.2 Recommendation, w3.org/TR/WCAG22 | International | Criteria cited in [design.md](design.md#7-accessibility-map) | None |
| SRC-23 | NMFTA, nmfta.org/nmfc | US | Publisher and access route | NMFC text is behind ClassIT+; not opened |

Blocked: Supply Chain 24/7 article (403), thomasnet.com (403), ima-net.org/membership (403). Claims that depend on them are labelled unverified where used. Methods: the arc42 section order shapes [TRD.md](TRD.md); Spec Kit's separation of outcome, plan and independently verifiable tasks shapes [PRD.md](PRD.md) and [execution-plan.md](execution-plan.md).

Assumptions that carry the most weight: recoverable share of spend (vendor range only); 60% of disputes won `[C]`; p = 0.6; the 60% and 33.33% funnel split; the shipper's time per claim; 3.5% churn against the brief's own warning that findings fall after the first clean-up `[C]`.
