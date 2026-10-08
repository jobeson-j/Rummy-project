import random
import time

from app.game.engine import RummyGameEngine, TurnStage


def test_many_games_run_to_completion_quickly():
    rng = random.Random(0)
    slowest = 0.0
    for seed in range(12):
        e = RummyGameEngine(num_players=rng.choice([2, 3]), seed=seed)
        for _ in range(300):
            if e.round_over:
                break
            if e.current_player.is_human:
                e.draw(rng.choice(["stock", "discard"]))
                e.discard(rng.choice(e.players[0].hand).id)
            else:
                t = time.time()
                e.play_bot_turn()
                slowest = max(slowest, time.time() - t)
        assert e.round_over
        assert e.round_result is not None
        # bots must never make a wrong show
        assert e.round_result.outcome != "wrong_show"
        if e.round_result.outcome == "declared":
            assert e.round_result.winner_id is not None
            assert all(p.points <= 80 for p in e.round_result.players)
    assert slowest < 2.0


def _c(code, deck=1):
    from app.models.card import Card, Rank, Suit
    rank, suit = code[:-1], code[-1]
    return Card(id=f"{suit}-{rank}-{deck}", suit=Suit(suit), rank=Rank(rank), deck_no=deck)


def test_human_valid_declaration_scores_opponents():
    e = RummyGameEngine(num_players=2, seed=3)
    hand = [_c(x) for x in ["2H", "3H", "4H", "5S", "6S", "7S", "9D", "10D", "JD", "QC", "QD", "QS", "KH", "AC"]]
    for c in hand:
        c.is_wild_joker = False
    e.players[0].hand = hand
    e.turn_stage = TurnStage.AWAITING_DISCARD
    groups = [["H-2-1", "H-3-1", "H-4-1"], ["S-5-1", "S-6-1", "S-7-1"], ["D-9-1", "D-10-1", "D-J-1"],
              ["C-Q-1", "D-Q-1", "S-Q-1", "H-K-1"]]
    res = e.declare("player-1", groups, finish_card_id="C-A-1")
    assert res.is_valid is False  # QC QD QS KH is not a set
    assert e.round_result.outcome == "wrong_show"


def test_human_valid_declaration_wins():
    e2 = RummyGameEngine(num_players=2, seed=3)
    hand2 = [_c(x) for x in ["2H", "3H", "4H", "5S", "6S", "7S", "9D", "10D", "JD", "QC", "QH", "QS", "KH", "AC"]]
    for c in hand2:
        c.is_wild_joker = False
    e2.players[0].hand = hand2
    e2.turn_stage = TurnStage.AWAITING_DISCARD
    groups2 = [["H-2-1", "H-3-1", "H-4-1"], ["S-5-1", "S-6-1", "S-7-1"], ["D-9-1", "D-10-1", "D-J-1"],
               ["C-Q-1", "H-Q-1", "S-Q-1"]]
    # 12 cards grouped; KH left over -> invalid (left out)
    res = e2.declare("player-1", groups2, finish_card_id="C-A-1")
    assert res.is_valid is False and "left out" in (res.reason or "")

    e3 = RummyGameEngine(num_players=2, seed=3)
    hand3 = [_c(x) for x in ["2H", "3H", "4H", "5S", "6S", "7S", "9D", "10D", "JD", "QC", "QH", "QS", "QD", "AC"]]
    for c in hand3:
        c.is_wild_joker = False
    e3.players[0].hand = hand3
    e3.turn_stage = TurnStage.AWAITING_DISCARD
    groups3 = [["H-2-1", "H-3-1", "H-4-1"], ["S-5-1", "S-6-1", "S-7-1"], ["D-9-1", "D-10-1", "D-J-1"],
               ["C-Q-1", "H-Q-1", "S-Q-1", "D-Q-1"]]
    res = e3.declare("player-1", groups3, finish_card_id="C-A-1")
    assert res.is_valid is True
    rr = e3.round_result
    assert rr.outcome == "declared" and rr.winner_id == "player-1"
    me = next(p for p in rr.players if p.is_human)
    bot = next(p for p in rr.players if not p.is_human)
    assert me.points == 0 and 0 < bot.points <= 80
