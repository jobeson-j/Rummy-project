"""
Deck management for Smart Rummy (Indian 13-card Rummy).

Builds the 106-card shoe (2 x 52-card decks + 2 printed jokers), handles
shuffling, the wild-joker "cut", dealing to players, and draw/discard
mechanics for gameplay. Everything here is deterministic, seedable, and
purely algorithmic — no ML, no external services.

Typical usage:

    deck = Deck(num_sub_decks=2, rng_seed=42)
    deck.shuffle()
    wild_info = deck.cut_joker()
    hands = deck.deal(num_players=4, cards_per_player=13)
    # place the next stock card as the first open/discard card
    deck.discard(deck.draw())

    card = deck.draw()                # draw from closed deck (stock)
    card = deck.draw(from_discard=True)  # equivalent to draw_discard()
    deck.discard(some_card)           # player discards a card face-up
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from app.models.card import (
    STANDARD_RANKS,
    STANDARD_SUITS,
    Card,
    Rank,
    Suit,
    WildJokerInfo,
)

MIN_PLAYERS = 2
MAX_PLAYERS = 6
DEFAULT_HAND_SIZE = 13


class DeckError(Exception):
    """Base exception for all deck/dealing related errors."""


class InsufficientCardsError(DeckError):
    """Raised when an operation needs more cards than are available."""


class InvalidPlayerCountError(DeckError):
    """Raised when `deal()` is called with an out-of-range player count."""


class WildJokerNotSetError(DeckError):
    """Raised when an operation that requires a cut wild joker runs before one exists."""


class EmptyPileError(DeckError):
    """Raised when drawing from a pile (stock or discard) that has no cards."""


class Deck:
    """
    Manages the full lifecycle of an Indian Rummy card shoe: construction,
    shuffling, wild-joker cutting, dealing, and the draw/discard piles used
    during play.

    Card objects are created exactly once (in `_build_deck`) and are then
    passed by reference between `stock`, `hands`, and `discard_pile`. This
    means mutating a card (e.g. `is_wild_joker`) is visible everywhere that
    card currently lives, and no card is ever duplicated or lost.
    """

    # Creates a shoe of 1-2 decks plus printed jokers, with an optional fixed seed.
    def __init__(self, num_sub_decks: int = 2, rng_seed: Optional[int] = None):
        if num_sub_decks < 1:
            raise ValueError("num_sub_decks must be at least 1")
        self.num_sub_decks = num_sub_decks
        self._rng = random.Random(rng_seed)

        self.all_cards: List[Card] = []
        self._cards_by_id: Dict[str, Card] = {}

        self.stock: List[Card] = []
        self.discard_pile: List[Card] = []
        self.hands: Dict[int, List[Card]] = {}

        self.wild_joker_info: Optional[WildJokerInfo] = None

        self._build_deck()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    # Fills the stock with every card of every sub-deck.
    def _build_deck(self) -> None:
        """Create the full shoe: N standard 52-card decks + N printed jokers."""
        self.all_cards.clear()
        self._cards_by_id.clear()

        for deck_no in range(1, self.num_sub_decks + 1):
            for suit in STANDARD_SUITS:
                for rank in STANDARD_RANKS:
                    card = Card(
                        id=Card.make_id(suit, rank, deck_no),
                        suit=suit,
                        rank=rank,
                        deck_no=deck_no,
                    )
                    self.all_cards.append(card)
                    self._cards_by_id[card.id] = card

            printed_joker = Card(
                id=Card.make_id(Suit.JOKER, Rank.PRINTED_JOKER, deck_no),
                suit=Suit.JOKER,
                rank=Rank.PRINTED_JOKER,
                deck_no=deck_no,
            )
            self.all_cards.append(printed_joker)
            self._cards_by_id[printed_joker.id] = printed_joker

        # Freshly built deck starts fully in the stock (closed/draw pile).
        self.stock = list(self.all_cards)
        self.discard_pile = []
        self.hands = {}
        self.wild_joker_info = None

    # Total number of cards in the shoe.
    @property
    def total_card_count(self) -> int:
        """Total number of physical cards in this shoe (106 for 2 sub-decks)."""
        return self.num_sub_decks * 53  # 52 standard + 1 printed joker per sub-deck

    # Finds a card by its id, or raises if it doesn't exist.
    def get_card(self, card_id: str) -> Card:
        try:
            return self._cards_by_id[card_id]
        except KeyError as exc:
            raise KeyError(f"No card with id {card_id!r} exists in this deck") from exc

    # ------------------------------------------------------------------
    # Shuffling
    # ------------------------------------------------------------------
    # Shuffles the stock (optionally with a new seed).
    def shuffle(self, seed: Optional[int] = None) -> None:
        """
        Shuffle the stock (closed deck) in place.

        Only the stock is shuffled — cards already dealt into hands or sitting
        in the discard pile are untouched. Pass `seed` to make a specific
        shuffle reproducible (useful for tests / replay debugging).
        """
        if seed is not None:
            self._rng.seed(seed)
        self._rng.shuffle(self.stock)

    # ------------------------------------------------------------------
    # Wild joker cut
    # ------------------------------------------------------------------
    # Cuts a card to pick this round's wild joker rank and marks those cards as wild.
    def cut_joker(self, index: Optional[int] = None) -> WildJokerInfo:
        """
        Cut a card from the stock to determine the Wild Joker rank.

        Every remaining card (in stock and, once dealt, in hands) whose rank
        matches the cut card's rank becomes a Wild Joker (`is_wild_joker =
        True`). If the cut card is itself a Printed Joker, the Ace rank
        becomes the Wild Joker rank instead (Ace-fallback rule).

        The cut (indicator) card itself is set aside into the discard pile
        as the first face-up card and is NOT marked as a wild joker, since
        it leaves play immediately.

        Args:
            index: Optional explicit position in `stock` to cut at. If
                omitted, a uniformly random position is chosen using this
                deck's RNG (seedable via `rng_seed` / `shuffle(seed=...)`).

        Returns:
            WildJokerInfo describing the indicator card, the resulting wild
            rank, whether the Ace-fallback rule applied, and the ids of
            every card that was marked wild.

        Raises:
            EmptyPileError: if the stock has no cards left to cut from.
            DeckError: if a wild joker has already been cut for this deck.
        """
        if not self.stock:
            raise EmptyPileError("Cannot cut joker: stock is empty")
        if self.wild_joker_info is not None:
            raise DeckError("A wild joker has already been cut for this deck")

        if index is None:
            index = self._rng.randrange(len(self.stock))
        if not (0 <= index < len(self.stock)):
            raise IndexError(f"Cut index {index} out of range for stock of size {len(self.stock)}")

        indicator = self.stock.pop(index)

        ace_fallback = indicator.rank == Rank.PRINTED_JOKER
        wild_rank = Rank.ACE if ace_fallback else indicator.rank

        wild_card_ids: List[str] = []
        for card in self.all_cards:
            if card.id == indicator.id:
                continue
            if card.rank == wild_rank:
                card.is_wild_joker = True
                wild_card_ids.append(card.id)

        info = WildJokerInfo(
            indicator_card=indicator,
            wild_rank=wild_rank,
            ace_fallback=ace_fallback,
            wild_card_ids=wild_card_ids,
        )
        self.wild_joker_info = info

        # The cut card conventionally becomes the first face-up (open) card.
        self.discard_pile.append(indicator)

        return info

    # ------------------------------------------------------------------
    # Dealing
    # ------------------------------------------------------------------
    # Deals the given number of cards to each player from the stock.
    def deal(self, num_players: int, cards_per_player: int = DEFAULT_HAND_SIZE) -> Dict[int, List[Card]]:
        """
        Deal `cards_per_player` cards to each of `num_players` players,
        round-robin, from the top of the stock.

        Requires that `cut_joker()` has already been called, matching real
        Indian Rummy play where the wild joker is determined before hands
        are dealt.

        Returns:
            A dict mapping player_number (1-indexed) -> list of dealt Cards.

        Raises:
            InvalidPlayerCountError: if num_players is outside [2, 6].
            WildJokerNotSetError: if called before `cut_joker()`.
            InsufficientCardsError: if the stock doesn't have enough cards.
        """
        if not (MIN_PLAYERS <= num_players <= MAX_PLAYERS):
            raise InvalidPlayerCountError(
                f"Indian Rummy supports {MIN_PLAYERS}-{MAX_PLAYERS} players, got {num_players}"
            )
        if cards_per_player < 1:
            raise ValueError("cards_per_player must be at least 1")
        if self.wild_joker_info is None:
            raise WildJokerNotSetError("cut_joker() must be called before dealing")

        total_needed = num_players * cards_per_player
        if total_needed > len(self.stock):
            raise InsufficientCardsError(
                f"Not enough cards in stock ({len(self.stock)}) to deal "
                f"{cards_per_player} cards to {num_players} players ({total_needed} needed)"
            )

        self.hands = {player: [] for player in range(1, num_players + 1)}
        for _ in range(cards_per_player):
            for player in range(1, num_players + 1):
                self.hands[player].append(self.stock.pop(0))

        return self.hands

    # ------------------------------------------------------------------
    # Draw / discard mechanics
    # ------------------------------------------------------------------
    # Takes the top card of the stock, reshuffling the discard pile if the stock is empty.
    def draw(self, from_discard: bool = False) -> Card:
        """
        Draw the top card from the closed deck (stock), or from the open
        deck (discard pile) if `from_discard=True`.

        If the stock is empty, it is automatically replenished by reshuffling
        the discard pile (except its current top/open card) back into stock,
        matching standard Rummy rules.
        """
        if from_discard:
            return self.draw_discard()

        if not self.stock:
            self._reshuffle_discard_into_stock()
        if not self.stock:
            raise EmptyPileError("No cards left to draw: stock and discard pile are both empty")

        return self.stock.pop(0)

    # Takes the top card of the discard pile.
    def draw_discard(self) -> Card:
        """Draw (pick up) the top-most face-up card from the discard pile."""
        if not self.discard_pile:
            raise EmptyPileError("Discard pile is empty; cannot draw from it")
        return self.discard_pile.pop()

    # Puts a card face up on top of the discard pile.
    def discard(self, card: Card) -> None:
        """Place a card face-up on top of the discard pile."""
        self.discard_pile.append(card)

    # Turns the discard pile (except its top card) into a fresh stock.
    def _reshuffle_discard_into_stock(self) -> None:
        """
        Replenish an empty stock by shuffling the discard pile back in,
        keeping the current top (most recently discarded) card face-up in
        an otherwise-empty discard pile.
        """
        if len(self.discard_pile) <= 1:
            # Nothing meaningful to reshuffle (0 or 1 cards can't refill stock).
            return
        top_card = self.discard_pile.pop()
        remaining = self.discard_pile
        self.discard_pile = [top_card]
        self._rng.shuffle(remaining)
        self.stock = remaining

    # ------------------------------------------------------------------
    # Introspection helpers (useful for tests / debugging / UI state)
    # ------------------------------------------------------------------
    # Number of cards left in the stock.
    def remaining_stock_count(self) -> int:
        return len(self.stock)

    # Number of cards in the discard pile.
    def remaining_discard_count(self) -> int:
        return len(self.discard_pile)

    # Every card currently in a player's hand.
    def all_dealt_cards(self) -> List[Card]:
        cards: List[Card] = []
        for hand in self.hands.values():
            cards.extend(hand)
        return cards

    # Counts of cards by location, for tests and debugging.
    def composition_summary(self) -> Dict[str, int]:
        """
        Return counts of key card categories across the whole 106-card shoe,
        useful for sanity-checking deck integrity in tests.
        """
        summary = {
            "total": len(self.all_cards),
            "printed_jokers": sum(1 for c in self.all_cards if c.is_printed_joker),
            "wild_jokers": sum(1 for c in self.all_cards if c.is_wild_joker),
            "standard_cards": sum(1 for c in self.all_cards if not c.is_printed_joker),
        }
        for suit in STANDARD_SUITS:
            summary[f"suit_{suit.value}"] = sum(1 for c in self.all_cards if c.suit == suit)
        for rank in STANDARD_RANKS:
            summary[f"rank_{rank.value}"] = sum(1 for c in self.all_cards if c.rank == rank)
        return summary

    # Checks no card has been lost or duplicated across stock, discard and hands.
    def validate_integrity(self) -> bool:
        """
        Confirm that every card currently exists in exactly one of:
        stock, discard_pile, or a player's hand — with no duplicates and
        no cards lost.
        """
        seen_ids: List[str] = []
        for pile in (self.stock, self.discard_pile, *self.hands.values()):
            seen_ids.extend(c.id for c in pile)

        if len(seen_ids) != len(self.all_cards):
            return False
        if len(set(seen_ids)) != len(seen_ids):
            return False
        return set(seen_ids) == set(self._cards_by_id.keys())
