import pytest

from tournament_pm.domain.errors import InvalidPlayerNameError
from tournament_pm.domain.players import MAX_NAME_LENGTH, normalize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ada", "Ada"),
        ("  Ada   Lovelace  ", "Ada Lovelace"),
        ("O'Brien-Smith Jr.", "O'Brien-Smith Jr."),
        ("Zoë_99", "Zoë_99"),
        ("x" * MAX_NAME_LENGTH, "x" * MAX_NAME_LENGTH),
    ],
)
def test_valid_names_are_normalized(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "empty"),
        ("   \t ", "empty"),
        ("x" * (MAX_NAME_LENGTH + 1), "at most"),
        ("<script>", "only contain"),
        ("Robert'); DROP TABLE player;--", "only contain"),
    ],
)
def test_invalid_names_are_rejected(raw: str, message: str) -> None:
    with pytest.raises(InvalidPlayerNameError, match=message):
        normalize_name(raw)
