"""Turn supplier ledgers into per-dealer features.

Ledgers from all suppliers are pooled and matched on GSTIN. Every feature is
computed "as of" the end of a given month, so we only use what was known then.
"""
from pathlib import Path

import numpy as np
import pandas as pd

import config as C

FEATURES = [
    "avg_dbt", "latest_dbt", "dbt_change_3m", "log_total_outstanding",
    "n_suppliers", "outstanding_growth_6m", "share_overdue", "largest_supplier_share",
]

LATE_DAYS = 7   # paid more than a week past terms counts as "overdue"

FEATURE_LABELS = {
    "avg_dbt": "Average days beyond terms (12 months)",
    "latest_dbt": "Days beyond terms, last 3 months",
    "dbt_change_3m": "Payments slowing (3-month change)",
    "log_total_outstanding": "Total outstanding across the network",
    "n_suppliers": "Number of suppliers",
    "outstanding_growth_6m": "Outstanding growth over 6 months",
    "share_overdue": "Share of recent invoices paid late",
    "largest_supplier_share": "Concentration on one supplier",
}


def load_invoices(data_dir: Path = C.DATA_DIR) -> pd.DataFrame:
    """Pool all supplier ledgers into one table (matching is simply on GSTIN)."""
    files = sorted((Path(data_dir) / "ledgers").glob("ledger_*.csv"))
    inv = pd.concat([pd.read_csv(f, parse_dates=["invoice_date", "paid_date"]) for f in files],
                    ignore_index=True)
    inv["due_date"] = inv.invoice_date + pd.to_timedelta(inv.credit_terms_days, unit="D")
    return inv


def _status_asof(inv: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """Invoices raised by `asof`, with outstanding / overdue flags and DBT at that date."""
    d = inv[inv.invoice_date <= asof].copy()
    paid = d.paid_date.notna() & (d.paid_date <= asof)
    due_passed = d.due_date <= asof
    late_paid = (d.paid_date - d.due_date).dt.days
    late_open = (asof - d.due_date).dt.days
    d["dbt"] = np.where(paid, late_paid, np.where(due_passed, late_open, np.nan))
    d["dbt"] = d.dbt.clip(lower=0)
    d["outstanding"] = np.where(paid, 0.0, d.amount)
    d["overdue"] = np.where(~paid & due_passed, d.amount, 0.0)
    return d


def compute_features(inv: pd.DataFrame, month: int) -> pd.DataFrame:
    """One row per GSTIN with the model features as of the end of `month`."""
    asof = C.month_end(month)
    d = _status_asof(inv, asof)
    g = d.groupby("gstin")

    still_open = d.overdue > 0

    def window_mean(lo_days, hi_days, include_open=True):
        """Mean DBT of invoices due in the window. Unpaid overdue invoices always
        count (at their current age), so a dealer who stops paying can't look clean."""
        in_window = ((d.due_date > asof - pd.Timedelta(days=lo_days)) &
                     (d.due_date <= asof - pd.Timedelta(days=hi_days)))
        w = d[in_window | (still_open & include_open)]
        return w.groupby("gstin").dbt.mean()

    f = pd.DataFrame(index=g.size().index)
    f["avg_dbt"] = window_mean(365, 0)
    f["latest_dbt"] = window_mean(90, 0)
    f["dbt_change_3m"] = f.latest_dbt - window_mean(180, 90, include_open=False)
    f["total_outstanding"] = g.outstanding.sum()
    # Oldest unpaid invoice, in days past due (not a model input; 90+ = in default)
    f["max_days_past_due"] = d[still_open].groupby("gstin").dbt.max()
    f["log_total_outstanding"] = np.log1p(f.total_outstanding)

    last12 = d[d.invoice_date > asof - pd.Timedelta(days=365)]
    f["n_suppliers"] = last12.groupby("gstin").supplier_id.nunique()

    prev = _status_asof(inv, C.month_end(month - 6)).groupby("gstin").outstanding.sum()
    prev = prev.reindex(f.index).fillna(0)
    f["outstanding_growth_6m"] = (f.total_outstanding / (prev + C.LAKH) - 1).clip(-1, 5)

    # Share of invoices due in the last 6 months that were paid (or are still
    # open) more than a week past terms. New orders that aren't due yet don't
    # dilute it, so booking more credit can never make a dealer look safer.
    due6 = d[(d.due_date > asof - pd.DateOffset(months=6)) & d.dbt.notna()]
    f["share_overdue"] = (due6.dbt > LATE_DAYS).groupby(due6.gstin).mean()

    by_sup = last12.groupby(["gstin", "supplier_id"]).amount.sum()
    f["largest_supplier_share"] = by_sup.groupby("gstin").max() / by_sup.groupby("gstin").sum()

    # Average monthly purchases over the last 6 months (network), for reference
    last6 = d[d.invoice_date > asof - pd.DateOffset(months=6)]
    f["avg_monthly_purchases"] = last6.groupby("gstin").amount.sum() / 6

    # A dealer with nothing due in a window simply has no lateness there
    f[FEATURES] = f[FEATURES].fillna(0)
    f["avg_monthly_purchases"] = f.avg_monthly_purchases.fillna(0)
    f["max_days_past_due"] = f.max_days_past_due.fillna(0)
    f["dbt_change_3m"] = f.dbt_change_3m.fillna(0)
    return f


def pair_stats(inv: pd.DataFrame, month: int = C.N_MONTHS) -> pd.DataFrame:
    """Per supplier-dealer pair: that supplier's own outstanding and purchases."""
    asof = C.month_end(month)
    d = _status_asof(inv, asof)
    last6 = d[d.invoice_date > asof - pd.DateOffset(months=6)]
    out = d.groupby(["supplier_id", "gstin"]).agg(
        dealer_name=("dealer_name", "first"), city=("city", "first"),
        own_outstanding=("outstanding", "sum"), own_overdue=("overdue", "sum"))
    out["own_avg_monthly_purchases"] = last6.groupby(["supplier_id", "gstin"]).amount.sum() / 6
    return out.fillna({"own_avg_monthly_purchases": 0}).reset_index()


def monthly_dbt(inv: pd.DataFrame, month: int = C.N_MONTHS) -> pd.DataFrame:
    """Average days beyond terms by due month: per supplier and for the whole network."""
    d = _status_asof(inv, C.month_end(month)).dropna(subset=["dbt"])
    d["month"] = ((d.due_date.dt.year - C.START.year) * 12 + d.due_date.dt.month - C.START.month + 1)
    per_sup = d.groupby(["gstin", "supplier_id", "month"]).dbt.mean().reset_index()
    network = d.groupby(["gstin", "month"]).dbt.mean().reset_index()
    network["supplier_id"] = "ALL"
    return pd.concat([per_sup, network], ignore_index=True)
