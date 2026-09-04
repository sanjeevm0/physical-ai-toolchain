from __future__ import annotations

import json
import random
from collections import Counter

from remoter import autoremote

_CALL_COUNT = 100


def main() -> None:
    autoremote.start(False)

    from tests import remoter_test_fixture

    server_identity = remoter_test_fixture.MultiInstanceServerIdentity()
    random.seed(0)
    distribution = dict(
        sorted(
            Counter(
                server_identity.get_server_id()
                for _ in range(_CALL_COUNT)
            ).items()
        )
    )
    print(
        f"MULTIINSTANCE_ID_DISTRIBUTION={json.dumps(distribution, sort_keys=True)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
