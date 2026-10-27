"""Run: python -m pytest -q   (corpus-dependent tests skip if the corpus is not present; see README)"""
import copy
import json
import sys
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discretion  # noqa: E402
import engine  # noqa: E402

EXAMPLES = sorted((HERE / "examples").glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_examples_validate(path):
    m = engine.load_mandate(path)
    assert m["mandate_id"] == path.stem


def test_no_example_claims_adoption():
    for p in EXAMPLES:
        m = json.loads(p.read_text())
        assert m["status"] in {"descriptive", "illustrative"}
        if m["status"] == "illustrative":
            assert m["authority"]["kind"] == "example" and "Not adopted" in m["authority"]["name"]


def test_adopted_mandate_requires_public_record():
    m = json.loads((HERE / "examples/illustrative-community-precautionary.json").read_text())
    m["status"] = "adopted"
    m["authority"]["kind"] = "community_body"
    with pytest.raises(ValueError):
        engine.validate(m)
    m["authority"]["record_uri"] = "https://example.org/minutes/2027-01-15"
    engine.validate(m)


def test_schema_rejects_unknown_rule():
    m = json.loads(EXAMPLES[0].read_text())
    m["rules"]["auditor_may_override"] = True
    with pytest.raises(jsonschema.ValidationError):
        engine.validate(m)


def test_hash_is_canonical_and_sensitive():
    m = json.loads(EXAMPLES[0].read_text())
    shuffled = json.loads(json.dumps(m, sort_keys=True))
    assert engine.mandate_sha256(m) == engine.mandate_sha256(shuffled)
    m2 = copy.deepcopy(m)
    m2["rules"]["threshold"] = 0.79
    assert engine.mandate_sha256(m) != engine.mandate_sha256(m2)


def _audit(states, points, data_type="Historical"):
    return {"data_type": data_type, "ratios": [{"is_comparator": True, "point": 1.0, "state": "determinate_at_or_above", "fw_state": "determinate_at_or_above"}] +
            [{"is_comparator": False, "point": p, "state": s, "fw_state": s} for s, p in zip(states, points)]}


RULES = {"threshold": 0.8, "reading": "interval", "alpha": 0.1, "familywise": True, "comparator_rule": "max_rate_all",
         "small_category_exclusion": None, "indeterminate_is": "insufficient_evidence", "accept_test_data": False}


def test_judge_point_reading_ignores_uncertainty():
    r = {**RULES, "reading": "point"}
    assert engine.judge(_audit(["indeterminate"], [0.85]), r)[0] == "meets"
    assert engine.judge(_audit(["indeterminate"], [0.79]), r)[0] == "fails"


def test_judge_interval_reading_and_burden():
    a = _audit(["determinate_at_or_above", "indeterminate"], [0.95, 0.85])
    assert engine.judge(a, RULES)[0] == "insufficient_evidence"
    assert engine.judge(a, {**RULES, "indeterminate_is": "pass"})[0] == "meets"
    assert engine.judge(a, {**RULES, "indeterminate_is": "fail"})[0] == "fails"
    assert engine.judge(_audit(["determinate_below", "indeterminate"], [0.6, 0.85]), RULES)[0] == "fails"
    assert engine.judge(_audit(["determinate_at_or_above"], [0.95]), RULES)[0] == "meets"


def test_judge_test_data_rule():
    a = _audit(["determinate_at_or_above"], [0.95], data_type="Test")
    assert engine.judge(a, RULES)[0] == "insufficient_evidence"
    assert engine.judge(a, {**RULES, "accept_test_data": True})[0] == "meets"


def test_params_for_null_exclusion_means_all_groups():
    p = engine.params_for({**RULES, "comparator_rule": "max_rate_eligible", "small_category_exclusion": None})
    assert p["comparator_rule"] == "max_rate_all" and p["small_category_exclusion"] is None


needs_corpus = pytest.mark.skipif(not engine.build.CSV.exists(), reason="ACLU corpus not present (see README step 2)")


@needs_corpus
def test_corpus_is_the_pinned_version():
    assert engine.build.sha256(engine.build.CSV) == engine.build.CORPUS_SHA256


@pytest.fixture(scope="module")
def finding():
    if not engine.build.CSV.exists():
        pytest.skip("ACLU corpus not present (see README step 2)")
    return discretion.run()


def test_finding_headline_numbers(finding):
    f = finding
    assert f["audits"] == 114
    assert f["outcome_depends_on_option"] == 22
    assert f["option_turns_fail_into_pass"] == 22
    assert f["option_turns_pass_into_fail"] == 0
    assert f["of_those_published_the_passing_version"] == 19
    assert f["tallies"]["with_exclusion"] == {"meets": 49, "fails": 65, "insufficient_evidence": 0}
    assert f["tallies"]["without_exclusion"] == {"meets": 27, "fails": 87, "insufficient_evidence": 0}


def test_finding_dropped_groups_are_real_groups(finding):
    s = finding["dropped_reference_groups"]
    assert s["instances"] == len(finding["dropped_reference_group_list"]) == 40
    assert s["with_100_or_more_applicants"] == 25
    assert all(g["share_pct"] < 2 for g in finding["dropped_reference_group_list"])
    d = finding["dropped_reference_groups_distinct"]  # each group once per audit (the paper's counts)
    assert (d["groups"], d["with_100_or_more_applicants"], d["with_1000_or_more_applicants"], d["native"]) == (34, 19, 5, 28)


def test_finding_one_selection_definition(finding):
    od = finding["one_selection_definition"]
    assert od["top"]["outcome_depends_on_option"] == 20 and od["top_and_middle"]["outcome_depends_on_option"] == 35
    assert all(v["option_turns_pass_into_fail"] == 0 for v in od.values())
    assert sorted(v["without_largest_auditor"] for v in od.values()) == [14, 16]


def test_finding_rounding_envelope(finding):
    env = finding["rounding_envelope_point"]
    assert env["decided_under_every_consistent_count"] == 17 and env["not_decided_under_some_consistent_count"] == 5


def test_finding_not_driven_by_largest_auditor(finding):
    w = finding["without_largest_auditor"]
    assert w["audits"] == 44 and w["outcome_depends_on_option"] == 16 and w["published_passing_version"] == 15


def test_finding_robust_to_interval_readings(finding):
    for k, v in finding["robustness_interval_readings"].items():
        assert v["outcome_depends_on_option"] >= 20, k
        assert v["exclusion_more_favourable"] > v["exclusion_less_favourable"], k


def test_permitted_exclusion_matches_observatory_parameters():
    m = engine.load_mandate(HERE / "examples/ll144-as-permitted-exclude.json")
    p = engine.params_for(m["rules"])
    assert p == {**engine.build.PARAMS, "thresholds": [0.8]}
