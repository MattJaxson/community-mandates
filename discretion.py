"""Who decides? Measure how much of a published LL144 outcome is set by a choice the rule leaves to the auditor.

The DCWP rule lets an auditor "exclude a category that represents less than 2% of the data" from the
impact-ratio calculations (6 RCNY 5-301(d)). Both options are lawful. This script:
  1. judges every audit under each permitted option (four-fifths point reading, as audits are read);
  2. counts audits whose outcome depends only on that option, and in which direction;
  3. checks which version each such audit actually published (its own reported impact ratios);
  4. repeats under interval readings as a robustness check.

Run: python discretion.py
Out: out/discretion.json and out/FINDING_NUMBERS.md (git-ignored: they list employers and audit firms from the CC BY-NC corpus)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import engine

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
EX = HERE / "examples"


def published_point_outcome(df: pd.DataFrame, thr: float = 0.8) -> dict:
    """Outcome a reader gets from the ratios the audit itself published (known categories only)."""
    d = df[~df.missing_cat].copy()
    d["ir_pub"] = pd.to_numeric(d.impact_ratio, errors="coerce")
    out = {}
    for aid, a in d.groupby("audit_id"):
        v = a.ir_pub.dropna()
        out[aid] = None if v.empty else ("fails" if (v < thr).any() else "meets")
    return out


def _units(df: pd.DataFrame, aid: str) -> list[list[dict]]:
    """Known categories per analysis unit of one audit, as build.score passes them to libra-check."""
    a = df[(df.audit_id == aid) & ~df.missing_cat]
    units = []
    for _, g in a.groupby(engine.build.UNIT[1:], dropna=False, sort=False):
        g = g[g.n > 0]
        cats = [engine.build.category(r) for _, r in g.iterrows()]
        if len(g) >= 2 and sum("k" in c for c in cats) >= 2:
            units.append(cats)
    return units


def _envelope_unit(cats: list[dict], exclude: bool, thr: float) -> tuple[bool, bool]:
    """Point reading over every count consistent with the published rounded rates.
    Returns (can_fail, can_meet) for one unit under one exclusion option."""
    base = sum(c["n"] for c in cats)
    pool = [c for c in cats if "k" in c and not (exclude and c["n"] < 0.02 * base)]
    if len(pool) < 2:
        return False, True
    lo = [c.get("k_bounds", [c["k"], c["k"]])[0] / c["n"] for c in pool]
    hi = [c.get("k_bounds", [c["k"], c["k"]])[1] / c["n"] for c in pool]
    # some ratio below thr: one category at its lowest rate, another at its highest
    can_fail = any(lo[i] < thr * max(hi[j] for j in range(len(pool)) if j != i) for i in range(len(pool)))
    # every ratio at or above thr: all rates fit in [a, a / thr] for some a
    can_meet = thr * max(lo) <= min(hi)
    return can_fail, can_meet


def rounding_envelope_point(df: pd.DataFrame, ids: list[str], thr: float = 0.8) -> dict:
    """For audits the option decides, does that survive every count consistent with the rounded rates?"""
    still, lost = [], []
    for i in ids:
        units = _units(df, i)
        ex = [_envelope_unit(u, True, thr) for u in units]
        inc = [_envelope_unit(u, False, thr) for u in units]
        excl_can_fail = any(f for f, _ in ex)
        incl_can_meet = all(m for _, m in inc)
        (lost if (excl_can_fail or incl_can_meet) else still).append(
            {"id": i, "with_exclusion_can_fail": excl_can_fail, "without_exclusion_can_meet": incl_can_meet})
    return {"audits": len(ids), "decided_under_every_consistent_count": len(still),
            "not_decided_under_some_consistent_count": len(lost), "detail": lost}


def run(df: pd.DataFrame | None = None, sensitivity: bool = True) -> dict:
    df = engine.build.load() if df is None else df
    m_ex = engine.load_mandate(EX / "ll144-as-permitted-exclude.json")
    m_in = engine.load_mandate(EX / "ll144-as-permitted-include.json")
    m_cm = engine.load_mandate(EX / "illustrative-community-precautionary.json")
    ex, inc, cm = (engine.evaluate(m, df) for m in (m_ex, m_in, m_cm))
    E = {r["id"]: r for r in ex["results"]}
    I = {r["id"]: r for r in inc["results"]}
    C = {r["id"]: r for r in cm["results"]}
    ids = sorted(set(E) & set(I))
    pub = published_point_outcome(df)

    dep = [i for i in ids if E[i]["outcome"] != I[i]["outcome"]]
    favourable = [i for i in dep if E[i]["outcome"] == "meets" and I[i]["outcome"] == "fails"]
    adverse = [i for i in dep if E[i]["outcome"] == "fails" and I[i]["outcome"] == "meets"]
    pub_meets = [i for i in favourable if pub.get(i) == "meets"]
    pub_fails = [i for i in favourable if pub.get(i) == "fails"]
    pub_none = [i for i in favourable if pub.get(i) is None]

    # robustness: interval readings (90% and 95%, familywise on/off) under each permitted option
    robust = {}
    for alpha in (0.10, 0.05):
        for fw in (False, True):
            ru = {**m_ex["rules"], "reading": "interval", "alpha": alpha, "familywise": fw, "indeterminate_is": "insufficient_evidence"}
            rv = {**m_in["rules"], "reading": "interval", "alpha": alpha, "familywise": fw, "indeterminate_is": "insufficient_evidence"}
            a = engine.evaluate({**m_ex, "mandate_id": "robust-ex", "rules": ru}, df)
            b = engine.evaluate({**m_in, "mandate_id": "robust-in", "rules": rv}, df)
            A = {r["id"]: r["outcome"] for r in a["results"]}
            B = {r["id"]: r["outcome"] for r in b["results"]}
            common = sorted(set(A) & set(B))
            rank = {"fails": 0, "insufficient_evidence": 1, "meets": 2}
            robust[f"alpha={alpha:g},familywise={fw}"] = {
                "audits": len(common),
                "outcome_depends_on_option": sum(A[i] != B[i] for i in common),
                "exclusion_more_favourable": sum(rank[A[i]] > rank[B[i]] for i in common),
                "exclusion_less_favourable": sum(rank[A[i]] < rank[B[i]] for i in common),
                "flip_fails_to_meets": sum(A[i] == "meets" and B[i] == "fails" for i in common),
            }

    # which groups does the permitted exclusion remove from the reference position in those audits?
    d = df[~df.missing_cat]
    dropped = []
    for i in favourable:
        for (ch, rk), g in d[d.audit_id == i].groupby(["protected_char_group", "selection_or_scoring_rate"]):
            g = g.assign(rate=pd.to_numeric(g.n_selected_or_n_above_median, errors="coerce") / g.n, share=g.n / g.n.sum())
            g = g.dropna(subset=["rate"]).sort_values("rate", ascending=False)
            if len(g) and g.iloc[0].share < 0.02:
                t = g.iloc[0]
                dropped.append({"audit": i, "unit": f"{ch} / {rk}", "group": f"{t.race_ethnicity} · {t.sex}".replace("Total · ", "").replace(" · Total", ""),
                                "applicants": int(t.n), "share_pct": round(100 * float(t.share), 3), "rate": round(float(t.rate), 3)})
    # the same group can hold the reference position in several units (race and intersectional; both selection
    # definitions of a tiered tool): count each group once per audit, at its largest size
    distinct = {}
    for x in dropped:
        k = (x["audit"], x["group"])
        distinct[k] = max(distinct.get(k, 0), x["applicants"])
    nd = sorted(distinct.values())
    distinct_summary = {"groups": len(nd), "median_applicants": float(pd.Series(nd).median()) if nd else None,
                        "max_applicants": nd[-1] if nd else None, "with_100_or_more_applicants": sum(n >= 100 for n in nd),
                        "with_1000_or_more_applicants": sum(n >= 1000 for n in nd),
                        "native": sum(any(s in g for s in ("American Indian", "Native Hawaiian")) for _, g in distinct)}
    ns = sorted(x["applicants"] for x in dropped)
    dropped_summary = {"instances": len(ns), "median_applicants": float(pd.Series(ns).median()) if ns else None,
                       "min_applicants": ns[0] if ns else None, "max_applicants": ns[-1] if ns else None,
                       "with_100_or_more_applicants": sum(n >= 100 for n in ns), "with_1000_or_more_applicants": sum(n >= 1000 for n in ns)}

    row = lambda i: {"id": i, "entity": E[i]["entity"], "auditor": E[i]["auditor"], "year": E[i]["year"],
                     "with_exclusion": E[i]["outcome"], "without_exclusion": I[i]["outcome"],
                     "as_published": pub.get(i), "community_mandate": C.get(i, {}).get("outcome")}
    # sensitivity: drop the largest audit firm (most audits in the corpus; its reference rates appear pooled
    # across deployments, see the paper's methods). Identified from the data and never printed by name.
    counts = {}
    for i in E:
        counts[E[i]["auditor"]] = counts.get(E[i]["auditor"], 0) + 1
    big = max(sorted(counts), key=lambda k: counts[k])
    nd_ids = [i for i in ids if E[i]["auditor"] != big]
    nd_fav = [i for i in favourable if E[i]["auditor"] != big]
    without_largest = {"auditor_removed": "the largest audit firm", "audits": len(nd_ids), "outcome_depends_on_option": len(nd_fav),
                       "pct": round(100 * len(nd_fav) / len(nd_ids), 1) if nd_ids else None,
                       "published_passing_version": sum(pub.get(i) == "meets" for i in nd_fav),
                       "distinct_employers": len({E[i]["entity"] for i in nd_fav})}

    res = {
        "question": "How often does a choice the LL144 rule leaves to the auditor decide the four-fifths outcome?",
        "rule": "6 RCNY 5-301(d): an auditor 'may exclude a category that represents less than 2% of the data'",
        "audits": len(ids),
        "tallies": {"with_exclusion": ex["tally"], "without_exclusion": inc["tally"], "illustrative_community": cm["tally"]},
        "outcome_depends_on_option": len(dep),
        "pct_outcome_depends_on_option": round(100 * len(dep) / len(ids), 1),
        "option_turns_fail_into_pass": len(favourable),
        "option_turns_pass_into_fail": len(adverse),
        "of_those_published_the_passing_version": len(pub_meets),
        "of_those_published_a_failing_version": len(pub_fails),
        "of_those_no_published_ratios": len(pub_none),
        "distinct_employers": len({E[i]["entity"] for i in favourable}),
        "distinct_auditors": len({E[i]["auditor"] for i in favourable}),
        "community_mandate_on_these": {o: sum(C.get(i, {}).get("outcome") == o for i in favourable) for o in engine.OUTCOMES},
        "robustness_interval_readings": robust,
        "without_largest_auditor": without_largest,
        "dropped_reference_groups": dropped_summary,
        "dropped_reference_groups_distinct": distinct_summary,
        "dropped_reference_group_list": dropped,
        "audits_where_option_decides": [row(i) for i in favourable],
        "mandate_hashes": {m["mandate_id"]: engine.mandate_sha256(m) for m in (m_ex, m_in, m_cm)},
        "corpus_sha256": engine.build.sha256(engine.build.CSV),
    }
    if sensitivity:
        res["rounding_envelope_point"] = rounding_envelope_point(df, favourable)
        # tiered tools report two selection definitions; judge each audit on one of them
        two = df.groupby("audit_id").selection_or_scoring_rate.transform(lambda s: s.nunique() > 1)
        res["one_selection_definition"] = {}
        for name, drop in (("top", "Selection, top and middle"), ("top_and_middle", "Selection, top")):
            r = run(df[~(two & (df.selection_or_scoring_rate == drop))], sensitivity=False)
            res["one_selection_definition"][name] = {
                "audits": r["audits"], "outcome_depends_on_option": r["outcome_depends_on_option"],
                "option_turns_pass_into_fail": r["option_turns_pass_into_fail"],
                "published_passing_version": r["of_those_published_the_passing_version"],
                "without_largest_auditor": r["without_largest_auditor"]["outcome_depends_on_option"],
                "without_largest_auditor_audits": r["without_largest_auditor"]["audits"]}
    return res


def main() -> None:
    res = run()
    OUT.mkdir(exist_ok=True)
    (OUT / "discretion.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    r = res
    lines = [
        "# Who decides? Numbers (generated by discretion.py; do not edit)", "",
        f"- Audits judged: {r['audits']}",
        f"- Outcome depends only on the auditor's permitted exclusion option: **{r['outcome_depends_on_option']} ({r['pct_outcome_depends_on_option']}%)**",
        f"- Direction: option turns fail into pass in {r['option_turns_fail_into_pass']}; pass into fail in {r['option_turns_pass_into_fail']} (structural under the point reading: exclusion can only lower the reference rate or remove a ratio)",
        f"- Without {r['without_largest_auditor']['auditor_removed']} (pooled references): {r['without_largest_auditor']['outcome_depends_on_option']} of {r['without_largest_auditor']['audits']} audits ({r['without_largest_auditor']['pct']}%), {r['without_largest_auditor']['distinct_employers']} employers; published passing version in {r['without_largest_auditor']['published_passing_version']}",
        f"- Of the {r['option_turns_fail_into_pass']}, the audit as published shows the passing version in **{r['of_those_published_the_passing_version']}**, a failing version in {r['of_those_published_a_failing_version']}, no ratios in {r['of_those_no_published_ratios']}",
        f"- Employers affected: {r['distinct_employers']}; audit firms: {r['distinct_auditors']}",
        f"- Same {r['option_turns_fail_into_pass']} audits under the illustrative community mandate: {r['community_mandate_on_these']}",
        f"- Tallies: {json.dumps(r['tallies'])}",
        f"- Highest-rate groups the option removes from the reference position in those audits: {json.dumps(r['dropped_reference_groups'])}", "",
        "## Robustness (interval readings; indeterminate = insufficient evidence)", "",
        "| Reading | Outcome depends on option | Exclusion more favourable | Less favourable | Fail to pass |", "|---|---|---|---|---|",
        *[f"| {k} | {v['outcome_depends_on_option']} | {v['exclusion_more_favourable']} | {v['exclusion_less_favourable']} | {v['flip_fails_to_meets']} |" for k, v in r["robustness_interval_readings"].items()],
        "", "## Audits where the option decides the outcome", "",
        "| Employer | Auditor | Year | With exclusion | Without | As published | Community mandate |", "|---|---|---|---|---|---|---|",
        *[f"| {a['entity']} | {a['auditor']} | {a['year']} | {a['with_exclusion']} | {a['without_exclusion']} | {a['as_published']} | {a['community_mandate']} |" for a in r["audits_where_option_decides"]],
        "", f"Corpus SHA-256 `{r['corpus_sha256']}`. Mandate hashes: " + ", ".join(f"`{k}` {v[:16]}" for k, v in r["mandate_hashes"].items()),
    ]
    (OUT / "FINDING_NUMBERS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print("\n".join(lines[12:20]))


if __name__ == "__main__":
    main()
