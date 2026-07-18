# Where IntentFlow fits

The first question every evaluator asks is "how is this different from what I
already use?" The short answer: IntentFlow is a **governance and verification
layer**, and it typically sits *alongside* the tools below rather than replacing
them.

Each category below is described factually, from those projects' own
documentation — no comparative judgments.

## Orchestration frameworks

Tools like **LangGraph** and **CrewAI** coordinate the *steps* of an agent:
which node runs next, how state flows, how tools are called. They answer "what
happens in what order."

IntentFlow does not orchestrate steps. It compiles a per-task **governance
contract** and audits the run against it. **Works well with:** keep your
orchestration framework driving control flow, and wrap the consequential steps
as governed IntentFlow actions so each one carries an auditable envelope and
witness.

## Guardrail systems

Tools like **NeMo Guardrails** and **Invariant** filter runtime I/O — checking
or transforming prompts and responses as they pass through.

IntentFlow's checks are declared in the program (evidence requirements,
verification rules, uncertainty policy) and are recorded in the witness for
after-the-fact audit, rather than applied only as an inline filter. **Works well
with:** use guardrails for real-time I/O filtering and IntentFlow for the
governed contract + independent audit trail.

## Policy engines

Tools like **OPA (Open Policy Agent)** and **Cedar** decide *authorization* —
is this request, by this principal, permitted? — over general-purpose policy.

IntentFlow's ActionGate makes the analogous decision for a run's actions, but
from the compiled plan, and it emits a hash-chained witness proving what was
authorized and invoked. **Works well with:** a policy engine can own
organization-wide authorization while IntentFlow governs and records a specific
cognitive task.

## In one line

Orchestration frameworks coordinate steps; guardrail systems filter runtime
I/O; policy engines decide authorization; **IntentFlow compiles a per-task
governance contract and independently audits the run against it.**
