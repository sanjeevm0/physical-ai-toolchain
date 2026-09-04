from __future__ import annotations

import concurrent.futures
import json
import os
import sys

from remoter import autoremote, remoter


def main() -> None:
    autoremote.start(False)

    from tests import remoter_test_fixture

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(remoter_test_fixture.add, value, 10)
            for value in (1, 2, 3)
        ]
        concurrent_results = [future.result(timeout=10) for future in futures]

    remote_error = None
    try:
        remoter_test_fixture.fail("expected remote failure")
    except remoter.RemoteExecutionError as error:
        remote_error = str(error)

    constructor_accumulator = remoter_test_fixture.Accumulator(10)
    constructor_initial_value = constructor_accumulator.get_value()
    constructor_added_value = constructor_accumulator.add(5)
    constructor_accumulator.value = 21
    constructor_assigned_value = constructor_accumulator.value
    constructor_accumulator.syncwithremote()

    factory_accumulator = remoter_test_fixture.create_accumulator(30)
    factory_initial_value = factory_accumulator.get_value()
    factory_added_value = factory_accumulator.add(4)
    factory_accumulator.syncwithremote()

    first_singleton = remoter_test_fixture.SingletonAccumulator(100)
    first_singleton_id = first_singleton.get_instance_id()
    first_singleton.add(5)
    second_singleton = remoter_test_fixture.SingletonAccumulator(999)
    second_singleton_id = second_singleton.get_instance_id()
    second_singleton_initial_value = second_singleton.get_value()
    second_singleton.add(5)

    first_server = sys.argv[1]
    second_server = sys.argv[2]
    class_key = "tests.remoter_test_fixture/ReplicatedAccumulator"

    constructor_replica = remoter_test_fixture.ReplicatedAccumulator(40)
    factory_replica = remoter_test_fixture.create_replicated_accumulator(70)
    bundle_replica = remoter_test_fixture.create_replicated_bundle(90)["accumulator"]
    second_server_replica = remoter_test_fixture.create_second_server_accumulator(120)
    constructor_initial_locations = sorted(constructor_replica.rmtinstances_rmt0bf)
    factory_initial_locations = sorted(factory_replica.rmtinstances_rmt0bf)
    bundle_initial_locations = sorted(bundle_replica.rmtinstances_rmt0bf)
    returned_constructor = constructor_replica.return_self()

    remoter.remoter.updateRunLoc(
        {
            class_key: {
                "locations": {
                    first_server: 1.0,
                    second_server: 0.0,
                }
            }
        }
    )
    constructor_first_value = constructor_replica.add(2)
    constructor_first_pid = constructor_replica.get_created_by_pid()
    factory_first_value = factory_replica.add(3)
    bundle_first_value = bundle_replica.add(4)

    remoter.remoter.updateRunLoc(
        {
            class_key: {
                "locations": {
                    first_server: 0.0,
                    second_server: 1.0,
                }
            }
        }
    )
    constructor_second_value = constructor_replica.get_value()
    constructor_second_pid = constructor_replica.get_created_by_pid()
    factory_second_value = factory_replica.get_value()
    bundle_second_value = bundle_replica.get_value()

    remoter.remoter.updateRunLoc(
        {class_key: {"locations": {first_server: 1.0}}}
    )
    constructor_after_removal = sorted(constructor_replica.rmtinstances_rmt0bf)
    factory_after_removal = sorted(factory_replica.rmtinstances_rmt0bf)
    bundle_after_removal = sorted(bundle_replica.rmtinstances_rmt0bf)

    remoter.remoter.updateRunLoc(
        {
            class_key: {
                "locations": {
                    first_server: 0.0,
                    second_server: 1.0,
                }
            }
        }
    )
    constructor_after_addition = sorted(constructor_replica.rmtinstances_rmt0bf)
    factory_after_addition = sorted(factory_replica.rmtinstances_rmt0bf)
    bundle_after_addition = sorted(bundle_replica.rmtinstances_rmt0bf)
    constructor_recreated_value = constructor_replica.get_value()
    factory_recreated_value = factory_replica.get_value()
    bundle_recreated_value = bundle_replica.get_value()

    result = {
        "add": remoter_test_fixture.add(7, 8),
        "multiply": remoter_test_fixture.multiply(6, 7),
        "concurrent": concurrent_results,
        "remote_error": remote_error,
        "client_pid": os.getpid(),
        "constructor_initial_value": constructor_initial_value,
        "constructor_added_value": constructor_added_value,
        "constructor_assigned_value": constructor_assigned_value,
        "constructor_synced_value": constructor_accumulator.__dict__["value"],
        "constructor_server_pid": constructor_accumulator.get_created_by_pid(),
        "factory_initial_value": factory_initial_value,
        "factory_added_value": factory_added_value,
        "factory_synced_value": factory_accumulator.__dict__["value"],
        "factory_server_pid": factory_accumulator.get_created_by_pid(),
        "distinct_remote_objects": (
            constructor_accumulator.uuid_rmt0bf != factory_accumulator.uuid_rmt0bf
        ),
        "singleton_same_id": first_singleton_id == second_singleton_id,
        "singleton_second_initial_value": second_singleton_initial_value,
        "singleton_shared_value": first_singleton.get_value(),
        "constructor_replica_initial_locations": constructor_initial_locations,
        "factory_replica_initial_locations": factory_initial_locations,
        "bundle_replica_initial_locations": bundle_initial_locations,
        "returned_constructor_is_canonical": returned_constructor is constructor_replica,
        "constructor_replica_first_value": constructor_first_value,
        "constructor_replica_first_pid": constructor_first_pid,
        "constructor_replica_second_value": constructor_second_value,
        "constructor_replica_second_pid": constructor_second_pid,
        "factory_replica_first_value": factory_first_value,
        "factory_replica_second_value": factory_second_value,
        "bundle_replica_first_value": bundle_first_value,
        "bundle_replica_second_value": bundle_second_value,
        "constructor_replica_after_removal": constructor_after_removal,
        "factory_replica_after_removal": factory_after_removal,
        "bundle_replica_after_removal": bundle_after_removal,
        "constructor_replica_after_addition": constructor_after_addition,
        "factory_replica_after_addition": factory_after_addition,
        "bundle_replica_after_addition": bundle_after_addition,
        "constructor_replica_recreated_value": constructor_recreated_value,
        "factory_replica_recreated_value": factory_recreated_value,
        "bundle_replica_recreated_value": bundle_recreated_value,
        "second_server_replica_locations": sorted(
            second_server_replica.rmtinstances_rmt0bf
        ),
        "second_server_replica_pid": second_server_replica.get_created_by_pid(),
        "second_server_replica_value": second_server_replica.get_value(),
    }
    print(f"REMOTER_TEST_RESULT={json.dumps(result, sort_keys=True)}", flush=True)


if __name__ == "__main__":
    main()
