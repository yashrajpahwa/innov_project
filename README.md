# Creditly: network credit ratings for B2B dealers (classroom demo)

Suppliers (brands and distributors) in India's IT and electronics channel share their dealer
ledgers with Creditly. Creditly matches the same dealer across suppliers by **GSTIN** and gives
each dealer one rating from **AAA to D**, an **exposure band** (for example "₹3-5 cr") and a
**suggested credit limit**. A supplier only ever sees the rating and the band, never another
supplier's name or figures.

> Everything here is synthetic. No auth, no external APIs, no cloud services.

```
backend/    FastAPI + pandas + scikit-learn (Python 3.11)
  config.py         rating cut-offs, limit multipliers, exposure bands (one place)
  generate_data.py  synthetic ledgers (fixed seed)
  features.py       per-dealer features, pooled across suppliers by GSTIN
  train.py          logistic regression vs random forest, ratings, history
  rescore.py        approved orders -> ledger -> model re-rates the dealer live
  main.py           REST API
  tests/            pytest
frontend/   React + Vite + Recharts
data/       generated CSVs, model.joblib, metrics.json (created on first run)
```

## One-time setup

You need Python 3.11 and Node 18 or later.

```bash
# backend
py -3.11 -m venv backend/.venv          # macOS/Linux: python3.11 -m venv backend/.venv
backend/.venv/Scripts/pip install -r backend/requirements.txt   # macOS/Linux: backend/.venv/bin/pip ...

# frontend
cd frontend && npm install
```

`run.bat` and `run.sh` do these steps automatically if they haven't been done yet.

## Run

The quickest way starts both servers:

```bash
run.bat          # Windows: opens two windows
./run.sh         # macOS/Linux/Git Bash
```

Or start each one yourself:

```bash
# Terminal 1: API on http://localhost:8000  (docs at /docs)
cd backend
.venv/Scripts/python -m uvicorn main:app --reload --port 8000

# Terminal 2: app on http://localhost:5173
cd frontend
npm run dev
```

On first start, the API generates the data and trains the model if `data/model/model.joblib`
doesn't exist yet (about 20 seconds). To rebuild by hand:

```bash
cd backend
.venv/Scripts/python generate_data.py
.venv/Scripts/python train.py
```

Run the tests:

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

## 2-minute demo script

1. **Log in as Supplier A.** Open http://localhost:5173. The header dropdown already says
   *Logged in as Supplier A - Laptops*. The Portfolio shows A's 136 dealers by rating.
2. **Open the order.** Go to **Order approval**. It is prefilled with *SHARMA ELECTRONICS PVT LTD*
   and an order of **₹18,40,000**.
   - Point at the ERP on the left: *Owed to us ₹1,02,00,000*, *Our credit limit
     ₹1,50,00,000* and a green **✔ Within our credit limit**. In A's own books, Sharma looks fine.
     It pays A a little early.
   - Point at the Creditly panel on the right: **BB ▼ from A**, network exposure **₹3-5 cr**,
     suggested limit **₹47.7 L**, recommendation **Hold**. Across the network Sharma owes about
     ₹4.2 cr to four suppliers and has started paying the other three late.
   - Point out that the panel never says *who* the other suppliers are or *how much* they're owed.
   - *(Optional)* Click **Approve** anyway. The order is booked into A's ledger, the model re-scores
     Sharma (PD 8.8% → 8.9%), and the decision appears under *Your order decisions*. Approve a few
     more times and the PD keeps climbing. Use **Reset all decisions** to start over.
3. **Why?** Open **Dealer lookup** (Sharma loads by default). It shows the rating history
   (A, A, A, then BB) and the days-beyond-terms chart: "Your ledger" stays flat at 0 while
   "Whole network" climbs. The top factors are payments slowing, total network exposure and
   overdue share.
4. **Portfolio alerts.** Back on **Portfolio**, the *Downgrade alerts* table lists every dealer
   whose rating fell in the last 3 months. Sharma is near the top (A → BB, ₹1.02 cr owed to you).
