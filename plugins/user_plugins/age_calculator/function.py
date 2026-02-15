from datetime import date, datetime


def age_calculator(birthdate: str, fmt: str = '%Y-%m-%d') -> int:
    birth = datetime.strptime(birthdate, fmt).date()
    today = date.today()
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    if years < 0:
        raise ValueError('birthdate cannot be in the future')
    return years
