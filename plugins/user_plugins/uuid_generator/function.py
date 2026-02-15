import uuid
from typing import List

def uuid_generator(count: int = 1) -> List[str]:
    if count <= 0 or count > 20:
        raise ValueError("count must be between 1 and 20")
    return [str(uuid.uuid4()) for _ in range(count)]
