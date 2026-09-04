from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from remoter import remoter, rmtconfigkube

_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
_RESULT_PREFIX = "REMOTER_TEST_RESULT="
_START_TIMEOUT_SECONDS = 10
_CLIENT_TIMEOUT_SECONDS = 30


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(process: subprocess.Popen[str], port: int, log_path: Path) -> None:
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log = log_path.read_text(encoding="utf-8")
            raise RuntimeError(f"remoter server exited with status {process.returncode}\n{log}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    log = log_path.read_text(encoding="utf-8")
    raise TimeoutError(f"remoter server did not listen on port {port}\n{log}")


def _start_server(config_path: Path, port: int, log_path: Path) -> subprocess.Popen[str]:
    env = _subprocess_env(config_path, port)
    env["SERVER"] = "true"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "remoter.autoremote"],
            cwd=_RUNTIME_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    _wait_for_port(process, port, log_path)
    return process


def _subprocess_env(config_path: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    python_path = env.get("PYTHONPATH")
    env.update(
        {
            "PRINTLOGLEVEL": "warning",
            "PYTHONPATH": str(_RUNTIME_ROOT) if not python_path else f"{_RUNTIME_ROOT}{os.pathsep}{python_path}",
            "PYTHONUNBUFFERED": "1",
            "REMOTER_CONFIG": str(config_path),
            "REMOTERHOST": "127.0.0.1",
            "REMOTERPORT": str(port),
        }
    )
    env.pop("SERVER", None)
    return env


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _write_config(
    config_path: Path,
    location_config_path: Path,
    first_server_port: int,
    second_server_port: int,
) -> None:
    first_server = f"127.0.0.1:{first_server_port}"
    second_server = f"127.0.0.1:{second_server_port}"
    config = {
        "configfile": str(location_config_path),
        "remoteclasses": [
            {
                "tests.remoter_test_fixture/Accumulator": {
                    "remoteloc": f"127.0.0.1:{second_server_port}",
                }
            },
            {
                "tests.remoter_test_fixture/SingletonAccumulator": {
                    "remoteloc": second_server,
                    "singleinstance": True,
                }
            },
            {
                "tests.remoter_test_fixture/ReplicatedAccumulator": {
                    "instantiateon": [first_server, second_server],
                }
            },
            {
                "tests.remoter_test_fixture/SecondServerAccumulator": {
                    "instantiateon": [second_server],
                }
            },
        ],
        "remotefuncs": [
            {
                "tests.remoter_test_fixture//add": {
                    "remoteloc": f"127.0.0.1:{first_server_port}",
                }
            },
            {
                "tests.remoter_test_fixture//multiply": {
                    "remoteloc": f"127.0.0.1:{second_server_port}",
                }
            },
            {
                "tests.remoter_test_fixture//fail": {
                    "remoteloc": f"127.0.0.1:{first_server_port}",
                }
            },
            {
                "tests.remoter_test_fixture//create_accumulator": {
                    "remoteloc": first_server,
                }
            },
            {
                "tests.remoter_test_fixture//create_replicated_accumulator": {
                    "remoteloc": first_server,
                }
            },
            {
                "tests.remoter_test_fixture//create_replicated_bundle": {
                    "remoteloc": first_server,
                }
            },
            {
                "tests.remoter_test_fixture//create_second_server_accumulator": {
                    "remoteloc": first_server,
                }
            },
        ],
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    location_config = {
        "tests.remoter_test_fixture/ReplicatedAccumulator": {
            "locations": {
                first_server: 0.5,
                second_server: 0.5,
            }
        }
    }
    location_config_path.write_text(
        yaml.safe_dump(location_config, sort_keys=False),
        encoding="utf-8",
    )


def _parse_result(output: str) -> dict[str, Any]:
    for line in output.splitlines():
        if line.startswith(_RESULT_PREFIX):
            return json.loads(line.removeprefix(_RESULT_PREFIX))
    raise AssertionError(f"client did not emit {_RESULT_PREFIX!r}\n{output}")


def test_get_keys_registers_every_instantiateon_server_label() -> None:
    config = {
        "remoteclasses": [
            {
                "tests.remoter_test_fixture/ReplicatedAccumulator": {
                    "serverlabels": ["stage-a=true", "stage-b=true"],
                }
            }
        ]
    }

    keys = rmtconfigkube.get_keys(config)

    expected = {"tests.remoter_test_fixture/ReplicatedAccumulator"}
    assert keys == {
        "stage-a=true": expected,
        "stage-b=true": expected,
    }


def test_createconfig_combines_locations_for_replicated_classes() -> None:
    keys = {
        "stage-a=true": {"module/Replicated"},
        "stage-b=true": {"module/Replicated"},
    }
    locations = {
        "stage-a=true": {"10.0.0.1:9000"},
        "stage-b=true": {"10.0.0.2:9000"},
    }

    config = rmtconfigkube.createconfig(keys, locations)

    assert config == {
        "module/Replicated": {
            "locations": {
                "10.0.0.1:9000": 0.5,
                "10.0.0.2:9000": 0.5,
            }
        }
    }


def test_connection_loss_removes_only_the_failed_replica() -> None:
    class ReplicatedProxy:
        instantiateon_rmt0bf = ("first", "second")

    first_uuid = uuid.uuid4()
    second_uuid = uuid.uuid4()
    first_loc = "tcp://127.0.0.1:8000"
    second_loc = "tcp://127.0.0.1:9000"
    proxy = ReplicatedProxy()
    proxy.failed_rmt0bf = False
    proxy.uuid_rmt0bf = second_uuid
    proxy.rmtloc_rmt0bf = second_loc
    proxy.rmtinstances_rmt0bf = {
        first_loc: SimpleNamespace(uuid_rmt0bf=first_uuid, rmtloc_rmt0bf=first_loc),
        second_loc: SimpleNamespace(uuid_rmt0bf=second_uuid, rmtloc_rmt0bf=second_loc),
    }

    runtime = remoter.Remoter.createemptyinstance()
    runtime.connlock = threading.Lock()
    runtime.multiLocationLock = threading.RLock()
    runtime.multiLocationObjectsByUUID = {second_uuid: proxy}
    runtime.remotedClassesConn = {second_uuid: object()}
    runtime.events = {}
    runtime.conns = {
        second_loc: {
            "alive": True,
            "classes": {second_uuid: object()},
            "fnuid": set(),
            "lock": threading.Lock(),
        }
    }

    runtime.closeclientconn(second_loc, SimpleNamespace(), "unused")

    assert proxy.failed_rmt0bf is False
    assert proxy.uuid_rmt0bf == first_uuid
    assert proxy.rmtloc_rmt0bf == first_loc
    assert proxy.rmtinstances_rmt0bf == {
        first_loc: SimpleNamespace(uuid_rmt0bf=first_uuid, rmtloc_rmt0bf=first_loc)
    }
    assert second_uuid not in runtime.multiLocationObjectsByUUID
    assert second_uuid not in runtime.remotedClassesConn


def test_remoter_routes_functions_and_classes_across_processes(tmp_path: Path) -> None:
    first_server_port = _free_port()
    second_server_port = _free_port()
    client_port = _free_port()
    config_path = tmp_path / "remote.yaml"
    location_config_path = tmp_path / "locations.yaml"
    _write_config(
        config_path,
        location_config_path,
        first_server_port,
        second_server_port,
    )
    first_server = f"127.0.0.1:{first_server_port}"
    second_server = f"127.0.0.1:{second_server_port}"

    servers: list[subprocess.Popen[str]] = []
    try:
        servers.append(_start_server(config_path, first_server_port, tmp_path / "server-1.log"))
        servers.append(_start_server(config_path, second_server_port, tmp_path / "server-2.log"))

        client = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.remoter_test_client",
                f"tcp://{first_server}",
                f"tcp://{second_server}",
            ],
            cwd=_RUNTIME_ROOT,
            env=_subprocess_env(config_path, client_port),
            capture_output=True,
            text=True,
            timeout=_CLIENT_TIMEOUT_SECONDS,
            check=False,
        )

        assert client.returncode == 0, client.stdout + client.stderr
        result = _parse_result(client.stdout)
        assert result == {
            "add": 15,
            "multiply": 42,
            "concurrent": [11, 12, 13],
            "remote_error": result["remote_error"],
            "client_pid": result["client_pid"],
            "constructor_initial_value": 10,
            "constructor_added_value": 15,
            "constructor_assigned_value": 21,
            "constructor_synced_value": 21,
            "constructor_server_pid": result["constructor_server_pid"],
            "factory_initial_value": 30,
            "factory_added_value": 34,
            "factory_synced_value": 34,
            "factory_server_pid": result["factory_server_pid"],
            "distinct_remote_objects": True,
            "singleton_same_id": True,
            "singleton_second_initial_value": 105,
            "singleton_shared_value": 110,
            "constructor_replica_initial_locations": sorted(
                [f"tcp://{first_server}", f"tcp://{second_server}"]
            ),
            "factory_replica_initial_locations": sorted(
                [f"tcp://{first_server}", f"tcp://{second_server}"]
            ),
            "bundle_replica_initial_locations": sorted(
                [f"tcp://{first_server}", f"tcp://{second_server}"]
            ),
            "returned_constructor_is_canonical": True,
            "constructor_replica_first_value": 42,
            "constructor_replica_first_pid": result["factory_server_pid"],
            "constructor_replica_second_value": 40,
            "constructor_replica_second_pid": result["constructor_server_pid"],
            "factory_replica_first_value": 73,
            "factory_replica_second_value": 70,
            "bundle_replica_first_value": 94,
            "bundle_replica_second_value": 90,
            "constructor_replica_after_removal": [f"tcp://{first_server}"],
            "factory_replica_after_removal": [f"tcp://{first_server}"],
            "bundle_replica_after_removal": [f"tcp://{first_server}"],
            "constructor_replica_after_addition": sorted(
                [f"tcp://{first_server}", f"tcp://{second_server}"]
            ),
            "factory_replica_after_addition": sorted(
                [f"tcp://{first_server}", f"tcp://{second_server}"]
            ),
            "bundle_replica_after_addition": sorted(
                [f"tcp://{first_server}", f"tcp://{second_server}"]
            ),
            "constructor_replica_recreated_value": 40,
            "factory_replica_recreated_value": 70,
            "bundle_replica_recreated_value": 90,
            "second_server_replica_locations": [f"tcp://{second_server}"],
            "second_server_replica_pid": result["constructor_server_pid"],
            "second_server_replica_value": 120,
        }
        assert "ValueError" in result["remote_error"]
        assert "expected remote failure" in result["remote_error"]
        assert result["constructor_server_pid"] != result["client_pid"]
        assert result["factory_server_pid"] != result["client_pid"]
        assert result["constructor_server_pid"] != result["factory_server_pid"]
    finally:
        for server in reversed(servers):
            _stop_process(server)
