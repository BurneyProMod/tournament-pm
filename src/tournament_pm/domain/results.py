from collections.abc import Sequence

from tournament_pm.domain.errors import InvalidBestOfError, InvalidGameSequenceError
from tournament_pm.domain.models import PlayerId


def wins_needed(best_of: int) -> int:
    if best_of < 1 or best_of % 2 == 0:
        raise InvalidBestOfError("best_of must be a positive odd number", best_of=best_of)
    return best_of // 2 + 1


def match_winner(
    best_of: int,
    game_winners: Sequence[PlayerId],
    player_one: PlayerId,
    player_two: PlayerId,
) -> PlayerId:
    """Validate a best-of-N game sequence and return the match winner.

    The sequence must end exactly when one player reaches the required wins:
    no unknown players, no games after the match is decided, no unfinished matches.
    """
    needed = wins_needed(best_of)
    wins = {player_one: 0, player_two: 0}

    for game, winner in enumerate(game_winners, start=1):
        if winner not in wins:
            raise InvalidGameSequenceError(
                f"Game {game} winner is not a player in this match", game=game, winner_id=winner
            )
        if needed in wins.values():
            raise InvalidGameSequenceError(
                f"Game {game} was recorded after the match was already decided", game=game
            )
        wins[winner] += 1

    leader = max(wins, key=wins.__getitem__)
    if wins[leader] < needed:
        raise InvalidGameSequenceError(
            f"Match is not decided: a player needs {needed} wins",
            needed=needed,
            player_one_wins=wins[player_one],
            player_two_wins=wins[player_two],
        )
    return leader
