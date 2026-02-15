CONVERSION_FACTORS = {
    ("kilometers", "miles"): 0.621371,
    ("miles", "kilometers"): 1.60934,
    ("meters", "feet"): 3.28084,
    ("feet", "meters"): 0.3048,
}

def distance_converter(value: float, from_unit: str, to_unit: str) -> float:
    key = (from_unit.lower(), to_unit.lower())
    if key not in CONVERSION_FACTORS:
        raise ValueError("Unsupported conversion pair")
    result = value * CONVERSION_FACTORS[key]
    return round(result, 4)
