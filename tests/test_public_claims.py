from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_does_not_restore_retired_v0_assurance_claims() -> None:
    retired = (
        "audit` recompiles the source and proves — without trusting the runtime",
        "Conformance is independently verifiable",
        "`intentflow audit` proves a\n   run stayed inside its envelope",
        "auditor.py      independent trace conformance checking",
    )
    for phrase in retired:
        assert phrase not in README


def test_readme_links_claims_and_limitations() -> None:
    assert "CLAIMS.md" in README
    assert "docs/limitations.md" in README
    assert "INCUBATION.md" in README