5. *(Optional)* The **Model** page shows ROC-AUC, accuracy and the confusion matrix, and notes
   that the data is synthetic.

## How it works

**Data** (`generate_data.py`, seed 42): 6 suppliers, 300 dealers, about 48,000 invoices over 24
months (Nov 2024 to Oct 2026).
- Behaviour types: reliable 60%, slow payer 25%, over-leveraged 10%, defaulted 5%.
  Over-leveraged dealers buy more across all suppliers while their payments slow, sharply in the last 6 months.
  Dealers who default show stress in months 1-18, before the default.
- Each dealer has a different name spelling in each supplier's book, but always the same GSTIN.
- Story dealer: Sharma Electronics, `07ABCDE1234F1Z5`, buys from suppliers A, B, C and E, with about ₹1 cr
  outstanding at each (₹4.2 cr total).

**Features** (pooled across suppliers, as of a month-end): average and latest days beyond terms,
3-month change in days beyond terms, total outstanding (log), number of suppliers, 6-month
outstanding growth, share of invoices due in the last 6 months that were paid or are still open more than 7 days past
terms, and largest single-supplier share.

**Model** (`train.py`): features as of month 18 predict "defaulted in months 19-24".
Logistic regression and random forest are trained and compared on a 70/30 split, and the
results are saved to `data/model/metrics.json`. Logistic regression is kept because its
coefficients explain each rating. Each dealer's top 3 factors are its largest values of
coefficient × standardised feature.

**Ratings** (`config.py`): PD cut-offs map to AAA < 1.25% < AA < 2% < A < 3.5% < BBB < 6% <
BB < 12% < B < 25% < C < 50% ≤ D. Any invoice 90 or more days past due means D. The rating is
computed at months 15, 18, 21 and 24, so the app can show downgrades.

**Suggested limit**: that supplier's average monthly purchases × a multiplier
(AAA 3.0, AA 2.5, A 2.0, BBB 1.5, BB 1.0, B 0.5, C 0.25, D 0).

**Approve / Hold feed back into the model** (`rescore.py`): an approved order is booked as a new
unpaid invoice in that supplier's ledger, dated today and due after the dealer's usual credit terms.
The dealer's features are recomputed across the network and the same trained model scores it
again, so PD, rating, band and suggested limits update for **every** supplier selling to that
dealer. More credit means more exposure and faster outstanding growth, so PD only goes up. A
held order books nothing, so the model's view doesn't change; the decision is just logged.
Before you decide, the Creditly panel previews the rating the model would give if you approved.
Decisions are stored in `data/orders.csv` and replayed on startup.

**Order check**: Hold if rated C or D. Approve if the supplier's exposure after the order fits
under the suggested limit. Approve with a reduced limit if some headroom is left. Hold otherwise.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/suppliers` | for the login dropdown |
| GET | `/dealers?supplier_id=A` | that supplier's dealers: rating, trend, band, suggested limit |
| GET | `/dealers/{gstin}?supplier_id=A` | detail (404 if the dealer isn't in A's ledger) |
| POST | `/check-order` | `{supplier_id, gstin, order_value}` returns a recommendation and reason |
| POST | `/orders` | `{supplier_id, gstin, order_value, decision: "approve"\|"hold"}`; approve re-rates the dealer |
| GET | `/orders?supplier_id=A` | that supplier's own decisions, with rating before → after |
| POST | `/admin/reset-orders` | forget all decisions and restore the trained ratings |
| GET | `/alerts?supplier_id=A` | dealers downgraded in the last 3 months |
| GET | `/model/metrics` | ROC-AUC, accuracy, confusion matrices, coefficients |
| POST | `/admin/regenerate` | regenerate data and retrain (demo only) |

## Caveats

- The data is simulated, so the model scores (ROC-AUC ≈ 1.0) are much higher than they would be in real life.
- Sharma's numbers were tuned by hand so its rating lands at A three months ago and BB today.
  If you change the seed or the generator, the story dealer may land on a different rating.
