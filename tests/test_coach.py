from fastapi.testclient import TestClient

from app.algorithms.coach import coach
from app.game.engine import RummyGameEngine, TurnStage
from app.main import app
from app.models.card import Card, Rank, Suit

client = TestClient(app)


def test_coach_draw_then_discard_flow():
    s = client.post("/api/game/new", json={"num_players": 2, "seed": 11}).json()
    gid = s["game_id"]
    c = client.get(f"/api/game/{gid}/coach").json()
    assert c["stage"] == "draw"
    assert c["action"]["kind"] in ("take_discard", "draw_stock")
    assert c["detail"] and c["tip"] and c["status"]
    src = "discard" if c["action"]["kind"] == "take_discard" else "stock"
    s = client.post(f"/api/game/{gid}/draw", json={"source": src}).json()
    c = client.get(f"/api/game/{gid}/coach").json()
    assert c["stage"] == "discard"
    assert len(c["options"]) == 14
    hand_ids = {x["id"] for x in s["human_hand"]}
    assert c["action"]["card_id"] in hand_ids
    costs = [o["cost"] for o in c["options"]]
    assert costs == sorted(costs)
    s = client.post(f"/api/game/{gid}/discard", json={"card_id": c["action"]["card_id"]}).json()
    c = client.get(f"/api/game/{gid}/coach").json()
    assert c["stage"] == "waiting"
    assert len(c["reads"]) == 1


def _c(code):
    rank, suit = code[:-1], code[-1]
    return Card(id=f"{suit}-{rank}-1", suit=Suit(suit), rank=Rank(rank))


def test_coach_says_declare_when_hand_is_complete():
    e = RummyGameEngine(num_players=2, seed=3)
    e.players[0].hand = [_c(x) for x in ["2H", "3H", "4H", "5S", "6S", "7S", "9D", "10D", "JD",
                                          "QC", "QH", "QS", "QD", "KC"]]
    for card in e.players[0].hand:
        card.is_wild_joker = False
    e.turn_stage = TurnStage.AWAITING_DISCARD
    c = coach(e)
    assert c.action.kind == "declare"
    assert c.action.card_id == "C-K-1"
