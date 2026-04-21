"""Phase 4 workflow_engine smoke test.

Exercises:
  1. Enumerate workflows from workflows/*.yaml (morning/evening/research).
  2. Validate that a YAML with a forbidden gate step is rejected.
  3. Validate cycle detection.
  4. Run research_run end-to-end. filter_universe runs for real;
     compute_macro/analyze/plan are stubs that log "not yet implemented".
  5. Verify data/universe_latest.json + data/pipeline_status.json get written.

Run:  .venv\\Scripts\\python.exe -m scripts.smoke_phase4_workflow
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

from services.settings_service import Settings
from services.workflow_engine import (
    PIPELINE_STATUS_FILE,
    UNIVERSE_LATEST_FILE,
    WorkflowEngine,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> int:
    print("=" * 70)
    print("Phase 4 workflow_engine smoke test")
    print("=" * 70)

    settings = Settings()
    engine = WorkflowEngine(settings)

    # ---- 1. list_workflows discovers the three seed YAMLs ---------------
    print("\n[1/5] list_workflows() enumerates seed YAMLs")
    workflows = await engine.list_workflows()
    ids = sorted(w.workflow_id for w in workflows)
    expected = ["evening_run", "morning_run", "research_run"]
    assert ids == expected, f"expected {expected}, got {ids}"
    print(f"  OK - found: {ids}")

    # ---- 2. forbidden gate step is rejected ------------------------------
    print("\n[2/5] workflow YAML with 'compliance_officer' is rejected")
    bad_yaml = """
workflow_id: bad_gate
description: should fail to load
default_mode: research
steps:
  - id: gate_injection
    kind: compliance_officer
"""
    with tempfile.TemporaryDirectory() as td:
        bad_path = Path(td) / "bad.yaml"
        bad_path.write_text(bad_yaml, encoding="utf-8")
        try:
            await engine.load(bad_path)
            print("  FAIL - engine accepted a forbidden gate step")
            return 1
        except Exception as e:
            assert "compliance_officer" in str(e) or "risk_manager" in str(e), (
                f"wrong rejection reason: {e}"
            )
            print(f"  OK - rejected: {type(e).__name__}")

    # ---- 3. cycle detection ---------------------------------------------
    print("\n[3/5] cycle in depends_on is rejected")
    cycle_yaml = """
workflow_id: cycle_wf
description: a -> b -> a
default_mode: research
steps:
  - id: a
    kind: filter_universe
    depends_on: [b]
  - id: b
    kind: compute_macro
    depends_on: [a]
"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cycle.yaml"
        p.write_text(cycle_yaml, encoding="utf-8")
        try:
            await engine.load(p)
            print("  FAIL - engine accepted a cyclic workflow")
            return 1
        except Exception as e:
            assert "cycle" in str(e).lower() or "unresolved" in str(e).lower(), (
                f"wrong rejection reason: {e}"
            )
            print(f"  OK - rejected: {e}")

    # ---- 4. run research_run end-to-end ---------------------------------
    print("\n[4/5] research_run end-to-end")
    wf = await engine.load_by_id("research_run")
    run_result = await engine.run(wf)
    assert run_result.error is None, f"workflow errored: {run_result.error}"
    step_ids = [s.step_id for s in run_result.step_results]
    assert set(step_ids) == {"filter_universe", "compute_macro", "analyze", "plan"}, (
        f"unexpected step set: {step_ids}"
    )
    print(
        f"  OK - 4 steps completed, duration={run_result.duration_seconds:.2f}s, "
        f"shortlist={run_result.symbols_in_shortlist}, "
        f"signals={run_result.signals_generated}, "
        f"plans={run_result.plans_proposed}"
    )
    # Every step that matters reports duration
    for s in run_result.step_results:
        status = "stub" if s.output.get("stub") else "real"
        print(f"    - {s.step_id:20s} [{s.kind:16s}] {s.duration_seconds:.2f}s {status}")

    # ---- 5. side effects written to disk --------------------------------
    print("\n[5/5] side-effect files written")
    assert UNIVERSE_LATEST_FILE.exists(), "data/universe_latest.json not written"
    assert PIPELINE_STATUS_FILE.exists(), "data/pipeline_status.json not written"
    ul = json.loads(UNIVERSE_LATEST_FILE.read_text(encoding="utf-8"))
    ps = json.loads(PIPELINE_STATUS_FILE.read_text(encoding="utf-8"))
    assert ul.get("preset_name") == "liquid_momentum_core"
    assert ps.get("status") == "idle", f"status: {ps.get('status')}"
    print(f"  OK - universe_latest.json: preset={ul['preset_name']} "
          f"shortlist={ul['shortlist_size']}")
    print(f"  OK - pipeline_status.json: status={ps['status']} "
          f"workflow_id={ps['workflow_id']}")

    print("\n" + "=" * 70)
    print("ALL GREEN - workflow_engine is wired up correctly.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
