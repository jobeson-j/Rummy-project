from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _new(seed=7):
    r = client.post("/api/game/new", json={"num_players": 2, "difficulty": "medium", "seed": seed})
    assert r.status_code == 200
    return r.json()


def test_turn_flow_with_bot_turn_and_events():
    s = _new()
    gid = s["game_id"]
    assert s["is_human_turn"] and s["turn_stage"] == "AWAITING_DRAW"
    assert len(s["human_hand"]) == 13
    assert s["events"][0]["action"] == "round_start"

    # discarding before drawing is rejected with a readable message
    r = client.post(f"/api/game/{gid}/discard", json={"card_id": s["human_hand"][0]["id"]})
    assert r.status_code == 400 and "Draw" in r.json()["detail"]

    s = client.post(f"/api/game/{gid}/draw", json={"source": "stock"}).json()
    assert len(s["human_hand"]) == 14
    s = client.post(f"/api/game/{gid}/discard", json={"card_id": s["human_hand"][0]["id"]}).json()
    assert not s["is_human_turn"]

    s = client.post(f"/api/game/{gid}/bot-turn").json()
    assert s["is_human_turn"] or s["round_result"] is not None
    actions = [e["action"] for e in s["events"]]
    assert "discard" in actions


def test_check_and_arrange_endpoints():
    s = _new()
    gid = s["game_id"]
    ids = [c["id"] for c in s["human_hand"]]
    r = client.post(f"/api/game/{gid}/check", json={"groups": [ids[:3], ids[3:]]})
    assert r.status_code == 200
    assert r.json()["declaration"]["is_valid"] is False
    assert len(r.json()["groups"]) == 2
    r = client.get(f"/api/game/{gid}/assist/arrange")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body and isinstance(body["groups"], list)


def test_wrong_show_ends_round_with_penalty_and_next_round():
    s = _new()
    gid = s["game_id"]
    s = client.post(f"/api/game/{gid}/draw", json={"source": "stock"}).json()
    ids = [c["id"] for c in s["human_hand"]]
    r = client.post(f"/api/game/{gid}/declare", json={"groups": [ids[:4], ids[4:8], ids[8:13]], "finish_card_id": ids[13]})
    assert r.status_code == 200
    body = r.json()
    assert body["declaration_result"]["is_valid"] is False
    st = body["game_state"]
    assert st["turn_stage"] == "ROUND_OVER"
    assert st["round_result"]["outcome"] == "wrong_show"
    me = next(p for p in st["players_summary"] if p["is_human"])
    assert me["score"] == 80

    st = client.post(f"/api/game/{gid}/next-round").json()
    assert st["round_number"] == 2 and st["round_result"] is None
    assert len(st["human_hand"]) == 13


def test_first_drop_costs_20():
    s = _new()
    gid = s["game_id"]
    st = client.post(f"/api/game/{gid}/drop").json()
    assert st["round_result"]["outcome"] == "drop"
    me = next(p for p in st["players_summary"] if p["is_human"])
    assert me["score"] == 20
