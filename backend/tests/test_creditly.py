"""Creditly tests: reproducible data, rating rules, and no cross-supplier leaks."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import config as C
from generate_data import generate


# ---- 1. The generator is reproducible --------------------------------------
def test_generator_is_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, seed=7)
    generate(b, seed=7)
    files = sorted(p.relative_to(a) for p in a.rglob("*.csv"))
    assert len(files) == 3 + len(C.SUPPLIERS)   # suppliers, limits, truth + ledgers
    for f in files:
        assert (a / f).read_bytes() == (b / f).read_bytes(), f"{f} differs between runs"


def test_story_dealer_is_seeded(tmp_path):
    generate(tmp_path)
    rows = pd.concat(pd.read_csv(f) for f in (tmp_path / "ledgers").glob("*.csv"))
    sharma = rows[rows.gstin == "07ABCDE1234F1Z5"]
    assert sorted(sharma.supplier_id.unique()) == ["A", "B", "C", "E"]
    assert sharma.dealer_name.nunique() == 4           # spelled differently in each book
    open_total = sharma[sharma.paid_date.isna()].amount.sum()
    assert abs(open_total - 4.2 * C.CRORE) < 0.01 * C.CRORE


# ---- 2. Ratings map correctly ----------------------------------------------
@pytest.mark.parametrize("pd_value,rating", [
    (0.0, "AAA"), (0.0124, "AAA"), (0.0125, "AA"), (0.03, "A"), (0.05, "BBB"),
    (0.11, "BB"), (0.2, "B"), (0.45, "C"), (0.5, "D"), (0.99, "D"), (1.0, "D"),
])
def test_pd_to_rating(pd_value, rating):
    assert C.pd_to_rating(pd_value) == rating


def test_cutoffs_and_multipliers_are_ordered():
    uppers = [u for _, u in C.PD_CUTOFFS]
    assert uppers == sorted(uppers)
    assert [r for r, _ in C.PD_CUTOFFS] == C.RATINGS
    mults = [C.LIMIT_MULTIPLIER[r] for r in C.RATINGS]
    assert mults == sorted(mults, reverse=True) and mults[0] == 3.0 and mults[-1] == 0


def test_exposure_band():
    assert C.exposure_band(42_000_000) == "₹3-5 cr"
    assert C.exposure_band(10 * C.LAKH) == "< ₹50 L"


# ---- 3. The API never leaks another supplier's name or amounts --------------
@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """API running on a private copy of data/, so tests never touch your real
    data or your saved order decisions."""
    import shutil
    import main
    data = tmp_path_factory.mktemp("data")
    shutil.copytree(C.DATA_DIR, data, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("orders.csv"))
    real = C.DATA_DIR, C.MODEL_DIR
    C.DATA_DIR, C.MODEL_DIR = data, data / "model"
    try:
        with TestClient(main.app) as c:
            yield c
    finally:
        C.DATA_DIR, C.MODEL_DIR = real


def _numbers(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numbers(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield float(obj)


def test_api_does_not_leak_other_suppliers(client):
    pairs = pd.read_csv(C.DATA_DIR / "pair_stats.csv")
    scores = pd.read_csv(C.DATA_DIR / "scores.csv").set_index("gstin")
    names = dict(C.SUPPLIERS)
    me = "A"
    others = [s for s in names if s != me]

    shared = pairs.groupby("gstin").supplier_id.nunique()
    mine = set(pairs[pairs.supplier_id == me].gstin)
    gstins = ["07ABCDE1234F1Z5"] + [g for g in shared[shared > 1].index if g in mine][:15]

    lists = [client.get("/dealers", params={"supplier_id": me}).json(),
             client.get("/alerts", params={"supplier_id": me}).json()]
    per_dealer = {}
    for g in gstins:
        per_dealer[g] = [
            client.get(f"/dealers/{g}", params={"supplier_id": me}).json(),
            client.post("/check-order", json={"supplier_id": me, "gstin": g, "order_value": 1_840_000}).json(),
        ] + [row for lst in lists for row in lst if row["gstin"] == g]

    # No other supplier's name anywhere
    text = json.dumps([lists, per_dealer], ensure_ascii=False)
    for s in others:
        assert names[s] not in text
        assert names[s].split(" - ")[1] not in text       # e.g. "Printers"

    # No other supplier's amounts (or the exact network total) for that dealer
    for g, resp in per_dealer.items():
        numbers = set(round(x) for x in _numbers(resp))
        own = pairs[(pairs.gstin == g) & (pairs.supplier_id == me)].iloc[0]
        own_values = {round(own.own_outstanding), round(own.credit_limit), round(own.own_avg_monthly_purchases)}
        theirs = pairs[(pairs.gstin == g) & (pairs.supplier_id != me)]
        secret = list(theirs.own_outstanding) + list(theirs.credit_limit) + list(theirs.own_avg_monthly_purchases)
        secret.append(scores.loc[g, "total_outstanding"])   # only the band may be shown
        for amount in secret:
            if amount > 0 and round(amount) not in own_values:
                assert round(amount) not in numbers, f"leaked {amount} for {g}"


def test_supplier_cannot_open_dealer_outside_its_ledger(client):
    r = client.get("/dealers/07ABCDE1234F1Z5", params={"supplier_id": "D"})
    assert r.status_code == 404


def test_story_order_is_held(client):
    r = client.post("/check-order", json={
        "supplier_id": "A", "gstin": "07ABCDE1234F1Z5", "order_value": 1_840_000}).json()
    assert r["rating"] == "BB" and r["band"] == "₹3-5 cr"
    assert r["own_outstanding"] + 1_840_000 <= r["own_credit_limit"]   # fine in A's own books
    assert r["recommendation"] == "Hold"


# ---- 4. Approve / hold feed back into the model -----------------------------
def test_rescoring_without_orders_matches_training(client):
    import main
    scorer, scores = main.STATE["scorer"], main.STATE["scores"]
    empty = scorer.load_orders().iloc[0:0]
    for g in scores.index[:25]:
        assert abs(scorer.score(g, empty)["pd"] - scores.loc[g, "pd"]) < 1e-9


def test_approve_rerates_dealer_and_hold_does_not(client):
    import main
    client.post("/admin/reset-orders")
    try:
        scores, pairs = main.STATE["scores"], main.STATE["pairs"]
        # An A-rated dealer that buys from at least two suppliers
        multi = pairs.groupby("gstin").supplier_id.nunique()
        g = next(x for x in scores.index[scores.rating == "A"] if multi.get(x, 0) >= 2)
        me, other = sorted(pairs[pairs.gstin == g].supplier_id)[:2]
        start = client.get(f"/dealers/{g}", params={"supplier_id": me}).json()
        order = {"supplier_id": me, "gstin": g, "order_value": scores.loc[g, "total_outstanding"] * 0.5}

        held = client.post("/orders", json={**order, "decision": "hold"}).json()
        assert held["after"]["pd"] == start["pd"] and held["after"]["own_outstanding"] == start["own_outstanding"]

        preview = client.post("/check-order", json=order).json()["if_approved"]
        r = client.post("/orders", json={**order, "decision": "approve"}).json()
        assert r["after"]["pd"] == preview["pd"]                       # preview = what really happens
        assert r["after"]["pd"] > start["pd"]                          # more credit, more risk
        assert r["after"]["own_outstanding"] == start["own_outstanding"] + order["order_value"]

        pds = [r["after"]["pd"]]
        while r["after"]["rating"] == "A" and len(pds) < 10:
            r = client.post("/orders", json={**order, "decision": "approve"}).json()
            pds.append(r["after"]["pd"])
        assert pds == sorted(pds) and r["after"]["rating"] != "A"      # eventually downgraded

        # The other supplier sees the new rating, but not my orders
        seen = client.get(f"/dealers/{g}", params={"supplier_id": other}).json()
        assert seen["rating"] == r["after"]["rating"]
        assert client.get("/orders", params={"supplier_id": other}).json() == []
        assert len(client.get("/orders", params={"supplier_id": me}).json()) == len(pds) + 1
    finally:
        client.post("/admin/reset-orders")
    assert client.get(f"/dealers/{g}", params={"supplier_id": me}).json()["pd"] == start["pd"]
