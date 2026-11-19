"""Train the Creditly default model and score every dealer.

Training set: features as of month 18 -> label "defaulted in months 19-24".
Scoring:      the chosen model is applied to features as of months 15/18/21/24
              to get today's rating and its history.

Outputs (data/):
  model/model.joblib, model/metrics.json
  scores.csv       current rating, PD, band, top factors per dealer
  history.csv      rating at months 15, 18, 21, 24
  pair_stats.csv   each supplier's own outstanding / purchases / limits per dealer
  dbt_monthly.csv  days-beyond-terms trend (per supplier and network)

Run:  python train.py
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import config as C
from features import FEATURES, compute_features, load_invoices, monthly_dbt, pair_stats


def evaluate(name, model, X_test, y_test):
    proba = model.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)
    return {
        "model": name,
        "roc_auc": round(float(roc_auc_score(y_test, proba)), 3),
        "accuracy": round(float(accuracy_score(y_test, pred)), 3),
        "confusion_matrix": confusion_matrix(y_test, pred, labels=[0, 1]).tolist(),
    }


def predict_pd(model, F: pd.DataFrame) -> np.ndarray:
    """Model PD, except a dealer already in default (an invoice 90+ days past due) is D."""
    p = model.predict_proba(F[FEATURES])[:, 1]
    return np.where(F.max_days_past_due >= C.DEFAULT_DAYS_PAST_DUE, C.IN_DEFAULT_PD, p)


def suggested_limits(avg_monthly: pd.Series, ratings: pd.Series) -> pd.Series:
    return (avg_monthly * ratings.map(C.LIMIT_MULTIPLIER)).round(-3)


def top_factors(model, X: pd.DataFrame, n: int = 3) -> list[list[dict]]:
    """Per row: the n features pushing risk up most (coefficient x standardised value)."""
    scaler = model.named_steps["standardscaler"]
    coef = model.named_steps["logisticregression"].coef_[0]
    contrib = scaler.transform(X[FEATURES]) * coef
    out = []
    for row in contrib:
        order = np.argsort(row)[::-1][:n]
        out.append([{"feature": FEATURES[i], "contribution": round(float(row[i]), 3)}
                    for i in order if row[i] > 0])
    return out


def train(data_dir: Path = C.DATA_DIR) -> dict:
    data_dir = Path(data_dir)
    model_dir = data_dir / "model"
    (data_dir / "orders.csv").unlink(missing_ok=True)   # decisions were made on the old data
    model_dir.mkdir(parents=True, exist_ok=True)

    inv = load_invoices(data_dir)
    truth = pd.read_csv(data_dir / "dealer_truth.csv").set_index("gstin")

    # ---- training data: months 1-18 features, default label for 19-24 -----
    X = compute_features(inv, C.TRAIN_MONTH)
    X = X[X.index.isin(truth.index)]
    y = truth.loc[X.index, "defaulted"]
    X_train, X_test, y_train, y_test = train_test_split(
        X[FEATURES], y, test_size=0.3, random_state=C.SEED, stratify=y)

    logreg = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000))
    logreg.fit(X_train, y_train)
    forest = RandomForestClassifier(n_estimators=300, min_samples_leaf=3, random_state=C.SEED)
    forest.fit(X_train, y_train)

    results = [evaluate("Logistic regression", logreg, X_test, y_test),
               evaluate("Random forest", forest, X_test, y_test)]
    # We keep logistic regression: comparable accuracy, and its coefficients
    # explain every rating ("top factors"), which matters for a credit decision.
    chosen = logreg
    coefs = dict(zip(FEATURES, chosen.named_steps["logisticregression"].coef_[0].round(3).tolist()))
    metrics = {
        "chosen_model": "Logistic regression",
        "why": "Similar accuracy to the random forest, and its coefficients explain each rating.",
        "train_rows": int(len(X_train)), "test_rows": int(len(X_test)),
        "default_rate": round(float(y.mean()), 3),
        "threshold": 0.5,
        "models": results,
        "coefficients": coefs,
        "rating_cutoffs": [{"rating": r, "pd_below": u} for r, u in C.PD_CUTOFFS],
        "synthetic": True,
    }
    joblib.dump({"model": chosen, "features": FEATURES}, model_dir / "model.joblib")
    (model_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # ---- score: rating history at months 15, 18, 21, 24 --------------------
    hist_rows, current = [], None
    for m in C.HISTORY_MONTHS:
        F = compute_features(inv, m)
        pd_m = predict_pd(chosen, F)
        for gstin, p in zip(F.index, pd_m):
            hist_rows.append({"gstin": gstin, "month": m, "label": C.month_label(m),
                              "pd": round(float(p), 4), "rating": C.pd_to_rating(p)})
        if m == C.N_MONTHS:
            current = F.assign(pd=pd_m)
    history = pd.DataFrame(hist_rows)

    scores = current.copy()
    scores["rating"] = scores.pd.map(C.pd_to_rating)
    scores["band"] = scores.total_outstanding.map(C.exposure_band)
    prev = history[history.month == C.N_MONTHS - 3].set_index("gstin").rating
    scores["rating_3m_ago"] = prev.reindex(scores.index)
    scores["top_factors"] = [json.dumps(t) for t in top_factors(chosen, scores)]
    scores.index.name = "gstin"
    scores.reset_index().to_csv(data_dir / "scores.csv", index=False)
    history.to_csv(data_dir / "history.csv", index=False)

    ps = pair_stats(inv)
    limits = pd.read_csv(data_dir / "credit_limits.csv")
    ps = ps.merge(limits, on=["supplier_id", "gstin"], how="left")
    ps = ps.merge(scores[["rating"]], left_on="gstin", right_index=True)
    ps["suggested_limit"] = suggested_limits(ps.own_avg_monthly_purchases, ps.rating)
    ps.drop(columns="rating").to_csv(data_dir / "pair_stats.csv", index=False)
    monthly_dbt(inv).to_csv(data_dir / "dbt_monthly.csv", index=False)

    # ---- console summary ---------------------------------------------------
    for r in results:
        print(f"{r['model']:<20} ROC-AUC {r['roc_auc']:.3f}  accuracy {r['accuracy']:.3f}  "
              f"confusion {r['confusion_matrix']}")
    print("Ratings today:", scores.rating.value_counts().reindex(C.RATINGS, fill_value=0).to_dict())
    story = history[history.gstin == "07ABCDE1234F1Z5"]
    print("Sharma Electronics:", " -> ".join(f"{r.label}: {r.rating} ({r.pd:.1%})" for r in story.itertuples()))
    return metrics


if __name__ == "__main__":
    train()
