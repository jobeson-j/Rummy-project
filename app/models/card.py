"""
Core card models for Smart Rummy (Indian 13-card Rummy).

This module defines the Suit and Rank enumerations, the point-value table
used for hand scoring, and the Card pydantic model that represents a
single physical card within one of the two 52-card decks (plus the two
printed jokers).

No randomness, ML, or external services are involved here — this module
is purely a data model layer used by `backend/app/game/deck.py`.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Suit(str, Enum):
    """Card suits. JOKER is a pseudo-suit used only for the two printed jokers."""

    HEARTS = "H"
    DIAMONDS = "D"
    CLUBS = "C"
    SPADES = "S"
    JOKER = "JK"

    # Prints the suit as its one-letter code.
    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Rank(str, Enum):
    """Card ranks. PJ (Printed Joker) has no suit-equivalent in a real deck."""

    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"
    PRINTED_JOKER = "PJ"

    # Prints the rank as its short code.
    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


ORDERED_RANKS: list[Rank] = [
    Rank.ACE,
    Rank.TWO,
    Rank.THREE,
    Rank.FOUR,
    Rank.FIVE,
    Rank.SIX,
    Rank.SEVEN,
    Rank.EIGHT,
    Rank.NINE,
    Rank.TEN,
    Rank.JACK,
    Rank.QUEEN,
    Rank.KING,
]

RANK_SEQUENCE_ORDER: dict[Rank, int] = {
    Rank.ACE: 1,
    Rank.TWO: 2,
    Rank.THREE: 3,
    Rank.FOUR: 4,
    Rank.FIVE: 5,
    Rank.SIX: 6,
    Rank.SEVEN: 7,
    Rank.EIGHT: 8,
    Rank.NINE: 9,
    Rank.TEN: 10,
    Rank.JACK: 11,
    Rank.QUEEN: 12,
    Rank.KING: 13,
}

STANDARD_SUITS: tuple[Suit, ...] = (
    Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES)

STANDARD_RANKS: tuple[Rank, ...] = (
    Rank.TWO,
    Rank.THREE,
    Rank.FOUR,
    Rank.FIVE,
    Rank.SIX,
    Rank.SEVEN,
    Rank.EIGHT,
    Rank.NINE,
    Rank.TEN,
    Rank.JACK,
    Rank.QUEEN,
    Rank.KING,
    Rank.ACE,
)

RANK_POINTS: dict[Rank, int] = {
    Rank.TWO: 2,
    Rank.THREE: 3,
    Rank.FOUR: 4,
    Rank.FIVE: 5,
    Rank.SIX: 6,
    Rank.SEVEN: 7,
    Rank.EIGHT: 8,
    Rank.NINE: 9,
    Rank.TEN: 10,
    Rank.JACK: 10,
    Rank.QUEEN: 10,
    Rank.KING: 10,
    Rank.ACE: 10,
    Rank.PRINTED_JOKER: 0,
}


# Point value of a rank, ignoring jokers.
def rank_base_points(rank: Rank) -> int:
    """Return the base point value of a rank, ignoring wild-joker status."""
    return RANK_POINTS[rank]


class Card(BaseModel):
    """
    A single physical playing card.

    `id` is a deterministic, globally unique identifier of the form
    `<SUIT>-<RANK>-<DECK_NO>`, e.g. `H-7-1` (Hearts 7, Deck 1) or
    `JK-PJ-2` (Printed Joker, Deck 2).
    """

    id: str
    suit: Suit
    rank: Rank
    deck_no: int = Field(default=1, ge=1, le=2)
    is_wild_joker: bool = False

    model_config = {"frozen": False}

    # Ensures the joker suit and joker rank only ever appear together.
    @model_validator(mode="after")
    def _validate_suit_rank_combo(self) -> "Card":
        is_joker_suit = self.suit == Suit.JOKER
        is_joker_rank = self.rank == Rank.PRINTED_JOKER
        if is_joker_suit != is_joker_rank:
            raise ValueError(
                "Suit.JOKER and Rank.PRINTED_JOKER must always be paired together "
                f"(got suit={self.suit}, rank={self.rank})"
            )
        return self

    # True for the physical printed joker cards.
    @property
    def is_printed_joker(self) -> bool:
        """True for the physical printed-joker cards in the shoe."""
        return self.rank == Rank.PRINTED_JOKER

    # True if the card can be used as a joker (printed or wild).
    @property
    def is_joker(self) -> bool:
        """True if this card can currently be used as *any* joker (printed or wild)."""
        return self.is_printed_joker or self.is_wild_joker

    # Alias of is_joker used by the algorithm modules.
    @property
    def is_any_joker(self) -> bool:
        """Alias for is_joker for backward compatibility with algorithm modules."""
        return self.is_joker

    # Points this card costs if left ungrouped (jokers cost 0).
    @property
    def points(self) -> int:
        """Point value of this card for hand-scoring purposes."""
        if self.is_joker:
            return 0
        return RANK_POINTS[self.rank]

    # Alias of points used by the hand partitioner.
    @property
    def point_value(self) -> int:
        """Alias for points property used across partitioning algorithms."""
        return self.points

    # Builds a card's unique id, e.g. "H-7-1".
    @staticmethod
    def make_id(suit: Suit, rank: Rank, deck_no: int) -> str:
        return f"{suit.value}-{rank.value}-{deck_no}"

    # Short text form of the card, e.g. "7H" or "7H*" for a wild joker.
    def __str__(self) -> str:  # pragma: no cover - convenience only
        if self.is_printed_joker:
            return f"PJ{self.deck_no}"
        marker = "*" if self.is_wild_joker else ""
        return f"{self.rank.value}{self.suit.value}{marker}"

    # Debug form of the card showing its id and wild flag.
    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"<Card {self.id} wild={self.is_wild_joker}>"

    # Hashes a card by its unique id.
    def __hash__(self) -> int:
        return hash(self.id)

    # Two cards are equal when their ids match.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Card):
            return NotImplemented
        return self.id == other.id


class WildJokerInfo(BaseModel):
    """Metadata describing the result of a cut-joker draw."""

    indicator_card: Card
    wild_rank: Rank
    ace_fallback: bool = False
    wild_card_ids: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}
