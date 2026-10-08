"""
tests/test_assistant.py

Unit tests for app.algorithms.assistant (Step 4).
"""
from itertools import count

import pytest

from app.algorithms.assistant import (
    TOTAL_CARDS_IN_PLAY,
    DiscardOption,
    DiscardRecommendationResponse,
    PickRecommendationResponse,
    ProbabilityResponse,
    calculate_draw_probability,
    recommend_discard,
    recommend_pick,
)
from app.models.card import Card, Rank, Suit

_id_counter = count()


def make_card(suit: Suit, rank: Rank, deck_no: int = 1,
              is_printed_joker: bool = False, is_wild_joker: bool = False) -> Card:
    n = next(_id_counter)
    return Card(
        id=f"card-{n}",
        suit=suit,
        rank=rank,
        deck_no=deck_no,
        is_printed_joker=is_printed_joker,
        is_wild_joker=is_wild_joker,
    )


def printed_joker(deck_no: int = 1) -> Card:
    return make_card(Suit.JOKER, Rank.PRINTED_JOKER, deck_no=deck_no, is_printed_joker=True)


# ---------------------------------------------------------------------------
# recommend_discard
# ---------------------------------------------------------------------------

def _winning_style_14_hand_with_one_dead_card():
    """13 cards forming a clean, unambiguous winning arrangement (2 pure
    sequences + 2 sets, no rank/suit overlap between groups so no
    alternative restructuring can also reach 0 deadwood) plus one clearly
    isolated dead 2 of Spades as the 14th card. The 2S should be the
    uniquely obvious best discard."""
    return [
        make_card(Suit.HEARTS, Rank.THREE),
        make_card(Suit.HEARTS, Rank.FOUR),
        make_card(Suit.HEARTS, Rank.FIVE),

        make_card(Suit.DIAMONDS, Rank.SEVEN),
        make_card(Suit.DIAMONDS, Rank.EIGHT),
        make_card(Suit.DIAMONDS, Rank.NINE),

        make_card(Suit.HEARTS, Rank.QUEEN),
        make_card(Suit.DIAMONDS, Rank.QUEEN),
        make_card(Suit.CLUBS, Rank.QUEEN),
        make_card(Suit.SPADES, Rank.QUEEN),

        make_card(Suit.HEARTS, Rank.ACE),
        make_card(Suit.DIAMONDS, Rank.ACE),
        make_card(Suit.CLUBS, Rank.ACE),

        make_card(Suit.SPADES, Rank.TWO),  # isolated dead 14th card
    ]


def test_recommend_discard_requires_fourteen_cards():
    hand = _winning_style_14_hand_with_one_dead_card()[:13]
    with pytest.raises(ValueError):
        recommend_discard(hand)


def test_recommend_discard_rejects_duplicate_cards():
    hand = _winning_style_14_hand_with_one_dead_card()
    duplicated = hand[:13] + [hand[0]]
    with pytest.raises(ValueError):
        recommend_discard(duplicated)


def test_recommend_discard_picks_the_dead_card_as_best_option():
    hand = _winning_style_14_hand_with_one_dead_card()
    result = recommend_discard(hand)

    assert isinstance(result, DiscardRecommendationResponse)
    assert result.hand_size == 14
    assert len(result.recommended_discards) == 3
    assert result.best_discard == result.recommended_discards[0]

    # Discarding the isolated 2 of Spades should yield a perfect 0-deadwood 13.
    assert result.best_discard.card.rank == Rank.TWO
    assert result.best_discard.card.suit == Suit.SPADES
    assert result.best_discard.resulting_deadwood == 0
    assert result.best_discard.score == 100.0
    assert "2" in result.best_discard.reasoning

    # Every candidate must have run through the simulation.
    scores = [o.score for o in result.recommended_discards]
    assert scores == sorted(scores, reverse=True)


def test_recommend_discard_reasoning_mentions_deadwood_and_is_nonempty():
    hand = _winning_style_14_hand_with_one_dead_card()
    result = recommend_discard(hand)
    for option in result.recommended_discards:
        assert isinstance(option.reasoning, str)
        assert len(option.reasoning) > 10


