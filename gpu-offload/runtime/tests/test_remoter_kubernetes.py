from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
import yaml

_TEST_ROOT = Path(__file__).resolve().parent / "kubernetes"
_NAMESPACE = "gpu-offload-remoter-scaling-test"
_CLIENT_DEPLOYMENT = "remoter-scaling-client"
_SERVER_DEPLOYMENT = "remoter-scaling-client-remote-server-workers"
_INITIAL_PREFIX = "INITIAL_ID_DISTRIBUTION="
_SCALED_PREFIX = "SCALED_ID_DISTRIBUTION="
_TIMEOUT_SECONDS = 180

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_KUBERNETES_TESTS") != "true",
    reason="Kubernetes integration tests require RUN_KUBERNETES_TESTS=true",
)


def _kubectl(context: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", "--context", context, *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _wait_for_deployment(context: str, deployment: str) -> None:
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = _kubectl(
            context,
            "get",
            "deployment",
            deployment,
            "--namespace",
            _NAMESPACE,
            "--output",
            "name",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for deployment/{deployment}")


def _wait_for_log_distribution(context: str, prefix: str) -> dict[str, int]:
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    latest_logs = ""
    while time.monotonic() < deadline:
        result = _kubectl(
            context,
            "logs",
            f"deployment/{_CLIENT_DEPLOYMENT}",
            "--namespace",
            _NAMESPACE,
            check=False,
        )
        latest_logs = result.stdout + result.stderr
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                return json.loads(line.removeprefix(prefix))
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {prefix!r} in client logs:\n{latest_logs}")


def _deployment_replicas(context: str, deployment: str) -> tuple[int, int]:
    result = _kubectl(
        context,
        "get",
        "deployment",
        deployment,
        "--namespace",
        _NAMESPACE,
        "--output",
        "json",
    )
    payload = json.loads(result.stdout)
    return payload["spec"]["replicas"], payload.get("status", {}).get("availableReplicas", 0)


def _set_server_replicas(context: str, replicas: int) -> None:
    result = _kubectl(
        context,
        "get",
        "configmap",
        "remoter-scaling-test",
        "--namespace",
        _NAMESPACE,
        "--output",
        "json",
    )
    configmap = json.loads(result.stdout)
    remote_config = yaml.safe_load(configmap["data"]["remote.yaml"])
    remote_config["serverstages"][0]["serverreplicas"] = replicas
    patch = {
        "data": {
            "remote.yaml": yaml.safe_dump(remote_config, sort_keys=False),
        }
    }
    _kubectl(
        context,
        "patch",
        "configmap",
        "remoter-scaling-test",
        "--namespace",
        _NAMESPACE,
        "--type",
        "merge",
        "--patch",
        json.dumps(patch),
    )


def test_multiinstance_distribution_updates_after_kubernetes_scale() -> None:
    context = os.environ["KUBERNETES_TEST_CONTEXT"]
    _kubectl(context, "delete", "namespace", _NAMESPACE, "--ignore-not-found=true", "--wait=true")
    try:
        _kubectl(context, "create", "namespace", _NAMESPACE)
        _kubectl(
            context,
            "apply",
            "--namespace",
            _NAMESPACE,
            "--filename",
            str(_TEST_ROOT / "workload.yaml"),
        )

        _wait_for_deployment(context, _SERVER_DEPLOYMENT)
        _kubectl(
            context,
            "rollout",
            "status",
            f"deployment/{_SERVER_DEPLOYMENT}",
            "--namespace",
            _NAMESPACE,
            f"--timeout={_TIMEOUT_SECONDS}s",
        )
        _kubectl(
            context,
            "rollout",
            "status",
            f"deployment/{_CLIENT_DEPLOYMENT}",
            "--namespace",
            _NAMESPACE,
            f"--timeout={_TIMEOUT_SECONDS}s",
        )

        assert _deployment_replicas(context, _SERVER_DEPLOYMENT) == (1, 1)
        initial_distribution = _wait_for_log_distribution(context, _INITIAL_PREFIX)
        print(f"Initial server ID distribution: {initial_distribution}")
        assert list(initial_distribution.values()) == [100]

        _set_server_replicas(context, 3)
        _kubectl(
            context,
            "scale",
            f"deployment/{_SERVER_DEPLOYMENT}",
            "--namespace",
            _NAMESPACE,
            "--replicas=3",
        )
        _kubectl(
            context,
            "rollout",
            "status",
            f"deployment/{_SERVER_DEPLOYMENT}",
            "--namespace",
            _NAMESPACE,
            f"--timeout={_TIMEOUT_SECONDS}s",
        )

        assert _deployment_replicas(context, _SERVER_DEPLOYMENT) == (3, 3)
        scaled_distribution = _wait_for_log_distribution(context, _SCALED_PREFIX)
        print(f"Scaled server ID distribution: {scaled_distribution}")
        assert len(scaled_distribution) == 3
        assert sum(scaled_distribution.values()) == 1_000
        assert all(280 <= count <= 380 for count in scaled_distribution.values())
    finally:
        _kubectl(context, "delete", "namespace", _NAMESPACE, "--ignore-not-found=true", "--wait=true", check=False)
