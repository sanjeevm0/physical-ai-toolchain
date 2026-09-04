---
title: Remoter Runtime
description: RPC-like Python function and class offloading between processes
ms.date: 2026-09-03
ms.topic: reference
---

<!-- cspell:ignore msgtcp msgudp msgunix noremotefuncs remoteableon -->
<!-- cspell:ignore remoteableserver REMOTERHOST REMOTERSOCK REMOTEPORT -->
<!-- cspell:ignore rmtclass rmtconfig rmtconfigkube syncwithremote taskkey -->
<!-- cspell:ignore deallocates functype instantiateon -->

The remoter runtime redirects selected Python function calls and class operations
to another process while preserving the application-facing API. It supports direct
execution, in-process queues, TCP, UDP, and Unix domain sockets. Configuration-driven
decoration supports applications that cannot modify upstream code.

## 🚀 Quick Start

Install the runtime and test dependencies:

```bash
cd gpu-offload/runtime
uv sync --extra test
```

Run the automated unit and multiprocess integration tests:

```bash
cd gpu-offload
mise run e-runtime-10-test
```

The integration test starts two server processes and one client process on
ephemeral localhost ports. The client verifies routing, concurrent calls, remote
exceptions, singleton classes, both class creation modes, methods, attributes,
and state synchronization.

## 🏗️ Architecture

| Component | Purpose |
| --------- | ------- |
| `autoremote.py` | Load configuration and apply decorators |
| `remoter.py` | Dispatch calls and track tasks and objects |
| `rmtclass.py` | Create client-side class proxies |
| `safe_codec.py` | Encode bounded MessagePack envelopes |
| `class2dict.py` | Convert objects and tensors to wire values |
| `msgtcp.py` | Provide the default TCP transport |
| `msgudp.py` | Provide optional UDP transport |
| `msgunix.py` | Provide Unix domain socket transport |
| `rmtconfig.py` | Watch dynamic location configuration |
| `rmtconfigkube.py` | Discover server locations from Kubernetes |

Each process runs a `Remoter` instance. Client wrappers serialize a call
description, send it to the selected location, wait for the result, and
reconstruct the returned value or exception. Servers validate each target
against the allowed function set before execution.

Remote class construction creates the authoritative object on the selected server.
The client retains a proxy carrying the remote object UUID and location. Method
calls and non-local attribute operations use the authoritative server object.
Call `syncwithremote()` to copy its current serializable state into the proxy.

## ⚙️ Configuration

Set `REMOTER_CONFIG` to a YAML file that identifies remote functions, remote
classes, and their locations:

```yaml
remoteclasses:
  - application.models/Policy:
      remoteloc: 127.0.0.1:9000

remotefuncs:
  - application.inference//predict:
      remoteloc: 127.0.0.1:9000
      functype: threadpooltask
      timeout: 30
```

Target paths use slash-separated forms:

| Target | Format | Example |
| ------ | ------ | ------- |
| Module function | `module//function` | `application.inference//predict` |
| Class | `module/ClassName` | `application.models/Policy` |
| Method | `module/Class/method` | `application.models/Policy/predict` |

Common target parameters:

| Parameter | Purpose |
| --------- | ------- |
| `remoteloc` | Set the fixed destination |
| `taskkey` | Overrides the routing key for a configured function |
| `functype` | Select the thread, pool, or process execution mode |
| `timeout` | Limits how long the caller waits for completion |
| `singleinstance` | Reuses one server-side function result or class instance |
| `instantiateon` | Create one class instance at every listed location |
| `noremotefuncs` | Keep selected configured class methods local |
| `remoteableserver` | Allow server-side methods to route again |
| `remoteableon` | Enables server-side remoting only at selected locations |

Environment variables override runtime endpoints and process roles:

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `REMOTER_CONFIG` | Path to the remote target configuration | `remote.yaml` |
| `SERVER` | Marks a process as a server when set to `true` | `false` |
| `REMOTERHOST` | Listener address | `0.0.0.0` |
| `REMOTERPORT` | Listener port | `9000` |
| `REMOTERSOCK` | Unix domain socket path | unset |
| `REMOTELOC` | Default remote destination | unset |
| `REMOTEPORT` | Replace destination ports during routing | `0` |
| `USE_TCP` | Enables TCP transport | `true` |
| `USE_UDP` | Enables UDP transport | `false` |

