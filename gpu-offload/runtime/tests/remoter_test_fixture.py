from __future__ import annotations

import os
import uuid


def add(left: int, right: int) -> int:
    return left + right


def multiply(left: int, right: int) -> int:
    return left * right


def fail(message: str) -> None:
    raise ValueError(message)


def create_accumulator(value: int) -> Accumulator:
    return Accumulator(value)


def create_replicated_accumulator(value: int) -> ReplicatedAccumulator:
    return ReplicatedAccumulator(value)


def create_replicated_bundle(value: int) -> dict[str, ReplicatedAccumulator]:
    return {"accumulator": ReplicatedAccumulator(value)}


def create_second_server_accumulator(value: int) -> SecondServerAccumulator:
    return SecondServerAccumulator(value)


class Accumulator:
    def __init__(self, value: int) -> None:
        self.value = value
        self.created_by_pid = os.getpid()

    def add(self, amount: int) -> int:
        self.value += amount
        return self.value

    def get_value(self) -> int:
        return self.value

    def get_created_by_pid(self) -> int:
        return self.created_by_pid


class SingletonAccumulator:
    def __init__(self, value: int) -> None:
        self.value = value
        self.instance_id = str(uuid.uuid4())

    def add(self, amount: int) -> int:
        self.value += amount
        return self.value

    def get_instance_id(self) -> str:
        return self.instance_id

    def get_value(self) -> int:
        return self.value


class ReplicatedAccumulator:
    def __init__(self, value: int) -> None:
        self.value = value
        self.created_by_pid = os.getpid()

    def add(self, amount: int) -> int:
        self.value += amount
        return self.value

    def get_created_by_pid(self) -> int:
        return self.created_by_pid

    def get_value(self) -> int:
        return self.value

    def return_self(self) -> ReplicatedAccumulator:
        return self


class SecondServerAccumulator:
    def __init__(self, value: int) -> None:
        self.value = value
        self.created_by_pid = os.getpid()

    def get_created_by_pid(self) -> int:
        return self.created_by_pid

    def get_value(self) -> int:
        return self.value
