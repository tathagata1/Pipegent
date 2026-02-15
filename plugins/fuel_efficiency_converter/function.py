def fuel_efficiency_converter(value: float, from_unit: str, to_unit: str) -> float:
    from_unit = from_unit.lower()
    to_unit = to_unit.lower()
    if from_unit == to_unit:
        return round(value, 4)
    if from_unit == "mpg" and to_unit == "l_per_100km":
        return round(235.214583 / value, 4)
    if from_unit == "l_per_100km" and to_unit == "mpg":
        return round(235.214583 / value, 4)
    raise ValueError("Unsupported fuel efficiency conversion")
