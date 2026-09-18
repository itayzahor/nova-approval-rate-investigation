# Payments Ops — change log

Running notes from the payments operations team. One entry per change or incident.
Not everything in here is relevant to any particular question.

---

**2026-04-03** — Scheduled maintenance on SORVA-22, roughly two hours from 01:00
UTC. E-wallet attempts during the window failed over to the merchant's existing
bank transfer route. No action needed.

**2026-04-17** — Updated the decline reason mapping for KRTX. Some reasons that
previously came through as `issuer_unavailable` are now correctly reported as
`do_not_honor`. Historic rows were not backfilled.

**2026-05-05** — KRTX raised our per-minute request limit. This mostly removes the
throughput ceiling we were hitting during Asian evening peak.

**2026-05-21** — Enabled cascading for NOVA-FX bank transfer traffic. Retries now
happen automatically rather than requiring the customer to start over.

**2026-06-02** — NBLX-07 went live for NOVA-FX: local bank transfer, IDR and VND.
Traffic will ramp over the first week as we widen the routing rules. This was
requested by the commercial team to open up Indonesian and Vietnamese deposits,
which we previously could not serve at all.

**2026-06-08** — NBLX-07 risk rules tightened after a chargeback spike in the
first week. Expect more attempts to be stopped by risk screening on this route
than on our older ones.

**2026-06-11** — SORVA notified us that their acquirer reallocated BIN ranges for
Japanese cards. We were not given advance notice and have asked for detail.

**2026-06-15** — ATLAS-CFD also onboarded to NBLX-07 for IDR.

**2026-06-19** — Settlement window for NBLX moved to T+2.

**2026-06-22** — Fixed a display bug in the merchant-facing dashboard where the
date filter was off by one for merchants in UTC+8. Underlying figures were always
correct; only the filter label was wrong.

**2026-06-24** — Reminder for anyone pulling data: the nightly extract now runs at
18:00 UTC instead of after midnight. That means the last two days of any pull are
partial — attempts created after the extract runs have not reached a final status
yet. Use complete days only for trend work.

**2026-06-27** — HALO-01 certification passed. Not yet enabled for any merchant.

---

## Notes on the merchant dashboard

Merchants see their own numbers in the merchant portal, which is a different
system from our internal reporting. Two things differ by design:

- The portal buckets by **the merchant's local date**, not UTC. NOVA-FX is
  configured as UTC+8.
- The portal shows deposits only, and only attempts that actually reached a
  payment provider. Attempts stopped by our own risk screening are not shown to
  the merchant.
