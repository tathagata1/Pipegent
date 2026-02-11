from typing import Callable


def calculator(a: float, b: float, operation: str) -> float:
    if operation == "add":
        return a + b
    if operation == "subtract":
        return a - b
    if operation == "multiply":
        return a * b
    if operation == "divide":
        return a / b
    raise ValueError("Invalid operation")


def register() -> tuple[str, Callable]:
    return "calculator", calculator