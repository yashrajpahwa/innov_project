"""Live re-scoring: approved orders feed back into the ledgers and the model.

When a supplier approves an order, it is booked as a new unpaid invoice in
that supplier's ledger (dated today, due after the usual credit terms). The
dealer's features are recomputed across the whole network and the trained
model scores it again, so the rating, band and suggested limits move. Every
supplier who sells to that dealer sees the new rating.

A held order books nothing, so the model's view of the dealer doesn't change.
Decisions are saved in data/orders.csv and replayed when the API starts.
"""
import json
from pathlib import Path

import joblib
import pandas as pd

import config as C
from features import compute_features, load_invoices, pair_stats
from train import predict_pd, suggested_limits, top_factors

ORDER_COLS = ["order_id", "supplier_id", "gstin", "order_value", "decision", "created_at",
              "rating_before", "pd_before", "rating_after", "pd_after"]


class Scorer:
    def __init__(self, data_dir: Path = C.DATA_DIR):
        self.data_dir = Path(data_dir)
        self.inv = load_invoices(self.data_dir)
        self.model = joblib.load(self.data_dir / "model" / "model.joblib")["model"]
        last = self.inv.sort_values("invoice_date").groupby(["supplier_id", "gstin"]).last()
        self.terms = last.credit_terms_days
        self.names = last.dealer_name
        self.cities = last.city
        self.limits = (pd.read_csv(self.data_dir / "credit_limits.csv")
                       .set_index(["supplier_id", "gstin"]).credit_limit)

    # ---- orders file -------------------------------------------------------
    @property
    def orders_file(self) -> Path:
        return self.data_dir / "orders.csv"

    def load_orders(self) -> pd.DataFrame:
        if self.orders_file.exists():
            return pd.read_csv(self.orders_file)
        return pd.DataFrame(columns=ORDER_COLS)

    def save_orders(self, orders: pd.DataFrame) -> None:
        orders[ORDER_COLS].to_csv(self.orders_file, index=False)

    # ---- scoring -----------------------------------------------------------
    def _order_invoices(self, orders: pd.DataFrame) -> pd.DataFrame:
        """Approved orders as ledger rows: unpaid invoices raised on the as-of date."""
        approved = orders[orders.decision == "approve"]
        rows = []
        for o in approved.itertuples():
            key = (o.supplier_id, o.gstin)
            terms = int(self.terms[key])
            rows.append(dict(
                supplier_id=o.supplier_id, invoice_no=o.order_id, dealer_name=self.names[key],
                gstin=o.gstin, city=self.cities[key], invoice_date=C.AS_OF,
                amount=float(o.order_value), credit_terms_days=terms, paid_date=pd.NaT,
                due_date=C.AS_OF + pd.Timedelta(days=terms)))
        return pd.DataFrame(rows)

    def score(self, gstin: str, orders: pd.DataFrame) -> dict:
        """Re-score one dealer from its full network ledger plus approved orders."""
        d = self.inv[self.inv.gstin == gstin]
        extra = self._order_invoices(orders[orders.gstin == gstin])
        if len(extra):
            d = pd.concat([d, extra], ignore_index=True)

        F = compute_features(d, C.N_MONTHS)
        pd_now = float(predict_pd(self.model, F)[0])
        rating = C.pd_to_rating(pd_now)
        F = F.assign(pd=pd_now, rating=rating,
                     band=C.exposure_band(F.total_outstanding.iloc[0]))
        F["top_factors"] = [json.dumps(t) for t in top_factors(self.model, F)]

        pairs = pair_stats(d).set_index(["supplier_id", "gstin"])
        pairs["credit_limit"] = self.limits.reindex(pairs.index)
        pairs["suggested_limit"] = suggested_limits(
            pairs.own_avg_monthly_purchases, pd.Series(rating, index=pairs.index))
        return {"features": F.iloc[0], "pairs": pairs.reset_index(), "pd": pd_now, "rating": rating}
