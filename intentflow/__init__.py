"""IntentFlow: an experimental language for governed cognitive processes.

Classical programming languages describe deterministic procedures.
IntentFlow describes *governed cognitive processes*: goals, evidence
requirements, uncertainty handling, governed actions, verification rules,
human escalation, and auditable execution traces.

The pipeline is:

    .iflow source -> parser -> cognitive IR (AST) -> compiler ->
    execution plan (JSON) -> runtime -> verified, traced result
"""

from intentflow.iflow_ast import (
    ActionPolicy,
    ContextPolicy,
    EvidenceRequirement,
    Goal,
    OutputSpec,
    Pipeline,
    Program,
    Section,
    Statement,
    UncertaintyRule,
    VerificationRule,
)
from intentflow.parser import ParseError, parse_file, parse_source
from intentflow.compiler import CompileError, compile_goal, compile_program, validate_program
from intentflow.auditor import audit_document, audit_result
from intentflow.backends import AnthropicCognition, SimulatedCognition, make_backend
from intentflow.linter import lint_program
from intentflow.runtime import GoalRuntime, SimulationRuntime, run_pipeline

__version__ = "0.2.0"

__all__ = [
    "ActionPolicy",
    "AnthropicCognition",
    "CompileError",
    "ContextPolicy",
    "EvidenceRequirement",
    "Goal",
    "GoalRuntime",
    "OutputSpec",
    "ParseError",
    "Pipeline",
    "Program",
    "Section",
    "SimulatedCognition",
    "SimulationRuntime",
    "Statement",
    "UncertaintyRule",
    "VerificationRule",
    "audit_document",
    "audit_result",
    "compile_goal",
    "compile_program",
    "lint_program",
    "make_backend",
    "parse_file",
    "parse_source",
    "run_pipeline",
    "validate_program",
    "__version__",
]
