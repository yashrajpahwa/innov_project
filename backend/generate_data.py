"""Generate synthetic supplier ledgers for the Creditly demo.

Output (all under data/):
  suppliers.csv               supplier id + name
  ledgers/ledger_<ID>.csv     one invoice ledger per supplier (what each supplier "shares")
  credit_limits.csv           each supplier's own credit limit per dealer (their ERP setting)
  dealer_truth.csv            hidden truth: behaviour type + default label (used only for training)

Run:  python generate_data.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

import config as C

N_DEALERS = 300

BEHAVIOUR_MIX = {"reliable": 0.60, "slow": 0.25, "overleveraged": 0.10, "defaulted": 0.05}
# Chance that a dealer of each type defaults in months 19-24
DEFAULT_PROB = {"reliable": 0.01, "slow": 0.05, "overleveraged": 0.35, "defaulted": 1.0}

CITIES = {
    "Delhi": ("07", ["Karol Bagh", "Nehru Place", "Lajpat Nagar", "Chandni Chowk"]),
    "Mumbai": ("27", ["Lamington Road", "Andheri", "Dadar"]),
    "Pune": ("27", ["Budhwar Peth", "Shivajinagar"]),
    "Bengaluru": ("29", ["SP Road", "Jayanagar", "Koramangala"]),
    "Chennai": ("33", ["Ritchie Street", "T Nagar"]),
    "Hyderabad": ("36", ["CTC Secunderabad", "Ameerpet"]),
    "Ahmedabad": ("24", ["CG Road", "Navrangpura"]),
    "Kolkata": ("19", ["Esplanade", "Salt Lake"]),
    "Jaipur": ("08", ["MI Road", "Raja Park"]),
    "Lucknow": ("09", ["Naza Market", "Hazratganj"]),
}

FIRST = ["Sharma", "Gupta", "Agarwal", "Jain", "Mehta", "Patel", "Shah", "Reddy", "Iyer",
         "Nair", "Singh", "Verma", "Bansal", "Goyal", "Malhotra", "Kapoor", "Chopra", "Arora",
         "Khanna", "Rao", "Das", "Bose", "Ghosh", "Mittal", "Joshi", "Desai", "Kulkarni",
         "Pillai", "Menon", "Saxena", "Sethi", "Batra", "Shree Ganesh", "Sai", "Om", "Royal",
         "Star", "Galaxy", "New India", "Balaji", "Krishna", "Laxmi", "Vision", "Matrix",
         "Pioneer", "Supreme", "Apex", "Quantum", "Bharat", "National"]
TRADE = ["Electronics", "Computers", "Infotech", "Systems", "Technologies", "IT Solutions",
         "Digital", "Peripherals", "Infosystems", "Computer Services"]
SUFFIX = ["Pvt Ltd", "Private Limited", "LLP", "& Co", "Enterprises", "Traders", "Distributors"]
ABBREV = {"Electronics": "Elect.", "Computers": "Comp.", "Technologies": "Tech.",
          "Infotech": "Infotek", "Private Limited": "Pvt. Ltd.", "Pvt Ltd": "P. Ltd.",
          "Systems": "Sys.", "Distributors": "Distr.", "Enterprises": "Ent.",
          "Computer Services": "Comp. Services", "Peripherals": "Periph."}

STORY_GSTIN = "07ABCDE1234F1Z5"
STORY_NAME = "Sharma Electronics Pvt Ltd"
STORY_SUPPLIERS = ["A", "B", "C", "E"]
# Target outstanding (₹) at each story supplier as of month 24 -> total ₹4.2 cr
STORY_OUTSTANDING = {"A": 1.02e7, "B": 1.06e7, "C": 1.04e7, "E": 1.08e7}

GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ---------------------------------------------------------------------------
# Names and GSTINs
# ---------------------------------------------------------------------------
def gstin_checksum(first14: str) -> str:
    """Standard GSTIN check character (mod-36 weighted sum)."""
    total = 0
    for i, ch in enumerate(first14):
        val = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += val // 36 + val % 36
    return GSTIN_CHARS[(36 - total % 36) % 36]


def make_gstin(rng, state: str) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    pan = ("".join(rng.choice(list(letters), 3)) + rng.choice(list("CFP")) +
           rng.choice(list(letters)) + f"{rng.integers(0, 10000):04d}" + rng.choice(list(letters)))
    first14 = state + pan + "1Z"
    return first14 + gstin_checksum(first14)


def name_variant(rng, name: str, area: str) -> str:
    """How one supplier's clerk might have typed the dealer name."""
    style = rng.integers(0, 5)
    if style == 0:
        return name.upper()
    if style == 1:
        out = name
        for full, short in ABBREV.items():
            out = out.replace(full, short)
        return f"{out} ({area})"
    if style == 2:
        base = name
        for s in SUFFIX:
            base = base.replace(" " + s, "")
        return f"M/s {base}"
    if style == 3:
        return f"{name.title()}, {area}"
    return name