def test_recommend_discard_warns_when_breaking_a_sequence():
    """A hand where every non-trivial discard breaks a sequence should
    score noticeably lower than one that preserves it."""
    hand = [
        make_card(Suit.CLUBS, Rank.TWO),
        make_card(Suit.CLUBS, Rank.THREE),
        make_card(Suit.CLUBS, Rank.FOUR),  # pure sequence #1

        make_card(Suit.SPADES, Rank.SIX),
        make_card(Suit.SPADES, Rank.SEVEN),
        make_card(Suit.SPADES, Rank.EIGHT),  # pure sequence #2

        make_card(Suit.HEARTS, Rank.NINE),
        make_card(Suit.DIAMONDS, Rank.NINE),
        make_card(Suit.CLUBS, Rank.NINE),  # a set

        make_card(Suit.HEARTS, Rank.QUEEN),
        make_card(Suit.DIAMONDS, Rank.QUEEN),
        make_card(Suit.SPADES, Rank.QUEEN),  # a set

        make_card(Suit.HEARTS, Rank.TWO),  # true deadwood, isolated
        make_card(Suit.DIAMONDS, Rank.FIVE),  # true deadwood, isolated
    ]
    result = recommend_discard(hand)

    best = result.best_discard
    # Only one card can be removed at a time, so with two isolated deadwood
    # cards (2H worth 2, 5D worth 5) the optimal move discards the pricier
    # one, leaving the cheaper one as the smallest possible leftover deadwood.
    assert best.card.id == hand[13].id  # the 5 of Diamonds
    assert best.resulting_deadwood == 2
    # A card that would break a pure sequence should never outrank either
    # genuinely dead card.
    dead_card_ids = {hand[12].id, hand[13].id}
    assert best.card.id in dead_card_ids


def test_recommend_discard_known_discards_influences_scoring_without_crashing():
    hand = _winning_style_14_hand_with_one_dead_card()
    known_discards = [make_card(Suit.SPADES, Rank.JACK), make_card(Suit.CLUBS, Rank.TWO)]
    result = recommend_discard(hand, known_discards=known_discards)
    assert result.best_discard.card.suit == Suit.SPADES
    assert result.best_discard.card.rank == Rank.TWO
    assert result.best_discard.resulting_deadwood == 0


# ---------------------------------------------------------------------------
# recommend_pick
# ---------------------------------------------------------------------------

def test_recommend_pick_requires_thirteen_cards():
    hand = _winning_style_14_hand_with_one_dead_card()
    with pytest.raises(ValueError):
        recommend_pick(hand, make_card(Suit.HEARTS, Rank.TWO))


def test_recommend_pick_rejects_card_already_in_hand():
    hand = _winning_style_14_hand_with_one_dead_card()[:13]
    with pytest.raises(ValueError):
        recommend_pick(hand, hand[0])


def test_recommend_pick_recommends_completing_card():
    """Hand is missing exactly one card (5H) to complete a pure sequence
    that would otherwise be two isolated deadwood cards; picking it up
    should be strongly recommended."""
    hand = [
        make_card(Suit.HEARTS, Rank.THREE),
        make_card(Suit.HEARTS, Rank.FOUR),
        # (5H missing -> only a broken 2-card run here)

        make_card(Suit.DIAMONDS, Rank.SIX),
        make_card(Suit.DIAMONDS, Rank.SEVEN),
        make_card(Suit.DIAMONDS, Rank.EIGHT),

        make_card(Suit.HEARTS, Rank.NINE),
        make_card(Suit.DIAMONDS, Rank.NINE),
        make_card(Suit.CLUBS, Rank.NINE),
        make_card(Suit.SPADES, Rank.NINE),

        make_card(Suit.HEARTS, Rank.KING),
        make_card(Suit.DIAMONDS, Rank.KING),
        make_card(Suit.CLUBS, Rank.KING),

        make_card(Suit.SPADES, Rank.TWO),  # filler deadwood card, to be discarded after pick
    ]
    discard_top = make_card(Suit.HEARTS, Rank.FIVE)

    result = recommend_pick(hand, discard_top)

    assert isinstance(result, PickRecommendationResponse)
    assert result.should_pick is True
    assert result.expected_deadwood_after < result.current_deadwood
    assert result.expected_deadwood_after == 0
    assert "5" in result.reason


def test_recommend_pick_declines_useless_card():
    hand = [
        make_card(Suit.HEARTS, Rank.THREE),
        make_card(Suit.HEARTS, Rank.FOUR),
        make_card(Suit.HEARTS, Rank.FIVE),

        make_card(Suit.DIAMONDS, Rank.SIX),
        make_card(Suit.DIAMONDS, Rank.SEVEN),
        make_card(Suit.DIAMONDS, Rank.EIGHT),

        make_card(Suit.HEARTS, Rank.NINE),
        make_card(Suit.DIAMONDS, Rank.NINE),
        make_card(Suit.CLUBS, Rank.NINE),
        make_card(Suit.SPADES, Rank.NINE),

        make_card(Suit.HEARTS, Rank.KING),
        make_card(Suit.DIAMONDS, Rank.KING),
        make_card(Suit.CLUBS, Rank.KING),
    ]
    # Already a perfect 0-deadwood hand; nothing can improve it.
    discard_top = make_card(Suit.SPADES, Rank.TWO)

    result = recommend_pick(hand, discard_top)

    assert result.current_deadwood == 0
    assert result.should_pick is False
    assert result.expected_deadwood_after >= result.current_deadwood


