# Nova Markets approval-rate drop — memo

## What's going on

Nova Markets is right that their deposit approval rate dropped — we can reproduce
their dashboard numbers exactly from our raw logs, so that part isn't a reporting
error. But "fell off a cliff" is misleading about the cause. Deposit approval rate
(approved ÷ (approved+declined) attempts) went from **79.6% (Apr–May) to 72.4%
(Jun 1–28)**.

**~96% of that drop is arithmetic, not a quality problem.** On June 2 we switched
on a brand-new route (`NBLX-07`, local bank transfer for Indonesia/Vietnam) that
Nova's own commercial team had requested to open a market we couldn't serve before.
That route approves at only ~54% — normal for a first-week integration with
freshly tightened risk rules — and it's now ~28% of Nova's deposit volume.
Excluding it, Nova's approval rate in June is **79.3%, essentially flat** versus
the baseline.

**There is one real, separate problem**: on `SORVA-14` (a card route via
processor SORVA), Japanese-card approval rate fell from 74.6% to 54.8% right
after June 11, when SORVA reallocated BIN ranges for Japanese cards without
notifying us. Declines are dominated by `do_not_honor` — consistent with an
issuer/routing mismatch on their end, not anything Nova or we did.

Estimated cost, June 1–28, using dollar-weighted approval rate (approved $ ÷
attempted $, which is the right way to cost this — a flat count-based estimate
overstates it, see below): **~$158K in deposit volume that didn't go through**
across all of Nova's business. Almost all of that (**~$174K**) is the NBLX-07
new-route effect; the rest of Nova's existing business actually ran slightly
*ahead* of baseline in aggregate, which **masks** the SORVA problem in the
whole-book number. Looked at on its own terms, the SORVA/JP issue alone cost
**~$101K** in lost deposits from Japanese card customers — real money, just
netted out by unrelated gains elsewhere in the total.

Ruled out: the June 22 dashboard bug (ops log confirms it only mislabeled a date
filter, underlying figures were unaffected) and UTC-vs-local-time bucketing (we
match the merchant's own UTC+8 bucketing exactly in the reconciliation below).

## What we should do

- **Tell Nova**: the number is real but mostly the growing pain of the new ID/VN
  corridor they asked us to open, not a break in existing service — share the
  NBLX-07 breakout so they see it's isolated to one new market/rail.
- **Own the SORVA issue separately**: it's a genuine, unannounced degradation on
  our card route, unrelated to Nova's new corridor. Escalate to SORVA and
  consider de-weighting `SORVA-14` for JP cards if it isn't fixed soon.
- **Internally**: review whether NBLX-07's tightened risk rules are
  over-filtering — ~22–24% of its attempts are blocked by our own screening
  before reaching a processor, invisible to Nova, and fully within our control.
- Track NBLX-07 as a maturing route, not a new permanent baseline.

## Assumptions and open questions

- Defined approval rate as `APPROVED / (APPROVED + DECLINED)` on `SALE` (deposit)
  attempts only, excluding `FILTERED` (never reached a processor — a different,
  internal problem) and `PENDING` (no outcome yet). This is a judgment call; an
  internal, filtered-inclusive view of the same period is 67.8% → 58.0%.
- Excluded the last 2 days of the snapshot (Jun 29–30): the ops log says the
  nightly extract was recently moved earlier, so recent days are only partially
  settled.
- Excluded a `QA-TEST` merchant present in the raw data.
- Normalized several data-quality issues found along the way: inconsistent
  casing on `status`/`route_id`/`currency` (e.g. `approved` vs `APPROVED`),
  trailing whitespace on `currency`, and three spellings of the Philippines in
  `customer_country` (`PH`/`PHILIPPINES`/`PHL`).
- Missing `amount_usd` was back-filled from `fx_rates.csv`; weekend/holiday gaps
  in the FX file were forward-filled from the last known rate.
- Cost estimate compares actual approved dollar volume to what a dollar-weighted
  pre-June approval rate would produce against the same attempted volume; doesn't
  control for normal week-to-week variation. Want a longer pre-period than 2
  months, and confirmation from Ops on whether NBLX-07's ~54% is steady-state or
  still trending.
- `NBLX-07` rows have unreliable `customer_country` (route doesn't pass geography
  through, per `routes.json`), so didn't segment its numbers by country.

## How to reproduce

```
pip install pandas numpy
python analysis.py
```

Runs against `data/` (the files provided in the task) and prints every number
cited above, including a line-for-line reconciliation against
`merchant_dashboard_export.csv` (0 mismatches once the merchant's own bucketing
rules — UTC+8 local date, deposits only, excludes filtered/pending — are applied).

## How you used AI

Used Claude Code throughout: to scaffold the analysis script, think through what
"approval rate" should mean, and review the draft before sending.

Where it went wrong and how I caught it: the first cost estimate turned "lost
attempts" into dollars by multiplying by one blended average transaction value
for all of Nova's business — giving ~$433K. That's wrong, because `NBLX-07`'s
deposits average ~$300 vs. ~$900 for the rest of Nova's business, so one blended
average overstated the true cost by 2x+. I caught it by re-deriving the number a
second way (dollar-weighted approval rate applied directly to attempted dollar
volume, per route) and finding the two methods disagreed. The ~$158K figure above
is the corrected one.
