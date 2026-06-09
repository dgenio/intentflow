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
    Program,
    Section,
    Statement,
    UncertaintyRule,
    VerificationRule,
)
from intentflow.parser import ParseError, parse_file, parse_source
from intentflow.compiler import CompileError, compile_goal, compile_program, validate_program
from intentflow.runtime import SimulationRuntime

__version__ = "0.1.0"

__all__ = [
    "ActionPolicy",
    "CompileError",
    "ContextPolicy",
    "EvidenceRequirement",
    "Goal",
    "OutputSpec",
    "ParseError",
    "Program",
    "Section",
    "SimulationRuntime",
    "Statement",
    "UncertaintyRule",
    "VerificationRule",
    "compile_goal",
    "compile_program",
    "parse_file",
    "parse_source",
    "validate_program",
    "__version__",
]
