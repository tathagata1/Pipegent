def z_score_calculator(value: float, mean: float, std_dev: float) -> float:
    if std_dev == 0:
        raise ValueError('std_dev cannot be zero')
    return round((value - mean) / std_dev, 4)
