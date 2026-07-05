"""JSON Schema conformance tests (issue #17).

Every plan and result the compiler/runtime produces for the bundled examples —
goals and pipelines — must validate against the published schemas under
``schemas/``. This turns the two contract artifacts from "whatever the code
emits" into an open, versioned format others can build on.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime, run_pipeline

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted(glob.glob(str(ROOT / "examples" / "*.iflow")))
WORKSPACE = str(ROOT / "examples" / "workspace")


def _load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text())


PLAN_SCHEMA = _load_schema("plan.schema.json")
RESULT_SCHEMA = _load_schema("result.schema.json")


def test_schemas_are_themselves_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(PLAN_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(RESULT_SCHEMA)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: Path(p).stem)
def test_example_plan_validates(path: str) -> None:
    document = compile_program(parse_file(path))
    jsonschema.validate(document, PLAN_SCHEMA)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: Path(p).stem)
def test_example_goal_results_validate(path: str) -> None:
    document = compile_program(parse_file(path))
    for plan in document["goals"]:
        result = GoalRuntime(plan, printer=None, workspace=WORKSPACE).run()
        jsonschema.validate(result, RESULT_SCHEMA)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: Path(p).stem)
def test_example_pipeline_results_validate(path: str) -> None:
    document = compile_program(parse_file(path))
    for pipeline in document.get("pipelines", []):
        result = run_pipeline(document, pipeline["name"], workspace=WORKSPACE)
        jsonschema.validate(result, RESULT_SCHEMA)


def test_result_schema_rejects_a_bad_status() -> None:
    document = compile_program(parse_file(EXAMPLES[0]))
    result = GoalRuntime(document["goals"][0], printer=None, workspace=WORKSPACE).run()
    result["status"] = "totally_made_up"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, RESULT_SCHEMA)


def test_plan_schema_rejects_unknown_top_level_key() -> None:
    document = compile_program(parse_file(EXAMPLES[0]))
    document["surprise"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, PLAN_SCHEMA)
