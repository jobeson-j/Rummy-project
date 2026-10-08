"""
Unit tests for Smart Rummy's deck construction, shuffling, wild-joker
cutting, and dealing mechanics.
"""

from __future__ import annotations

import pytest

from app.game.deck import (
    Deck,
    EmptyPileError,
    InsufficientCardsError,
    InvalidPlayerCountError,
    WildJokerNotSetError,
)
from app.models.card import RANK_POINTS, STANDARD_RANKS, STANDARD_SUITS, Rank, Suit


# ----------------------------------------------------------------------
# Deck composition
# ----------------------------------------------------------------------
class TestDeckComposition:
    def test_total_card_count_is_106(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        assert len(deck.all_cards) == 106
        assert deck.total_card_count == 106
        assert len(deck.stock) == 106  # nothing dealt/discarded yet

    def test_all_card_ids_unique(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        ids = [c.id for c in deck.all_cards]
        assert len(ids) == len(set(ids)) == 106

    def test_printed_joker_count_is_two(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        printed_jokers = [c for c in deck.all_cards if c.is_printed_joker]
        assert len(printed_jokers) == 2
        ids = {c.id for c in printed_jokers}
        assert ids == {"JK-PJ-1", "JK-PJ-2"}

    def test_each_standard_suit_rank_combo_appears_twice(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        for suit in STANDARD_SUITS:
            for rank in STANDARD_RANKS:
                matches = [
                    c for c in deck.all_cards if c.suit == suit and c.rank == rank
                ]
                assert len(matches) == 2, f"expected 2x {suit}-{rank}, got {len(matches)}"
                deck_nos = sorted(c.deck_no for c in matches)
                assert deck_nos == [1, 2]

    def test_deterministic_id_format(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        seven_of_hearts_deck1 = deck.get_card("H-7-1")
        assert seven_of_hearts_deck1.suit == Suit.HEARTS
        assert seven_of_hearts_deck1.rank == Rank.SEVEN
        assert seven_of_hearts_deck1.deck_no == 1

        pj_deck2 = deck.get_card("JK-PJ-2")
        assert pj_deck2.suit == Suit.JOKER
        assert pj_deck2.rank == Rank.PRINTED_JOKER
        assert pj_deck2.deck_no == 2

    def test_get_card_missing_id_raises(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        with pytest.raises(KeyError):
            deck.get_card("X-99-1")


# ----------------------------------------------------------------------
# Point values
# ----------------------------------------------------------------------
class TestRankPoints:
    @pytest.mark.parametrize(
        "rank,expected",
        [
            (Rank.TWO, 2),
            (Rank.THREE, 3),
            (Rank.FOUR, 4),
            (Rank.FIVE, 5),
            (Rank.SIX, 6),
            (Rank.SEVEN, 7),
            (Rank.EIGHT, 8),
            (Rank.NINE, 9),
            (Rank.TEN, 10),
            (Rank.JACK, 10),
            (Rank.QUEEN, 10),
            (Rank.KING, 10),
            (Rank.ACE, 10),
            (Rank.PRINTED_JOKER, 0),
        ],
    )
    def test_rank_points_table(self, rank, expected):
        assert RANK_POINTS[rank] == expected

    def test_card_points_property_matches_table(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        king = deck.get_card("S-K-1")
        assert king.points == 10
        two = deck.get_card("D-2-1")
        assert two.points == 2

    def test_printed_joker_always_zero_points(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        pj = deck.get_card("JK-PJ-1")
        assert pj.points == 0

    def test_wild_joker_card_becomes_zero_points(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        card = deck.get_card("H-9-1")
        assert card.points == 9
        card.is_wild_joker = True
        assert card.points == 0


# ----------------------------------------------------------------------
# Shuffling
# ----------------------------------------------------------------------
class TestShuffle:
    def test_shuffle_preserves_card_set(self):
        deck = Deck(num_sub_decks=2, rng_seed=1)
        before_ids = sorted(c.id for c in deck.stock)
        deck.shuffle()
        after_ids = sorted(c.id for c in deck.stock)
        assert before_ids == after_ids

    def test_shuffle_with_seed_is_reproducible(self):
        deck_a = Deck(num_sub_decks=2, rng_seed=0)
        deck_b = Deck(num_sub_decks=2, rng_seed=0)
        deck_a.shuffle(seed=123)
        deck_b.shuffle(seed=123)
        assert [c.id for c in deck_a.stock] == [c.id for c in deck_b.stock]

    def test_shuffle_only_touches_stock(self):
        deck = Deck(num_sub_decks=2, rng_seed=5)
        deck.shuffle(seed=5)
        info = deck.cut_joker(index=0)
        discard_before = list(deck.discard_pile)
        deck.shuffle(seed=99)
        assert deck.discard_pile == discard_before
        assert info.indicator_card in deck.discard_pile


# ----------------------------------------------------------------------
# Wild joker cutting
# ----------------------------------------------------------------------
class TestCutJoker:
    def test_cut_joker_normal_rank_marks_remaining_same_rank_cards(self):
        deck = Deck(num_sub_decks=2, rng_seed=7)
        deck.shuffle(seed=7)
        # Force the cut to land on a known, non-printed-joker card.
        target_index = next(
            i for i, c in enumerate(deck.stock) if c.id == "H-9-1"
        )
        info = deck.cut_joker(index=target_index)

        assert info.wild_rank == Rank.NINE
        assert info.ace_fallback is False
        assert info.indicator_card.id == "H-9-1"

        # 4 suits x 2 sub-decks = 8 nines total; indicator itself is excluded.
        nines = [c for c in deck.all_cards if c.rank == Rank.NINE]
        assert len(nines) == 8
        wild_nines = [c for c in nines if c.is_wild_joker]
        assert len(wild_nines) == 7
        assert info.indicator_card.is_wild_joker is False
        assert set(info.wild_card_ids) == {c.id for c in wild_nines}

        # No other rank should have been touched.
        non_nines_wild = [c for c in deck.all_cards if c.rank != Rank.NINE and c.is_wild_joker]
        assert non_nines_wild == []

    def test_cut_printed_joker_falls_back_to_ace(self):
        deck = Deck(num_sub_decks=2, rng_seed=11)
        deck.shuffle(seed=11)
        target_index = next(
            i for i, c in enumerate(deck.stock) if c.id == "JK-PJ-1"
        )
        info = deck.cut_joker(index=target_index)

        assert info.ace_fallback is True
        assert info.wild_rank == Rank.ACE
        assert info.indicator_card.is_printed_joker is True

        # All 8 aces (4 suits x 2 decks) should be marked wild, since the
        # indicator card was a printed joker, not an ace itself.
        aces = [c for c in deck.all_cards if c.rank == Rank.ACE]
        assert len(aces) == 8
        assert all(c.is_wild_joker for c in aces)
        assert len(info.wild_card_ids) == 8

    def test_cut_joker_moves_indicator_to_discard_pile(self):
        deck = Deck(num_sub_decks=2, rng_seed=3)
        deck.shuffle(seed=3)
        stock_size_before = len(deck.stock)
        info = deck.cut_joker(index=0)
        assert len(deck.stock) == stock_size_before - 1
        assert deck.discard_pile == [info.indicator_card]

    def test_cut_joker_twice_raises(self):
        deck = Deck(num_sub_decks=2, rng_seed=3)
        deck.shuffle(seed=3)
        deck.cut_joker(index=0)
        with pytest.raises(Exception):
            deck.cut_joker(index=0)

    def test_cut_joker_on_empty_stock_raises(self):
        deck = Deck(num_sub_decks=2, rng_seed=3)
        deck.stock = []
        with pytest.raises(EmptyPileError):
            deck.cut_joker()

    def test_cut_joker_random_when_no_index_given(self):
        deck = Deck(num_sub_decks=2, rng_seed=42)
        deck.shuffle(seed=42)
        info = deck.cut_joker()
        assert info.wild_rank in list(STANDARD_RANKS) + [Rank.ACE]
        assert info.indicator_card not in deck.stock


# ----------------------------------------------------------------------
# Dealing
# ----------------------------------------------------------------------
class TestDeal:
    def _prepared_deck(self, seed: int = 21) -> Deck:
        deck = Deck(num_sub_decks=2, rng_seed=seed)
        deck.shuffle(seed=seed)
        deck.cut_joker(index=0)
        return deck

    def test_deal_requires_wild_joker_first(self):
        deck = Deck(num_sub_decks=2, rng_seed=21)
        deck.shuffle(seed=21)
        with pytest.raises(WildJokerNotSetError):
            deck.deal(num_players=4)

    def test_deal_four_players_thirteen_cards_each(self):
        deck = self._prepared_deck()
        stock_before = len(deck.stock)
        hands = deck.deal(num_players=4, cards_per_player=13)

        assert set(hands.keys()) == {1, 2, 3, 4}
        for player, hand in hands.items():
            assert len(hand) == 13

        dealt_ids = [c.id for h in hands.values() for c in h]
        assert len(dealt_ids) == len(set(dealt_ids)) == 52
        assert len(deck.stock) == stock_before - 52

    def test_deal_round_robin_order(self):
        deck = Deck(num_sub_decks=2, rng_seed=99)
        deck.shuffle(seed=99)
        deck.cut_joker(index=0)
        expected_first_round = [deck.stock[i].id for i in range(3)]
        hands = deck.deal(num_players=3, cards_per_player=13)
        first_round_dealt = [hands[1][0].id, hands[2][0].id, hands[3][0].id]
        assert first_round_dealt == expected_first_round

    def test_deal_rejects_out_of_range_player_counts(self):
        deck = self._prepared_deck()
        with pytest.raises(InvalidPlayerCountError):
            deck.deal(num_players=1)
        deck2 = self._prepared_deck(seed=22)
        with pytest.raises(InvalidPlayerCountError):
            deck2.deal(num_players=7)

    def test_deal_insufficient_cards_raises(self):
        deck = self._prepared_deck()
        with pytest.raises(InsufficientCardsError):
            deck.deal(num_players=6, cards_per_player=20)  # needs 120 > available

    def test_deal_twice_extends_hands_from_remaining_stock(self):
        deck = self._prepared_deck()
        deck.deal(num_players=2, cards_per_player=13)
        stock_after_first_deal = len(deck.stock)
        # Dealing again (e.g. a new round) replaces hands using the deal()
        # call's own stock state - simulate a fresh deal call.
        deck.deal(num_players=2, cards_per_player=5)
        assert len(deck.hands[1]) == 5
        assert len(deck.stock) == stock_after_first_deal - 10

    def test_full_integrity_after_deal(self):
        deck = self._prepared_deck()
        deck.deal(num_players=4, cards_per_player=13)
        assert deck.validate_integrity() is True


# ----------------------------------------------------------------------
# Draw / discard mechanics
# ----------------------------------------------------------------------
class TestDrawAndDiscard:
    def _dealt_deck(self, seed: int = 55) -> Deck:
        deck = Deck(num_sub_decks=2, rng_seed=seed)
        deck.shuffle(seed=seed)
        deck.cut_joker(index=0)
        deck.deal(num_players=2, cards_per_player=13)
        return deck

    def test_draw_from_stock_removes_top_card(self):
        deck = self._dealt_deck()
        stock_before = len(deck.stock)
        top_card = deck.stock[0]
        drawn = deck.draw()
        assert drawn.id == top_card.id
        assert len(deck.stock) == stock_before - 1
        assert drawn not in deck.stock

    def test_draw_discard_removes_top_of_discard_pile(self):
        deck = self._dealt_deck()
        card = deck.draw()
        deck.discard(card)
        assert deck.discard_pile[-1].id == card.id
        drawn_back = deck.draw_discard()
        assert drawn_back.id == card.id
        assert card not in deck.discard_pile

    def test_draw_with_from_discard_flag_matches_draw_discard(self):
        deck = self._dealt_deck()
        card = deck.draw()
        deck.discard(card)
        drawn_back = deck.draw(from_discard=True)
        assert drawn_back.id == card.id

    def test_draw_discard_on_empty_pile_raises(self):
        deck = self._dealt_deck()
        # cut_joker() seeds the discard pile with the indicator card; drain
        # it so the pile is genuinely empty for this test.
        deck.discard_pile.clear()
        with pytest.raises(EmptyPileError):
            deck.draw_discard()

    def test_draw_reshuffles_discard_when_stock_empty(self):
        deck = self._dealt_deck()
        # cut_joker() already placed its indicator card into the discard
        # pile; account for it alongside the cards we drain and discard here.
        preexisting_discard_count = len(deck.discard_pile)
        drained_ids = []
        while deck.stock:
            c = deck.draw()
            drained_ids.append(c.id)
            deck.discard(c)

        assert len(deck.stock) == 0
        assert len(deck.discard_pile) == len(drained_ids) + preexisting_discard_count

        # Next draw() should trigger an automatic reshuffle-from-discard.
        next_card = deck.draw()
        assert next_card.id in drained_ids
        # Exactly one card (the prior top-of-discard) should remain out of stock.
        assert len(deck.discard_pile) == 1

    def test_draw_raises_when_both_piles_truly_empty(self):
        deck = self._dealt_deck()
        deck.stock = []
        deck.discard_pile = []
        with pytest.raises(EmptyPileError):
            deck.draw()

    def test_reshuffle_keeps_top_discard_card_face_up_and_out_of_stock(self):
        deck = self._dealt_deck()
        while deck.stock:
            c = deck.draw()
            deck.discard(c)
        top_before_reshuffle = deck.discard_pile[-1]

        deck.draw()  # triggers reshuffle
        assert deck.discard_pile == [top_before_reshuffle]
        assert top_before_reshuffle not in deck.stock


# ----------------------------------------------------------------------
# End-to-end sanity check
# ----------------------------------------------------------------------
class TestEndToEndIntegrity:
    def test_full_game_setup_preserves_all_106_cards(self):
        deck = Deck(num_sub_decks=2, rng_seed=2024)
        deck.shuffle(seed=2024)
        deck.cut_joker()
        deck.deal(num_players=4, cards_per_player=13)
        # First stock card becomes the opening face-up discard card.
        deck.discard(deck.draw())

        assert deck.validate_integrity() is True

        all_ids = set()
        all_ids.update(c.id for c in deck.stock)
        all_ids.update(c.id for c in deck.discard_pile)
        for hand in deck.hands.values():
            all_ids.update(c.id for c in hand)

        assert len(all_ids) == 106
        assert all_ids == {c.id for c in deck.all_cards}
