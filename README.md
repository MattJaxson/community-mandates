# Community Mandates

**Rules for judging AI bias audits, set by the public instead of by the company being audited.**

New York City's Local Law 144 requires employers to publish a bias audit of the AI hiring tools
they use. The company pays for that audit, and the rule leaves several outcome-deciding choices to
the auditor. One of them is whether to drop demographic groups under 2% of applicants from the
comparison. Run every published audit in the public corpus both ways, and that single permitted
choice decides whether the audit clears the four-fifths line in **22 of 114 audits**, every time in
the company's favour.

The fix isn't a better auditor. It's moving the choice. A **Community Mandate** is a
machine-readable rulebook in which a public body (a regulator, a council, a community
organisation) fixes every parameter that decides an outcome, records its authority and process,
and gets a content fingerprint, so any verdict is tied to the exact rules used. The engine here
re-judges any published audit under any mandate: same evidence, the public's rules.

> **Status (October 2026): working, tested, open. No public body has adopted a mandate yet.**
> The only community mandate here (`examples/illustrative-community-precautionary.json`) is an
> illustration adopted by no one. The two `ll144-as-permitted-*` mandates *describe* what NYC's
> rule lets an auditor do. They are not endorsements.

Paper: Matthew Jackson, *Four-Fifths of What? Statistical Indeterminacy in NYC Local Law 144 Bias
Audits and the Governance Parameters It Exposes*, Zenodo,
[doi:10.5281/zenodo.23672859](https://doi.org/10.5281/zenodo.23672859). Not peer reviewed.
Statistics: [libra-check](https://github.com/MattJaxson/libra-check) (LARS v0.1).

## What's here

| File | What it is |
| --- | --- |
| `mandate.schema.json` | The Community Mandate format: threshold, how uncertainty is read, small-group exclusion, who carries the burden when evidence is unsettled (`indeterminate_is`), whether test data counts, plus authority, process and status. An *adopted* mandate must cite a public record of the decision. |
| `engine.py` | Validates a mandate, fingerprints it, and judges every audit in the corpus under it: **meets / fails / insufficient evidence**. |
| `discretion.py` | The finding: how often NYC's permitted exclusion option alone decides the four-fifths outcome, with robustness checks. |
| `corpus.py` | Loads the ACLU corpus and scores each audit with libra-check. |
| `examples/` | Two descriptive mandates (NYC's rule with and without the exclusion) and one illustrative community mandate. |
| `FINDING.md` | The finding in plain language, with what it does **not** show. |
| `test_mandates.py` | Tests that pin every headline number. |

## Reproduce

Requires Python 3.12.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 1. Tests that don't need the corpus (schema, fingerprints, judging rules)
.venv/bin/python -m pytest -q

# 2. Get the corpus from its authors (not redistributed here; CC BY-NC 4.0)
git clone https://github.com/aclu-national/auditing-the-audits-facct-2025 data/aclu-auditing-the-audits
git -C data/aclu-auditing-the-audits checkout cef7c27398dc73852f06f20120500d361abbd37e
shasum -a 256 data/aclu-auditing-the-audits/audits/audits_full.csv
#   expected: 69fd290fb0be9523254027e3508722e70501f8501a9a3d92f47f7ffd31bbf85e

# 3. The finding and every pinned number
.venv/bin/python discretion.py          # writes out/discretion.json, out/FINDING_NUMBERS.md
.venv/bin/python engine.py              # tallies per example mandate
.venv/bin/python -m pytest -q           # now also checks 22/114, 16/44, 21-30 under intervals, ...
```

To use a corpus clone elsewhere, set `LL144_CORPUS_DIR=/path/to/clone`.

**The largest audit firm.** One result is reported with and without the audit firm that produced
the most audits in the corpus. The code identifies that firm from the data and does not name it.
The locally generated `out/` files list employers and audit firms from the corpus. They are
git-ignored and should not be committed (CC BY-NC corpus; right of reply).

## Write your own mandate

Copy `examples/illustrative-community-precautionary.json` and set the `rules` your body has
decided: `threshold`, `reading` (point estimate or interval), `alpha`, `familywise`,
`comparator_rule`, `small_category_exclusion`, `indeterminate_is` (who carries the burden when the
evidence can't settle it) and `accept_test_data`. Then describe your `authority` (`kind`, `name`,
`process`, `adopted_on`, `record_uri`) and run `python engine.py path/to/your-mandate.json`. If `status` is `adopted`, validation requires a
public record of the decision (`authority.record_uri`). Every mandate gets a SHA-256 fingerprint of
its canonical JSON, so a verdict always says exactly which rules produced it.

## What this does not show

It does not show that any hiring tool discriminates, that any employer broke the law, or that any
auditor chose exclusion to help a client. LL144 requires publishing an audit, not passing one.
Excluding a very small group can be statistically reasonable. The point is who holds the choice.
See `FINDING.md`.

## License

- **Code and schema:** Apache-2.0 (`LICENSE`).
- **`FINDING.md` and the examples:** CC BY 4.0.
- **Corpus:** Gerchick et al. / ACLU, *Auditing the Audits* (FAccT 2025), CC BY-NC 4.0, not
  redistributed. Anything derived from it inherits the non-commercial license. The corpus authors
  are not responsible for this analysis.

## Cite

Jackson, M. (2026). *Four-Fifths of What?* Zenodo. https://doi.org/10.5281/zenodo.23672859
