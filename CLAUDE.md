# CLAUDE.md — FreightCheck

Read [AGENTS.md](AGENTS.md) first; it is canonical. This file adds product guidance only. Build milestones B1 and B2 exist (see the AGENTS.md state line); commands not marked there as existing are proposed.

## The buyer's workflow

A Midwest manufacturer or distributor receives 100-500 LTL and truckload invoices a month from 3-10 carriers. An AP clerk approves them by eye. With FreightCheck the clerk forwards invoices, confirms extracted fields, and works a queue of variances; the logistics manager approves each dispute and sends it from their own mailbox; later they record the carrier's decision and the credit. The controller reads one number: settled credits minus fee minus the team's time.

The question the pilot answers: do settled carrier credits exceed the shipper's setup, review and dispute costs? Found errors are not the answer.

## Highest-consequence error

**Wrong-basis dispute sent**: a dispute goes to a carrier claiming an amount computed from a rate document version or fuel surcharge week that did not govern the shipment. It cannot be recalled. Guard it at every step: confirmed rule versions only, effective dates checked against the governing date, recompute at approval, fail closed on a stale basis ([TRD.md](TRD.md#62-highest-consequence-failure-sequence-wrong-basis-dispute-sent)).

Second: an unsettled amount counted as settled. Claimed, accepted and settled are three fields and never merge.

## Sensitive data

- Contract rate sheets, tariffs, accessorial and fuel schedules: confidential between shipper and carrier.
- Invoices, bills of lading, carrier correspondence, settlement documents.
- User credentials and TOTP secrets.

No regulated personal data is expected, but treat names and emails of carrier and shipper staff as personal data.

## Prohibited shortcuts

- Do not let a model decide pass or fail, compute money, pick a rate version, write dispute text or classify a carrier reply.
- Do not treat an exception (missing rate, missing fuel basis, unconfirmed field) as a pass, and do not skip the other checks when one is an exception.
- Do not invent a date: receipt means the shipper's receipt of the carrier's bill, never the time a forward reached FreightCheck; with no evidence use the labelled invoice-date proxy; a broker invoice with no contract term gets no deadline.
- Do not let an approval through on a stale basis or past the contest-by date without the recorded override, and do not use an unconfirmed fuel index value.
- Do not count a short-pay, a promise or an accepted amount as settled without the carrier's document.
- Do not send anything to a carrier from the system.
- Do not use real invoices, rates or company names in fixtures, prompts, logs or examples.
- Do not add email-link sign-in.
- Do not start build work before the week-10 gate or add features outside the must-haves.

## First verification checks when implementation begins

Run in this order. B1 and B2 results (commands and counts) are in [verification-report-fixing.md](verification-report-fixing.md#9-build-milestone-b1-2026-11-11) sections 9 and 10; items not listed there as passed stay `Not run`:

1. IT-01 cross-tenant denial on API, worker and file links.
2. UT-06 exception semantics: an exception never yields `clean` and never stops other checks.
3. UT-02 and UT-03 governing-rate and fuel-week resolution.
4. IT-06 stale-basis approval is refused; IT-19 approval past the contest-by date is refused; IT-20 a basis change after sending is flagged.
5. IT-07 settlement needs a document; reversal produces a negative fee line.
6. UT-07 deadline bases, including the forwarded-late and broker cases.
7. IT-13 worker starts without web modules and carries the correlation ID.
