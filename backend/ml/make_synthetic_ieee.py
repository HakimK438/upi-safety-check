"""Generate a SYNTHETIC payment-fraud dataset in the IEEE-CIS file layout.     Run from backend/:  python ml/make_synthetic_ieee.py

Why: the real IEEE-CIS data tops out near 89% precision / 88% recall with merchant-visible fields. The user asked for a
dataset where the fraud patterns are clear enough for one cut-off to reach 90%+ precision AND recall. Every number
measured on this data is SYNTHETIC and must be labelled so; the real-data results stay as a side check.

Realism: amounts, product codes, card networks, email domains and device strings are sampled from the REAL IEEE-CIS
rows; the time span (183 days), row count (~590k) and fraud rate (~3.5%) match the real data.

Simulated people:
  genuine customers  steady habits, but with honest look-alikes: new phones, trips far from home, night shopping,
                     several quick purchases, big one-off buys, families sharing one device, privacy email domains.
  fraud patterns     account_takeover    stolen login: new device, burst of payments, amount far above usual, often at night/far away
                     card_testing        brand-new account, throwaway email, tiny odd-cents test payments then a big one
                     mule_ring           one device cycling through many fresh accounts in a week
                     repeat_offender     an account caught before (chargeback > 30 days ago) commits fraud again
                     friendly_fraud      the real customer disputes a normal-looking payment (almost impossible to catch)

Writes data/train_transaction.csv, train_identity.csv (same columns the real loader reads) and
_patterns.csv (TransactionID -> pattern; for EDA only, never a model input).
"""

from __future__ import annotations

import argparse
import string
import time
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
REAL = BACKEND / "data" / "raw" / "ieee_cis"
OUT = BACKEND / "data"
DAY, HOUR = 86400, 3600
DAYS = 183
START = 86400  # the real TransactionDT starts at 86400

# Share of fraud ROWS per pattern, and tuning knobs (set so one cut-off lands near 90-92% precision and recall).
PATTERNS = {"account_takeover": 0.38, "card_testing": 0.24, "mule_ring": 0.24, "repeat_offender": 0.10, "friendly_fraud": 0.04}
FRAUD_RATE = 0.035
# local-time hour profile for genuine shoppers (quiet at night)
HOUR_W = np.array([1.2, 0.7, 0.5, 0.4, 0.4, 0.6, 1.5, 3, 4.5, 5.5, 6, 6.5, 7, 6.5, 6, 6, 6.2, 6.8, 7.5, 7.8, 7.2, 6, 4.2, 2.4])
HOUR_P = HOUR_W / HOUR_W.sum()
NIGHT_P = np.array([1.0 if h < 6 else 0.15 for h in range(24)])
NIGHT_P /= NIGHT_P.sum()
ANON = ["anonymous.com", "protonmail.com", "mail.com", "yandex.ru", "mail.ru", "guerrillamail.com"]


# ------------------------------------------------------------------ real-data profile
def real_profile() -> dict:
    """Empirical pools sampled from the real IEEE-CIS files, so synthetic values look like the real ones."""
    t = pd.read_csv(REAL / "train_transaction.csv", usecols=["TransactionID", "isFraud", "TransactionAmt", "ProductCD", "card1", "card2", "card3", "card4",
                                                             "card5", "card6", "addr1", "addr2", "P_emaildomain", "R_emaildomain"])
    i = pd.read_csv(REAL / "train_identity.csv", usecols=["TransactionID", "DeviceType", "DeviceInfo", "id_30", "id_31", "id_33"])
    g = t[t.isFraud == 0]
    prod = g.ProductCD.value_counts(normalize=True)
    devs = i.dropna(subset=["DeviceType", "DeviceInfo", "id_30", "id_31"]).merge(t[["TransactionID", "ProductCD"]], on="TransactionID")
    cards = g[["card1", "card2", "card3", "card4", "card5", "card6"]].dropna(subset=["card4", "card6"])
    return {
        "products": prod.index.to_numpy(), "product_p": prod.to_numpy(),
        "amount": {p: g.loc[g.ProductCD == p, "TransactionAmt"].to_numpy() for p in prod.index},
        "cards": cards.to_numpy(object), "addr1": g.addr1.dropna().to_numpy(), "addr2": g.addr2.dropna().to_numpy(),
        "email": g.P_emaildomain.fillna("").to_numpy(), "email_f": t.loc[t.isFraud == 1, "P_emaildomain"].fillna("").to_numpy(),
        "res": i.id_33.dropna().to_numpy(),
        "devices": devs[["DeviceType", "DeviceInfo", "id_30", "id_31"]].to_numpy(object),
        "id_rate": t.assign(has=t.TransactionID.isin(i.TransactionID)).groupby("ProductCD")["has"].mean().to_dict(),
    }