# ---------------------------------------------------------------------------
# Behaviour: days-beyond-terms and purchase growth by month
# ---------------------------------------------------------------------------
def dbt_for(rng, behaviour: str, m: int) -> float:
    if behaviour == "reliable":
        return rng.exponential(3) - 2
    if behaviour == "slow":
        return 10 + rng.exponential(12)
    if behaviour == "overleveraged":
        stress = max(0, m - 12) * 2.5           # payments slow from month 13
        return rng.exponential(4) + stress + rng.normal(0, 3)
    if behaviour == "defaulted":
        stress = max(0, m - 8) * 3.5            # visibly deteriorating well before month 19
        return rng.exponential(5) + stress + rng.normal(0, 4)
    raise ValueError(behaviour)


def growth_for(behaviour: str, m: int, trend: float) -> float:
    if behaviour == "overleveraged":
        g = 1.03 ** max(0, min(m, 18) - 10)     # buying more ...
        return g * 1.08 ** max(0, m - 18)       # ... and much more in the last 6 months
    if behaviour == "defaulted":
        return 1.02 ** max(0, m - 10)
    return (1 + trend) ** m


def story_dbt(rng, supplier: str, m: int) -> float:
    """Sharma Electronics: pays Supplier A on time, slips everywhere else lately."""
    if supplier == "A" or m <= 20:
        return rng.exponential(1.5) - 3          # pays a little early
    return 3 + (m - 20) * 4 + rng.normal(0, 2)   # then clearly slowing


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
def make_dealers(rng) -> pd.DataFrame:
    types = rng.choice(list(BEHAVIOUR_MIX), size=N_DEALERS - 1, p=list(BEHAVIOUR_MIX.values()))
    rows, used_gstins, used_names = [], {STORY_GSTIN}, {STORY_NAME}
    for behaviour in types:
        city = rng.choice(list(CITIES))
        state, areas = CITIES[city]
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(TRADE)} {rng.choice(SUFFIX)}"
            if name not in used_names:
                break
        while True:
            gstin = make_gstin(rng, state)
            if gstin not in used_gstins:
                break
        used_gstins.add(gstin)
        used_names.add(name)
        n_sup = rng.choice([1, 2, 3, 4, 5], p=[0.20, 0.30, 0.25, 0.15, 0.10])
        suppliers = sorted(rng.choice([s for s, _ in C.SUPPLIERS], size=n_sup, replace=False))
        defaulted = rng.random() < DEFAULT_PROB[behaviour]
        rows.append(dict(
            gstin=gstin, name=name, city=city, area=rng.choice(areas), behaviour=behaviour,
            suppliers=",".join(suppliers),
            base_monthly=float(rng.lognormal(np.log(6 * C.LAKH), 1.0)),
            trend=float(rng.normal(0.004, 0.006)),
            defaulted=int(defaulted),
            default_month=int(rng.integers(19, 25)) if defaulted else 0,
        ))
    rows.append(dict(
        gstin=STORY_GSTIN, name=STORY_NAME, city="Delhi", area="Karol Bagh", behaviour="story",
        suppliers=",".join(STORY_SUPPLIERS), base_monthly=40 * C.LAKH, trend=0.0,
        defaulted=0, default_month=0,
    ))
    return pd.DataFrame(rows)


