from backend.app.services.btc_demo_runtime import _DurableOperatorOperationStore


def test_compound_start_failure_survives_durable_projection(tmp_path):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start",
        payload={},
        idempotency_key="diagnostic-regression-0001",
    )
    codes = (
        "okx_demo_fault_drill_runtime_root_writer_lock_unavailable",
        "okx_demo_startup_worker_thread_join_timed_out",
    )
    result = store.transition(
        operation.operation_id, state="timed_out", phase="timed_out",
        blockers=(";".join(codes),), result_present=True,
    )
    assert result.blocker_codes == tuple(sorted(codes))
    assert store.get(operation.operation_id).blocker_codes == tuple(sorted(codes))
    assert not any(result.safety_flags.values())


def test_malformed_diagnostic_does_not_become_empty_success(tmp_path):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start", payload={},
        idempotency_key="diagnostic-regression-0002",
    )
    result = store.transition(
        operation.operation_id, state="failed", phase="blocked",
        blockers=("not a valid code",), result_present=True,
    )
    assert result.state == "failed"
    assert result.blocker_codes == ("operator_diagnostic_code_invalid",)
    assert not any(result.safety_flags.values())
