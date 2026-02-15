from datetime import datetime


def date_difference(start_date: str, end_date: str, fmt: str = '%Y-%m-%d') -> int:
    start = datetime.strptime(start_date, fmt)
    end = datetime.strptime(end_date, fmt)
    return (end - start).days
