import re

from tournament_pm.domain.errors import InvalidPlayerNameError

MAX_NAME_LENGTH = 50
_ALLOWED = re.compile(r"[\w .'\-]+")  # letters/digits/underscore (any script), space, . ' -


def normalize_name(raw: str) -> str:
    """Trim, collapse inner whitespace and check the allowed characters and length."""
    name = " ".join(raw.split())
    if not name:
        raise InvalidPlayerNameError("Name must not be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidPlayerNameError(
            f"Name must be at most {MAX_NAME_LENGTH} characters", length=len(name)
        )
    if not _ALLOWED.fullmatch(name):
        raise InvalidPlayerNameError(
            "Name may only contain letters, digits, spaces and . ' - _", name=name
        )
    return name
