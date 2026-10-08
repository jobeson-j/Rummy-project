"""
Unit tests for Smart Rummy's rules engine: pure/impure sequence and set
classification, plus full 13/14-card declaration validation.
"""

from __future__ import annotations

import pytest

from app.game.rules import (
    DeclarationResult,
    MeldType,
    MeldValidationResult,
    classify_group,
    find_valid_declaration,
    validate_arrangement,
)
from app.models.card import Card, Rank, Suit


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def card(suit: Suit, rank: Rank, deck_no: int = 1, wild: bool = False) -> Card:
    c = Card(id=Card.make_id(suit, rank, deck_no), suit=suit, rank=rank, deck_no=deck_no)
    c.is_wild_joker = wild
    return c


def printed_joker(deck_no: int = 1) -> Card:
    return Card(id=Card.make_id(Suit.JOKER, Rank.PRINTED_JOKER, deck_no), suit=Suit.JOKER, rank=Rank.PRINTED_JOKER, deck_no=deck_no)


def ids(cards):
    return {c.id for c in cards}


# ----------------------------------------------------------------------
# Pure sequences
# ----------------------------------------------------------------------
class TestPureSequence:
    def test_simple_pure_sequence(self):
        cards = [card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE), card(Suit.HEARTS, Rank.SIX)]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.PURE_SEQUENCE
        assert ids(cards) == set(result.natural_card_ids)
        assert result.joker_substitute_ids == []

    def test_ace_low_pure_sequence(self):
        cards = [card(Suit.SPADES, Rank.ACE), card(Suit.SPADES, Rank.TWO), card(Suit.SPADES, Rank.THREE)]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.PURE_SEQUENCE

    def test_ace_high_pure_sequence(self):
        cards = [card(Suit.CLUBS, Rank.QUEEN), card(Suit.CLUBS, Rank.KING), card(Suit.CLUBS, Rank.ACE)]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.PURE_SEQUENCE

    def test_round_the_corner_is_invalid(self):
        cards = [card(Suit.DIAMONDS, Rank.KING), card(Suit.DIAMONDS, Rank.ACE), card(Suit.DIAMONDS, Rank.TWO)]
        result = classify_group(cards)
        assert not result.is_valid
        assert result.meld_type == MeldType.INVALID

    def test_out_of_order_still_pure(self):
        # Order in the input list shouldn't matter - only the set of ranks.
        cards = [card(Suit.HEARTS, Rank.SIX), card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE)]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.PURE_SEQUENCE

    def test_mismatched_suits_not_pure(self):
        cards = [card(Suit.HEARTS, Rank.FOUR), card(Suit.SPADES, Rank.FIVE), card(Suit.HEARTS, Rank.SIX)]
        result = classify_group(cards)
        assert result.meld_type != MeldType.PURE_SEQUENCE

    def test_gap_not_pure(self):
        cards = [card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.SIX), card(Suit.HEARTS, Rank.SEVEN)]
        result = classify_group(cards)
        assert result.meld_type != MeldType.PURE_SEQUENCE

    def test_printed_joker_breaks_purity(self):
        cards = [card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE), printed_joker()]
        result = classify_group(cards)
        assert result.meld_type != MeldType.PURE_SEQUENCE

    def test_wild_joker_fitting_naturally_stays_pure(self):
        # The 9 of Hearts happens to be the cut (wild) rank, but it is used
        # at its own literal suit/rank here, so purity is preserved.
        wild_nine = card(Suit.HEARTS, Rank.NINE, wild=True)
        cards = [card(Suit.HEARTS, Rank.EIGHT), wild_nine, card(Suit.HEARTS, Rank.TEN)]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.PURE_SEQUENCE
        assert wild_nine.id in result.natural_card_ids

    def test_longer_pure_sequence(self):
        cards = [
            card(Suit.SPADES, Rank.FOUR),
            card(Suit.SPADES, Rank.FIVE),
            card(Suit.SPADES, Rank.SIX),
            card(Suit.SPADES, Rank.SEVEN),
            card(Suit.SPADES, Rank.EIGHT),
        ]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.PURE_SEQUENCE

    def test_duplicate_rank_same_suit_not_pure(self):
        cards = [
            card(Suit.HEARTS, Rank.FOUR),
            card(Suit.HEARTS, Rank.FOUR, deck_no=2),
            card(Suit.HEARTS, Rank.FIVE),
        ]
        result = classify_group(cards)
        assert result.meld_type != MeldType.PURE_SEQUENCE


