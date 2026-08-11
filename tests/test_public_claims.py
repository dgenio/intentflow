from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CLAIM_DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "design_principles.md",
    ROOT / "docs" / "concepts.md",
)


def _public_claim_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_CLAIM_DOCS)


def test_public_docs_do_not_restore_retired_v0_assurance_claims() -> None:
    text = _public_claim_text()
    retired = (
        "audit` recompiles the source and proves — without trusting the runtime",
        "Conformance is independently verifiable",
        "`intentflow audit` proves a\n   run stayed inside its envelope",
        "auditor.py      independent trace conformance checking",
        "proof-carrying agent behavior",
        "Confidence is calibrated before rules fire",
        "The trace is append-only and complete",
    )
    for phrase in retired:
        assert phrase not in text


def test_readme_links_claims_limitations_and_incubation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "CLAIMS.md" in readme
    assert "docs/limitations.md" in readme
    assert "INCUBATION.md" in readme


def test_claims_document_keeps_v0_v1_boundary_explicit() -> None:
    claims = (ROOT / "CLAIMS.md").read_text(encoding="utf-8")
    assert "legacy/experimental" in claims
    assert "v1 hypotheses are not v0 claims" in claims.lower()
    assert "Issue #160" in claims
