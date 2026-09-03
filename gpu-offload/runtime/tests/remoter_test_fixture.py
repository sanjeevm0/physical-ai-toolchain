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