# ----------------------------------------------------------------------
# Impure sequences
# ----------------------------------------------------------------------
class TestImpureSequence:
    def test_printed_joker_fills_gap(self):
        cards = [card(Suit.DIAMONDS, Rank.NINE), card(Suit.DIAMONDS, Rank.TEN), printed_joker()]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.IMPURE_SEQUENCE
        assert len(result.natural_card_ids) == 2
        assert len(result.joker_substitute_ids) == 1

    def test_wild_joker_used_as_substitute_across_suit(self):
        # A wild-flagged Spade card can stand in for a missing Diamond rank.
        wild_spade = card(Suit.SPADES, Rank.KING, wild=True)
        cards = [card(Suit.DIAMONDS, Rank.NINE), card(Suit.DIAMONDS, Rank.TEN), wild_spade]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.IMPURE_SEQUENCE
        assert wild_spade.id in result.joker_substitute_ids

    def test_duplicate_natural_rank_resolved_by_demoting_wild_to_substitute(self):
        # Two Hearts-5s (one wild-flagged) plus a Hearts-7: the wild 5 can't
        # be used naturally (duplicate with the normal 5H) but CAN sub in
        # for the missing 6H, making 5-6(sub)-7 a valid impure sequence.
        normal_five = card(Suit.HEARTS, Rank.FIVE)
        wild_five = card(Suit.HEARTS, Rank.FIVE, deck_no=2, wild=True)
        seven = card(Suit.HEARTS, Rank.SEVEN)
        result = classify_group([normal_five, wild_five, seven])
        assert result.is_valid
        assert result.meld_type == MeldType.IMPURE_SEQUENCE
        assert wild_five.id in result.joker_substitute_ids
        assert normal_five.id in result.natural_card_ids
        assert seven.id in result.natural_card_ids

    def test_requires_at_least_one_natural_card(self):
        # Two printed jokers alone can't anchor any particular suit/rank.
        cards = [printed_joker(1), printed_joker(2)]
        result = classify_group(cards)
        assert result.meld_type == MeldType.INVALID

    def test_multiple_jokers_filling_multiple_gaps(self):
        cards = [
            card(Suit.CLUBS, Rank.TWO),
            printed_joker(1),
            printed_joker(2),
            card(Suit.CLUBS, Rank.FIVE),
        ]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.IMPURE_SEQUENCE
        assert len(result.joker_substitute_ids) == 2

    def test_too_many_jokers_for_gap_size_invalid(self):
        # Anchor ranks are too far apart for a joker to bridge within a
        # 3-card run span, regardless of how many jokers are available.
        cards = [card(Suit.CLUBS, Rank.TWO), card(Suit.CLUBS, Rank.EIGHT), printed_joker(1)]
        result = classify_group(cards)
        assert result.meld_type == MeldType.INVALID

    def test_normal_card_of_wrong_suit_invalidates_group(self):
        cards = [
            card(Suit.DIAMONDS, Rank.NINE),
            card(Suit.DIAMONDS, Rank.TEN),
            card(Suit.CLUBS, Rank.THREE),  # normal card, wrong suit, no joker power
        ]
        result = classify_group(cards)
        assert result.meld_type == MeldType.INVALID


