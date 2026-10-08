"""
Rules engine for Smart Rummy (Indian 13-card Rummy).

Implements meld classification (pure sequence / impure sequence / set) and
full-hand declaration validation, per strict Indian Rummy rules:

  * Pure sequence: 3+ consecutive same-suit cards, no joker substitution.
    A card that is flagged as a wild joker (`Card.is_wild_joker`) may still
    contribute to a pure sequence if it fits its own literal suit/rank in
    the run — i.e. it is being used *naturally*, not as a wildcard.
  * Impure sequence: 3+ same-suit cards where one or more jokers (printed
    or wild, used as wildcards) fill in for missing ranks. At least one
    card must be used at its natural identity.
  * Set: 3-4 same-rank cards of different suits. Jokers may substitute for
    missing suits. Two physically identical cards (same suit + rank) can
    never both appear in the same set.
  * A valid declaration needs >= 2 sequences, at least one of them pure,
    with every remaining card forming a valid sequence or set.

No randomness, ML, or external services — purely deterministic, algorithmic
validation over `Card` objects built by `app.models.card` / `app.game.deck`.
"""

from __future__ import annotations

import itertools
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.models.card import Card, Rank

# ----------------------------------------------------------------------
# Rank ordering for sequence (run) evaluation
# ----------------------------------------------------------------------

