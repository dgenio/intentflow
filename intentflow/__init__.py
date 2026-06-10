"""IntentFlow: an experimental language for governed cognitive processes.

Classical programming languages describe deterministic procedures.
IntentFlow describes *governed cognitive processes*: goals, evidence
requirements, uncertainty handling, governed actions, verification rules,
human escalation, and auditable execution traces.

The pipeline is:

    .iflow source -> parser -> AST -> analyzer (diagnostics) -> compiler ->
    execution plan (JSON) -> runtime (phase machine) -> verified, traced
    result -> replay / audit
"""

from intentflow._version import __version__
from intentflow.iflow_ast import (
    ActionPolicy,
    ActionRule,
    ContextPolicy,
    EvidencePolicy,
    EvidenceRequirement,
    Goal,
    GoalMetadata,
    OutputField,
    OutputSchema,
    OutputSpec,
    Pipeline,
    Program,
    PromptBlock,
    PromptPlan,
    RiskProfile,
    Section,
    Statement,
    UncertaintyAction,
    UncertaintyCondition,
    UncertaintyPolicy,
    UncertaintyRule,
    VerificationPolicy,
    VerificationRule,
)
from intentflow.parser import ParseError, parse_file, parse_source
from intentflow.analyzer import Diagnostic, analyze_goal, analyze_program
from intentflow.actions import ActionRegistry, ActionSpec, default_registry
from intentflow.compiler import (
    CompileError,
    ExecutionPlan,
    compile_goal,
    compile_program,
    inspect_program,
)
from intentflow.auditor import audit_document, audit_result
from intentflow.backends import (
    AnthropicCognition,
    BackendError,
    BackendResponse,
    Cassette,
    MockBackend,
    OpenAICompatibleBackend,
    OpenAICompatibleCognition,
    RecordingBackend,
    ReplayBackend,
    SimulatedCognition,
    SimulatorBackend,
    make_backend,
)
from intentflow.explain import explain_program, render_explanation
from intentflow.judges import Judge, JudgeVerdict, LLMJudge, SimulatedJudge, make_judge
from intentflow.tools import (
    ActionDenied,
    ActionGate,
    ApprovalDecision,
    ApprovalError,
    Approver,
    CallbackApprover,
    PreGrantedApprover,
    Tool,
    ToolRegistry,
    TTYApprover,
    WebhookApprover,
)
from intentflow.formatter import format_file, format_source
from intentflow.linter import lint_program
from intentflow.runtime import (
    GoalRuntime,
    SimulationRuntime,
    execute_program,
    run_pipeline,
)
from intentflow.api import IntentFlowProgram, load, load_source

__all__ = [
    "ActionDenied",
    "ActionGate",
    "ActionPolicy",
    "ActionRegistry",
    "ActionRule",
    "ActionSpec",
    "AnthropicCognition",
    "ApprovalDecision",
    "ApprovalError",
    "Approver",
    "BackendError",
    "BackendResponse",
    "CallbackApprover",
    "Cassette",
    "CompileError",
    "ContextPolicy",
    "Diagnostic",
    "EvidencePolicy",
    "EvidenceRequirement",
    "ExecutionPlan",
    "Goal",
    "GoalMetadata",
    "GoalRuntime",
    "IntentFlowProgram",
    "Judge",
    "JudgeVerdict",
    "LLMJudge",
    "MockBackend",
    "OpenAICompatibleBackend",
    "OpenAICompatibleCognition",
    "OutputField",
    "OutputSchema",
    "OutputSpec",
    "ParseError",
    "Pipeline",
    "PreGrantedApprover",
    "Program",
    "PromptBlock",
    "PromptPlan",
    "RecordingBackend",
    "ReplayBackend",
    "RiskProfile",
    "Section",
    "SimulatedCognition",
    "SimulatedJudge",
    "SimulationRuntime",
    "SimulatorBackend",
    "Statement",
    "TTYApprover",
    "Tool",
    "ToolRegistry",
    "UncertaintyAction",
    "UncertaintyCondition",
    "UncertaintyPolicy",
    "UncertaintyRule",
    "VerificationPolicy",
    "VerificationRule",
    "WebhookApprover",
    "analyze_goal",
    "analyze_program",
    "audit_document",
    "audit_result",
    "compile_goal",
    "compile_program",
    "default_registry",
    "execute_program",
    "explain_program",
    "format_file",
    "format_source",
    "inspect_program",
    "lint_program",
    "load",
    "load_source",
    "make_backend",
    "make_judge",
    "parse_file",
    "parse_source",
    "render_explanation",
    "run_pipeline",
    "__version__",
]
