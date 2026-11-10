# Design brief — FreightCheck carrier invoice audit

Screens and routes: [App-flow.md](App-flow.md#2-screen-inventory). All values proposed `[P]`.

## 1. Principles

1. **Evidence beside every number.** No amount appears without a way to see the page or rule it came from.
2. **Three money states never blur.** Claimed, accepted and settled have fixed positions, labels and icons everywhere.
3. **Exceptions look unfinished, not fine.** "Needs input" is visually closer to a warning than to a pass.
4. **Dense, calm, keyboard-first.** The daily user works tables for an hour at a time.

## 2. Visual hierarchy and layout

- Shell: left navigation 224 px, top bar with tenant name, timer button and account menu, content max width 1440 px.
- List screens (S-07, S-09, S-11): filter row, summary strip of totals, table. Row height 40 px, sticky header, numbers right-aligned.
- Detail screens (S-08, S-10, S-04): two panes. Left 55%: source page viewer with zoom and region highlight. Right 45%: fields, checks or rule rows. The primary action sits bottom right of the right pane and stays visible.
- Order on S-08: status and contest-by date; fields; checks; duplicates; linked documents.

## 3. Typography and colour

| Use | Value |
|---|---|
| Typeface | Inter, system sans fallback; tabular numerals for all amounts and dates |
| Sizes | 14 px body and tables, 12 px captions, 16 px form inputs, 20 px page title, 28 px report totals |
| Text `#1B2430` on `#FFFFFF` | 15.65:1 |
| Secondary text `#52606D` on `#FFFFFF` / on surface `#F4F6F8` | 6.46:1 / 5.96:1 |
| Primary action `#0B5CAD`, white label | 6.67:1 |
| Variance and error `#B42318` on `#FFFFFF` / on `#FDECEA` | 6.57:1 / 5.75:1 |
| Needs input `#8A4B00` on `#FFF4E0` | 6.24:1 |
| Pass and settled `#0F6B3E` on `#FFFFFF` / on `#E8F5EE` | 6.58:1 / 5.87:1 |
| Focus ring | 2 px `#0B5CAD` with 2 px offset |

Ratios computed by the author from the hex values with the WCAG relative-luminance formula; not measured in a browser. Colour never carries a state alone: each status has an icon and a word.

## 4. Components

| Component | Behaviour |
|---|---|
| Status chip | Icon plus word: Pass, Variance, Needs input, Not applicable; Draft, Approved, Sent, Acknowledged, Accepted, Partly accepted, Denied, Settled, Withdrawn, Expired |
| Money triple | Three fixed columns: Claimed, Accepted, Settled. Empty states read "not decided" and "nothing settled", never 0.00 |
| Evidence link | Document name, page, effective dates; opens the viewer at the region |
| Check row | Name, status chip, expected, billed, difference, "show arithmetic" disclosure, rule version |
| Days-left badge | Number and basis: "112 days · received 2 Mar (AP stamp) + 180", "97 days · proxy: invoice date, receipt not evidenced", "contract: 90 days", "no default applied", "past contest-by date" |
| Draft watermark | Diagonal "DRAFT – not approved" on the dispute preview and its PDF until approval |
| Summary strip | Totals for the current filter; each total is a link to its rows |
| Toast and live region | Non-blocking status; mirrored in a polite live region |
| Confirm dialog | For approve, mark as sent, settlement, withdraw, delete; restates the consequence; default focus on Cancel |

## 5. Principal screens, enough to sketch

**S-08 Invoice detail.** Left: page viewer, thumbnails below. Right, top: carrier, invoice number, PRO, total, chip, days-left badge. Fields in two columns; an unconfirmed field has an amber left border, its confidence, and a "Confirm" button; selecting a field highlights its region. Checks list below: one row per check. A duplicate candidate opens a split view of both invoices. Footer: "Confirm fields and re-run".

**S-09 Exception queue.** Tabs: Variances (count), Below threshold (count), Needs input (count). Columns: carrier, invoice, reason code in words, difference, days left, decision. Keyboard: arrow keys move rows, Enter opens, C confirms for claim, D opens the dismiss reason menu; the same actions exist as buttons.

**S-10 Claim detail.** Header: carrier, claim reference, status timeline. Left: dispute preview with watermark while draft. Right: line table (charge, billed, expected, claimed, document and page), attachments checklist, basis block (rule version, effective dates, governing date, contest-by). Buttons: Approve, Download packet, Copy text, Mark as sent.

**S-11 Claims ledger.** Summary strip: Claimed, Accepted, Settled, Pending, and settled ÷ claimed. Table with the money triple, sent date, expected acknowledgment and decision dates, contest-by. Overdue carrier dates show a clock icon and "carrier overdue".

**S-14 Net settled value report.** One line of arithmetic in large type: Settled − Fee − Time cost = Net. Beneath: claimed, accepted and pending as secondary figures marked "not counted"; baseline; drill-down tables. On gainshare, fee statement lines with their settlement documents.

**S-04 Rate document.** Left: source page. Right: rule grid with effective dates per row; banner "Entered by operator, not confirmed" until an Approver confirms; overlap errors name the conflicting version.

## 6. Interaction feedback and microcopy

| Situation | Copy |
|---|---|
| Pending operation (S-06) | "Reading 14 of 20 files. You can leave this page; results stay here." |
| Pending operation (S-10) | "Building the evidence packet…" then "Packet ready: 4 attachments." |
| Recoverable error (S-06) | "2 files could not be read: `inv-0042.pdf` is password-protected; `scan-7.tif` is not a supported type. The other 18 are done. Retry these 2 after fixing them." |
| Recoverable error (S-10) | "The fuel schedule for this carrier changed after this draft was made. Claimed amount was USD 46.20; on the confirmed schedule it is USD 31.75. Review the lines, then approve." |
| Human approval (S-10) | "Approve dispute to Example Freight Lines for USD 31.75 on invoice 884213? You are confirming that rate sheet v2 (effective 1 Jan to 30 Jun, basis: pickup date) governed the 14 Mar pickup, and that 97 days remain to contest on the invoice-date proxy. FreightCheck will not send anything; you send it from your mailbox." Buttons: "Approve dispute", "Cancel" |
| Mark as sent | "Record that this dispute was sent to claims@carrier.example on 22 Apr? This cannot be undone; a wrong dispute must be withdrawn." |
| Settlement | "Record USD 31.75 as settled by credit memo CM-5521? This amount will count in the report." |
| Exception | "Needs input: no confirmed fuel schedule covers 14 Mar. Other checks ran." |
| Broker deadline | "No default deadline applied. This is a broker invoice; enter the dispute period from your broker contract." |

**Inspecting evidence.** Any amount → evidence link → viewer at the page and region; any expected amount → "show arithmetic" lists inputs, rule version and rounding.
**Correcting a suggestion.** Edit the field in place; the old value stays visible as struck text with the user and time; checks re-run and the row announces the new result.
**Draft versus approved.** Drafts carry the watermark, an amber "Draft" chip and no claimed amount in ledger totals; approved claims show the approver and time and a locked amount.

## 7. Accessibility map

Target: WCAG 2.2 level AA `[S: SRC-22]`. This is a design intent; nothing has been built or tested, so no conformance is claimed.

| Criterion | Screens | Design decision | Manual check |
|---|---|---|---|
| 2.1.1 Keyboard | S-08, S-09, S-10 | Viewer zoom and pan, field confirm, queue decisions and dialogs all operable by keyboard; single-key shortcuts only while the table has focus | Complete E2E-04 with no pointer |
| 2.1.4 Character Key Shortcuts | S-09 | The C and D shortcuts are active only while the queue table has focus and can be turned off in the account menu | Turn them off; type C in the table; nothing happens |
| 2.4.3 Focus Order | S-08, S-12 | Order follows the right pane top to bottom, then the viewer | Tab through; order matches reading order |
| 2.4.7 Focus Visible, 2.4.11 Focus Not Obscured (Minimum) | All | 2 px ring; sticky header and action bar leave the focused row visible | Tab to the last row of a long table |
| 2.5.8 Target Size (Minimum) | S-09, S-11 | Row actions at least 24 by 24 CSS px | Measure icon buttons |
| 1.4.1 Use of Color, 1.4.3 Contrast (Minimum), 1.4.11 Non-text Contrast | All | Icon and word on every chip; ratios in section 3; chip borders at 3:1 | Greyscale screenshot remains readable |
| 1.3.1 Info and Relationships | Tables, S-14 | Real table markup with header cells; the money triple has column headers, not position alone | Screen reader reads header with each cell |
| 3.3.1 Error Identification, 3.3.3 Error Suggestion | S-04, S-12, S-15 | Message beside the field and in a focused summary; suggestion where known ("effective-to must be after 1 Jan") | Submit an overlap; focus lands on the summary |
| 3.3.2 Labels or Instructions | All forms | Visible labels; amount fields state currency and format | Inspect each form |
| 3.3.4 Error Prevention (Legal, Financial, Data) | S-10, S-12, S-15 | Approve, settlement and deletion are reviewed in a dialog before commit; settlement is reversible; deletion is confirmed by typing the tenant name | Each action shows the review step |
| 3.3.7 Redundant Entry | S-12 | Carrier, claim and claimed amount are carried in, not retyped | Open S-12 from S-10 |
| 3.3.8 Accessible Authentication (Minimum) | S-01 | Password managers and paste allowed in password and code fields | Paste a code |
| 4.1.3 Status Messages | S-06, S-08, S-10 | Processing counts, re-run results and "packet ready" go to a polite live region; errors to an assertive one | Screen reader announces without focus moving (E2E-05) |
| 2.2.1 Timing Adjustable | Session | Warning 2 minutes before idle expiry with "Stay signed in" | Wait for the warning |
| 1.4.10 Reflow, 1.4.4 Resize Text | All, checked on S-08, S-09, S-10, S-11, S-14 | Every screen stays fully operable down to 320 CSS px: lists become stacked cards, two-pane screens stack with the page viewer above the fields. Two-dimensional scrolling remains only inside the page viewer and the rule grid | At 1280 px and 200% zoom confirm a field on S-08, decide a row on S-09 and approve on S-10; at 400% read S-11 and S-14 |

Known gap, not met: the page-image viewer conveys scanned content that has no text alternative beyond the extracted fields; a user who cannot see the image cannot independently verify a scan.

## 8. Responsive behaviour

Built for 1280 px and wider. Between 768 and 1279 px the navigation collapses to icons with labels on focus. Below 768 px (which includes a 1280 px screen at 200% zoom) nothing becomes read-only: panes stack with the page viewer above the fields, a "Jump to source" link moves between them, and the primary action stays pinned at the bottom. Comparing a field with its page then needs scrolling; that is slower, not blocked. (The first version made review screens read-only below 768 px; removed under F-012.)
