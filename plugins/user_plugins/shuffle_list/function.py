import random
from typing import Any, List


def shuffle_list(items: List[Any]) -> List[Any]:
    shuffled = list(items)
    random.shuffle(shuffled)
    return shuffled
