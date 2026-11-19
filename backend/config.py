"""Shared settings for Creditly: paths, timeline, suppliers, rating rules.

Everything a reader might want to tweak (rating cut-offs, credit-limit
multipliers, exposure bands) lives in this one file.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = DATA_DIR / "model"

SEED = 42

# ---- Timeline -------------------------------------------------------------
# 24 months of history. Month 1 = Nov 2024, month 24 = Oct 2026.
START = pd.Timestamp("2024-11-01")
N_MONTHS = 24
TRAIN_MONTH = 18          # features from months 1-18 ...
# ... predict a default in months 19-24 (the label)
HISTORY_MONTHS = [15, 18, 21, 24]


def month_start(k: int) -> pd.Timestamp:
    return START + pd.DateOffset(months=k - 1)


def month_end(k: int) -> pd.Timestamp:
    return month_start(k) + pd.offsets.MonthEnd(0)


def month_label(k: int) -> str:
    return month_start(k).strftime("%b %Y")


AS_OF = month_end(N_MONTHS)

# ---- Suppliers ------------------------------------------------------------
SUPPLIERS = [
    ("A", "Supplier A - Laptops"),
    ("B", "Supplier B - Printers"),
    ("C", "Supplier C - Networking"),
    ("D", "Supplier D - Mobiles & Tablets"),
    ("E", "Supplier E - Storage & Memory"),
    ("F", "Supplier F - Monitors & Peripherals"),
]

# ---- Rating rules (the single place for cut-offs) -------------------------
# A dealer gets the first rating whose upper PD bound is above its PD.
RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B", "C", "D"]
PD_CUTOFFS = [
    ("AAA", 0.0125),
    ("AA", 0.020),
    ("A", 0.035),
    ("BBB", 0.060),
    ("BB", 0.120),
    ("B", 0.250),
    ("C", 0.500),
    ("D", 1.001),
]

# Suggested credit limit = average monthly purchases x multiplier
LIMIT_MULTIPLIER = {
    "AAA": 3.0, "AA": 2.5, "A": 2.0, "BBB": 1.5,
    "BB": 1.0, "B": 0.5, "C": 0.25, "D": 0.0,
}

LAKH = 100_000
CRORE = 10_000_000

# Exposure bands on the dealer's total outstanding across the network
EXPOSURE_BANDS = [
    (50 * LAKH, "< ₹50 L"),
    (1 * CRORE, "₹50 L-1 cr"),
    (3 * CRORE, "₹1-3 cr"),
    (5 * CRORE, "₹3-5 cr"),
    (10 * CRORE, "₹5-10 cr"),
    (float("inf"), "> ₹10 cr"),
]


# Any invoice this many days past due and unpaid = the dealer is in default (D)
DEFAULT_DAYS_PAST_DUE = 90
IN_DEFAULT_PD = 0.99


def pd_to_rating(pd_value: float) -> str:
    for rating, upper in PD_CUTOFFS:
        if pd_value < upper:
            return rating
    return "D"


def exposure_band(amount: float) -> str:
    for upper, label in EXPOSURE_BANDS:
        if amount < upper:
            return label
    return EXPOSURE_BANDS[-1][1]


def rating_index(rating: str) -> int:
    """0 = best (AAA), 7 = worst (D)."""
    return RATINGS.index(rating)
