from typing import ClassVar


class DomainError(Exception):
    """A broken tournament rule. `code` is stable and safe to expose to API clients."""

    code: ClassVar[str] = "DOMAIN_ERROR"

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class InvalidEloDeltaError(DomainError):
    code = "INVALID_ELO_DELTA"


class InvalidEloError(DomainError):
    code = "INVALID_ELO"


class InvalidBestOfError(DomainError):
    code = "INVALID_BEST_OF"


class InvalidGameSequenceError(DomainError):
    code = "INVALID_GAME_SEQUENCE"


class NotEnoughPlayersError(DomainError):
    code = "NOT_ENOUGH_PLAYERS"


class InvalidPlayerNameError(DomainError):
    code = "INVALID_PLAYER_NAME"


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class ConflictError(DomainError):
    """The request is valid but clashes with current state (wrong status, duplicate, ...)."""

    code = "CONFLICT"


class DuplicatePlayerNameError(ConflictError):
    code = "DUPLICATE_PLAYER_NAME"


class AlreadyEnteredError(ConflictError):
    code = "ALREADY_ENTERED"


class InvalidStateError(ConflictError):
    code = "INVALID_STATE"


class StaleVersionError(ConflictError):
    code = "STALE_VERSION"