Configuration values can reference environment variables using `${NAME}`.

## 📦 Integration Modes

### Configuration-driven decoration

Use `autoremote` when offloading existing code without adding decorators:

```bash
# Server
SERVER=true \
REMOTER_CONFIG=./remote.yaml \
REMOTERPORT=9000 \
uv run python -m remoter.autoremote
```

Start the client runtime before importing or invoking configured targets:

```python
from __future__ import annotations

from remoter import autoremote

autoremote.start(False)
```

The `sitecustomize.py` integration can initialize the runtime automatically when
it is included in an application image. The GPU offload examples use this mode
so upstream application code remains unchanged.

### Decorator-driven remoting

Use decorators when the application owns the target source:

```python
from __future__ import annotations

from remoter import remoter, rmtclass


@remoter.remotetask("inference", "threadpooltask", timeout=30)
def predict(observation: list[float]) -> list[float]:
    return observation


@rmtclass.remotedclass(taskname="models/Policy")
class Policy:
    def __init__(self, name: str) -> None:
        self.name = name

    def predict(self, observation: list[float]) -> list[float]:
        return observation
```

Initialize the `Remoter` before invoking decorated targets. Use
`remoter.add_args()` and `remoter.initRemoterFromArgs()` for command-line
applications, or call `remoter.initRemoter()` directly.

### Remote class creation

Create a configured remote class with normal constructor syntax:

```python
policy = Policy("pick-and-place")
```

The client-side `__init__` wrapper creates the authoritative class instance on
the class's configured remote location and retains a local proxy.

Alternatively, return the configured class from a remoted factory function:

```python
def create_policy(name: str) -> Policy:
    return Policy(name)


policy = create_policy("pick-and-place")
```

The factory executes at its configured location. The returned class is stored
there and converted into a proxy before the result reaches the client. This
allows the factory to select constructor inputs or build nested remote objects
without performing construction in the client process.

### Multi-location class instances

Set `instantiateon` on a remote class to create one server-side instance at each
configured location:

```yaml
remoteclasses:
  - application.models/Policy:
      instantiateon:
        - 10.0.0.10:9000
        - 10.0.0.11:9000
```

Both supported creation forms replicate the class:

```python
constructor_policy = Policy("pick-and-place")
factory_policy = create_policy("pick-and-place")
```

Factory results can contain the class directly or inside lists, tuples, and
dictionaries. The client keeps one logical proxy with a per-location object
stub. Each method or attribute operation selects an active location using the
class routing weights, then sends the location-specific object UUID.

The location configuration overrides the initial `instantiateon` list after it
loads. Adding a location replays the saved constructor or factory call there.
Removing a location deallocates its server object and removes its cached stub.
Calls only select active locations that have a successfully created instance.

> [!IMPORTANT]
> Replicas have independent state. A mutation routed to one location does not
> update the other instances. Use multi-location classes for immutable models,
> stateless services, or classes that synchronize state externally.

`instantiateon` and `singleinstance` cannot be enabled on the same class.
Multi-location creation currently requires synchronous constructors and factory
functions.

## 🔒 Serialization and Errors

The wire codec accepts bounded primitive collections, UUID values, registered
adapter types, serialized class values, and supported PyTorch tensors.
Unsupported values fail serialization instead of falling back to pickle.

Server exceptions return as wire-safe descriptors and are raised in the client
as `RemoteExecutionError`. Remote `AttributeError` values remain
`AttributeError`, preserving `hasattr()` and normal attribute fallback.

## 🔍 Test Layout

| File | Coverage |
| ---- | -------- |
| `test_safe_codec.py` | Codec, tensors, limits, and errors |
| `test_remoter_integration.py` | Routing, factories, replicas, and singletons |
| `remoter_test_fixture.py` | Shared remote functions and classes |
| `remoter_test_client.py` | Isolated client assertions |

Run only the multiprocess test while developing transport or proxy behavior:

```bash
cd gpu-offload/runtime
uv run --extra test pytest tests/test_remoter_integration.py -v
```

## 🔗 Related Documentation

- [GPU offload overview](../README.md)
- [Remote specification schema](../specifications/remote-spec-schema.md)
- [First-run example](../examples/first-run/README.md)
