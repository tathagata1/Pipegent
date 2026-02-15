CONVERSION = {
    ("kmh", "mph"): 0.621371,
    ("mph", "kmh"): 1.60934,
}


def speed_converter(value: float, from_unit: str, to_unit: str) -> float:
    key = (from_unit.lower(), to_unit.lower())
    if key not in CONVERSION:
        raise ValueError("Unsupported speed conversion")
    return round(value * CONVERSION[key], 4)
