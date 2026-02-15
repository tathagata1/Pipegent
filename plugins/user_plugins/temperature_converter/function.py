from typing import Literal

ALLOWED_UNITS = ("celsius", "fahrenheit", "kelvin")

def temperature_converter(value: float, from_unit: Literal["celsius", "fahrenheit", "kelvin"], to_unit: Literal["celsius", "fahrenheit", "kelvin"]) -> float:
    from_unit = from_unit.lower()
    to_unit = to_unit.lower()
    if from_unit not in ALLOWED_UNITS or to_unit not in ALLOWED_UNITS:
        raise ValueError("Unsupported temperature unit")

    celsius = _to_celsius(value, from_unit)
    result = _from_celsius(celsius, to_unit)
    return round(result, 4)

def _to_celsius(value: float, unit: str) -> float:
    if unit == "celsius":
        return value
    if unit == "fahrenheit":
        return (value - 32) * 5 / 9
    if unit == "kelvin":
        return value - 273.15
    raise ValueError("Invalid unit")

def _from_celsius(value: float, unit: str) -> float:
    if unit == "celsius":
        return value
    if unit == "fahrenheit":
        return (value * 9 / 5) + 32
    if unit == "kelvin":
        return value + 273.15
    raise ValueError("Invalid unit")