def make_invoices(rng, dealers: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for d in dealers.itertuples():
        for sup in d.suppliers.split(","):
            terms = int(rng.choice([30, 45, 60])) if d.behaviour != "story" else (60 if sup == "A" else 45)
            spelling = name_variant(rng, d.name, d.area)
            if d.gstin == STORY_GSTIN:
                spelling = {"A": "SHARMA ELECTRONICS PVT LTD", "B": "Sharma Elect. (Karol Bagh)",
                            "C": "M/s Sharma Electronics", "E": "Sharma Electronics Pvt. Ltd."}[sup]
            pair_scale = rng.uniform(0.5, 1.5) if d.behaviour != "story" else 1.0
            last_month = d.default_month if d.defaulted else C.N_MONTHS
            for m in range(1, last_month + 1):
                for _ in range(int(rng.poisson(1.5)) + 1):
                    if d.behaviour == "story":
                        growth = 1.0 if m <= 21 else 1.08 ** (m - 21)
                    else:
                        growth = growth_for(d.behaviour, m, d.trend)
                    amount = d.base_monthly * pair_scale * growth / 2.5 * rng.lognormal(0, 0.25)
                    inv_date = C.month_start(m) + pd.Timedelta(days=int(rng.integers(0, 28)))
                    due = inv_date + pd.Timedelta(days=terms)

                    if d.behaviour == "story":
                        dbt = story_dbt(rng, sup, m)
                    else:
                        dbt = dbt_for(rng, d.behaviour, m)
                        # Dealers who will default: things get bad shortly before
                        if d.defaulted and m >= d.default_month - 4:
                            dbt += 40
                    paid = due + pd.Timedelta(days=int(round(max(-5.0, dbt))))
                    if d.defaulted and m >= d.default_month - 2:
                        paid = pd.NaT                      # never paid
                    if pd.notna(paid) and paid > C.AS_OF:
                        paid = pd.NaT                      # not yet paid as of today
                    rows.append(dict(supplier_id=sup, gstin=d.gstin, dealer_name=spelling,
                                     city=d.city, invoice_date=inv_date,
                                     amount=round(amount, -2), credit_terms_days=terms,
                                     paid_date=paid))
    inv = pd.DataFrame(rows)
    return _scale_story(inv)


def _scale_story(inv: pd.DataFrame) -> pd.DataFrame:
    """Scale Sharma's invoice amounts so each supplier sees ~₹1 cr outstanding."""
    for sup, target in STORY_OUTSTANDING.items():
        mask = (inv.gstin == STORY_GSTIN) & (inv.supplier_id == sup)
        current = inv.loc[mask & inv.paid_date.isna(), "amount"].sum()
        inv.loc[mask, "amount"] = (inv.loc[mask, "amount"] * target / current).round(-2)
    return inv


def make_credit_limits(rng, inv: pd.DataFrame) -> pd.DataFrame:
    """Each supplier's own ERP credit limit: ~1.2-1.6x the peak monthly-ish exposure."""
    recent = inv[inv.invoice_date >= C.month_start(C.N_MONTHS - 5)]
    monthly = recent.groupby(["supplier_id", "gstin"]).amount.sum() / 6
    out = monthly.reset_index(name="avg_monthly")
    out["credit_limit"] = (out.avg_monthly * 2.5 * rng.uniform(1.2, 1.6, len(out)) / C.LAKH).round() * C.LAKH
    out.loc[(out.gstin == STORY_GSTIN) & (out.supplier_id == "A"), "credit_limit"] = 1.5 * C.CRORE
    return out[["supplier_id", "gstin", "credit_limit"]]


def generate(out_dir: Path = C.DATA_DIR, seed: int = C.SEED) -> None:
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    (out_dir / "ledgers").mkdir(parents=True, exist_ok=True)

    dealers = make_dealers(rng)
    inv = make_invoices(rng, dealers)
    inv = inv.sort_values(["supplier_id", "invoice_date", "gstin"]).reset_index(drop=True)
    inv["invoice_no"] = inv.supplier_id + "-" + (inv.groupby("supplier_id").cumcount() + 1).astype(str).str.zfill(6)

    pd.DataFrame(C.SUPPLIERS, columns=["supplier_id", "name"]).to_csv(out_dir / "suppliers.csv", index=False)
    cols = ["supplier_id", "invoice_no", "dealer_name", "gstin", "city", "invoice_date",
            "amount", "credit_terms_days", "paid_date"]
    for sup, ledger in inv.groupby("supplier_id"):
        ledger[cols].to_csv(out_dir / "ledgers" / f"ledger_{sup}.csv", index=False, date_format="%Y-%m-%d")
    make_credit_limits(rng, inv).to_csv(out_dir / "credit_limits.csv", index=False)
    dealers[["gstin", "name", "city", "behaviour", "defaulted", "default_month"]].to_csv(
        out_dir / "dealer_truth.csv", index=False)

    print(f"Generated {len(dealers)} dealers, {len(inv):,} invoices "
          f"across {inv.supplier_id.nunique()} suppliers -> {out_dir}")
    print("Behaviour mix:", {str(k): int(v) for k, v in dealers.behaviour.value_counts().items()})
    print("Defaults in months 19-24:", int(dealers.defaulted.sum()))


if __name__ == "__main__":
    generate()
