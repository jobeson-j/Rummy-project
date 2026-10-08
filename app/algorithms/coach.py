"""
Coach: explains the best next move and teaches *why*.

Built on the same classical algorithms as the hints (hand partitioner +
discard simulation), plus:

  * outs       - which unseen cards would improve your hand, how many copies
                 are still unseen, and the chance the next stock card helps;
  * reads      - what each opponent has picked from the discard pile, so you
                 learn which cards are dangerous to throw;
  * tips       - one short, situation-specific strategy lesson;
  * options    - every possible discard ranked, so the UI can grade the move
                 you actually made against the best one.
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.algorithms.assistant import (
    _card_display,
    _neighbours,
    _progress_cost,
    _rank_values,
    recommend_discard,
)
from app.algorithms.hand_partitioner import (
    HandArrangement,
    enumerate_candidates_by_id,
    find_optimal_arrangement,
)
from app.game.rules import MeldType, classify_group
from app.models.card import RANK_SEQUENCE_ORDER, STANDARD_SUITS, Card, Rank, Suit

NUM_DECKS = 2
TOTAL_CARDS = 106
MAX_OUTS_SHOWN = 8


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class CoachAction(BaseModel):
    kind: str  # take_discard | draw_stock | discard | declare | drop | wait | none
    card_id: Optional[str] = None
    card_label: Optional[str] = None


class CoachOption(BaseModel):
    card: Card
    cost: int
    reasoning: str
    danger: Optional[str] = None


class CoachOut(BaseModel):
    label: str
    copies_left: int
    effect: str


class CoachRead(BaseModel):
    player_id: str
    player_name: str
    picked: List[str]
    text: str


class CoachResponse(BaseModel):
    stage: str  # draw | discard | waiting | over
    headline: str
    detail: str
    action: CoachAction
    options: List[CoachOption] = []
    take_discard_card: Optional[Card] = None
    outs: List[CoachOut] = []
    out_copies: int = 0
    unseen_cards: int = 0
    out_chance_pct: float = 0.0
    reads: List[CoachRead] = []
    tip: str = ""
    status: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Short text label for a card in coach messages.
def _label(card: Card) -> str:
    return _card_display(card)


# One-line summary of the hand: pure sequence, second sequence and loose points.
def _status(arr: HandArrangement) -> str:
    pure = len(arr.pure_sequences)
    seqs = pure + len(arr.impure_sequences)
    loose = len(arr.deadwood_cards)
    if arr.is_winning_hand:
        return "Your hand is complete."
    parts = [
        "pure sequence ✓" if pure else "no pure sequence yet",
        "second sequence ✓" if seqs >= 2 else ("second sequence missing" if pure else ""),
        f"{loose} loose card{'s' if loose != 1 else ''} ({arr.loose_points} pts)",
    ]
    return ", ".join(p for p in parts if p).capitalize() + "."


# Picks a short strategy lesson that fits the current state of the hand.
def _tip(arr: HandArrangement, stage: str, jokers_in_hand: int) -> str:
    pure = len(arr.pure_sequences)
    seqs = pure + len(arr.impure_sequences)
    if arr.is_winning_hand:
        return "When you can declare, do it straight away: every extra turn gives an opponent a chance to finish first."
    if pure == 0:
        if jokers_in_hand:
            return ("A pure sequence can't use jokers, so build it from natural cards first. "
                    "Save your jokers for the second sequence or a set.")
        return ("Your first goal is a pure sequence: 3 cards in a row of one suit. Keep pairs like 6♥-7♥ "
                "or 6♥-8♥; they need just one card.")
    if seqs < 2:
        return ("You have your pure sequence. Any second sequence will do now, and jokers are allowed, "
                "so two cards a gap apart plus a joker already counts.")
    if arr.loose_points >= 25:
        return ("Both sequences are done, so you're safe from the 80-point full count. Now shed high loose "
                "cards (A, K, Q, J, 10): each costs 10 points if someone else declares.")
    return "You're close. Keep the cards that complete your last group and throw anything that can't."


# True if a card identity would combine with a card an opponent picked up.
def _near(card_rank: Rank, card_suit: Suit, other: Card) -> bool:
    """Would ``other`` (a card an opponent picked) combine with this identity?"""
    if other.is_any_joker:
        return False
    if other.rank == card_rank and other.suit != card_suit:
        return True
    if other.suit == card_suit and other.rank != card_rank:
        return any(abs(a - b) <= 2 for a in _rank_values(card_rank) for b in _rank_values(other.rank))
    return False


# ---------------------------------------------------------------------------
# Opponent reads
# ---------------------------------------------------------------------------
# Summarises what each bot took from the discard pile and what that suggests.
def opponent_reads(engine) -> Tuple[List[CoachRead], Dict[str, List[Card]]]:
    picked: Dict[str, List[Card]] = {}
    for e in engine.events:
        if e.round_number != engine.round_number or e.player_id == "player-1":
            continue
        if e.action == "draw_discard" and e.card is not None:
            picked.setdefault(e.player_id, []).append(e.card)
    reads: List[CoachRead] = []
    for p in engine.players[1:]:
        cards = picked.get(p.id, [])
        if not cards:
            text = f"{p.name} hasn't taken anything from the discard pile yet, so there's no read on their hand."
        else:
            labels = ", ".join(_label(c) for c in cards[-3:])
            last = cards[-1]
            if last.is_any_joker:
                text = f"{p.name} picked {labels}."
            else:
                text = (f"{p.name} picked {labels}: they are probably building around it. Avoid throwing "
                        f"other {last.rank.value}s, or {_suit_name(last.suit)} close to {last.rank.value}.")
        reads.append(CoachRead(player_id=p.id, player_name=p.name, picked=[_label(c) for c in cards], text=text))
    return reads, picked


# Full suit name for a suit, e.g. "hearts".
def _suit_name(s: Suit) -> str:
    return {"H": "hearts", "D": "diamonds", "C": "clubs", "S": "spades"}.get(s.value, "")


# ---------------------------------------------------------------------------
# Outs
# ---------------------------------------------------------------------------
# Adds to a hand's meld list every meld that includes one extra card.
def _candidates_with(base: List[Tuple[List[Card], MeldType]], hand: List[Card], extra: Card):
    """Melds of hand+[extra] = melds of hand + melds that include extra."""
    out = list(base)
    for size in (2, 3, 4):
        for combo in combinations(hand, size):
            group = list(combo) + [extra]
            res = classify_group(group)
            if res.is_valid:
                out.append((group, res.meld_type))
    return out


# Best hand cost after drawing a card and throwing the least useful one.
def _best_after_draw(hand: List[Card], extra: Card, base_cands) -> Tuple[int, HandArrangement, Card]:
    """Best progress cost of the 13 cards kept after drawing ``extra``."""
    full = hand + [extra]
    cands = _candidates_with(base_cands, hand, extra)
    arr14 = find_optimal_arrangement(full, cands)
    to_try = {c.id: c for c in arr14.deadwood_cards}
    to_try[extra.id] = extra
    if not arr14.deadwood_cards:
        to_try.update({c.id: c for c in full})
    best_cost, best_arr, best_drop = 10**6, arr14, extra
    for d in to_try.values():
        if d.is_any_joker and d.id != extra.id:
            continue
        rest = [c for c in full if c.id != d.id]
        arr = find_optimal_arrangement(rest, cands)
        cost = _progress_cost(arr)
        if cost < best_cost:
            best_cost, best_arr, best_drop = cost, arr, d
    return best_cost, best_arr, best_drop


# Describes in words what drawing a card did to the hand.
def _effect(before: HandArrangement, after: HandArrangement, extra: Card) -> str:
    bp, ap = len(before.pure_sequences), len(after.pure_sequences)
    bs = bp + len(before.impure_sequences)
    as_ = ap + len(after.impure_sequences)
    if after.is_winning_hand:
        return "completes your hand"
    if ap > bp:
        return "gives you a pure sequence"
    if as_ > bs:
        return "completes your second sequence" if as_ == 2 else "adds a sequence"
    if len(after.sets) > len(before.sets):
        return "completes a set"
    return f"cuts loose points from {before.loose_points} to {after.loose_points}"


# Finds unseen cards that would improve the hand and how many copies remain.
def compute_outs(engine, hand: List[Card]) -> Tuple[List[CoachOut], int, int]:
    seen = list(hand) + list(engine.deck.discard_pile)
    unseen_total = max(TOTAL_CARDS - len(seen), 1)
    wild = engine.wild_rank
    before = find_optimal_arrangement(hand)
    before_cost = _progress_cost(before)
    base = enumerate_candidates_by_id(hand)

    # Identities worth testing: neighbours of loose cards and of cards in
    # sequences that use a joker (a natural card could purify them).
    focus = list(before.deadwood_cards) + [c for g in before.impure_sequences for c in g]
    identities = set()
    for card in focus:
        if card.is_any_joker:
            continue
        for s in STANDARD_SUITS:
            if s != card.suit:
                identities.add((s, card.rank))
        for v in _rank_values(card.rank):
            for d in (-2, -1, 1, 2):
                w = v + d
                if w in (1, 14):
                    identities.add((card.suit, Rank.ACE))
                elif 2 <= w <= 13:
                    rank = next(r for r, o in RANK_SEQUENCE_ORDER.items() if o == w)
                    identities.add((card.suit, rank))

    # How many copies of a card identity are not in your hand or the discard pile.
    def copies_unseen(suit: Suit, rank: Rank) -> int:
        return max(0, NUM_DECKS - sum(1 for c in seen if c.suit == suit and c.rank == rank))

    outs: List[Tuple[int, CoachOut]] = []
    total_copies = 0
    for suit, rank in sorted(identities, key=lambda t: (t[0].value, RANK_SEQUENCE_ORDER.get(t[1], 0))):
        if rank == wild:
            continue  # wild cards are counted with the jokers below
        left = copies_unseen(suit, rank)
        if not left:
            continue
        probe = Card(id=f"OUT-{suit.value}-{rank.value}", suit=suit, rank=rank, deck_no=1)
        cost, after, _ = _best_after_draw(hand, probe, base)
        if cost < before_cost:
            gain = before_cost - cost
            outs.append((gain, CoachOut(label=_label(probe), copies_left=left, effect=_effect(before, after, probe))))
            total_copies += left

    # Any joker (printed or wild) as one entry.
    joker_left = max(0, NUM_DECKS - sum(1 for c in seen if c.is_printed_joker))
    if wild is not None and wild != Rank.PRINTED_JOKER:
        joker_left += sum(copies_unseen(s, wild) for s in STANDARD_SUITS)
    if joker_left:
        probe = Card(id="OUT-JK", suit=Suit.JOKER, rank=Rank.PRINTED_JOKER, deck_no=1)
        cost, after, _ = _best_after_draw(hand, probe, base)
        if cost < before_cost:
            outs.append((before_cost - cost, CoachOut(label="Any joker", copies_left=joker_left,
                                                      effect=_effect(before, after, probe))))
            total_copies += joker_left

    outs.sort(key=lambda t: (-t[0], -t[1].copies_left))
    return [o for _, o in outs[:MAX_OUTS_SHOWN]], total_copies, unseen_total


# Ranks every discard, preferring ones that don't feed the next player on ties.
def ranked_discards(engine, hand: List[Card], picked: Dict[str, List[Card]]) -> List[CoachOption]:
    """Every discard from a 14-card hand, best first. Ties go to the card
    that doesn't feed the next player."""
    rec = recommend_discard(hand, known_discards=engine.deck.discard_pile, top_n=len(hand))
    human_idx = 0
    nxt = engine.players[(human_idx + 1) % len(engine.players)]
    next_picks = picked.get(nxt.id, [])
    options: List[CoachOption] = []
    for o in rec.recommended_discards:
        danger = None
        hit = next((p for p in next_picks if _near(o.card.rank, o.card.suit, p)), None)
        if hit is not None and not o.card.is_any_joker:
            danger = f"{nxt.name} (next to play) picked {_label(hit)}, so {_label(o.card)} may help them."
        options.append(CoachOption(card=o.card, cost=o.progress_cost, reasoning=o.reasoning, danger=danger))
    options.sort(key=lambda o: (o.cost, o.danger is not None))
    return options


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
# Builds the full coach response (best move, reason, outs, reads, tip) for the human.
def coach(engine) -> CoachResponse:
    human = engine.players[0]
    hand = list(human.hand)
    reads, picked = opponent_reads(engine)
    jokers = sum(1 for c in hand if c.is_any_joker)

    if engine.round_over:
        return CoachResponse(stage="over", headline="Round over", detail="Review the hands on the results screen.",
                             action=CoachAction(kind="none"), reads=reads)

    if not engine.current_player.is_human:
        arr = find_optimal_arrangement(hand)
        outs, out_copies, unseen = compute_outs(engine, hand) if len(hand) == 13 else ([], 0, 1)
        return CoachResponse(
            stage="waiting",
            headline=f"{engine.current_player.name} is playing",
            detail="Use the wait to check which cards you need and what your opponents are collecting.",
            action=CoachAction(kind="wait"),
            outs=outs, out_copies=out_copies, unseen_cards=unseen,
            out_chance_pct=round(100 * out_copies / unseen, 1),
            reads=reads, tip=_tip(arr, "waiting", jokers), status=_status(arr),
        )

    # ---------------------------------------------------------------- draw
    if len(hand) == 13:
        arr = find_optimal_arrangement(hand)
        top = engine._peek_discard()
        outs, out_copies, unseen = compute_outs(engine, hand)
        chance = round(100 * out_copies / unseen, 1)
        take, reason = False, "The discard pile is empty."
        if top is not None:
            before_cost = _progress_cost(arr)
            cost, after, drop = _best_after_draw(hand, top, enumerate_candidates_by_id(hand))
            effect = _effect(arr, after, top)
            structural = not effect.startswith("cuts")
            gain = before_cost - cost
            # Picking from the pile tells opponents what you collect, so only
            # do it for a real gain.
            take = drop.id != top.id and gain > 0 and (structural or gain >= 5)
            if take:
                # Name the same discard the coach will recommend next step.
                plan = ranked_discards(engine, hand + [top], picked)[0].card
                if plan.id == top.id:
                    take = False
                else:
                    drop = plan
            if take:
                reason = f"Take {_label(top)}: it {effect}. Then discard {_label(drop)}."
            elif gain > 0 and drop.id != top.id:
                reason = (f"{_label(top)} would only {effect.replace('cuts', 'cut')}. Taking it shows opponents "
                          "what you're collecting, so draw from the stock instead.")
            else:
                reason = f"{_label(top)} doesn't improve your hand."
        # First-turn drop advice for very weak hands.
        weak = (
            human.draws_this_round == 0 and not take and len(arr.pure_sequences) == 0
            and jokers == 0 and arr.loose_points >= 60
        )
        if take:
            headline = f"Take {_label(top)} from the discard pile"
            action = CoachAction(kind="take_discard", card_id=top.id, card_label=_label(top))
        else:
            headline = "Draw from the stock"
            action = CoachAction(kind="draw_stock")
            if out_copies:
                reason += f" About {chance:.0f}% of the unseen cards would help you."
        if weak:
            reason += (" This hand has no pure sequence, no jokers and lots of high cards. A first drop costs "
                       "only 20 points, which may be cheaper than playing it out.")
        return CoachResponse(
            stage="draw", headline=headline, detail=reason, action=action,
            take_discard_card=top if take else None,
            outs=outs, out_copies=out_copies, unseen_cards=unseen, out_chance_pct=chance,
            reads=reads, tip=_tip(arr, "draw", jokers), status=_status(arr),
        )

    # ------------------------------------------------------------- discard
    options = ranked_discards(engine, hand, picked)
    best = options[0]

    rest = [c for c in hand if c.id != best.card.id]
    arr_after = find_optimal_arrangement(rest)
    if arr_after.is_winning_hand:
        return CoachResponse(
            stage="discard",
            headline=f"Declare! Put {_label(best.card)} in the finish slot",
            detail=("Your other 13 cards form a valid hand. Select "
                    f"{_label(best.card)} and press Declare."),
            action=CoachAction(kind="declare", card_id=best.card.id, card_label=_label(best.card)),
            options=options, reads=reads, tip=_tip(arr_after, "discard", jokers), status=_status(arr_after),
        )
    detail = best.reasoning
    if best.danger:
        detail += f" Note: {best.danger}"
    elif any(o.danger for o in options[1:3]):
        risky = next(o for o in options[1:3] if o.danger)
        detail += f" It's also safer than {_label(risky.card)}: {risky.danger}"
    return CoachResponse(
        stage="discard",
        headline=f"Discard {_label(best.card)}",
        detail=detail,
        action=CoachAction(kind="discard", card_id=best.card.id, card_label=_label(best.card)),
        options=options, reads=reads, tip=_tip(arr_after, "discard", jokers), status=_status(arr_after),
    )
