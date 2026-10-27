"""Load the ACLU LL144 audit corpus and score each audit with libra-check.

Standalone extract of the scoring used by the LL144 Audit Observatory and "Four-Fifths of What?"
(doi:10.5281/zenodo.23672859). The corpus is not redistributed here (CC BY-NC 4.0); see README.
Set LL144_CORPUS_DIR to use a clone somewhere other than ./data/aclu-auditing-the-audits.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pandas as pd

from libra_check.core import analyze

HERE = Path(__file__).resolve().parent
CORPUS_DIR = Path(os.environ.get("LL144_CORPUS_DIR", HERE / "data/aclu-auditing-the-audits"))
CSV = CORPUS_DIR / "audits/audits_full.csv"
CORPUS_SHA256 = "69fd290fb0be9523254027e3508722e70501f8501a9a3d92f47f7ffd31bbf85e"

THETA = 0.8
ALPHA = 0.10
PARAMS = {
    "thresholds": [THETA],
    "alpha": ALPHA,
    "comparator_rule": "max_rate_eligible",
    "selection_adjustment": "none",
    "small_category_exclusion": 0.02,
}
UNIT = ["audit_id", "protected_char_group", "selection_or_scoring_rate"]
T = f"{THETA:g}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, low_memory=False, dtype={"comparator_group": str})
    rs = pd.read_csv(CSV, low_memory=False, usecols=["result"], dtype={"result": str}).result
    df["missing_cat"] = (df.race_ethnicity == "Missing/Unknown") | (df.sex == "Missing/Unknown")
    df["n"] = pd.to_numeric(df.number_of_applications, errors="coerce")
    df["kraw"] = pd.to_numeric(df.n_selected_or_n_above_median, errors="coerce")
    dec = rs.str.split(".").str[1].str.len().fillna(0)
    df["dec"] = np.where(rs.notna(), np.maximum(dec, 2), np.nan)
    df["data_kind"] = np.where(df.data_type.fillna("Unknown").str.lower() == "historical", "historical", "test_or_unknown")
    return df


def category(r) -> dict:
    """k = round(k_raw); if k is missing, k = round(rate x n); rounding bounds when the count is reconstructed."""
    lab = f"{r.race_ethnicity}|{r.sex}|{r.name}"
    n = r.n
    k = r.kraw
    from_rate = pd.isna(k) and pd.notna(r.result) and n > 0
    frac = pd.notna(k) and abs(k - round(k)) > 1e-9
    if from_rate:
        k = r.result * n
    if pd.isna(k):
        return {"label": lab, "n": int(n)}
    kk = int(np.round(k))
    if kk < 0 or kk > n:
        return {"label": lab, "n": int(n)}
    c = {"label": lab, "n": int(n), "k": kk}
    if (from_rate or frac) and np.isfinite(r.dec):
        h = 0.5 * 10.0 ** (-r.dec)
        rate = kk / n
        lo = int(max(0, np.ceil((rate - h) * n - 1e-9)))
        hi = int(min(n, np.floor((rate + h) * n + 1e-9)))
        c["k_bounds"] = [min(lo, kk), max(hi, kk)]
    return c


def pretty(label: str, dimension: str) -> str:
    race, sex, _ = label.split("|")
    char = dimension.split("::")[0]
    if char == "sex":
        return sex
    if char == "race/ethnicity":
        return race
    return f"{race} · {sex}"


def first(s: pd.Series):
    v = s.dropna()
    return None if v.empty else v.iloc[0]


def clean(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def audit_meta(a: pd.DataFrame) -> dict:
    year = first(a.year_of_audit_result)
    return {
        "entity": clean(first(a.deploying_entity)),
        "auditor": clean(first(a.auditor)),
        "tool": clean(first(a.tool_id)),
        "vendor": clean(first(a.tool_vendor)),
        "tool_type": clean(first(a.type_of_tool)),
        "year": int(year) if year is not None and str(year).isdigit() else clean(year),
        "link": clean(first(a.link_to_result)),
        "data_type": clean(first(a.data_type)) or "Unknown",
    }


def score(df: pd.DataFrame, params: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    params = PARAMS if params is None else params
    audits, excluded = [], []
    report_hashes = {}
    kg = df[~df.missing_cat]
    for aid, a_all in df.groupby("audit_id", sort=False):
        meta = {"id": aid, **audit_meta(a_all)}
        a = kg[kg.audit_id == aid]
        units = []
        for key, g in a.groupby(UNIT[1:], dropna=False, sort=False):
            g = g[g.n > 0]
            if len(g) < 2:
                continue
            units.append({"dimension": "::".join(map(str, key)), "categories": [category(r) for _, r in g.iterrows()]})
        units = [u for u in units if sum("k" in c for c in u["categories"]) >= 2]
        if not units:
            excluded.append({**meta, "reason": "Fewer than two categories with usable counts in every unit"})
            continue
        rep = analyze(units, {"data_source": "historical"}, cli=params, compute_power=False)
        report_hashes[aid] = {"input_sha256": rep.get("input_sha256"), "parameters_sha256": rep.get("parameters_sha256")}
        ratios = []
        for u in rep["units"]:
            if u["comparator_category"] is None:
                continue
            comp = next(c for c in u["categories"] if c["label"] == u["comparator_category"])
            if comp.get("k") == 0:
                continue
            dim = u["dimension"]
            char, rate_kind = dim.split("::")
            for r in u["ratios"]:
                ratios.append({
                    "char": char,
                    "rate": rate_kind,
                    "group": pretty(r["category"], dim),
                    "comparator": pretty(u["comparator_category"], dim),
                    "is_comparator": bool(r.get("is_comparator")),
                    "n": clean(r.get("n")),
                    "k": clean(r.get("k")),
                    "point": clean(r.get("point")),
                    "lower": clean(r.get("lower")),
                    "upper": None if r.get("upper_infinite") else clean(r.get("upper")),
                    "state": r["state_by_threshold"][T],
                    "fw_state": r["adjusted_states"]["state_by_threshold"][T],
                })
        if not ratios:
            excluded.append({**meta, "reason": "No estimable impact ratio (comparator missing or zero selected)"})
            continue
        states = [x["state"] for x in ratios]
        fw = [x["fw_state"] for x in ratios]
        if any(s == "determinate_below" for s in fw):
            verdict = "below"
        elif all(s == "determinate_at_or_above" for s in fw):
            verdict = "clear"
        else:
            verdict = "unresolved"
        point_pass = all(x["point"] is not None and x["point"] >= THETA for x in ratios)
        audits.append({
            **meta,
            "n_ratios": len(ratios),
            "n_indeterminate": states.count("indeterminate"),
            "n_below": states.count("determinate_below"),
            "n_above": states.count("determinate_at_or_above"),
            "verdict": verdict,
            "point_pass": point_pass,
            "min_point": min((x["point"] for x in ratios if x["point"] is not None), default=None),
            "ratios": ratios,
        })
    return audits, excluded, report_hashes