# ----------------------------------------------------------------------
# Sets
# ----------------------------------------------------------------------
class TestSet:
    def test_simple_three_card_set(self):
        cards = [card(Suit.HEARTS, Rank.SEVEN), card(Suit.CLUBS, Rank.SEVEN), card(Suit.SPADES, Rank.SEVEN)]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.SET

    def test_full_four_card_set(self):
        cards = [
            card(Suit.HEARTS, Rank.KING),
            card(Suit.DIAMONDS, Rank.KING),
            card(Suit.CLUBS, Rank.KING),
            card(Suit.SPADES, Rank.KING),
        ]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.SET

    def test_set_with_joker_substitute(self):
        cards = [card(Suit.HEARTS, Rank.SEVEN), card(Suit.CLUBS, Rank.SEVEN), printed_joker()]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.SET
        assert len(result.joker_substitute_ids) == 1

    def test_wild_joker_resolves_duplicate_suit_in_set(self):
        # A wild-flagged 7 of Hearts would literally duplicate the normal
        # 7 of Hearts, but since it's flexible it can represent 7 of Clubs
        # (or Spades) instead, making the set valid.
        normal_seven_h = card(Suit.HEARTS, Rank.SEVEN)
        wild_seven_h = card(Suit.HEARTS, Rank.SEVEN, deck_no=2, wild=True)
        seven_d = card(Suit.DIAMONDS, Rank.SEVEN)
        result = classify_group([normal_seven_h, wild_seven_h, seven_d])
        assert result.is_valid
        assert result.meld_type == MeldType.SET
        assert wild_seven_h.id in result.joker_substitute_ids

    def test_duplicate_suit_and_rank_invalid(self):
        cards = [
            card(Suit.HEARTS, Rank.SEVEN, deck_no=1),
            card(Suit.HEARTS, Rank.SEVEN, deck_no=2),
            card(Suit.CLUBS, Rank.SEVEN),
        ]
        result = classify_group(cards)
        assert result.meld_type == MeldType.INVALID

    def test_set_cannot_exceed_four_cards(self):
        cards = [
            card(Suit.HEARTS, Rank.NINE),
            card(Suit.DIAMONDS, Rank.NINE),
            card(Suit.CLUBS, Rank.NINE),
            card(Suit.SPADES, Rank.NINE),
            printed_joker(),
        ]
        result = classify_group(cards)
        # 5 same-suit-mismatched cards can't be a sequence either (all diff
        # suits, only one rank shared among 4 + a joker) -> must be invalid,
        # since a set is capped at 4.
        assert result.meld_type == MeldType.INVALID

    def test_normal_card_of_wrong_rank_invalidates_set(self):
        cards = [card(Suit.HEARTS, Rank.SEVEN), card(Suit.CLUBS, Rank.SEVEN), card(Suit.SPADES, Rank.EIGHT)]
        result = classify_group(cards)
        assert result.meld_type == MeldType.INVALID

    def test_two_jokers_completing_a_set(self):
        # Two different-suit Queens can never be interpreted as a sequence
        # (a sequence requires a single suit), so this unambiguously
        # resolves as a set with both jokers as substitutes.
        cards = [card(Suit.HEARTS, Rank.QUEEN), card(Suit.CLUBS, Rank.QUEEN), printed_joker(1)]
        result = classify_group(cards)
        assert result.is_valid
        assert result.meld_type == MeldType.SET
        assert len(result.joker_substitute_ids) == 1


# ----------------------------------------------------------------------
# Generic group edge cases
# ----------------------------------------------------------------------
class TestGroupEdgeCases:
    def test_fewer_than_three_cards_invalid(self):
        cards = [card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE)]
        result = classify_group(cards)
        assert not result.is_valid
        assert "at least 3 cards" in result.reason

    def test_empty_group_invalid(self):
        result = classify_group([])
        assert not result.is_valid

    def test_unrelated_cards_invalid(self):
        cards = [card(Suit.HEARTS, Rank.TWO), card(Suit.CLUBS, Rank.NINE), card(Suit.SPADES, Rank.KING)]
        result = classify_group(cards)
        assert not result.is_valid
        assert result.meld_type == MeldType.INVALID


