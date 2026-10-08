"""
app/algorithms/assistant.py

Step 4 — Algorithmic Assistance Engine.

Pure classical algorithms only (greedy what-if simulation built on top of
Step 3's DP-based `find_optimal_arrangement`, plus exact combinatorial
probability). No ML/AI models anywhere in this module.

Provides three player-assistance capabilities:

  1. ``recommend_discard``  — simulate discarding each card in a 14-card
     hand, score the resulting 13-card arrangement, and surface the top 3
     discards with educational reasoning.
  2. ``recommend_pick``     — decide whether picking up the discard-pile's
     top card would improve (lower) the player's best achievable deadwood.
  3. ``calculate_draw_probability`` — exact probability of drawing at least
     one card useful to the player from the unseen portion of the deck(s).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.algorithms.hand_partitioner import (
    HandArrangement,
    enumerate_candidates_by_id,
    find_optimal_arrangement,
)
from app.models.card import RANK_SEQUENCE_ORDER, Card, Rank, Suit

# ---------------------------------------------------------------------------
# Deck composition constants (2-deck Indian Rummy: `deck_no` is 1 or 2).
# ---------------------------------------------------------------------------
NUM_DECKS = 2
PRINTED_JOKERS_PER_DECK = 1
STANDARD_CARDS_PER_DECK = 52
CARDS_PER_DECK = STANDARD_CARDS_PER_DECK + PRINTED_JOKERS_PER_DECK
TOTAL_CARDS_IN_PLAY = NUM_DECKS * CARDS_PER_DECK  # 106

_SUIT_SYMBOLS: Dict[str, str] = {
    Suit.HEARTS.value: "♥",
    Suit.DIAMONDS.value: "♦",
    Suit.CLUBS.value: "♣",
    Suit.SPADES.value: "♠",
    Suit.JOKER.value: "🃏",
}

# Scoring weights for recommend_discard (must sum to 1.0).
_WEIGHT_DEADWOOD = 0.60
_WEIGHT_SEQUENCE_PRESERVATION = 0.25
_WEIGHT_CONNECTIVITY_SAFETY = 0.15

# How many rank-steps away (same suit) still counts as "connected enough
# to plausibly complete a sequence" for connectivity scoring.
_CONNECTIVITY_RANK_RADIUS = 2


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

class DiscardOption(BaseModel):
    card: Card
    resulting_deadwood: int
    score: float
    pure_sequences_preserved: int
    impure_sequences_preserved: int
    reasoning: str
    progress_cost: int = 0


class DiscardRecommendationResponse(BaseModel):
    hand_size: int
    baseline_deadwood: int
    recommended_discards: List[DiscardOption]
    best_discard: DiscardOption


class PickRecommendationResponse(BaseModel):
    should_pick: bool
    current_deadwood: int
    expected_deadwood_after: int
    deadwood_delta: int
    reason: str


class ProbabilityResponse(BaseModel):
    target_identities: List[str]
    useful_unseen_count: int
    total_unseen_count: int
    probability: float
    probability_percentage: float
    reason: str


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

# Short text label for a card, e.g. "10♥", "Joker" or "4♣ (joker)".
def _card_display(card: Card) -> str:
    if card.is_printed_joker:
        return "Joker"
    label = f"{card.rank.value}{_SUIT_SYMBOLS.get(card.suit.value, card.suit.value)}"
    return f"{label} (joker)" if card.is_wild_joker else label


# Joins a group of cards into text like "4♥-5♥-6♥".
def _sequence_display(group: List[Card]) -> str:
    return "-".join(_card_display(c) for c in group)


# ---------------------------------------------------------------------------
# Hand progress and card connectivity (used by recommend_discard / pick)
# ---------------------------------------------------------------------------

# Penalties that give early hands a gradient: before a pure sequence exists
# every hand would otherwise count a flat 80 points, so all discards looked
# equal and the hint could pick a card that breaks a meld.
_NO_PURE_PENALTY = 30
_NO_SECOND_SEQ_PENALTY = 15
_JOKER_DISCARD_PENALTY = 100


# Scores how far a hand is from a valid declaration (lower is better).
def _progress_cost(arr: HandArrangement) -> int:
    """Lower is better. Equals the real deadwood once the declare structure
    (>= 1 pure, >= 2 sequences) exists; before that it is the ungrouped
    points plus a penalty for each missing structural requirement."""
    if arr.has_valid_structure:
        return arr.loose_points
    pure = len(arr.pure_sequences)
    seqs = pure + len(arr.impure_sequences)
    cost = arr.loose_points
    if pure == 0:
        cost += _NO_PURE_PENALTY
    if seqs < 2:
        cost += _NO_SECOND_SEQ_PENALTY
    return cost


# Sequence positions of a rank; an Ace counts as both 1 and 14.
def _rank_values(rank: Rank) -> List[int]:
    """Sequence positions of a rank. The Ace sits both below 2 and above K,
    matching the rules engine (A-2-3 and Q-K-A are both valid)."""
    if rank == Rank.ACE:
        return [1, 14]
    v = RANK_SEQUENCE_ORDER.get(rank)
    return [v] if v is not None else []


# Numeric order of a rank with Ace low (kept for older callers).
def _rank_order(rank: Rank) -> Optional[int]:  # kept for backwards compatibility
    return RANK_SEQUENCE_ORDER.get(rank)


# Cards that could form a meld with the given card (same rank, or same suit within 2).
def _neighbours(card: Card, others: List[Card]) -> List[Card]:
    """Cards in ``others`` that could form a meld with ``card``: same rank in
    another suit (set), or same suit within 2 ranks (sequence)."""
    if card.is_any_joker:
        return []
    out = []
    for o in others:
        if o.id == card.id or o.is_any_joker:
            continue
        if o.rank == card.rank and o.suit != card.suit:
            out.append(o)
        elif o.suit == card.suit and o.rank != card.rank:
            if any(abs(a - b) <= _CONNECTIVITY_RANK_RADIUS for a in _rank_values(card.rank) for b in _rank_values(o.rank)):
                out.append(o)
    return out


# Counts the sequence neighbours a card needs whose copies are all in the discard pile.
def _dead_neighbour_identities(card: Card, known_discards: Optional[List[Card]]) -> int:
    """How many of the sequence neighbours this card needs are already gone
    (both copies seen in the discard pile)."""
    if not known_discards or card.is_any_joker:
        return 0
    dead = 0
    for base in _rank_values(card.rank):
        for delta in (-2, -1, 1, 2):
            want = base + delta
            rank = Rank.ACE if want in (1, 14) else _rank_for_order(want)
            if rank is None:
                continue
            seen = sum(1 for d in known_discards if d.suit == card.suit and d.rank == rank)
            if seen >= NUM_DECKS:
                dead += 1
    return dead


# 0-100 score of how useful a card still is to the other cards.
def _connectivity_potential(card: Card, other_cards: List[Card],
                             known_discards: Optional[List[Card]] = None) -> float:
    """0-100: how useful ``card`` still is to ``other_cards``."""
    if card.is_any_joker:
        return 100.0
    score = min(100.0, len(_neighbours(card, other_cards)) * 25.0)
    return max(0.0, score - _dead_neighbour_identities(card, known_discards) * 10.0)


# Converts a sequence position (1-13) back into a Rank.
def _rank_for_order(order: int) -> Optional[Rank]:
    for rank, value in RANK_SEQUENCE_ORDER.items():
        if value == order:
            return rank
    return None


# ---------------------------------------------------------------------------
# Discard reasoning text
# ---------------------------------------------------------------------------

# Writes the plain-English explanation for why a card is a good discard.
def _build_discard_reasoning(candidate: Card, arrangement: HandArrangement,
                              resulting_deadwood: int, baseline_seq_count: int,
                              resulting_seq_count: int, connectivity: float,
                              links: Optional[List[Card]] = None) -> str:
    label = _card_display(candidate)
    links = links or []
    if candidate.is_any_joker:
        return f"{label} is a joker. Keep it: it can fill a gap in any sequence or set."
    if arrangement.is_winning_hand:
        return (f"Discarding {label} leaves a complete hand. Put {label} in the finish slot "
                f"and declare to win.")

    parts: List[str] = []
    if not links:
        parts.append(f"{label} doesn't connect to any of your loose cards")
    elif len(links) == 1:
        parts.append(f"{label} only links loosely with {_card_display(links[0])}")
    else:
        parts.append(f"{label} links with {', '.join(_card_display(c) for c in links[:3])}, "
                     f"but it is still your least useful card")
    parts[-1] += f" and is worth {candidate.points} point{'s' if candidate.points != 1 else ''}."

    if resulting_seq_count < baseline_seq_count:
        parts.append("It loosens one of your groups, but every other discard costs you more.")
    elif arrangement.has_valid_structure:
        parts.append(f"Your sequences stay intact and loose cards drop to {arrangement.loose_points} points.")
    else:
        pure = len(arrangement.pure_sequences)
        if pure == 0:
            parts.append("You still need a pure sequence, so keep cards that sit next to each other in a suit.")
        else:
            parts.append("Your melds stay intact; next, build a second sequence.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 1. Discard recommendation
# ---------------------------------------------------------------------------

# Simulates every possible discard from a 14-card hand and ranks them best-first.
def recommend_discard(hand: List[Card],
                       known_discards: Optional[List[Card]] = None,
                       top_n: int = 3) -> DiscardRecommendationResponse:
    """For each of the 14 cards, simulate discarding it and rank the outcome by:

      1. hand progress of the remaining 13 (``_progress_cost``: real deadwood
         once a valid structure exists, otherwise loose points + penalties
         for a missing pure / second sequence);
      2. how connected the card is to the remaining loose cards (partial
         melds you would give up);
      3. its point value (throw high cards first).

    Jokers are never suggested unless every card is a joker.
    """
    if len(hand) != 14:
        raise ValueError(f"recommend_discard requires exactly 14 cards (post-draw hand); got {len(hand)}.")

    ids = [c.id for c in hand]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate card instance supplied in hand.")

    candidates = enumerate_candidates_by_id(hand)
    baseline = find_optimal_arrangement(hand, candidates)
    baseline_deadwood = baseline.total_deadwood
    baseline_seq_count = len(baseline.pure_sequences) + len(baseline.impure_sequences)

    scored = []
    for i, candidate in enumerate(hand):
        remaining = hand[:i] + hand[i + 1:]
        arrangement = find_optimal_arrangement(remaining, candidates)
        cost = _progress_cost(arrangement)
        if candidate.is_any_joker:
            cost += _JOKER_DISCARD_PENALTY
        links = _neighbours(candidate, arrangement.deadwood_cards)
        connectivity = _connectivity_potential(candidate, arrangement.deadwood_cards, known_discards)
        resulting_seq_count = len(arrangement.pure_sequences) + len(arrangement.impure_sequences)
        key = (cost, connectivity, -candidate.points, candidate.id)
        scored.append((key, candidate, arrangement, resulting_seq_count, connectivity, links))

    scored.sort(key=lambda t: t[0])

    options: List[DiscardOption] = []
    prev_score = 100.0
    for key, candidate, arrangement, resulting_seq_count, connectivity, links in scored[:top_n]:
        cost = key[0]
        raw = 100.0 - cost - connectivity * 0.05
        score = round(max(0.0, min(prev_score, raw)), 1)
        prev_score = score
        options.append(DiscardOption(
            card=candidate,
            resulting_deadwood=arrangement.total_deadwood,
            score=score,
            pure_sequences_preserved=len(arrangement.pure_sequences),
            impure_sequences_preserved=len(arrangement.impure_sequences),
            reasoning=_build_discard_reasoning(
                candidate, arrangement, arrangement.total_deadwood,
                baseline_seq_count, resulting_seq_count, connectivity, links,
            ),
            progress_cost=cost,
        ))

    return DiscardRecommendationResponse(
        hand_size=len(hand),
        baseline_deadwood=baseline_deadwood,
        recommended_discards=options,
        best_discard=options[0],
    )

# ---------------------------------------------------------------------------
# 2. Pick recommendation
# ---------------------------------------------------------------------------

# Decides whether taking the top discard card would improve the hand.
def recommend_pick(hand: List[Card], discard_top: Card) -> PickRecommendationResponse:
    """Evaluates whether picking up ``discard_top`` (added to the current
    13-card ``hand``, then discarding whichever card is now least useful)
    would leave the player with lower deadwood than staying put."""
    if len(hand) != 13:
        raise ValueError(f"recommend_pick requires exactly 13 cards in hand; got {len(hand)}.")
    if any(c.id == discard_top.id for c in hand):
        raise ValueError("discard_top card is already present in hand.")

    current_arrangement = find_optimal_arrangement(hand)
    current_deadwood = current_arrangement.total_deadwood
    current_cost = _progress_cost(current_arrangement)

    hypothetical_hand = hand + [discard_top]
    discard_analysis = recommend_discard(hypothetical_hand)
    best = discard_analysis.best_discard
    expected_deadwood_after = best.resulting_deadwood
    delta = expected_deadwood_after - current_deadwood
    # Taking the card only helps if you would keep it and the hand improves.
    should_pick = best.card.id != discard_top.id and best.progress_cost < current_cost

    card_label = _card_display(discard_top)
    if should_pick:
        after_hand = [c for c in hypothetical_hand if c.id != best.card.id]
        after = find_optimal_arrangement(after_hand)
        gains = []
        if len(after.pure_sequences) > len(current_arrangement.pure_sequences):
            gains.append("gives you a pure sequence")
        elif (len(after.pure_sequences) + len(after.impure_sequences)
              > len(current_arrangement.pure_sequences) + len(current_arrangement.impure_sequences)):
            gains.append("completes another sequence")
        elif len(after.sets) > len(current_arrangement.sets):
            gains.append("completes a set")
        else:
            gains.append(f"cuts your loose cards from {current_arrangement.loose_points} to {after.loose_points} points")
        reason = (
            f"Take {card_label} from the discard pile: it {gains[0]}. "
            f"Then discard {_card_display(best.card)}."
        )
    else:
        reason = (
            f"{card_label} doesn't improve your hand. Draw from the stock instead."
        )

    return PickRecommendationResponse(
        should_pick=should_pick,
        current_deadwood=current_deadwood,
        expected_deadwood_after=expected_deadwood_after,
        deadwood_delta=delta,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# 3. Useful-card draw probability
# ---------------------------------------------------------------------------

# Number of physical copies of a card identity in the two-deck shoe.
def _copies_in_full_deck(suit: Suit, rank: Rank) -> int:
    if rank == Rank.PRINTED_JOKER:
        return NUM_DECKS * PRINTED_JOKERS_PER_DECK
    return NUM_DECKS  # exactly one physical copy of each suit+rank per deck


# Exact chance of drawing at least one useful card from the unseen cards.
def calculate_draw_probability(target_cards: List[Card], hand: List[Card],
                                visible_cards: List[Card]) -> ProbabilityResponse:
    """Exact probability of drawing at least one card matching any of the
    (suit, rank) identities in ``target_cards`` from the unseen stock:

        P = (useful unseen copies) / (total unseen cards)

    ``hand`` is the player's own 13-card hand; ``visible_cards`` is every
    other card known to be out of the stock (discard pile + any cards
    picked/shown by opponents). Both are treated as "seen" and excluded
    from the unseen pool.
    """
    target_identities: List[Tuple[Suit, Rank]] = []
    seen_identity_set = set()
    for c in target_cards:
        key = (c.suit, c.rank)
        if key not in seen_identity_set:
            seen_identity_set.add(key)
            target_identities.append(key)

    seen_cards = list(hand) + list(visible_cards)

    useful_unseen = 0
    for suit, rank in target_identities:
        total_copies = _copies_in_full_deck(suit, rank)
        already_seen = sum(1 for c in seen_cards if c.suit == suit and c.rank == rank)
        useful_unseen += max(total_copies - already_seen, 0)

    total_unseen = max(TOTAL_CARDS_IN_PLAY - len(seen_cards), 0)
    probability = (useful_unseen / total_unseen) if total_unseen > 0 else 0.0

    identity_labels = [
        f"{rank.value}{_SUIT_SYMBOLS.get(suit.value, suit.value)}" for suit, rank in target_identities
    ]

    reason = (
        f"{useful_unseen} useful card(s) among {total_unseen} unseen card(s) remain in the stock / "
        f"opponents' hands, giving a {probability * 100:.1f}% chance of drawing a useful card "
        f"({', '.join(identity_labels) if identity_labels else 'no targets specified'})."
    )

    return ProbabilityResponse(
        target_identities=identity_labels,
        useful_unseen_count=useful_unseen,
        total_unseen_count=total_unseen,
        probability=probability,
        probability_percentage=round(probability * 100, 2),
        reason=reason,
    )