# ------------------------------------------------------------------ simulation
class Sim:
    def __init__(self, prof: dict, seed: int) -> None:
        self.p = prof
        self.rng = np.random.default_rng(seed)
        self.rows: list[tuple] = []
        self.devices: list[tuple] = []  # (DeviceType, DeviceInfo, id_30, id_31, id_33)
        self.used_keys: set[tuple] = set()

    # --- building blocks
    def new_device(self) -> int:
        """A physical device: model / OS / browser from a real row, plus its own build tag and screen size."""
        r = self.rng
        dt, info, os_, br = self.p["devices"][r.integers(len(self.p["devices"]))]
        if dt == "mobile" and "Build/" in str(info):
            info = str(info).split(" Build/")[0] + " Build/" + "".join(r.choice(list(string.ascii_uppercase + string.digits), 6))
        self.devices.append((dt, info, os_, br, self.p["res"][r.integers(len(self.p["res"]))]))
        return len(self.devices) - 1

    def new_person(self, start_day: float, product: str | None = None, email: str | None = None) -> dict:
        r = self.rng
        while True:
            card = self.p["cards"][r.integers(len(self.p["cards"]))]
            addr1 = self.p["addr1"][r.integers(len(self.p["addr1"]))] if r.random() > 0.11 else np.nan
            key = (int(card[0]), addr1, int(np.floor(start_day)))
            if key not in self.used_keys:
                self.used_keys.add(key)
                break
        prod = product or r.choice(self.p["products"], p=self.p["product_p"])
        pool = self.p["amount"][prod]
        return {"card": card, "addr1": addr1, "addr2": 87.0 if not np.isnan(addr1) else np.nan, "start": np.floor(start_day), "product": prod,
                "usual": float(pool[r.integers(len(pool))]), "email": email if email is not None else self.p["email"][r.integers(len(self.p["email"]))],
                "has_id": r.random() < min(0.95, self.p["id_rate"].get(prod, 0.2) * 1.6), "home_dist": float(r.lognormal(1.6, 0.9)),
                "dist_known": prod == "W" and r.random() < 0.85, "devices": []}

    def emit(self, who: dict, t: float, amt: float, fraud: int, pattern: str, dev: int | None, dist: float | None = None, email: str | None = None) -> None:
        day = np.floor((t - START) / DAY)
        d1 = max(0.0, day - who["start"])
        c = who["card"]
        self.rows.append((t, round(max(0.25, amt), 3), who["product"], c[0], c[1], c[2], c[3], c[4], c[5], who["addr1"], who["addr2"],
                          (dist if dist is not None else who["home_dist"]) if who["dist_known"] else np.nan, email if email is not None else who["email"],
                          d1, -1 if dev is None else dev, fraud, pattern))

    def amount_like(self, base: float, spread: float = 0.35) -> float:
        a = base * self.rng.lognormal(0, spread)
        return round(a) if self.rng.random() < 0.45 else round(a, 2)

    def at_hour(self, day: float, hp: np.ndarray = HOUR_P) -> float:
        r = self.rng
        return START + float(np.floor(day)) * DAY + r.choice(24, p=hp) * HOUR + r.integers(0, HOUR)

    # --- genuine customers
    def genuine(self, n_customers: int) -> list[dict]:
        r = self.rng
        people = []
        family_pool: list[int] = []
        for _ in range(n_customers):
            first = r.uniform(0, DAYS - 1)
            age = r.uniform(0, 12) if r.random() < 0.12 else r.uniform(12, 640)
            who = self.new_person(first - age)
            if who["has_id"]:
                if r.random() < 0.035 and family_pool:  # family / shop counter sharing one device
                    who["devices"].append(family_pool[r.integers(len(family_pool))])
                else:
                    who["devices"].append(self.new_device())
                    if r.random() < 0.02:
                        family_pool.append(who["devices"][-1])
            rate = float(np.clip(r.lognormal(np.log(0.045), 0.9), 0.005, 1.5))
            n = max(1, r.poisson(rate * (DAYS - first)))
            days = np.sort(r.uniform(first, DAYS, n))
            for d in days:
                t = self.at_hour(d)
                dev = who["devices"][-1] if who["devices"] else None
                if dev is not None and r.random() < 0.035:  # new phone / laptop, used from now on
                    who["devices"].append(self.new_device())
                    dev = who["devices"][-1]
                amt = self.amount_like(who["usual"])
                if r.random() < 0.03:
                    amt *= r.uniform(3, 6)  # honest big one-off purchase
                dist = who["home_dist"] * r.lognormal(0, 0.5)
                if r.random() < 0.04:
                    dist = r.uniform(100, 1500)  # travelling
                self.emit(who, t, amt, 0, "genuine", dev, dist)
                if r.random() < 0.035:  # a few quick purchases in a row
                    for k in range(r.integers(1, 3)):
                        self.emit(who, t + r.uniform(2, 50) * 60 * (k + 1), self.amount_like(who["usual"]), 0, "genuine", dev, dist)
            who["last_day"] = days[-1]
            people.append(who)
        return people

    # --- fraud patterns (each returns rows emitted)
    def account_takeover(self, people: list[dict]) -> int:
        r = self.rng
        who = people[r.integers(len(people))]
        if who["last_day"] < 5:
            return 0
        d = r.uniform(max(3.0, who["last_day"] - 60), min(DAYS - 0.1, who["last_day"] + 20))
        t = self.at_hour(d, NIGHT_P if r.random() < 0.55 else HOUR_P)
        if who["has_id"] or r.random() < 0.5:  # a stolen login on a customer with no device record only sometimes reveals one
            dev = self.new_device() if r.random() < 0.9 else (who["devices"][-1] if who["devices"] else None)
        else:
            dev = None
        far = r.uniform(150, 2500) if r.random() < 0.6 else who["home_dist"]
        n = int(r.integers(2, 6)) if r.random() < 0.85 else 1
        for k in range(n):
            self.emit(who, t + k * r.uniform(1, 12) * 60, self.amount_like(who["usual"] * r.uniform(3, 12), 0.2), 1, "account_takeover", dev, far,
                      email=r.choice(ANON) if r.random() < 0.3 else None)
        return n

    def card_testing(self) -> int:
        r = self.rng
        d = r.uniform(0, DAYS - 0.1)
        who = self.new_person(d - r.uniform(0, 3), product="C" if r.random() < 0.6 else None,
                              email=r.choice(ANON) if r.random() < 0.55 else ("" if r.random() < 0.4 else None))
        who["has_id"] = r.random() < 0.85
        dev = self.new_device() if who["has_id"] else None
        t = self.at_hour(d, NIGHT_P if r.random() < 0.4 else HOUR_P)
        n_test = int(r.integers(1, 4))
        for k in range(n_test):  # tiny odd-cents probes
            self.emit(who, t + k * r.uniform(0.5, 6) * 60, round(r.uniform(0.5, 6), 3), 1, "card_testing", dev, r.uniform(50, 3000))
        for k in range(int(r.integers(1, 3))):
            self.emit(who, t + (n_test + k) * r.uniform(2, 15) * 60, self.amount_like(r.uniform(150, 900), 0.2), 1, "card_testing", dev, r.uniform(50, 3000))
        who["last_day"] = d
        self.offenders.append(who)
        return n_test + 2

    def mule_ring(self) -> int:
        r = self.rng
        d0 = r.uniform(0, DAYS - 7)
        dev = self.new_device()
        n_acc = int(r.integers(5, 14))
        rows = 0
        for _ in range(n_acc):
            d = d0 + r.uniform(0, 6)
            who = self.new_person(d - r.uniform(0, 25), product="C" if r.random() < 0.5 else "S" if r.random() < 0.3 else None)
            who["has_id"] = True
            t = self.at_hour(d)
            for k in range(int(r.integers(1, 3))):
                self.emit(who, t + k * r.uniform(5, 90) * 60, self.amount_like(r.uniform(80, 600), 0.3), 1, "mule_ring", dev)
                rows += 1
            who["last_day"] = d
            self.offenders.append(who)
        return rows

    def repeat_offender(self) -> int:
        r = self.rng
        old = [w for w in self.offenders if w["last_day"] < DAYS - 40]
        if not old:
            return 0
        who = old[r.integers(len(old))]
        d = r.uniform(who["last_day"] + 32, DAYS - 0.1)
        dev = self.new_device() if who["has_id"] and r.random() < 0.5 else None
        n = int(r.integers(1, 3))
        for k in range(n):
            self.emit(who, self.at_hour(d) + k * 600, self.amount_like(r.uniform(60, 500), 0.3), 1, "repeat_offender", dev)
        return n

    def friendly_fraud(self, people: list[dict]) -> int:
        r = self.rng
        who = people[r.integers(len(people))]
        d = r.uniform(0, DAYS - 0.1)
        self.emit(who, self.at_hour(d), self.amount_like(who["usual"] * r.uniform(1, 2.5)), 1, "friendly_fraud", who["devices"][-1] if who["devices"] else None)
        return 1

    def run(self, n_customers: int) -> pd.DataFrame:
        t0 = time.time()
        self.offenders: list[dict] = []
        people = self.genuine(n_customers)
        n_gen = len(self.rows)
        target = int(n_gen * FRAUD_RATE / (1 - FRAUD_RATE))
        made = {k: 0 for k in PATTERNS}
        # repeat offenders need earlier fraudsters, so they come last
        for pat in ["card_testing", "mule_ring", "account_takeover", "friendly_fraud", "repeat_offender"]:
            goal = int(target * PATTERNS[pat])
            tries = 0
            while made[pat] < goal and tries < goal * 20:
                tries += 1
                made[pat] += {"account_takeover": lambda: self.account_takeover(people), "card_testing": self.card_testing, "mule_ring": self.mule_ring,
                              "repeat_offender": self.repeat_offender, "friendly_fraud": lambda: self.friendly_fraud(people)}[pat]()
        print(f"simulated {n_gen:,} genuine + {sum(made.values()):,} fraud rows in {time.time() - t0:.0f}s: {made}", flush=True)
        cols = ["TransactionDT", "TransactionAmt", "ProductCD", "card1", "card2", "card3", "card4", "card5", "card6", "addr1", "addr2", "dist1",
                "P_emaildomain", "D1", "_dev", "isFraud", "_pattern"]
        df = pd.DataFrame(self.rows, columns=cols)
        df = df[(df.TransactionDT >= START) & (df.TransactionDT < START + DAYS * DAY)].sort_values("TransactionDT", kind="stable").reset_index(drop=True)
        df.insert(0, "TransactionID", np.arange(2987000, 2987000 + len(df)))
        df["TransactionDT"] = df["TransactionDT"].astype(np.int64)
        df["P_emaildomain"] = df["P_emaildomain"].replace("", np.nan)
        return df