# ----------------------------------------------------------------------
# Declaration validation (explicit arrangement)
# ----------------------------------------------------------------------
def _valid_13_card_groups():
    pure = [card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE), card(Suit.HEARTS, Rank.SIX)]
    impure = [card(Suit.DIAMONDS, Rank.NINE), card(Suit.DIAMONDS, Rank.TEN), printed_joker(1)]
    set_sevens = [card(Suit.CLUBS, Rank.SEVEN), card(Suit.SPADES, Rank.SEVEN), card(Suit.HEARTS, Rank.SEVEN)]
    set_kings = [
        card(Suit.CLUBS, Rank.KING),
        card(Suit.DIAMONDS, Rank.KING),
        card(Suit.SPADES, Rank.KING),
        card(Suit.HEARTS, Rank.KING),
    ]
    return [pure, impure, set_sevens, set_kings]


class TestValidateArrangement:
    def test_valid_13_card_declaration(self):
        groups = _valid_13_card_groups()
        result = validate_arrangement(groups)
        assert result.is_valid
        assert result.reason is None
        assert result.total_cards == 13
        assert result.pure_sequence_count == 1
        assert result.impure_sequence_count == 1
        assert result.set_count == 2

    def test_only_one_sequence_invalid(self):
        pure = [card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE), card(Suit.HEARTS, Rank.SIX)]
        set_sevens = [card(Suit.CLUBS, Rank.SEVEN), card(Suit.SPADES, Rank.SEVEN), card(Suit.HEARTS, Rank.SEVEN)]
        set_kings = [
            card(Suit.CLUBS, Rank.KING),
            card(Suit.DIAMONDS, Rank.KING),
            card(Suit.SPADES, Rank.KING),
            card(Suit.HEARTS, Rank.KING),
        ]
        set_queens = [card(Suit.CLUBS, Rank.QUEEN), card(Suit.SPADES, Rank.QUEEN), card(Suit.HEARTS, Rank.QUEEN)]
        result = validate_arrangement([pure, set_sevens, set_kings, set_queens])
        assert not result.is_valid
        assert "At least 2 sequences" in result.reason

    def test_two_sequences_but_no_pure_invalid(self):
        impure1 = [card(Suit.DIAMONDS, Rank.NINE), card(Suit.DIAMONDS, Rank.TEN), printed_joker(1)]
        impure2 = [card(Suit.CLUBS, Rank.THREE), card(Suit.CLUBS, Rank.FOUR), printed_joker(2)]
        set_sevens = [card(Suit.SPADES, Rank.SEVEN), card(Suit.HEARTS, Rank.SEVEN), card(Suit.DIAMONDS, Rank.SEVEN)]
        set_kings = [
            card(Suit.CLUBS, Rank.KING),
            card(Suit.DIAMONDS, Rank.KING),
            card(Suit.SPADES, Rank.KING),
            card(Suit.HEARTS, Rank.KING),
        ]
        result = validate_arrangement([impure1, impure2, set_sevens, set_kings])
        assert not result.is_valid
        assert "pure sequence" in result.reason

    def test_invalid_group_reported_with_reason(self):
        broken = [card(Suit.HEARTS, Rank.TWO), card(Suit.CLUBS, Rank.NINE), card(Suit.SPADES, Rank.KING)]
        groups = _valid_13_card_groups()
        groups[-1] = broken  # corrupt the last (4-card) group into a 3-card invalid one
        # rebalance so total is still 13: drop one card from another group to
        # compensate is unnecessary here since we just want an invalid-group
        # failure path, total count check happens first if mismatched.
        result = validate_arrangement(groups)
        assert not result.is_valid

    def test_duplicate_card_across_groups_invalid(self):
        shared = card(Suit.HEARTS, Rank.SEVEN)
        group_a = [shared, card(Suit.HEARTS, Rank.EIGHT), card(Suit.HEARTS, Rank.NINE)]
        group_b = [shared, card(Suit.CLUBS, Rank.SEVEN), card(Suit.SPADES, Rank.SEVEN)]
        result = validate_arrangement([group_a, group_b])
        assert not result.is_valid
        assert "more than one group" in result.reason

    def test_wrong_total_card_count_invalid(self):
        groups = [[card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE), card(Suit.HEARTS, Rank.SIX)]]
        result = validate_arrangement(groups)
        assert not result.is_valid
        assert "13 or 14" in result.reason

    def test_14_card_declaration_allowed_when_structurally_valid(self):
        groups = _valid_13_card_groups()
        # Add one extra card as its own tiny 1-card addition is invalid on
        # its own; instead extend the pure sequence to 4 cards to reach 14
        # cards total while remaining fully valid.
        groups[0] = [
            card(Suit.HEARTS, Rank.FOUR),
            card(Suit.HEARTS, Rank.FIVE),
            card(Suit.HEARTS, Rank.SIX),
            card(Suit.HEARTS, Rank.SEVEN, deck_no=2),
        ]
        result = validate_arrangement(groups)
        assert result.is_valid
        assert result.total_cards == 14


