CONVERSION = {
    ("centimeters", "inches"): 0.393701,
    ("inches", "centimeters"): 2.54,
}


def length_converter(value: float, from_unit: str, to_unit: str) -> float:
    key = (from_unit.lower(), to_unit.lower())
    if key not in CONVERSION:
        raise ValueError("Unsupported length conversion")
    return round(value * CONVERSION[key], 4)
