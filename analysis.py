"""
Nova Markets (NOVA-FX) approval-rate investigation.

Reproduces every number cited in README.md. Run:
    python analysis.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
pd.set_option("display.width", 120)


COUNTRY_ALIASES = {"PHILIPPINES": "PH", "PHL": "PH"}


def load_orders():
    df = pd.read_csv(DATA / "orders.csv")
    # Data bugs: status/route_id/currency have inconsistent casing (and currency
    # has trailing whitespace), and customer_country has 3 spellings for the
    # Philippines. Normalize all of it before anything else.
    df["status"] = df["status"].str.upper()
    df["order_type"] = df["order_type"].str.upper()
    df["route_id"] = df["route_id"].str.upper()
    df["currency"] = df["currency"].str.strip().str.upper()
    df["customer_country"] = (
        df["customer_country"].str.strip().str.upper().replace(COUNTRY_ALIASES)
    )
    df["created_at"] = pd.to_datetime(df["created_at"])
    # Merchant portal buckets by NOVA-FX local date, which is UTC+8.
    df["local_date"] = (df["created_at"] + pd.Timedelta(hours=8)).dt.date
    df["utc_date"] = df["created_at"].dt.date
    return df


def load_routes():
    routes = json.loads((DATA / "routes.json").read_text())["routes"]
    r = pd.DataFrame(routes)
    return r.rename(columns={"status": "route_status"})


def build_fx_lookup():
    fx = pd.read_csv(DATA / "fx_rates.csv")
    fx["date"] = pd.to_datetime(fx["date"]).dt.date
    # Rates come in mixed directions (some X->USD, some USD->X). Normalize to
    # a single (date, currency) -> "USD per 1 unit of currency" lookup.
    to_usd = fx[fx["to_currency"] == "USD"][["date", "from_currency", "rate"]]
    to_usd = to_usd.rename(columns={"from_currency": "currency", "rate": "usd_per_unit"})

    from_usd = fx[fx["from_currency"] == "USD"][["date", "to_currency", "rate"]]
    from_usd = from_usd.rename(columns={"to_currency": "currency"})
    from_usd["usd_per_unit"] = 1 / from_usd["rate"]
    from_usd = from_usd.drop(columns="rate")

    lookup = pd.concat([to_usd, from_usd]).drop_duplicates(subset=["date", "currency"])
    usd_rows = pd.DataFrame({"date": fx["date"].unique(), "currency": "USD", "usd_per_unit": 1.0})
    lookup = pd.concat([lookup, usd_rows]).drop_duplicates(subset=["date", "currency"])

    # FX rates aren't published on weekends/holidays (only 65 of 91 days have a
    # rate per currency). Forward-fill each currency across the full date range
    # with the last known rate rather than leaving weekend orders unpriced.
    full_dates = pd.date_range(min(lookup["date"]), max(lookup["date"])).date
    filled = []
    for ccy, g in lookup.groupby("currency"):
        s = g.set_index("date")["usd_per_unit"].reindex(full_dates).ffill().bfill()
        filled.append(pd.DataFrame({"date": full_dates, "currency": ccy, "usd_per_unit": s.values}))
    return pd.concat(filled, ignore_index=True)


def fill_amount_usd(df, fx_lookup):
    missing = df["amount_usd"].isna()
    print(f"amount_usd missing for {missing.sum()} / {len(df)} rows before backfill")
    merged = df.merge(
        fx_lookup, left_on=["utc_date", "currency"], right_on=["date", "currency"], how="left"
    )
    computed = merged["amount"] * merged["usd_per_unit"]
    df = df.copy()
    df["amount_usd"] = df["amount_usd"].where(~missing, computed)
    still_missing = df["amount_usd"].isna().sum()
    if still_missing:
        print(f"WARNING: {still_missing} rows still missing amount_usd after FX backfill "
              f"(no rate for that currency/date)")
    return df


def approval_rate(frame, include_filtered=False):
    if include_filtered:
        denom = frame[frame["status"].isin(["APPROVED", "DECLINED", "FILTERED"])]
    else:
        denom = frame[frame["status"].isin(["APPROVED", "DECLINED"])]
    if len(denom) == 0:
        return np.nan
    return (denom["status"] == "APPROVED").mean()


def main():
    orders = load_orders()
    routes = load_routes()
    fx_lookup = build_fx_lookup()

    orders = orders.merge(
        routes[["route_id", "processor", "route_status", "live_from", "geo_passthrough", "currencies"]],
        on="route_id", how="left", suffixes=("", "_route"),
    )
    orders = fill_amount_usd(orders, fx_lookup)

    # Exclude test merchant and the two partial-extract days at the end of the snapshot.
    orders = orders[orders["merchant_id"] != "QA-TEST"]
    complete_cutoff = pd.Timestamp("2026-06-28").date()  # snapshot is 6/30; last 2 days partial
    orders_complete = orders[orders["utc_date"] <= complete_cutoff]

    nova = orders_complete[(orders_complete["merchant_id"] == "NOVA-FX") & (orders_complete["order_type"] == "SALE")]

    print("\n=== 1. Overall NOVA-FX SALE approval rate, pre vs post June 1 (complete days only) ===")
    pre = nova[nova["utc_date"] < pd.Timestamp("2026-06-01").date()]
    post = nova[nova["utc_date"] >= pd.Timestamp("2026-06-01").date()]
    print(f"Pre-Jun-1  (Apr 1 - May 31): n={len(pre):5d}  approval_rate={approval_rate(pre):.3f}  "
          f"(incl. filtered={approval_rate(pre, True):.3f})")
    print(f"Post-Jun-1 (Jun 1 - Jun 28): n={len(post):5d}  approval_rate={approval_rate(post):.3f}  "
          f"(incl. filtered={approval_rate(post, True):.3f})")

    print("\n=== 2. Weekly trend (SALE, approved/declined only) ===")
    nova_wk = nova.copy()
    nova_wk["week"] = pd.to_datetime(nova_wk["utc_date"]).dt.to_period("W-MON")
    weekly = nova_wk.groupby("week").apply(lambda g: approval_rate(g), include_groups=False)
    print(weekly.to_string())

    print("\n=== 3. Baseline sensitivity: bank_transfer only, before/after cascading (5/21) ===")
    bt = nova[nova["payment_method"] == "BANK_TRANSFER"]
    bt_pre_cascade = bt[bt["utc_date"] < pd.Timestamp("2026-05-21").date()]
    bt_post_cascade_pre_june = bt[(bt["utc_date"] >= pd.Timestamp("2026-05-21").date()) &
                                   (bt["utc_date"] < pd.Timestamp("2026-06-01").date())]
    bt_post_june = bt[bt["utc_date"] >= pd.Timestamp("2026-06-01").date()]
    print(f"Bank transfer before cascading (before 5/21): n={len(bt_pre_cascade):4d} "
          f"approval_rate={approval_rate(bt_pre_cascade):.3f}")
    print(f"Bank transfer after cascading, before June (5/21-5/31): n={len(bt_post_cascade_pre_june):4d} "
          f"approval_rate={approval_rate(bt_post_cascade_pre_june):.3f}")
    print(f"Bank transfer June onward: n={len(bt_post_june):4d} "
          f"approval_rate={approval_rate(bt_post_june):.3f}")

    print("\n=== 4. Decomposition by route (SALE, June onward vs pre-June) ===")
    by_route_pre = pre.groupby("route_id").apply(lambda g: pd.Series({
        "n": len(g), "approval_rate": approval_rate(g)}), include_groups=False)
    by_route_post = post.groupby("route_id").apply(lambda g: pd.Series({
        "n": len(g), "approval_rate": approval_rate(g)}), include_groups=False)
    print("--- pre Jun 1 ---")
    print(by_route_pre.to_string())
    print("--- Jun 1 onward ---")
    print(by_route_post.to_string())

    print("\n=== 4b. Mix-shift vs within-route: post-Jun rate excluding NBLX-07 ===")
    post_ex_nblx = post[post["route_id"] != "NBLX-07"]
    print(f"Post-Jun-1 rate WITH NBLX-07:    n={len(post):5d}  approval_rate={approval_rate(post):.3f}")
    print(f"Post-Jun-1 rate EXCLUDING NBLX-07: n={len(post_ex_nblx):5d}  approval_rate={approval_rate(post_ex_nblx):.3f}")
    print(f"(pre-Jun baseline was {approval_rate(pre):.3f}, for reference)")

    print("\n=== 5. NBLX-07 specifically: ramp-in + filtered-rate before/after risk tightening (6/8) ===")
    nblx07 = post[post["route_id"] == "NBLX-07"]
    print(f"NBLX-07 total post-6/1 SALE attempts: {len(nblx07)}")
    nblx07_wk = nblx07.copy()
    nblx07_wk["week"] = pd.to_datetime(nblx07_wk["utc_date"]).dt.to_period("W-MON")
    print(nblx07_wk.groupby("week").apply(
        lambda g: pd.Series({
            "n": len(g),
            "approval_rate_excl_filtered": approval_rate(g),
            "filtered_share": (g["status"] == "FILTERED").mean(),
        }), include_groups=False).to_string())

    print("\n=== 6. SORVA-14 JP-card traffic before/after BIN reallocation (6/11) ===")
    sorva_jp = orders_complete[
        (orders_complete["merchant_id"] == "NOVA-FX") &
        (orders_complete["order_type"] == "SALE") &
        (orders_complete["route_id"] == "SORVA-14") &
        (orders_complete["customer_country"] == "JP")
    ]
    before_bin = sorva_jp[sorva_jp["utc_date"] < pd.Timestamp("2026-06-11").date()]
    after_bin = sorva_jp[sorva_jp["utc_date"] >= pd.Timestamp("2026-06-11").date()]
    print(f"SORVA-14 / JP before 6/11: n={len(before_bin):4d} approval_rate={approval_rate(before_bin):.3f}")
    print(f"SORVA-14 / JP after  6/11: n={len(after_bin):4d} approval_rate={approval_rate(after_bin):.3f}")
    print("Decline reasons after 6/11:")
    print(after_bin[after_bin["status"] == "DECLINED"]["decline_reason"].value_counts().to_string())

    print("\n=== 7. Cost estimate: dollar-weighted, not count-weighted ===")
    # NOTE: count-of-lost-attempts x a single blended average ticket size is
    # WRONG here because NBLX-07's tickets (~$300) are much smaller than the
    # rest of Nova's book (~$900) -- that approach overstated cost by >2x in
    # an earlier draft. Instead: compare actual approved USD to what the
    # PRE-JUNE DOLLAR-weighted approval rate (approved $ / reached $) would
    # have produced against the actual post-June dollar volume attempted.
    def dollar_rate(frame):
        r = frame[frame["status"].isin(["APPROVED", "DECLINED"])]
        return r.loc[r["status"] == "APPROVED", "amount_usd"].sum() / r["amount_usd"].sum()

    def cost_usd(frame, baseline, label):
        r = frame[frame["status"].isin(["APPROVED", "DECLINED"])]
        actual = r.loc[r["status"] == "APPROVED", "amount_usd"].sum()
        expected = baseline * r["amount_usd"].sum()
        lost = expected - actual
        print(f"{label}: reached_usd={r['amount_usd'].sum():,.0f} actual_approved_usd={actual:,.0f} "
              f"expected_usd={expected:,.0f} lost_usd={lost:,.0f}")
        return lost

    pre_dollar_rate = dollar_rate(pre)
    print(f"Dollar-weighted approval rate: pre-Jun={pre_dollar_rate:.3f} post-Jun={dollar_rate(post):.3f}")
    total_lost = cost_usd(post, pre_dollar_rate, "TOTAL, Jun vs pre-Jun dollar-rate baseline")
    excl_nblx_lost = cost_usd(post[post["route_id"] != "NBLX-07"], pre_dollar_rate, "  Excluding NBLX-07")
    nblx_lost = cost_usd(post[post["route_id"] == "NBLX-07"], pre_dollar_rate, "  NBLX-07 alone")
    print(f"  (check: {excl_nblx_lost:,.0f} + {nblx_lost:,.0f} = {excl_nblx_lost + nblx_lost:,.0f} "
          f"vs total {total_lost:,.0f})")

    sorva_jp = nova[(nova["route_id"] == "SORVA-14") & (nova["customer_country"] == "JP")]
    sorva_before = sorva_jp[sorva_jp["utc_date"] < pd.Timestamp("2026-06-11").date()]
    sorva_after = sorva_jp[sorva_jp["utc_date"] >= pd.Timestamp("2026-06-11").date()]
    sorva_baseline = dollar_rate(sorva_before)
    print(f"\nSORVA-14/JP own dollar-rate baseline (pre-6/11): {sorva_baseline:.3f}")
    cost_usd(sorva_after, sorva_baseline, "  SORVA-14/JP alone, vs its own pre-6/11 baseline")

    print("\n=== 8. Internal-only cost: FILTERED volume on NBLX-07 (invisible to merchant) ===")
    nblx07_filtered = nblx07[nblx07["status"] == "FILTERED"]
    print(f"NBLX-07 filtered attempts post-6/1: {len(nblx07_filtered)} "
          f"(USD value {nblx07_filtered['amount_usd'].sum():,.0f})")

    print("\n=== 9. Validation: reproduce merchant_dashboard_export.csv from raw orders ===")
    export = pd.read_csv(DATA / "merchant_dashboard_export.csv")
    export = export[export["date"].notna()]
    export["date"] = pd.to_datetime(export["date"]).dt.date
    # Portal: local date (UTC+8), deposits (SALE) only, attempts that reached a
    # provider (i.e. excludes FILTERED), grouped by payment_method.
    nova_all = orders[(orders["merchant_id"] == "NOVA-FX") & (orders["order_type"] == "SALE")]
    # Portal shows only attempts with a final outcome from a provider; PENDING
    # (no outcome yet) isn't shown either, confirmed by matching export exactly
    # once PENDING is excluded here.
    reached = nova_all[nova_all["status"].isin(["APPROVED", "DECLINED"])]
    recon = reached.groupby(["local_date", "payment_method"]).agg(
        attempts=("order_id", "count"),
        approved=("status", lambda s: (s == "APPROVED").sum()),
    ).reset_index().rename(columns={"local_date": "date"})
    check = export.merge(recon, on=["date", "payment_method"], suffixes=("_export", "_recomputed"), how="left")
    check["attempts_diff"] = check["attempts_export"] - check["attempts_recomputed"]
    check["approved_diff"] = check["approved_export"] - check["approved_recomputed"]
    print(f"Rows compared: {len(check)}")
    print(f"Attempts diff: mean={check['attempts_diff'].mean():.3f} max_abs={check['attempts_diff'].abs().max()}")
    print(f"Approved diff: mean={check['approved_diff'].mean():.3f} max_abs={check['approved_diff'].abs().max()}")
    mismatches = check[(check["attempts_diff"].abs() > 0) | (check["approved_diff"].abs() > 0)]
    print(f"Mismatched rows: {len(mismatches)}")
    if len(mismatches):
        print(mismatches.head(10).to_string())


if __name__ == "__main__":
    main()