# ------------------------------------------------------------------ bank-side columns (kept for layout; not used by the merchant model)
def bank_side(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n, y = len(df), df["isFraud"].to_numpy()
    out = pd.DataFrame(index=df.index)
    for c in (1, 2, 5, 6, 9, 11, 13, 14):
        out[f"C{c}"] = rng.poisson(1.2 + 2.5 * y).astype(float)
    d1 = df["D1"].to_numpy(float)
    out["D2"] = np.where(rng.random(n) < 0.45, np.nan, d1)
    for c in ("D3", "D4", "D10", "D11", "D15"):
        out[c] = np.where(rng.random(n) < 0.3, np.nan, np.round(np.maximum(0, d1 * rng.uniform(0.2, 1.1, n))))
    for m in range(1, 10):
        out[f"M{m}"] = np.where(rng.random(n) < 0.4, None, np.where(rng.random(n) < 0.75 - 0.2 * y, "T", "F"))
    return out


def identity(df: pd.DataFrame, devices: list[tuple], rng: np.random.Generator) -> pd.DataFrame:
    has = df["_dev"].to_numpy() >= 0
    sub = df.loc[has, ["TransactionID", "_dev", "isFraud"]]
    dv = np.array(devices, dtype=object)[sub["_dev"].to_numpy(int)]
    n, y = len(sub), sub["isFraud"].to_numpy()
    return pd.DataFrame({
        "TransactionID": sub["TransactionID"].to_numpy(),
        "id_01": np.where(rng.random(n) < 0.6, 0.0, -5.0 * rng.integers(1, 20, n)), "id_02": np.round(rng.lognormal(11.5, 0.9, n)),
        "id_05": np.where(rng.random(n) < 0.5, 0.0, rng.integers(-10, 30, n)).astype(float), "id_06": np.where(rng.random(n) < 0.5, 0.0, -rng.integers(1, 60, n)).astype(float),
        "id_13": rng.choice([49.0, 52.0, 64.0], n), "id_17": np.where(rng.random(n) < 0.8 - 0.2 * y, 166.0, 225.0), "id_19": rng.integers(100, 671, n).astype(float),
        "id_20": rng.integers(100, 661, n).astype(float), "id_30": dv[:, 2], "id_31": dv[:, 3], "id_33": dv[:, 4], "DeviceType": dv[:, 0], "DeviceInfo": dv[:, 1],
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=86_000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    t0 = time.time()
    prof = real_profile()
    print(f"real profile loaded in {time.time() - t0:.0f}s", flush=True)
    sim = Sim(prof, a.seed)
    df = sim.run(a.customers)
    rng = np.random.default_rng(a.seed + 1)
    ident = identity(df, sim.devices, rng)
    trans = pd.concat([df.drop(columns=["_dev", "_pattern"]), bank_side(df, rng)], axis=1)
    OUT.mkdir(parents=True, exist_ok=True)
    trans.to_csv(OUT / "train_transaction.csv", index=False)
    ident.to_csv(OUT / "train_identity.csv", index=False)
    df[["TransactionID", "_pattern"]].rename(columns={"_pattern": "pattern"}).to_csv(OUT / "_patterns.csv", index=False)
    for f in ("_features.pkl", "_walk_forward.json"):  # features changed -> old caches are stale
        (OUT / f).unlink(missing_ok=True)
    print(f"wrote {len(trans):,} rows ({trans.isFraud.mean():.2%} fraud), {len(ident):,} identity rows to {OUT} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