# Base numeric order for every rank except the Ace, which is contextually
# low (1) or high (14) but never both in the same run, and never wraps
# around (K-A-2 is always invalid).
_BASE_RANK_VALUE: Dict[Rank, int] = {
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


# Numeric value of a rank, with the Ace either low (1) or high (14).
def _rank_value(rank: Rank, ace_high: bool) -> int:
    if rank == Rank.ACE:
        return 14 if ace_high else 1
    return _BASE_RANK_VALUE[rank]


# True if the ranks form an unbroken run (Ace low or high, no wrap-around).
def _is_consecutive_run(ranks: List[Rank]) -> bool:
    """
    True if `ranks` (no jokers involved) form a strictly consecutive,
    duplicate-free run under EITHER an ace-low (A-2-3...) or ace-high
    (...Q-K-A) interpretation. Round-the-corner runs (K-A-2) fail both
    interpretations by construction and are correctly rejected.
    """
    if len(ranks) != len(set(ranks)):
        return False
    for ace_high in (False, True):
        values = sorted(_rank_value(r, ace_high) for r in ranks)
        if values[-1] - values[0] == len(values) - 1:
            return True
    return False


# True if real cards plus the available jokers can fill a run of the given length.
def _run_feasible(existing_ranks: List[Rank], jokers_available: int, run_length: int) -> bool:
    """
    True if `existing_ranks` (distinct, real ranks already anchored in the
    run) can be extended to a consecutive run of exactly `run_length` cards
    using at most `jokers_available` wildcard substitutes, under either an
    ace-low or ace-high interpretation, without wrapping around.

    Requires at least one existing (anchor) rank — a run with zero real
    anchors is ambiguous (any window would technically "fit") and is
    intentionally rejected.
    """
    if not existing_ranks:
        return False
    if len(existing_ranks) != len(set(existing_ranks)):
        return False

    for ace_high in (False, True):
        lower_bound = 2 if ace_high else 1
        upper_bound = 14 if ace_high else 13
        values = [_rank_value(r, ace_high) for r in existing_ranks]
        min_v, max_v = min(values), max(values)
        span = max_v - min_v + 1
        if span > run_length:
            continue

        lo = max(lower_bound, max_v - run_length + 1)
        hi = min(min_v, upper_bound - run_length + 1)
        if lo > hi:
            continue

        jokers_needed = run_length - len(existing_ranks)
        if jokers_needed <= jokers_available:
            return True
    return False


# ----------------------------------------------------------------------
# Result models
# ----------------------------------------------------------------------
class MeldType(str, Enum):
    PURE_SEQUENCE = "pure_sequence"
    IMPURE_SEQUENCE = "impure_sequence"
    SET = "set"
    INVALID = "invalid"


class MeldValidationResult(BaseModel):
    """Outcome of classifying a single proposed group of cards."""

    meld_type: MeldType
    is_valid: bool
    card_ids: List[str]
    reason: Optional[str] = None
    natural_card_ids: List[str] = Field(default_factory=list)
    joker_substitute_ids: List[str] = Field(default_factory=list)


class DeclarationResult(BaseModel):
    """Outcome of validating a full 13/14-card hand declaration."""

    is_valid: bool
    reason: Optional[str] = None
    groups: List[MeldValidationResult] = Field(default_factory=list)
    pure_sequence_count: int = 0
    impure_sequence_count: int = 0
    set_count: int = 0
    total_cards: int = 0


# ----------------------------------------------------------------------
# Single-group classification
# ----------------------------------------------------------------------
# Classifies a group as a pure sequence (same suit, in a row, no jokers) if it is one.
def _try_pure_sequence(cards: List[Card]) -> Optional[MeldValidationResult]:
    if len(cards) < 3:
        return None
    if any(c.is_printed_joker for c in cards):
        return None  # a printed joker can never contribute to a pure sequence

    suits = {c.suit for c in cards}
    if len(suits) != 1:
        return None  # every card's literal suit must match

    ranks = [c.rank for c in cards]
    if not _is_consecutive_run(ranks):
        return None

    ids = [c.id for c in cards]
    return MeldValidationResult(
        meld_type=MeldType.PURE_SEQUENCE,
        is_valid=True,
        card_ids=ids,
        natural_card_ids=ids,
        joker_substitute_ids=[],
    )


# Tries to build a sequence in one suit using jokers to fill the gaps.
def _sequence_candidate(
    target_suit,
    literal_cards: List[Card],
    printed_jokers: List[Card],
    run_length: int,
) -> Optional[Tuple[List[str], List[str]]]:
    """
    Attempt to build a `run_length`-card impure sequence of `target_suit`
    using `literal_cards` (non-printed-joker cards) plus `printed_jokers`
    as wildcards.

    Non-wild cards of `target_suit` are always used at their natural rank
    (no choice). Wild-joker cards (regardless of their own literal suit)
    may be used EITHER naturally (if same suit, contributing their literal
    rank) OR as a generic wildcard substitute — whichever combination
    yields a feasible run is tried, preferring to maximize natural usage.

    Returns (natural_card_ids, joker_substitute_ids) on success, else None.
    """
    forced_natural = [c for c in literal_cards if c.suit == target_suit and not c.is_wild_joker]
    invalid_literal = [c for c in literal_cards if c.suit != target_suit and not c.is_wild_joker]
    if invalid_literal:
        return None  # a normal card of the wrong suit can never belong here

    forced_ranks = [c.rank for c in forced_natural]
    if len(forced_ranks) != len(set(forced_ranks)):
        return None  # two forced (non-wild) cards share a rank - unresolvable

    optional_natural = [c for c in literal_cards if c.suit == target_suit and c.is_wild_joker]
    out_of_suit_flexible = [c for c in literal_cards if c.suit != target_suit and c.is_wild_joker]
    base_substitutes = printed_jokers + out_of_suit_flexible

    for subset_size in range(len(optional_natural), -1, -1):
        for subset in itertools.combinations(optional_natural, subset_size):
            natural_cards = forced_natural + list(subset)
            if not natural_cards:
                continue
            ranks = [c.rank for c in natural_cards]
            if len(ranks) != len(set(ranks)):
                continue

            subset_ids = {c.id for c in subset}
            remaining_optional = [c for c in optional_natural if c.id not in subset_ids]
            jokers_available = len(base_substitutes) + len(remaining_optional)

            if _run_feasible(ranks, jokers_available, run_length):
                jokers_used = run_length - len(natural_cards)
                substitute_pool = base_substitutes + remaining_optional
                substitute_ids = [c.id for c in substitute_pool[:jokers_used]]
                natural_ids = [c.id for c in natural_cards]
                return natural_ids, substitute_ids
    return None


# Classifies a group as a sequence that uses jokers, if it is one.
def _try_impure_sequence(cards: List[Card]) -> Optional[MeldValidationResult]:
    if len(cards) < 3:
        return None

    printed_jokers = [c for c in cards if c.is_printed_joker]
    literal_cards = [c for c in cards if not c.is_printed_joker]
    if not literal_cards:
        return None  # no real card anywhere - can't anchor a sequence

    candidate_suits = {c.suit for c in literal_cards}
    run_length = len(cards)

    for target_suit in candidate_suits:
        result = _sequence_candidate(target_suit, literal_cards, printed_jokers, run_length)
        if result is None:
            continue
        natural_ids, substitute_ids = result
        if not substitute_ids:
            continue  # zero jokers used => this is a pure sequence, not impure
        return MeldValidationResult(
            meld_type=MeldType.IMPURE_SEQUENCE,
            is_valid=True,
            card_ids=[c.id for c in cards],
            natural_card_ids=natural_ids,
            joker_substitute_ids=substitute_ids,
        )
    return None


# Classifies a group as a set (3-4 cards of one rank, different suits), if it is one.
def _try_set(cards: List[Card]) -> Optional[MeldValidationResult]:
    if not (3 <= len(cards) <= 4):
        return None

    printed_jokers = [c for c in cards if c.is_printed_joker]
    literal_cards = [c for c in cards if not c.is_printed_joker]
    if not literal_cards:
        return None

    candidate_ranks = {c.rank for c in literal_cards}

    for target_rank in candidate_ranks:
        forced_natural = [c for c in literal_cards if c.rank == target_rank and not c.is_wild_joker]
        invalid_literal = [c for c in literal_cards if c.rank != target_rank and not c.is_wild_joker]
        if invalid_literal:
            continue  # a normal card of the wrong rank can never belong here

        forced_suits = [c.suit for c in forced_natural]
        if len(forced_suits) != len(set(forced_suits)):
            continue  # two identical (same suit+rank) forced cards - invalid duplicate

        # Every wild-joker literal card (whether or not its own rank matches
        # target_rank) is free to act as a generic wildcard substitute for a
        # missing suit - this is always at least as good as forcing it
        # natural, and resolves any suit collision automatically.
        flexible_cards = printed_jokers + [c for c in literal_cards if c.is_wild_joker]

        if not forced_natural and not any(c.rank == target_rank for c in flexible_cards):
            continue  # no real card actually establishes this rank

        total_slots = len(forced_natural) + len(flexible_cards)
        if total_slots != len(cards):
            continue  # should always hold, but guard defensively
        if total_slots > 4:
            continue

        return MeldValidationResult(
            meld_type=MeldType.SET,
            is_valid=True,
            card_ids=[c.id for c in cards],
            natural_card_ids=[c.id for c in forced_natural],
            joker_substitute_ids=[c.id for c in flexible_cards],
        )
    return None


# Says whether a group is a pure sequence, joker sequence, set, or invalid.
def classify_group(cards: List[Card]) -> MeldValidationResult:
    """
    Classify a single proposed group of cards as a pure sequence, impure
    sequence, or set. Tries pure first (most specific/strict), then impure,
    then set, returning the first successful classification.
    """
    if len(cards) < 3:
        return MeldValidationResult(
            meld_type=MeldType.INVALID,
            is_valid=False,
            card_ids=[c.id for c in cards],
            reason=f"A meld requires at least 3 cards, got {len(cards)}",
        )

    ids = [c.id for c in cards]
    if len(ids) != len(set(ids)):
        return MeldValidationResult(
            meld_type=MeldType.INVALID,
            is_valid=False,
            card_ids=ids,
            reason="Duplicate card instance within the same group",
        )

    for attempt in (_try_pure_sequence, _try_impure_sequence, _try_set):
        result = attempt(cards)
        if result is not None:
            return result

    return MeldValidationResult(
        meld_type=MeldType.INVALID,
        is_valid=False,
        card_ids=ids,
        reason="these cards are not a sequence or a set",
    )


# ----------------------------------------------------------------------
# Full-hand declaration validation (explicit arrangement)
# ----------------------------------------------------------------------
# Checks a full declaration: every group valid, 2+ sequences, at least 1 pure.
def validate_arrangement(groups: List[List[Card]]) -> DeclarationResult:
    """
    Validate an explicit, already-formed arrangement of a hand into groups.

    Every group is classified independently; the overall declaration is
    valid only if every group is itself valid AND the combined groups
    contain at least 2 sequences (pure or impure) with at least 1 pure
    sequence among them.
    """
    all_cards = [card for group in groups for card in group]
    all_ids = [c.id for c in all_cards]
    total_cards = len(all_ids)

    if len(all_ids) != len(set(all_ids)):
        return DeclarationResult(
            is_valid=False,
            reason="A card was used in more than one group",
            total_cards=total_cards,
        )

    if total_cards not in (13, 14):
        return DeclarationResult(
            is_valid=False,
            reason=f"A declaration must contain 13 or 14 cards, got {total_cards}",
            total_cards=total_cards,
        )

    classified = [classify_group(group) for group in groups]

    invalid_indices = [i for i, r in enumerate(classified) if not r.is_valid]
    if invalid_indices:
        first = invalid_indices[0]
        return DeclarationResult(
            is_valid=False,
            reason=f"group {first + 1} is invalid ({classified[first].reason})",
            groups=classified,
            total_cards=total_cards,
        )

    pure_count = sum(1 for r in classified if r.meld_type == MeldType.PURE_SEQUENCE)
    impure_count = sum(1 for r in classified if r.meld_type == MeldType.IMPURE_SEQUENCE)
    set_count = sum(1 for r in classified if r.meld_type == MeldType.SET)
    sequence_count = pure_count + impure_count

    if sequence_count < 2:
        return DeclarationResult(
            is_valid=False,
            reason=f"At least 2 sequences are required, you have {sequence_count}",
            groups=classified,
            pure_sequence_count=pure_count,
            impure_sequence_count=impure_count,
            set_count=set_count,
            total_cards=total_cards,
        )

    if pure_count < 1:
        return DeclarationResult(
            is_valid=False,
            reason="At least 1 pure sequence is required among the sequences",
            groups=classified,
            pure_sequence_count=pure_count,
            impure_sequence_count=impure_count,
            set_count=set_count,
            total_cards=total_cards,
        )

    return DeclarationResult(
        is_valid=True,
        reason=None,
        groups=classified,
        pure_sequence_count=pure_count,
        impure_sequence_count=impure_count,
        set_count=set_count,
        total_cards=total_cards,
    )


# ----------------------------------------------------------------------
# Full-hand declaration validation (automatic search)
# ----------------------------------------------------------------------
_MAX_SEARCH_GROUP_SIZE = 8


# Searches all groupings of a hand for any valid declaration.
def find_valid_declaration(hand: List[Card]) -> DeclarationResult:
    """
    Determine whether `hand` (13 or 14 cards) CAN be arranged into a valid
    declaration at all, searching over possible groupings via backtracking.

    Returns the first valid arrangement found (>= 2 sequences, >= 1 pure),
    or an invalid result explaining that no valid arrangement exists.
    """
    total_cards = len(hand)
    if total_cards not in (13, 14):
        return DeclarationResult(
            is_valid=False,
            reason=f"A declaration must contain 13 or 14 cards, got {total_cards}",
            total_cards=total_cards,
        )

    ids = [c.id for c in hand]
    if len(ids) != len(set(ids)):
        return DeclarationResult(
            is_valid=False,
            reason="Hand contains duplicate card instances",
            total_cards=total_cards,
        )

    id_to_card: Dict[str, Card] = {c.id: c for c in hand}
    all_ids: FrozenSet[str] = frozenset(id_to_card.keys())

    unsolvable: set = set()

    # Recursive step: try every valid group containing the first remaining card.
    def search(
        remaining: FrozenSet[str], groups_so_far: List[MeldValidationResult]
    ) -> Optional[List[MeldValidationResult]]:
        if not remaining:
            pure_count = sum(1 for g in groups_so_far if g.meld_type == MeldType.PURE_SEQUENCE)
            sequence_count = sum(
                1 for g in groups_so_far if g.meld_type in (MeldType.PURE_SEQUENCE, MeldType.IMPURE_SEQUENCE)
            )
            if sequence_count >= 2 and pure_count >= 1:
                return groups_so_far
            return None

        if remaining in unsolvable:
            return None

        remaining_list = sorted(remaining)
        fixed_id = remaining_list[0]
        others = remaining_list[1:]
        max_size = min(len(remaining), _MAX_SEARCH_GROUP_SIZE)

        for size in range(3, max_size + 1):
            for combo in itertools.combinations(others, size - 1):
                group_ids = frozenset(combo) | {fixed_id}
                group_cards = [id_to_card[i] for i in group_ids]
                result = classify_group(group_cards)
                if not result.is_valid:
                    continue
                new_remaining = remaining - group_ids
                solved = search(new_remaining, groups_so_far + [result])
                if solved is not None:
                    return solved

        unsolvable.add(remaining)
        return None

    solution = search(all_ids, [])
    if solution is None:
        return DeclarationResult(
            is_valid=False,
            reason="No valid arrangement exists: could not form >= 2 sequences (>= 1 pure) from this hand",
            total_cards=total_cards,
        )

    pure_count = sum(1 for g in solution if g.meld_type == MeldType.PURE_SEQUENCE)
    impure_count = sum(1 for g in solution if g.meld_type == MeldType.IMPURE_SEQUENCE)
    set_count = sum(1 for g in solution if g.meld_type == MeldType.SET)

    return DeclarationResult(
        is_valid=True,
        reason=None,
        groups=solution,
        pure_sequence_count=pure_count,
        impure_sequence_count=impure_count,
        set_count=set_count,
        total_cards=total_cards,
    )
