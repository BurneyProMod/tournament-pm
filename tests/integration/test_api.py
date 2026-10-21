"""The REST API end to end, over HTTP, against real Postgres."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tournament_pm.db.session import SessionFactory
from tournament_pm.main import create_app


@pytest.fixture
def client(factory: SessionFactory) -> TestClient:
    return TestClient(create_app(factory))


def create_players(client: TestClient, elos: list[int], prefix: str = "Player") -> list[int]:
    ids = []
    for index, elo in enumerate(elos, start=1):
        response = client.post("/players", json={"name": f"{prefix} {index}", "elo": elo})
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    return ids


def create_started_tournament(client: TestClient, elos: list[int]) -> tuple[int, dict[str, Any]]:
    tournament_id = client.post("/tournaments", json={"name": "Cup", "best_of": 3}).json()["id"]
    for player_id in create_players(client, elos):
        client.post(f"/tournaments/{tournament_id}/entrants", json={"player_id": player_id})
    round_one = client.post(f"/tournaments/{tournament_id}/start").json()
    return tournament_id, round_one


def assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()["error"]
    assert body["code"] == code
    assert body["message"]
    return body


# --- The complete workflow ------------------------------------------------------------


def test_complete_tournament_workflow(client: TestClient) -> None:
    # 1. Register players.
    elos = [1500, 1400, 1300, 1200, 1100, 1000, 900]  # odd count: one BYE per round
    player_ids = create_players(client, elos)
    starting_elo = dict(zip(player_ids, elos, strict=True))

    # 2. Create a best-of-3 tournament and enter everyone.
    response = client.post(
        "/tournaments", json={"name": "Friday Swiss", "best_of": 3, "default_elo_delta": 20}
    )
    assert response.status_code == 201
    assert response.headers["Location"] == f"/tournaments/{response.json()['id']}"
    tournament_id = response.json()["id"]
    for player_id in player_ids:
        entry = client.post(f"/tournaments/{tournament_id}/entrants", json={"player_id": player_id})
        assert entry.status_code == 201

    # 3. Start: seeds come from Elo and round 1 is paired top half vs bottom half.
    response = client.post(f"/tournaments/{tournament_id}/start")
    assert response.status_code == 201
    current = response.json()
    first_pairs = [(m["player_one_id"], m["player_two_id"]) for m in current["matches"]]
    p = player_ids
    assert first_pairs == [(p[0], p[3]), (p[1], p[4]), (p[2], p[5]), (p[6], None)]
    entrants = client.get(f"/tournaments/{tournament_id}/entrants").json()
    assert [(e["player_id"], e["seed"]) for e in entrants] == [
        (player_id, seed) for seed, player_id in enumerate(p, start=1)
    ]
    tournament = client.get(f"/tournaments/{tournament_id}").json()
    assert (tournament["status"], tournament["rounds_planned"]) == ("active", 3)

    # 4. Play every round: report each match, then generate the next round.
    seen_pairs: set[frozenset[int]] = set()
    byes: list[int] = []
    for round_number in range(1, tournament["rounds_planned"] + 1):
        assert current["number"] == round_number
        for match in current["matches"]:
            if match["outcome"] == "bye":
                byes.append(match["player_one_id"])
                continue
            pair = frozenset((match["player_one_id"], match["player_two_id"]))
            assert pair not in seen_pairs, "no rematches"
            seen_pairs.add(pair)
            # Higher seed wins 2-1 after dropping game one.
            winner, loser = match["player_one_id"], match["player_two_id"]
            response = client.put(
                f"/matches/{match['id']}/result",
                json={"game_winners": [loser, winner, winner], "version": match["version"]},
            )
            assert response.status_code == 200, response.text
            assert (response.json()["outcome"], response.json()["winner_id"]) == ("played", winner)

        response = client.post(f"/tournaments/{tournament_id}/rounds")
        if round_number < tournament["rounds_planned"]:
            assert response.status_code == 201, response.text
            current = response.json()
        else:
            assert_error(response, 409, "INVALID_STATE")  # all planned rounds played

    assert len(byes) == len(set(byes)), "nobody gets a second BYE"

    # 5. Standings: points first, Elo moved by exactly ±20 per played match, zero-sum overall.
    standings = client.get(f"/tournaments/{tournament_id}/standings").json()
    assert [s["rank"] for s in standings] == sorted(s["rank"] for s in standings)
    assert [s["points"] for s in standings] == sorted(
        (s["points"] for s in standings), reverse=True
    )
    assert sum(s["points"] for s in standings) == 3 * 4  # 3 decided matches + 1 BYE per round
    assert sum(s["elo"] for s in standings) == sum(elos)
    for row in standings:
        assert (row["elo"] - starting_elo[row["player_id"]]) % 20 == 0

    leader = standings[0]
    player = client.get(f"/players/{leader['player_id']}").json()
    assert player["elo"] == leader["elo"]


# --- Contract details -----------------------------------------------------------------


def test_create_player_returns_201_with_location(client: TestClient) -> None:
    response = client.post("/players", json={"name": "  Ada   Lovelace "})

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["elo"]) == ("Ada Lovelace", 1000)
    assert response.headers["Location"] == f"/players/{body['id']}"


def test_list_players_hides_archived_by_default(client: TestClient) -> None:
    keep, retire = create_players(client, [1200, 1100])
    assert client.delete(f"/players/{retire}").status_code == 200

    assert [p["id"] for p in client.get("/players").json()] == [keep]
    everyone = client.get("/players", params={"include_archived": True}).json()
    assert {p["id"] for p in everyone} == {keep, retire}


def test_unknown_resources_are_404(client: TestClient) -> None:
    assert_error(client.get("/players/999"), 404, "NOT_FOUND")
    assert_error(client.get("/tournaments/999/rounds/1"), 404, "NOT_FOUND")
    assert_error(
        client.put("/matches/999/result", json={"game_winners": [1], "version": 0}),
        404,
        "NOT_FOUND",
    )


def test_duplicate_player_name_is_409(client: TestClient) -> None:
    client.post("/players", json={"name": "Ada"})

    error = assert_error(
        client.post("/players", json={"name": "ADA"}), 409, "DUPLICATE_PLAYER_NAME"
    )
    assert error["details"] == {"name": "ADA"}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"elo": 1000}, "body.name"),
        ({"name": "Ada", "elo": -5}, "body.elo"),
        ({"name": "Ada", "elo": "lots"}, "body.elo"),
    ],
)
def test_malformed_requests_are_422_with_field_errors(
    client: TestClient, payload: dict[str, object], field: str
) -> None:
    error = assert_error(client.post("/players", json=payload), 422, "VALIDATION_ERROR")

    assert field in [e["field"] for e in error["details"]["errors"]]


def test_domain_rule_violations_are_422(client: TestClient) -> None:
    assert_error(client.post("/players", json={"name": "<script>"}), 422, "INVALID_PLAYER_NAME")
    assert_error(
        client.post("/tournaments", json={"name": "Cup", "best_of": 2}), 422, "INVALID_BEST_OF"
    )


def test_invalid_game_sequence_is_422(client: TestClient) -> None:
    _, round_one = create_started_tournament(client, [1000, 1000])
    match = round_one["matches"][0]
    p1, p2 = match["player_one_id"], match["player_two_id"]

    error = assert_error(
        client.put(
            f"/matches/{match['id']}/result", json={"game_winners": [p1, p1, p2], "version": 0}
        ),
        422,
        "INVALID_GAME_SEQUENCE",
    )
    assert error["details"] == {"game": 3}


def test_stale_version_is_409_and_same_result_retry_is_200(client: TestClient) -> None:
    _, round_one = create_started_tournament(client, [1000, 1000])
    match = round_one["matches"][0]
    url = f"/matches/{match['id']}/result"
    p1, p2 = match["player_one_id"], match["player_two_id"]

    first = client.put(url, json={"game_winners": [p1, p1], "version": 0})
    retry = client.put(url, json={"game_winners": [p1, p1], "version": 0})
    conflict = client.put(url, json={"game_winners": [p2, p2], "version": 0})

    assert first.status_code == retry.status_code == 200
    assert retry.json()["version"] == 1
    error = assert_error(conflict, 409, "STALE_VERSION")
    assert error["details"] == {"expected_version": 0, "current_version": 1}


def test_undo_result_restores_elo(client: TestClient) -> None:
    _, round_one = create_started_tournament(client, [1000, 1000])
    match = round_one["matches"][0]
    p1 = match["player_one_id"]
    client.put(f"/matches/{match['id']}/result", json={"game_winners": [p1, p1], "version": 0})

    response = client.delete(f"/matches/{match['id']}/result", params={"version": 1})

    assert response.status_code == 200
    assert (response.json()["outcome"], response.json()["version"]) == ("pending", 2)
    assert client.get(f"/players/{p1}").json()["elo"] == 1000


def test_lifecycle_conflicts_are_409(client: TestClient) -> None:
    tournament_id, _ = create_started_tournament(client, [1000, 1000, 1000, 1000])
    late = create_players(client, [1000], prefix="Latecomer")[0]

    assert_error(client.post(f"/tournaments/{tournament_id}/start"), 409, "INVALID_STATE")
    assert_error(client.post(f"/tournaments/{tournament_id}/rounds"), 409, "INVALID_STATE")
    assert_error(
        client.post(f"/tournaments/{tournament_id}/entrants", json={"player_id": late}),
        409,
        "INVALID_STATE",
    )


def test_openapi_documents_the_error_shape(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()

    responses = spec["paths"]["/matches/{match_id}/result"]["put"]["responses"]
    assert {"200", "404", "409", "422"} <= responses.keys()
