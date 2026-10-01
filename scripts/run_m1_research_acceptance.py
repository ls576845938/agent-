"""Bounded offline M1 proof using the existing immutable OKX/Qlib/factory paths.

No services, promotion builders, secrets or exchange endpoints. Output is a new
task-owned directory outside Git; never resume/overwrite or update any latest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not args.output.is_absolute() or output == ROOT or output.is_relative_to(ROOT) or output.exists():
        raise ValueError("new_absolute_external_output_required")
    output.mkdir(parents=True)
    from integrations.qlib_adapter.research_pipeline import run_research_pipeline, read_sealed_evidence
    from integrations.qlib_adapter.schemas import resolve_git_commit, write_json
    from backend.app.services.alpha_factory import AlphaFactoryService
    from quant_shared.alpha_factory.contracts import SAFETY

    # Both configured producers consume already published immutable files.
    # No actual network transport is allowed during this acceptance run.
    def no_network(*a, **k): raise AssertionError("M1 acceptance prohibits network connections")
    original_connect = socket.socket.connect
    socket.socket.connect = no_network
    qlib_root = output/"qlib_runs"
    report = {"source_head":resolve_git_commit(ROOT), "kind":"offline_research_integration", "status":"running", **SAFETY}
    try:
        receipt = run_research_pipeline({"profile_id":"okx_btc_trend_1h", "run_id":"m1-okx-qlib"},
            artifacts_root=qlib_root, progress=lambda **x: print(x["message"], flush=True))
        ordinary = read_sealed_evidence(qlib_root/"m1-okx-qlib")
        assert receipt["status"] == "completed" and ordinary["integrity_status"] == "passed"
        assert ordinary["trend_environment"]["status"] == "completed"
        report["qlib"] = {"receipt":receipt,"environment":ordinary["trend_environment"], "seal":ordinary["seal"]}
        print("Qlib sidecar sealed; starting one bounded factory campaign", flush=True)
        class Context:
            task_id = "m1-offline-factory"
            def update(self, **kwargs): print(kwargs.get("message", "factory"), flush=True)
        class Queue:
            def submit(self, *, job, **kwargs):
                result = job(Context())
                return {"task_id":Context.task_id,"status":"completed","result":result}
        service = AlphaFactoryService(root=output/"alpha_factory", qlib_root=qlib_root, queue=Queue())
        factory_receipt = service.submit({"run_id":"m1-okx-factory","profile_id":"okx_btc_trend_1h", "population":4,
            "generations":1,"max_features":3,"model_trials":1,"seed":17,"generators":["registered","template","genetic"]})
        campaign = service.get(factory_receipt["run_id"])
        assert campaign["status"] == "completed" and campaign["integrity_status"] == "passed"
        trials = []
        for root in sorted(qlib_root.iterdir()):
            if not root.is_dir() or not (root/"factory_trial.json").exists(): continue
            detail = read_sealed_evidence(root)
            assert detail["integrity_status"] == "passed" and detail["trend_environment"]["status"] == "completed", detail
            assert not detail["research_trace"]
            trials.append({"run_id":root.name,"environment":detail["trend_environment"],"seal":detail["seal"]})
        assert trials, "A zero-fit campaign cannot prove factory training integration"
        report.update(factory={"receipt":factory_receipt,"detail":campaign,"trials":trials},status="passed")
        print(f"Factory sealed {len(trials)} actual Qlib trials; research nomination is not permission", flush=True)
    except Exception as exc:
        report.update(status="blocked",error=type(exc).__name__+":"+str(exc))
        raise
    finally:
        socket.socket.connect = original_connect
        write_json(output/"m1_acceptance.json", report)
        inventory = {p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in output.rglob("*") if p.is_file()}
        write_json(output/"m1_inventory.json", {"source_head":report["source_head"],"files":inventory,**SAFETY})
        print(json.dumps({"status":report["status"],"source_head":report["source_head"],"files":len(inventory)},ensure_ascii=False),flush=True)


if __name__ == "__main__": main()
