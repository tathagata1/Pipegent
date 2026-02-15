from typing import Dict, Union

BMI_CATEGORIES = [
    (18.5, "underweight"),
    (24.9, "normal"),
    (29.9, "overweight"),
]

def bmi_calculator(weight_kg: float, height_cm: float) -> Dict[str, Union[float, str]]:
    if height_cm <= 0:
        raise ValueError("height_cm must be positive")
    if weight_kg <= 0:
        raise ValueError("weight_kg must be positive")

    height_m = height_cm / 100
    bmi = weight_kg / (height_m ** 2)
    bmi = round(bmi, 2)

    if bmi < BMI_CATEGORIES[0][0]:
        category = BMI_CATEGORIES[0][1]
    elif bmi <= BMI_CATEGORIES[1][0]:
        category = BMI_CATEGORIES[1][1]
    elif bmi <= BMI_CATEGORIES[2][0]:
        category = BMI_CATEGORIES[2][1]
    else:
        category = "obese"

    return {"bmi": bmi, "category": category}