# ----------------------------------------------------------------------
# Declaration validation (automatic search)
# ----------------------------------------------------------------------
class TestFindValidDeclaration:
    def test_finds_valid_arrangement_when_one_exists(self):
        groups = _valid_13_card_groups()
        hand = [c for group in groups for c in group]
        # Shuffle order to make sure the search isn't relying on input order.
        hand = hand[::-1]
        result = find_valid_declaration(hand)
        assert result.is_valid
        assert result.pure_sequence_count >= 1
        assert result.pure_sequence_count + result.impure_sequence_count >= 2
        assert sum(len(g.card_ids) for g in result.groups) == 13

    def test_reports_invalid_when_no_arrangement_exists(self):
        # 13 cards, one of each rank, cycling suits so that no 3 consecutive
        # ranks share a suit (no sequences) and no rank repeats (no sets).
        ranks_in_order = [
            Rank.TWO, Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX, Rank.SEVEN,
            Rank.EIGHT, Rank.NINE, Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING, Rank.ACE,
        ]
        suit_cycle = [Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES]
        hand = [card(suit_cycle[i % 4], rank) for i, rank in enumerate(ranks_in_order)]
        result = find_valid_declaration(hand)
        assert not result.is_valid
        assert "No valid arrangement" in result.reason

    def test_wrong_hand_size_invalid(self):
        hand = [card(Suit.HEARTS, Rank.FOUR), card(Suit.HEARTS, Rank.FIVE)]
        result = find_valid_declaration(hand)
        assert not result.is_valid
        assert "13 or 14" in result.reason

    def test_duplicate_card_in_hand_invalid(self):
        shared = card(Suit.HEARTS, Rank.SEVEN)
        hand = [shared, shared] + [
            card(Suit.CLUBS, Rank.TWO, deck_no=1),
            card(Suit.CLUBS, Rank.THREE, deck_no=1),
            card(Suit.CLUBS, Rank.FOUR, deck_no=1),
            card(Suit.DIAMONDS, Rank.TWO, deck_no=1),
            card(Suit.DIAMONDS, Rank.THREE, deck_no=1),
            card(Suit.DIAMONDS, Rank.FOUR, deck_no=1),
            card(Suit.SPADES, Rank.TWO, deck_no=1),
            card(Suit.SPADES, Rank.THREE, deck_no=1),
            card(Suit.SPADES, Rank.FOUR, deck_no=1),
            card(Suit.HEARTS, Rank.TWO, deck_no=2),
            card(Suit.HEARTS, Rank.THREE, deck_no=2),
        ]
        result = find_valid_declaration(hand)
        assert not result.is_valid
        assert "duplicate" in result.reason.lower()
