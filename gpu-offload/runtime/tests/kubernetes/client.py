from __future__ import annotations

import json
import random
import time
from collections import Counter
from typing import Any

from remoter import autoremote, remoter

_CLASS_KEY = "server_identity/MultiInstanceServerIdentity"
_INITIAL_CALL_COUNT = 100
_SCALED_CALL_COUNT = 1_000
_LOCATION_TIMEOUT_SECONDS = 180


def _wait_for_run_locations(expected: int) -> None:
    deadline = time.monotonic() + _LOCATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with remoter.remoter.loclock:
            runloc = remoter.remoter.runloc.get(_CLASS_KEY)
            choices = [] if runloc is None else runloc["choices"]
        if len(choices) >= expected:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {_CLASS_KEY} to discover {expected} locations")


def _wait_for_instances(instance: Any, expected: int) -> None:
    deadline = time.monotonic() + _LOCATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        instances = object.__getattribute__(instance, "rmtinstances_rmt0bf")
        if len(instances) >= expected:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {expected} remote instances")


def _sample(instance: Any, calls: int, seed: int) -> dict[str, int]:
    random.seed(seed)
    return dict(
        sorted(
            Counter(
                instance.get_server_id()
                for _ in range(calls)
            ).items()
        )
    )


def main() -> None:
    autoremote.start(False)

    from server_identity import MultiInstanceServerIdentity

    _wait_for_run_locations(1)
    identity = MultiInstanceServerIdentity()
    initial_distribution = _sample(identity, _INITIAL_CALL_COUNT, seed=0)
    print(
        f"INITIAL_ID_DISTRIBUTION={json.dumps(initial_distribution, sort_keys=True)}",
        flush=True,
    )

    _wait_for_instances(identity, 3)
    scaled_distribution = _sample(identity, _SCALED_CALL_COUNT, seed=1)
    print(
        f"SCALED_ID_DISTRIBUTION={json.dumps(scaled_distribution, sort_keys=True)}",
        flush=True,
    )

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
