"""Embedding API: use IntentFlow from Python.

    import intentflow

    program = intentflow.load("examples/diagnose.iflow")
    result = program.run(backend="simulate")

You can also register plain Python functions as governed actions — they still
run *through the action gate*, so a goal that does not allow the action cannot
call it:

    program.register_tool("lookup_user", serves=("user_record",), handler=fn)
    program.run(goal="ResolveTicket")

This is the inverse of the CLI: Python programs *deterministic computation*,
IntentFlow programs *governed cognition*, and they compose in both directions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from intentflow.backends import CognitionBackend, make_backend
from intentflow.compiler import (
    Diagnostic,
    compile_program,
    inspect_program,
    validate_program,
)
from intentflow.judges import Judge, make_judge
from intentflow.parser import Program, parse_file, parse_source
from intentflow.runtime import GoalRuntime, run_pipeline
from intentflow.tools import Approver, PreGrantedApprover, Tool, ToolRegistry


class IntentFlowProgram:
    """A loaded ``.iflow`` program with a Python-friendly surface."""

    def __init__(self, program: Program) -> None:
        self._program = program
        self._extra_tools: list[Tool] = []

    # -- introspection ----------------------------------------------------

    @property
    def source_name(self) -> str:
        return self._program.source_name

    def goal_names(self) -> list[str]:
        return [g.name for g in self._program.goals]

    def pipeline_names(self) -> list[str]:
        return [p.name for p in self._program.pipelines]

    def validate(self) -> list[Diagnostic]:
        return validate_program(self._program)

    def compile(self) -> dict[str, Any]:
        return compile_program(self._program)

    def inspect(self) -> dict[str, Any]:
        return inspect_program(self._program)

    # -- governed Python tools -------------------------------------------

    def register_tool(
        self,
        action: str,
        serves: tuple[str, ...] | list[str],
        handler: Callable[[str], str],
        description: str = "",
    ) -> "IntentFlowProgram":
        """Register a Python function as a governed action. The handler is
        invoked only through the action gate."""
        self._extra_tools.append(
            Tool(action=action, serves=tuple(serves), handler=handler,
                 description=description)
        )
        return self

    def _registry(self, workspace: str | None) -> ToolRegistry | None:
        if not workspace and not self._extra_tools:
            return None
        registry = ToolRegistry.builtin(workspace) if workspace else ToolRegistry([])
        for tool in self._extra_tools:
            registry.add(tool)
        return registry

    # -- execution --------------------------------------------------------

    def run(
        self,
        goal: str | None = None,
        *,
        backend: str | CognitionBackend = "simulate",
        workspace: str | None = None,
        approve: set[str] | list[str] | None = None,
        approver: Approver | None = None,
        judge: str | Judge | None = None,
        sign_key: bytes | None = None,
        cassette: str | Path | None = None,
        printer: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Compile and run one goal, returning the verified, traced result."""
        document = self.compile()
        plans = {p["goal"]: p for p in document["plans"]}
        if goal is None:
            if not document["plans"]:
                raise ValueError("program has no goals to run")
            plan = document["plans"][0]
        elif goal in plans:
            plan = plans[goal]
        else:
            raise ValueError(
                f"unknown goal {goal!r}; available: {sorted(plans)}"
            )
        registry = self._registry(workspace)
        runtime = GoalRuntime(
            plan,
            backend=self._backend(backend, cassette),
            printer=printer,
            workspace=None if registry is not None else workspace,
            approver=self._approver(approve, approver),
            judge=self._judge(judge),
            registry=registry,
            sign_key=sign_key,
        )
        return runtime.run()

    def run_pipeline(
        self,
        name: str,
        *,
        backend: str | CognitionBackend = "simulate",
        workspace: str | None = None,
        approve: set[str] | list[str] | None = None,
        approver: Approver | None = None,
        judge: str | Judge | None = None,
        sign_key: bytes | None = None,
        cassette: str | Path | None = None,
        printer: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Compile and run a named pipeline."""
        document = self.compile()
        return run_pipeline(
            document,
            name,
            backend=self._backend(backend, cassette),
            printer=printer,
            workspace=None if self._registry(workspace) is not None else workspace,
            judge=self._judge(judge),
            approver=self._approver(approve, approver),
            registry=self._registry(workspace),
            sign_key=sign_key,
        )

    # -- resolvers --------------------------------------------------------

    @staticmethod
    def _backend(
        backend: str | CognitionBackend, cassette: str | Path | None
    ) -> CognitionBackend:
        if isinstance(backend, str):
            return make_backend(backend, cassette)
        return backend

    @staticmethod
    def _judge(judge: str | Judge | None) -> Judge | None:
        if judge is None or not isinstance(judge, str):
            return judge
        return make_judge(judge)

    @staticmethod
    def _approver(
        approve: set[str] | list[str] | None, approver: Approver | None
    ) -> Approver | None:
        if approver is not None:
            return approver
        if approve is not None:
            return PreGrantedApprover(set(approve))
        return None


def load(source: str | Path, name: str | None = None) -> IntentFlowProgram:
    """Load a program from a file path or raw source string.

    If ``source`` is an existing file it is read and parsed; otherwise it is
    treated as inline IntentFlow source."""
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file()):
        return IntentFlowProgram(parse_file(source))
    return IntentFlowProgram(parse_source(source, source_name=name or "<string>"))


def load_source(text: str, name: str = "<string>") -> IntentFlowProgram:
    """Load a program from inline source text."""
    return IntentFlowProgram(parse_source(text, source_name=name))
