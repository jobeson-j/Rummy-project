import itertools
import pytest
from app.models.card import Card, Rank, Suit
from app.algorithms.hand_partitioner import find_optimal_arrangement

_id_counter = itertools.count(1)


def make_card(suit: Suit, rank: Rank, is_printed_joker: bool = False, is_wild_joker: bool = False) -> Card:
    n = next(_id_counter)
    return Card(
        id=f"card-{n}",
        suit=suit,
        rank=rank,
        deck_no=1,
        is_printed_joker=is_printed_joker,
        is_wild_joker=is_wild_joker,
    )


def test_full_winning_hand_all_natural():
    hand = [
        # Pure 1: 4H 5H 6H
        make_card(Suit.HEARTS, Rank.FOUR),
        make_card(Suit.HEARTS, Rank.FIVE),
        make_card(Suit.HEARTS, Rank.SIX),
        # Pure 2: 7S 8S 9S
        make_card(Suit.SPADES, Rank.SEVEN),
        make_card(Suit.SPADES, Rank.EIGHT),
        make_card(Suit.SPADES, Rank.NINE),
        # Set 1: 3C 3D 3H
        make_card(Suit.CLUBS, Rank.THREE),
        make_card(Suit.DIAMONDS, Rank.THREE),
        make_card(Suit.HEARTS, Rank.THREE),
        # Set 2: KD KC KS KH
        make_card(Suit.DIAMONDS, Rank.KING),
        make_card(Suit.CLUBS, Rank.KING),
        make_card(Suit.SPADES, Rank.KING),
        make_card(Suit.HEARTS, Rank.KING),
    ]
    arr = find_optimal_arrangement(hand)
    assert arr.is_winning_hand is True
    assert arr.total_deadwood == 0
    assert len(arr.deadwood_cards) == 0
    assert len(arr.pure_sequences) == 2


def test_deadwood_points_computed_correctly_for_face_cards():
    hand = [
        # Pure 1
        make_card(Suit.HEARTS, Rank.FOUR),
        make_card(Suit.HEARTS, Rank.FIVE),
        make_card(Suit.HEARTS, Rank.SIX),
        # Sequence 2
        make_card(Suit.SPADES, Rank.SEVEN),
        make_card(Suit.SPADES, Rank.EIGHT),
        make_card(Suit.SPADES, Rank.NINE),
        # Deadwood cards: K (10) + 5 (5) = 15
        make_card(Suit.CLUBS, Rank.KING),
        make_card(Suit.DIAMONDS, Rank.FIVE),
    ]
    arr = find_optimal_arrangement(hand)
    assert arr.total_deadwood == 15
    assert len(arr.deadwood_cards) == 2


def test_no_sequence_at_all_makes_entire_hand_deadwood():
    hand = [
        make_card(Suit.CLUBS, Rank.TWO),
        make_card(Suit.DIAMONDS, Rank.FOUR),
        make_card(Suit.HEARTS, Rank.SEVEN),
        make_card(Suit.SPADES, Rank.JACK),
    ]
    arr = find_optimal_arrangement(hand)
    # Total points: 2 + 4 + 7 + 10 = 23
    assert arr.total_deadwood == 23
    assert len(arr.deadwood_cards) == 4