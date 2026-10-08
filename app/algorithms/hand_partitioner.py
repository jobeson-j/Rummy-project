"""
Hand partitioner: finds the arrangement of a hand into melds that leaves the
least deadwood, following Indian Rummy scoring.

Search strategy
---------------
The previous implementation tried every candidate meld at every level of the
recursion, which grew exponentially as a hand improved (bot turns reached
several seconds late in a round). This version uses the standard
"lowest undecided card" branching:

  * take the lowest-index card not yet decided;
  * either mark it as deadwood, or place it in one of the candidate melds
    that contains it and does not overlap already-used cards.

Each card is decided exactly once, so the state space is bounded by the
masks reachable this way and memoisation keeps it small.

Two searches are run:
  1. constrained  - the arrangement must contain >= 1 pure sequence and
                    >= 2 sequences overall (the condition for counting only
                    the ungrouped cards as deadwood);
  2. unconstrained - maximum points grouped, used only when (1) is impossible,
                    so the UI can still show the most useful grouping.
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel

from app.game.rules import MeldType, classify_group
from app.models.card import Card

FULL_HAND_CAP = 80
_NEG_INF = float("-inf")


class HandArrangement(BaseModel):
    pure_sequences: List[List[Card]]
    impure_sequences: List[List[Card]]
    sets: List[List[Card]]
    deadwood_cards: List[Card]
    total_deadwood: int
    is_winning_hand: bool
    # Points of the ungrouped cards in the arrangement shown, ignoring the
    # 80-cap rule; and whether the arrangement meets the declare structure
    # (>= 1 pure sequence and >= 2 sequences). Used for hints/progress.
    loose_points: int = 0
    has_valid_structure: bool = False


class CandidateMeld:
    __slots__ = ("cards", "meld_type", "mask", "points_saved", "ids")

    # Stores a candidate meld with its cards, type, bitmask and points saved.
    def __init__(self, cards: List[Card], meld_type: MeldType, mask: int):
        self.cards = cards
        self.meld_type = meld_type
        self.mask = mask
        self.points_saved = sum(c.point_value for c in cards)
        self.ids = frozenset(c.id for c in cards)


# Turns a list of card positions into a bitmask.
def _card_mask(indices: Sequence[int]) -> int:
    mask = 0
    for idx in indices:
        mask |= 1 << idx
    return mask


# Lists every valid 3-5 card meld that can be made from the hand.
def _enumerate_candidate_melds(hand: List[Card]) -> List[CandidateMeld]:
    """Every valid meld of 3, 4 or 5 cards drawn from ``hand``.

    Longer runs never need to be considered: any valid run of 6+ cards can
    be split into valid runs of 3-5 cards with the same total deadwood.
    """
    n = len(hand)
    candidates: List[CandidateMeld] = []
    for size in (3, 4, 5):
        if size > n:
            continue
        for combo_indices in combinations(range(n), size):
            combo_cards = [hand[i] for i in combo_indices]
            res = classify_group(combo_cards)
            if res.is_valid and res.meld_type != MeldType.INVALID:
                candidates.append(
                    CandidateMeld(combo_cards, res.meld_type, _card_mask(combo_indices))
                )
    return candidates


# Same meld list as (cards, type) pairs so it can be reused for sub-hands.
def enumerate_candidates_by_id(hand: List[Card]) -> List[Tuple[List[Card], MeldType]]:
    """Public helper: candidate melds as (cards, type) so callers can reuse
    them across many sub-hands (see ``find_optimal_arrangement``)."""
    return [(c.cards, c.meld_type) for c in _enumerate_candidate_melds(hand)]


# Memoised search for the set of melds that leaves the fewest loose points.
def _search(
    n: int,
    by_lowest: Dict[int, List[CandidateMeld]],
    constrained: bool,
) -> Tuple[float, List[CandidateMeld]]:
    full = (1 << n) - 1
    memo: Dict[Tuple[int, int, int], Tuple[float, Optional[Tuple]]] = {}

    # Recursive step: decide the lowest undecided card (loose, or part of a meld).
    def go(mask: int, pure: int, seqs: int) -> Tuple[float, Optional[Tuple]]:
        if mask == full:
            if constrained and not (pure >= 1 and seqs >= 2):
                return _NEG_INF, None
            return 0.0, None
        key = (mask, pure, seqs)
        hit = memo.get(key)
        if hit is not None:
            return hit

        # lowest undecided card
        low = (~mask & full) & -(~mask & full)
        i = low.bit_length() - 1

        # option 1: card i is deadwood
        best_val, _ = go(mask | low, pure, seqs)
        best_link: Optional[Tuple] = ("dead", i, (mask | low, pure, seqs)) if best_val != _NEG_INF else None

        # option 2: card i is part of a meld
        for cand in by_lowest.get(i, ()):
            if cand.mask & mask:
                continue
            np = min(2, pure + (1 if cand.meld_type == MeldType.PURE_SEQUENCE else 0))
            ns = min(2, seqs + (1 if cand.meld_type in (MeldType.PURE_SEQUENCE, MeldType.IMPURE_SEQUENCE) else 0))
            sub_val, _ = go(mask | cand.mask, np, ns)
            if sub_val == _NEG_INF:
                continue
            val = sub_val + cand.points_saved
            # tie-break: prefer grouping more cards (secondary, tiny weight)
            val += len(cand.cards) * 1e-3
            if val > best_val:
                best_val = val
                best_link = ("meld", cand, (mask | cand.mask, np, ns))

        memo[key] = (best_val, best_link)
        return memo[key]

    best, _ = go(0, 0, 0)
    if best == _NEG_INF:
        return best, []

    # reconstruct the chosen melds
    chosen: List[CandidateMeld] = []
    state = (0, 0, 0)
    while state[0] != full:
        _, link = memo[state]
        if link is None:
            break
        kind, payload, nxt = link
        if kind == "meld":
            chosen.append(payload)
        state = nxt
    return best, chosen


# Best grouping of a hand into sequences and sets, with its deadwood score.
def find_optimal_arrangement(
    cards: List[Card],
    candidates: Optional[List[Tuple[List[Card], MeldType]]] = None,
) -> HandArrangement:
    """Best arrangement of ``cards``.

    ``candidates`` may be a pre-computed list of melds from a superset hand
    (see ``enumerate_candidates_by_id``); melds using cards not in ``cards``
    are ignored. This avoids re-classifying thousands of combinations when
    evaluating every possible discard.
    """
    n = len(cards)
    index_of = {c.id: i for i, c in enumerate(cards)}
    total_hand_points = sum(c.point_value for c in cards)

    if candidates is None:
        cand_objs = _enumerate_candidate_melds(cards)
    else:
        cand_objs = []
        for meld_cards, meld_type in candidates:
            idxs = [index_of.get(c.id) for c in meld_cards]
            if any(i is None for i in idxs):
                continue
            cand_objs.append(CandidateMeld([cards[i] for i in idxs], meld_type, _card_mask(idxs)))

    by_lowest: Dict[int, List[CandidateMeld]] = {}
    for cand in cand_objs:
        lowest = (cand.mask & -cand.mask).bit_length() - 1
        by_lowest.setdefault(lowest, []).append(cand)

    valid_val, chosen = _search(n, by_lowest, constrained=True)
    has_valid_structure = valid_val != _NEG_INF
    if not has_valid_structure:
        _, chosen = _search(n, by_lowest, constrained=False)

    pure_sequences = [m.cards for m in chosen if m.meld_type == MeldType.PURE_SEQUENCE]
    impure_sequences = [m.cards for m in chosen if m.meld_type == MeldType.IMPURE_SEQUENCE]
    sets = [m.cards for m in chosen if m.meld_type == MeldType.SET]

    used = 0
    for m in chosen:
        used |= m.mask
    deadwood_cards = [cards[i] for i in range(n) if not (used >> i) & 1]

    # A joker adds 0 points to a meld, so the search has no reason to place a
    # spare one. Put leftover jokers into an existing meld so the hand can
    # actually be declared (sequences have no length limit; sets max 4).
    pure_sequences, impure_sequences, sets, deadwood_cards = _place_spare_jokers(
        pure_sequences, impure_sequences, sets, deadwood_cards
    )

    if has_valid_structure:
        total_deadwood = sum(c.point_value for c in deadwood_cards)
    else:
        total_deadwood = min(FULL_HAND_CAP, total_hand_points)

    return HandArrangement(
        pure_sequences=pure_sequences,
        impure_sequences=impure_sequences,
        sets=sets,
        deadwood_cards=deadwood_cards,
        total_deadwood=total_deadwood,
        is_winning_hand=has_valid_structure and not deadwood_cards,
        loose_points=sum(c.point_value for c in deadwood_cards),
        has_valid_structure=has_valid_structure,
    )


# Moves leftover jokers into existing melds so the hand can be declared.
def _place_spare_jokers(pure, impure, sets, deadwood):
    jokers = [c for c in deadwood if c.is_any_joker]
    if not jokers:
        return pure, impure, sets, deadwood
    pure, impure, sets = [list(g) for g in pure], [list(g) for g in impure], [list(g) for g in sets]
    rest = [c for c in deadwood if not c.is_any_joker]
    leftover = []
    for j in jokers:
        placed = False
        # Prefer groups where a joker is already allowed; only touch a pure
        # sequence when another pure sequence would remain.
        pools = [(impure, MeldType.IMPURE_SEQUENCE), (sets, MeldType.SET)]
        if len(pure) >= 2:
            pools.append((pure, None))
        for pool, _ in pools:
            for g in pool:
                trial = g + [j]
                res = classify_group(trial)
                if res.is_valid and res.meld_type in (MeldType.IMPURE_SEQUENCE, MeldType.SET):
                    g.append(j)
                    placed = True
                    if pool is pure:
                        pure.remove(g)
                        impure.append(g)
                    break
            if placed:
                break
        if not placed:
            leftover.append(j)
    return pure, impure, sets, rest + leftover