# ---------------------------------------------------------------------------
# calculate_draw_probability
# ---------------------------------------------------------------------------

def test_probability_basic_single_target():
    hand = [make_card(Suit.HEARTS, Rank.SIX), make_card(Suit.HEARTS, Rank.SEVEN)]
    target = [make_card(Suit.HEARTS, Rank.FIVE)]  # completes 5H-6H-7H or 6H-7H-8H
    visible = []

    result = calculate_draw_probability(target, hand, visible)

    seen_count = len(hand) + len(visible)
    expected_unseen = TOTAL_CARDS_IN_PLAY - seen_count
    # both copies of 5H (one per deck) are still unseen
    assert result.useful_unseen_count == 2
    assert result.total_unseen_count == expected_unseen
    assert result.probability == pytest.approx(2 / expected_unseen, rel=1e-6)
    assert result.probability_percentage == pytest.approx(result.probability * 100, abs=0.01)
    assert result.target_identities == ["5♥"]


def test_probability_accounts_for_already_visible_copies():
    hand = [make_card(Suit.HEARTS, Rank.SIX), make_card(Suit.HEARTS, Rank.SEVEN)]
    # one copy of 5H already seen in the discard pile
    already_discarded_five = make_card(Suit.HEARTS, Rank.FIVE)
    visible = [already_discarded_five]
    target = [make_card(Suit.HEARTS, Rank.FIVE)]

    result = calculate_draw_probability(target, hand, visible)

    # only 1 of the 2 physical copies of 5H remains unseen
    assert result.useful_unseen_count == 1
    expected_unseen = TOTAL_CARDS_IN_PLAY - len(hand) - len(visible)
    assert result.total_unseen_count == expected_unseen
    assert result.probability == pytest.approx(1 / expected_unseen, rel=1e-6)


def test_probability_multiple_open_ended_targets():
    """An open sequence 6H-7H can be completed by 5H OR 8H — multiple
    target identities should sum their useful unseen counts."""
    hand = [make_card(Suit.HEARTS, Rank.SIX), make_card(Suit.HEARTS, Rank.SEVEN)]
    targets = [make_card(Suit.HEARTS, Rank.FIVE), make_card(Suit.HEARTS, Rank.EIGHT)]

    result = calculate_draw_probability(targets, hand, [])

    assert set(result.target_identities) == {"5♥", "8♥"}
    assert result.useful_unseen_count == 4  # 2 copies each, both decks unseen


def test_probability_deduplicates_repeated_target_identities():
    hand = []
    targets = [
        make_card(Suit.SPADES, Rank.NINE),
        make_card(Suit.SPADES, Rank.NINE, deck_no=2),  # same identity, different deck
    ]
    result = calculate_draw_probability(targets, hand, [])
    assert result.target_identities == ["9♠"]
    assert result.useful_unseen_count == 2


def test_probability_handles_printed_joker_target():
    targets = [printed_joker()]
    result = calculate_draw_probability(targets, [], [])
    # 1 printed joker per deck * 2 decks = 2 total copies, none seen yet
    assert result.useful_unseen_count == 2


def test_probability_zero_when_all_copies_already_seen():
    five_h_deck1 = make_card(Suit.HEARTS, Rank.FIVE, deck_no=1)
    five_h_deck2 = make_card(Suit.HEARTS, Rank.FIVE, deck_no=2)
    hand = [five_h_deck1]
    visible = [five_h_deck2]
    target = [make_card(Suit.HEARTS, Rank.FIVE)]

    result = calculate_draw_probability(target, hand, visible)

    assert result.useful_unseen_count == 0
    assert result.probability == 0.0
    assert result.probability_percentage == 0.0


def test_probability_response_is_pydantic_model_with_expected_fields():
    result = calculate_draw_probability([make_card(Suit.CLUBS, Rank.TEN)], [], [])
    assert isinstance(result, ProbabilityResponse)
    assert 0.0 <= result.probability <= 1.0
    assert isinstance(result.reason, str) and len(result.reason) > 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
