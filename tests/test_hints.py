"""Regression tests for the hint engine (review feedback, Oct 2026)."""
from itertools import count

from app.algorithms.assistant import recommend_discard
from app.algorithms.hand_partitioner import find_optimal_arrangement
from app.models.card import Card, Rank, Suit

_n = count()


def c(code: str) -> Card:
    if code.startswith("PJ"):
        return Card(id=f"JK-PJ-{next(_n)}", suit=Suit.JOKER, rank=Rank.PRINTED_JOKER)
    rank, suit = code[:-1], code[-1]
    return Card(id=f"{suit}-{rank}-{next(_n)}", suit=Suit(suit), rank=Rank(rank))


def reviewer_hand():
    # K-A-joker sequence, a lone Q of spades and a freshly drawn printed joker
    return [c(x) for x in [
        "KC", "AC", "PJ",
        "QS",
        "4H", "5H", "6H",
        "9S", "9D", "9C",
        "2D", "7C", "JD",
        "PJ",
    ]]


def test_hint_never_breaks_a_meld_or_throws_a_joker():
    hand = reviewer_hand()
    rec = recommend_discard(hand)
    best = rec.best_discard.card
    assert not best.is_any_joker
    assert best.rank not in (Rank.KING, Rank.ACE)  # K-A-joker is a valid sequence
    assert best.id in {hand[3].id, hand[10].id, hand[11].id, hand[12].id}  # a loose card
    assert "point" in rec.best_discard.reasoning


def test_hint_prefers_isolated_high_card():
    hand = reviewer_hand()
    best = recommend_discard(hand).best_discard.card
    # Q of spades and J of diamonds connect to nothing; both are worth 10
    assert best.rank in (Rank.QUEEN, Rank.JACK)


def test_spare_printed_joker_is_placed_in_a_meld():
    hand = reviewer_hand()
    hand = [x for x in hand if x.rank != Rank.QUEEN]  # 13 cards
    arr = find_optimal_arrangement(hand)
    assert not any(x.is_any_joker for x in arr.deadwood_cards)


def test_king_ace_counts_as_connected():
    from app.algorithms.assistant import _neighbours
    k, a = c("KC"), c("AC")
    assert a in _neighbours(k, [a])
