"""Action registry tests: metadata, heuristics, and analyzer integration."""

from __future__ import annotations

from intentflow.actions import ActionSpec, default_registry


def test_default_registry_knows_the_core_actions() -> None:
    registry = default_registry()
    for name in (
        "read_issue", "search_repo", "draft_comment", "post_comment",
        "close_issue", "read_logs", "inspect_code", "deploy_change",
        "write_database", "run_discriminating_test", "ask_human", "block_action",
    ):
        assert registry.get(name) is not None, name


def test_read_actions_have_no_side_effects() -> None:
    registry = default_registry()
    for name in ("read_issue", "search_repo", "read_logs", "inspect_code",
                 "draft_comment"):
        assert registry.is_side_effect(name) is False, name


def test_side_effect_actions_require_approval_by_default() -> None:
    registry = default_registry()
    for name in ("post_comment", "close_issue", "deploy_change", "write_database"):
        spec = registry.get(name)
        assert spec.side_effect is True, name
        assert spec.requires_approval_by_default is True, name


def test_deploy_and_database_are_high_risk() -> None:
    registry = default_registry()
    assert registry.get("deploy_change").risk == "high"
    assert registry.get("write_database").risk == "high"


def test_unknown_action_risk_is_inferred_from_name() -> None:
    registry = default_registry()
    assert registry.is_side_effect("push_to_main") is True
    assert registry.spec_for("push_to_main").risk == "medium"
    assert registry.is_side_effect("summarize_thread") is False
    assert registry.spec_for("summarize_thread").risk == "low"


def test_overly_broad_actions_are_high_risk() -> None:
    registry = default_registry()
    assert registry.is_overly_broad("execute_code") is True
    spec = registry.spec_for("execute_code")
    assert spec.risk == "high"
    assert spec.requires_approval_by_default is True


def test_specs_are_json_serializable() -> None:
    spec = ActionSpec("x", "desc", True, "high", True)
    assert spec.to_dict() == {
        "name": "x",
        "description": "desc",
        "side_effect": True,
        "risk": "high",
        "requires_approval_by_default": True,
    }
    assert "post_comment" in default_registry().to_dict()
