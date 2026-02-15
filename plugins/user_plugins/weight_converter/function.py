CONVERSION = {
    ("kilograms", "pounds"): 2.20462,
    ("pounds", "kilograms"): 0.453592,
}


def weight_converter(value: float, from_unit: str, to_unit: str) -> float:
    key = (from_unit.lower(), to_unit.lower())
    if key not in CONVERSION:
        raise ValueError("Unsupported weight conversion")
    return round(value * CONVERSION[key], 4)
