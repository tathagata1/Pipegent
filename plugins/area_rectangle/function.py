def area_rectangle(width: float, height: float) -> float:
    if width < 0 or height < 0:
        raise ValueError("width and height must be non-negative")
    return round(width * height, 4)
