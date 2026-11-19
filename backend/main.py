"""Creditly API.

Privacy rule: a supplier only ever sees the dealer's rating, PD, exposure band
and its OWN figures. Other suppliers' names and amounts never leave this file.

Run:  uvicorn main:app --reload --port 8000
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config as C
from features import FEATURE_LABELS
from rescore import Scorer

STATE: dict = {}


def load_state() -> None:
    d = C.DATA_DIR
    STATE["suppliers"] = pd.read_csv(d / "suppliers.csv")
    STATE["scores"] = pd.read_csv(d / "scores.csv").set_index("gstin")
    STATE["history"] = pd.read_csv(d / "history.csv")
    STATE["pairs"] = pd.read_csv(d / "pair_stats.csv")
    STATE["dbt"] = pd.read_csv(d / "dbt_monthly.csv")
    STATE["metrics"] = json.loads((C.MODEL_DIR / "metrics.json").read_text())
    STATE["scorer"] = Scorer(d)
    STATE["orders"] = STATE["scorer"].load_orders()
    # Replay approved orders so ratings reflect every decision made so far
    for gstin in STATE["orders"].query("decision == 'approve'").gstin.unique():
        _apply(gstin)


def _apply(gstin: str) -> None:
    """Re-run the model for one dealer and update everything the API serves."""
    res = STATE["scorer"].score(gstin, STATE["orders"])
    F, scores = res["features"], STATE["scores"]
    for col in scores.columns:
        if col in F.index and col != "rating_3m_ago":
            scores.at[gstin, col] = F[col]
    pairs = STATE["pairs"]
    for r in res["pairs"].itertuples():
        mask = (pairs.supplier_id == r.supplier_id) & (pairs.gstin == gstin)
        for col in ["own_outstanding", "own_overdue", "own_avg_monthly_purchases", "suggested_limit"]:
            pairs.loc[mask, col] = getattr(r, col)
    h = STATE["history"]
    latest = (h.gstin == gstin) & (h.month == C.N_MONTHS)
    h.loc[latest, "pd"] = round(res["pd"], 4)
    h.loc[latest, "rating"] = res["rating"]


def build_all() -> None:
    from generate_data import generate
    from train import train
    generate()
    train()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not (C.MODEL_DIR / "model.joblib").exists() or not (C.DATA_DIR / "scores.csv").exists():
        build_all()
    load_state()
    yield


app = FastAPI(title="Creditly", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _check_supplier(supplier_id: str) -> None:
    if supplier_id not in set(STATE["suppliers"].supplier_id):
        raise HTTPException(404, f"Unknown supplier '{supplier_id}'")


def _pair(supplier_id: str, gstin: str) -> pd.Series:
    _check_supplier(supplier_id)
    p = STATE["pairs"]
    row = p[(p.supplier_id == supplier_id) & (p.gstin == gstin)]
    if row.empty:
        raise HTTPException(404, "This dealer is not in your ledger")
    return row.iloc[0]


def _trend(rating: str, before) -> str:
    if not isinstance(before, str):
        return "flat"
    diff = C.rating_index(rating) - C.rating_index(before)
    return "down" if diff > 0 else "up" if diff < 0 else "flat"


def _summary(pair: pd.Series) -> dict:
    """The fields a supplier may see about one of its dealers."""
    s = STATE["scores"].loc[pair.gstin]
    return {
        "gstin": pair.gstin,
        "name": pair.dealer_name,                       # the supplier's own spelling
        "city": pair.city,
        "rating": s.rating,
        "rating_3m_ago": s.rating_3m_ago,
        "trend": _trend(s.rating, s.rating_3m_ago),
        "pd": round(float(s.pd), 4),
        "band": s.band,
        "suggested_limit": float(pair.suggested_limit),
        "own_outstanding": float(pair.own_outstanding),
        "own_credit_limit": float(pair.credit_limit),
    }


def _factor_text(feature: str, s: pd.Series) -> str:
    """Readable value for a factor. Network amounts are shown only as a band."""
    v = s[feature]
    return {
        "avg_dbt": f"{v:.0f} days on average",
        "latest_dbt": f"{v:.0f} days recently",
        "dbt_change_3m": f"{v:+.0f} days vs the 3 months before",
        "log_total_outstanding": f"Band {s.band}",
        "n_suppliers": f"Buys from {int(v)} suppliers",
        "outstanding_growth_6m": f"{v:+.0%} in 6 months",
        "share_overdue": f"{v:.0%} of invoices due in 6 months were 7+ days late",
        "largest_supplier_share": "Most purchases with one supplier",
    }[feature]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/suppliers")
def suppliers():
    return [{"id": r.supplier_id, "name": r.name} for r in STATE["suppliers"].itertuples()]


@app.get("/dealers")
def dealers(supplier_id: str = Query(...)):
    _check_supplier(supplier_id)
    rows = STATE["pairs"][STATE["pairs"].supplier_id == supplier_id]
    out = [_summary(r) for _, r in rows.iterrows()]
    return sorted(out, key=lambda d: (-C.rating_index(d["rating"]), -d["own_outstanding"]))


@app.get("/dealers/{gstin}")
def dealer_detail(gstin: str, supplier_id: str = Query(...)):
    pair = _pair(supplier_id, gstin)
    s = STATE["scores"].loc[gstin]
    h = STATE["history"][STATE["history"].gstin == gstin].sort_values("month")

    dbt = STATE["dbt"][(STATE["dbt"].gstin == gstin) & STATE["dbt"].supplier_id.isin(["ALL", supplier_id])]
    trend = []
    for m in range(1, C.N_MONTHS + 1):
        sel = dbt[dbt.month == m]
        net = sel[sel.supplier_id == "ALL"].dbt
        own = sel[sel.supplier_id == supplier_id].dbt
        trend.append({"month": C.month_label(m),
                      "network": round(float(net.iloc[0]), 1) if len(net) else None,
                      "yours": round(float(own.iloc[0]), 1) if len(own) else None})

    factors = [{"feature": f["feature"], "label": FEATURE_LABELS[f["feature"]],
                "value": _factor_text(f["feature"], s), "contribution": f["contribution"]}
               for f in json.loads(s.top_factors)]

    return {
        **_summary(pair),
        "own_avg_monthly_purchases": float(pair.own_avg_monthly_purchases),
        "history": [{"month": r.label, "rating": r.rating, "pd": r.pd} for r in h.itertuples()],
        "dbt_trend": trend,
        "top_factors": factors,
    }


class OrderCheck(BaseModel):
    supplier_id: str
    gstin: str
    order_value: float


def _inr(x: float) -> str:
    if x >= C.CRORE:
        return f"₹{x / C.CRORE:.2f} cr"
    return f"₹{x / C.LAKH:.1f} L"


@app.post("/check-order")
def check_order(req: OrderCheck):
    pair = _pair(req.supplier_id, req.gstin)
    info = _summary(pair)
    rating, limit, owed = info["rating"], info["suggested_limit"], info["own_outstanding"]

    # What the model would say if this order were booked
    trial = _append(STATE["orders"], {
        "order_id": "preview", "supplier_id": req.supplier_id, "gstin": req.gstin,
        "order_value": req.order_value, "decision": "approve"})
    res = STATE["scorer"].score(req.gstin, trial)
    if_approved = {"rating": res["rating"], "pd": round(res["pd"], 4),
                   "band": res["features"].band,
                   "trend": _trend(res["rating"], rating)}
    after = owed + req.order_value

    if rating in ("C", "D"):
        rec, approved = "Hold", 0.0
        reason = f"Rated {rating}: high chance of default ({info['pd']:.0%}). Collect dues before shipping more."
    elif after <= limit:
        rec, approved = "Approve", req.order_value
        reason = f"Exposure after this order ({_inr(after)}) is within the suggested limit of {_inr(limit)}."
    elif owed < limit and rating not in ("B",):
        rec, approved = "Approve with reduced limit", round(limit - owed, -3)
        reason = f"Only {_inr(limit - owed)} of headroom left under the suggested limit of {_inr(limit)}."
    else:
        rec, approved = "Hold", 0.0
        reason = (f"Network rating {rating} (was {info['rating_3m_ago']}): you are already owed "
                  f"{_inr(owed)}, above the suggested limit of {_inr(limit)}.")
    return {**info, "order_value": req.order_value, "exposure_after_order": after,
            "recommendation": rec, "approved_amount": approved, "reason": reason,
            "if_approved": if_approved}


def _append(orders: pd.DataFrame, row: dict) -> pd.DataFrame:
    new = pd.DataFrame([row]).reindex(columns=orders.columns)
    return new if orders.empty else pd.concat([orders, new], ignore_index=True)


class OrderDecision(OrderCheck):
    decision: Literal["approve", "hold"]


@app.post("/orders")
def decide_order(req: OrderDecision):
    """Approve books the order into the ledger and re-runs the model; Hold books nothing."""
    pair = _pair(req.supplier_id, req.gstin)
    before = _summary(pair)
    orders = STATE["orders"]
    order_id = f"SO-{len(orders) + 1:05d}"
    row = {"order_id": order_id, "supplier_id": req.supplier_id, "gstin": req.gstin,
           "order_value": req.order_value, "decision": req.decision,
           "created_at": datetime.now().isoformat(timespec="seconds"),
           "rating_before": before["rating"], "pd_before": before["pd"],
           "rating_after": before["rating"], "pd_after": before["pd"]}   # updated below
    STATE["orders"] = _append(orders, row)
    if req.decision == "approve":
        _apply(req.gstin)
    after = _summary(_pair(req.supplier_id, req.gstin))
    last = STATE["orders"].index[-1]
    STATE["orders"].loc[last, ["rating_after", "pd_after"]] = [after["rating"], after["pd"]]
    STATE["scorer"].save_orders(STATE["orders"])

    message = "Order approved." if req.decision == "approve" else "Order held."
    return {"order_id": order_id, "decision": req.decision, "before": before, "after": after,
            "message": message}


@app.get("/orders")
def list_orders(supplier_id: str = Query(...)):
    """This supplier's own decisions only."""
    _check_supplier(supplier_id)
    o = STATE["orders"]
    o = o[o.supplier_id == supplier_id].iloc[::-1]
    names = STATE["pairs"].set_index(["supplier_id", "gstin"]).dealer_name
    return [{"order_id": r.order_id, "gstin": r.gstin, "name": names[(supplier_id, r.gstin)],
             "order_value": float(r.order_value), "decision": r.decision, "created_at": r.created_at,
             "rating_before": r.rating_before, "pd_before": float(r.pd_before),
             "rating_after": r.rating_after, "pd_after": float(r.pd_after)}
            for r in o.itertuples()]


@app.get("/alerts")
def alerts(supplier_id: str = Query(...)):
    out = [d for d in dealers(supplier_id) if d["trend"] == "down"]
    for d in out:
        d["notches_down"] = C.rating_index(d["rating"]) - C.rating_index(d["rating_3m_ago"])
    # Biggest money at risk first: notches dropped x amount owed to you
    return sorted(out, key=lambda d: -d["notches_down"] * d["own_outstanding"])


@app.get("/model/metrics")
def model_metrics():
    return STATE["metrics"]


@app.post("/admin/reset-orders")
def reset_orders():
    """Forget every approve/hold decision and go back to the ratings from training."""
    (C.DATA_DIR / "orders.csv").unlink(missing_ok=True)
    load_state()
    return {"status": "ok"}


@app.post("/admin/regenerate")
def regenerate():
    build_all()
    load_state()
    return {"status": "ok", "metrics": STATE["metrics"]}
