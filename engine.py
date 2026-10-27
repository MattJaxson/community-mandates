"""Judge published AI bias audits under a community mandate instead of the auditor's own choices.

Evidence = the counts a company published (here: the ACLU LL144 corpus).
Rules    = a mandate (mandate.schema.json), written by whoever holds authority to set them.
Engine   = libra-check for the statistics; this module applies the mandate's rules on top.

Outcomes per audit: meets / fails / insufficient_evidence.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus as build  # noqa: E402  (corpus loading and libra-check scoring)

SCHEMA = HERE / "mandate.schema.json"
OUTCOMES = ("meets", "fails", "insufficient_evidence")


def load_mandate(path: Path) -> dict:
    m = json.loads(Path(path).read_text())
    validate(m)
    return m


def validate(m: dict) -> None:
    import jsonschema
    jsonschema.validate(m, json.loads(SCHEMA.read_text()))
    if m["status"] == "adopted" and not m["authority"].get("record_uri"):
        raise ValueError(f"{m['mandate_id']}: an adopted mandate must cite a public record of the decision")


def mandate_sha256(m: dict) -> str:
    """Content hash of the mandate (canonical JSON), so an evaluation is bound to the exact rules used."""
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def params_for(rules: dict) -> dict:
    excl = rules["small_category_exclusion"]
    rule = rules["comparator_rule"] if excl is not None else "max_rate_all"
    return {"thresholds": [rules["threshold"]], "alpha": rules["alpha"], "comparator_rule": rule,
            "selection_adjustment": "none", "small_category_exclusion": excl if rule == "max_rate_eligible" else None}


def judge(audit: dict, rules: dict) -> tuple[str, str]:
    thr = rules["threshold"]
    if not rules["accept_test_data"] and str(audit["data_type"]).lower() != "historical":
        return "insufficient_evidence", "built on test or unknown data; the mandate requires real applicant data"
    focal = [r for r in audit["ratios"] if not r["is_comparator"]]
    if rules["reading"] == "point":
        low = [r for r in focal if r["point"] is not None and r["point"] < thr]
        if low:
            return "fails", f"{len(low)} published ratio(s) below {thr:g}"
        return "meets", f"every published ratio at or above {thr:g}"
    key = "fw_state" if rules["familywise"] else "state"
    states = [r[key] for r in focal]
    if "determinate_below" in states:
        return "fails", f"{states.count('determinate_below')} ratio(s) below {thr:g} with confidence"
    if all(s == "determinate_at_or_above" for s in states):
        return "meets", f"every ratio at or above {thr:g} with confidence"
    n = states.count("indeterminate")
    outcome = {"pass": "meets", "fail": "fails", "insufficient_evidence": "insufficient_evidence"}[rules["indeterminate_is"]]
    return outcome, f"{n} ratio(s) the evidence cannot settle; mandate treats that as '{rules['indeterminate_is']}'"


def evaluate(mandate: dict, df=None) -> dict:
    df = build.load() if df is None else df
    rules = mandate["rules"]
    p = params_for(rules)
    audits, excluded, _ = build.score(df, p)
    results = []
    for a in audits:
        outcome, reason = judge(a, rules)
        results.append({"id": a["id"], "entity": a["entity"], "auditor": a["auditor"], "year": a["year"],
                        "data_type": a["data_type"], "outcome": outcome, "reason": reason})
    tally = {o: sum(r["outcome"] == o for r in results) for o in OUTCOMES}
    return {"mandate_id": mandate["mandate_id"], "mandate_title": mandate["title"], "mandate_status": mandate["status"],
            "mandate_sha256": mandate_sha256(mandate), "engine_params": p, "tally": tally,
            "results": results, "not_scored": [{"id": e["id"], "reason": e["reason"]} for e in excluded]}


if __name__ == "__main__":
    for path in sys.argv[1:] or sorted((HERE / "examples").glob("*.json")):
        r = evaluate(load_mandate(Path(path)))
        print(f"{r['mandate_id']:40s} {r['tally']}  sha256={r['mandate_sha256'][:12]}")
