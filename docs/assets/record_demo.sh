#!/usr/bin/env bash
# Regenerate the terminal demo asset (docs/assets/demo.svg).
#
# The checked-in demo.svg is a hand-authored, dependency-free rendering of the
# run -> tamper -> audit loop so the README shows the signature moment without
# any external host. To capture a *live* recording instead (e.g. an animated
# SVG for the docs site), use asciinema + svg-term:
#
#   pip install intentflow
#   asciinema rec demo.cast -c "bash docs/assets/demo_script.sh"
#   npx svg-term-cli --in demo.cast --out docs/assets/demo.svg --window
#
# demo_script.sh below is the exact sequence the static asset depicts.
set -euo pipefail

cat > /tmp/triage.iflow <<'IFLOW'
goal TriageBug {
  objective:
    decide whether an incoming bug report is actionable
  evidence:
    require issue_body
    require comments
  actions:
    allow read_issue
    require_approval close_issue
  verify:
    require cites_evidence
    check confidence >= 0.6
  uncertainty:
    if confidence < 0.6 ask_human
    if missing_evidence ask_human
  output:
    verdict: string
    confidence: number
    rationale: markdown
}
IFLOW

intentflow run /tmp/triage.iflow --simulate --trace-out /tmp/result.json
intentflow audit /tmp/triage.iflow /tmp/result.json
python -c "import json; d=json.load(open('/tmp/result.json')); d['result']['citations']=['E99']; json.dump(d, open('/tmp/result.json','w'))"
intentflow audit /tmp/triage.iflow /tmp/result.json || true
