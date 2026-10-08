"""
Game engine for Smart Rummy (Indian 13-card Points Rummy).

Owns one table: players, deck, turn flow, an event log the UI can replay,
declarations (valid and wrong shows), drops, scoring and multi-round play.
Bot turns are played one at a time (``play_bot_turn``) so the frontend can
show an "Opponent is thinking..." state between them.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.algorithms.assistant import recommend_discard, recommend_pick
from app.algorithms.hand_partitioner import FULL_HAND_CAP, find_optimal_arrangement
from app.game.deck import Deck, DeckError
from app.game.rules import DeclarationResult, MeldType, classify_group, validate_arrangement
from app.models.card import Card, Rank

FIRST_DROP_PENALTY = 20
MIDDLE_DROP_PENALTY = 40
WRONG_SHOW_PENALTY = 80
MAX_EVENTS_RETURNED = 40


class TurnStage(str, Enum):
    AWAITING_DRAW = "AWAITING_DRAW"
    AWAITING_DISCARD = "AWAITING_DISCARD"
    ROUND_OVER = "ROUND_OVER"
    # Kept for backwards compatibility with older clients/tests.
    ROUND_DECLARED = "ROUND_DECLARED"
    GAME_OVER = "GAME_OVER"


class BotDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Player(BaseModel):
    id: str
    name: str
    is_human: bool
    difficulty: BotDifficulty = BotDifficulty.MEDIUM
    hand: List[Card] = Field(default_factory=list)
    score: int = 0  # cumulative penalty points across rounds (lower is better)
    declared: bool = False
    draws_this_round: int = 0

    model_config = {"arbitrary_types_allowed": True}


class GameEvent(BaseModel):
    seq: int
    round_number: int
    player_id: str
    player_name: str
    action: str  # round_start | draw_stock | draw_discard | discard | declare | wrong_show | drop | reshuffle | stock_empty
    card: Optional[Card] = None
    message: str


class ResultGroup(BaseModel):
    meld_type: str
    cards: List[Card]


class PlayerRoundResult(BaseModel):
    player_id: str
    name: str
    is_human: bool
    is_winner: bool
    points: int
    total_score: int
    groups: List[ResultGroup]
    deadwood: List[Card]
    note: str


class RoundResult(BaseModel):
    round_number: int
    outcome: str  # declared | wrong_show | drop | stock_exhausted
    winner_id: Optional[str]
    winner_name: Optional[str]
    message: str
    players: List[PlayerRoundResult]


class PlayerSummary(BaseModel):
    id: str
    name: str
    card_count: int
    is_human: bool
    score: int


class PublicGameState(BaseModel):
    game_id: str
    turn_stage: TurnStage
    current_player_id: str
    current_player_name: str
    is_human_turn: bool
    round_number: int
    cut_card: Optional[Card]
    wild_rank: Optional[Rank]
    discard_top: Optional[Card]
    discard_count: int
    cards_in_deck: int
    human_hand: List[Card]
    players_summary: List[PlayerSummary]
    events: List[GameEvent]
    last_event_seq: int
    can_drop: bool
    drop_penalty: int
    round_result: Optional[RoundResult] = None
    winner_id: Optional[str] = None
    winner_name: Optional[str] = None
    difficulty: BotDifficulty


# Short text label for a card in log messages, e.g. "10♥".
def _label(card: Card) -> str:
    if card.is_printed_joker:
        return "Joker"
    sym = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}.get(card.suit.value, "")
    return f"{card.rank.value}{sym}"


class RummyGameEngine:
    # Sets up players and bots, then deals the first round.
    def __init__(
        self,
        game_id: Optional[str] = None,
        num_players: int = 2,
        bot_difficulty: BotDifficulty = BotDifficulty.MEDIUM,
        seed: Optional[int] = None,
    ):
        if num_players < 2 or num_players > 6:
            raise ValueError("Number of players must be between 2 and 6.")

        self.game_id = game_id or str(uuid.uuid4())[:8]
        self.num_players = num_players
        self.bot_difficulty = bot_difficulty
        self.seed = seed
        self.round_number = 0
        self.events: List[GameEvent] = []
        self._event_seq = 0
        self.round_result: Optional[RoundResult] = None
        self.winner: Optional[Player] = None

        self.players: List[Player] = [Player(id="player-1", name="You", is_human=True)]
        bot_names = ["Asha", "Ravi", "Meera", "Kabir", "Zoya"]
        for i in range(2, num_players + 1):
            self.players.append(
                Player(
                    id=f"bot-{i}",
                    name=bot_names[i - 2],
                    is_human=False,
                    difficulty=bot_difficulty,
                )
            )
        self.start_round()

    # ------------------------------------------------------------------
    # Round lifecycle
    # ------------------------------------------------------------------
    # Shuffles, cuts the wild joker and deals a new round.
    def start_round(self) -> None:
        if self.round_result is None and self.round_number > 0:
            raise ValueError("The current round is still in progress.")
        self.round_number += 1
        round_seed = None if self.seed is None else self.seed + self.round_number - 1
        self.deck = Deck(num_sub_decks=2, rng_seed=round_seed)
        self.deck.shuffle()
        cut_info = self.deck.cut_joker()
        self.cut_card = cut_info.indicator_card
        self.wild_rank = cut_info.wild_rank

        hands = self.deck.deal(num_players=self.num_players, cards_per_player=13)
        for idx, p in enumerate(self.players):
            p.hand = hands[idx + 1]
            p.declared = False
            p.draws_this_round = 0

        first_discard = self.deck.draw()
        self.deck.discard(first_discard)

        # Rotate the first player each round (human starts round 1).
        self.current_player_index = (self.round_number - 1) % len(self.players)
        self.turn_stage = TurnStage.AWAITING_DRAW
        self.round_result = None
        self.winner = None
        wild_label = "Ace" if self.wild_rank == Rank.ACE else self.wild_rank.value
        self._log(
            self.players[0],
            "round_start",
            None,
            f"Round {self.round_number} dealt. Wild joker rank: {wild_label}. "
            f"{self.current_player.name} to play first.",
        )

    # Sequence number of the latest event (changes after every move).
    def last_event_seq_value(self) -> int:
        return self._event_seq

    # The player whose turn it is.
    @property
    def current_player(self) -> Player:
        return self.players[self.current_player_index]

    # True once the round has ended (declare, drop, wrong show or empty stock).
    @property
    def round_over(self) -> bool:
        return self.turn_stage in (TurnStage.ROUND_OVER, TurnStage.GAME_OVER, TurnStage.ROUND_DECLARED)

    # The top card of the discard pile without taking it.
    def _peek_discard(self) -> Optional[Card]:
        return self.deck.discard_pile[-1] if self.deck.discard_pile else None

    # Adds an entry to the table log that the UI shows and animates.
    def _log(self, player: Player, action: str, card: Optional[Card], message: str) -> None:
        self._event_seq += 1
        self.events.append(
            GameEvent(
                seq=self._event_seq,
                round_number=self.round_number,
                player_id=player.id,
                player_name=player.name,
                action=action,
                card=card,
                message=message,
            )
        )
        if len(self.events) > 200:
            self.events = self.events[-200:]

    # Raises if the round is already over.
    def _require_active(self) -> None:
        if self.round_over:
            raise ValueError("The round is over. Start the next round to keep playing.")

    # ------------------------------------------------------------------
    # Turn actions
    # ------------------------------------------------------------------
    # The current player draws from the stock or the discard pile.
    def draw(self, source: str) -> Card:
        self._require_active()
        if self.turn_stage != TurnStage.AWAITING_DRAW:
            raise ValueError("You already drew a card this turn. Discard one to finish your turn.")

        player = self.current_player
        source_clean = source.lower().strip()
        try:
            if source_clean == "stock":
                stock_before = self.deck.remaining_stock_count()
                card = self.deck.draw()
                if stock_before == 0:
                    self._log(player, "reshuffle", None, "Stock ran out. Discard pile reshuffled into the stock.")
            elif source_clean == "discard":
                top = self._peek_discard()
                if top is None:
                    raise ValueError("The discard pile is empty.")
                card = self.deck.draw_discard()
            else:
                raise ValueError(f"Invalid draw source: '{source}'. Choose 'stock' or 'discard'.")
        except DeckError as exc:
            self._end_round_stock_exhausted()
            raise ValueError(str(exc)) from exc

        player.hand.append(card)
        player.draws_this_round += 1
        self.turn_stage = TurnStage.AWAITING_DISCARD
        if source_clean == "stock":
            msg = "You drew from the stock." if player.is_human else f"{player.name} drew from the stock."
            self._log(player, "draw_stock", card if player.is_human else None, msg)
        else:
            who = "You" if player.is_human else player.name
            self._log(player, "draw_discard", card, f"{who} picked {_label(card)} from the discard pile.")
        return card

    # The current player discards a card and the turn moves on.
    def discard(self, card_id: str) -> Card:
        self._require_active()
        if self.turn_stage != TurnStage.AWAITING_DISCARD:
            raise ValueError("Draw a card first (from the stock or the discard pile).")

        player = self.current_player
        card = next((c for c in player.hand if c.id == card_id), None)
        if card is None:
            raise ValueError("That card is not in your hand.")

        player.hand.remove(card)
        self.deck.discard(card)
        who = "You" if player.is_human else player.name
        self._log(player, "discard", card, f"{who} discarded {_label(card)}.")
        self._advance_turn()
        return card

    # Passes the turn to the next player.
    def _advance_turn(self) -> None:
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.turn_stage = TurnStage.AWAITING_DRAW

    # ------------------------------------------------------------------
    # Drop
    # ------------------------------------------------------------------
    # Drop penalty for a player: 20 before their first draw, 40 after.
    def drop_penalty_for(self, player: Player) -> int:
        return FIRST_DROP_PENALTY if player.draws_this_round == 0 else MIDDLE_DROP_PENALTY

    # True if the player may drop now (their turn, before drawing).
    def can_drop(self, player: Player) -> bool:
        return (
            not self.round_over
            and self.current_player.id == player.id
            and self.turn_stage == TurnStage.AWAITING_DRAW
        )

    # The player drops out of the round and takes the drop penalty.
    def drop(self, player_id: str) -> RoundResult:
        player = self._player(player_id)
        if not self.can_drop(player):
            raise ValueError("You can only drop at the start of your turn, before drawing.")
        penalty = self.drop_penalty_for(player)
        kind = "first drop" if player.draws_this_round == 0 else "middle drop"
        self._log(player, "drop", None, f"{'You' if player.is_human else player.name} dropped ({kind}, {penalty} pts).")

        # The remaining player with the best hand takes the round.
        others = [p for p in self.players if p.id != player.id]
        best = min(others, key=lambda p: find_optimal_arrangement(p.hand).total_deadwood)
        points = {p.id: 0 for p in self.players}
        points[player.id] = penalty
        notes = {player.id: f"Dropped ({kind})"}
        return self._finish_round(
            outcome="drop",
            winner=best,
            points=points,
            notes=notes,
            message=f"{'You' if player.is_human else player.name} dropped out ({kind}) for {penalty} points.",
        )

    # ------------------------------------------------------------------
    # Declaration
    # ------------------------------------------------------------------
    # Finds a player by id, or raises if there is none.
    def _player(self, player_id: str) -> Player:
        player = next((p for p in self.players if p.id == player_id), None)
        if player is None:
            raise ValueError("Player not found.")
        return player

    # Validates a player's proposed groups without ending the round.
    def check_groups(self, player_id: str, group_ids: List[List[str]]) -> DeclarationResult:
        """Non-binding validation of a proposed arrangement (no penalty)."""
        player = self._player(player_id)
        by_id = {c.id: c for c in player.hand}
        groups: List[List[Card]] = []
        for g in group_ids:
            cards = [by_id[i] for i in g if i in by_id]
            groups.append(cards)
        return validate_arrangement(groups)

    # A player declares: valid hands win, invalid ones are a wrong show (80 points).
    def declare(self, player_id: str, groups, finish_card_id: Optional[str] = None):
        """Declare a hand.

        * ``groups`` may be a list of lists of card ids (frontend) or of
          ``Card`` objects (bots / older callers).
        * A human declares during AWAITING_DISCARD with 14 cards: the
          ``finish_card_id`` card is discarded to the finish slot and the
          remaining 13 must be fully grouped.
        * An invalid declaration is a wrong show: 80 points and the round ends.
        """
        self._require_active()
        player = self._player(player_id)
        if self.current_player.id != player.id:
            raise ValueError("You can only declare on your own turn.")
        if self.turn_stage != TurnStage.AWAITING_DISCARD:
            raise ValueError("Draw a card first, then declare by placing one card in the finish slot.")

        by_id = {c.id: c for c in player.hand}
        if finish_card_id is not None:
            finish = by_id.get(finish_card_id)
            if finish is None:
                raise ValueError("The finish card is not in your hand.")
        else:
            finish = None

        card_groups: List[List[Card]] = []
        for g in groups:
            cards: List[Card] = []
            for item in g:
                cid = item if isinstance(item, str) else item.id
                if cid not in by_id:
                    raise ValueError("A grouped card is not in your hand.")
                cards.append(by_id[cid])
            if cards:
                card_groups.append(cards)

        if finish is not None:
            if any(c.id == finish.id for g in card_groups for c in g):
                raise ValueError("The finish card cannot also be in a group.")
            player.hand.remove(finish)
            self.deck.discard(finish)

        grouped_ids = {c.id for g in card_groups for c in g}
        missing = [c for c in player.hand if c.id not in grouped_ids]
        if missing:
            result = DeclarationResult(
                is_valid=False,
                reason=f"{len(missing)} card(s) were left out of your groups.",
                total_cards=len(grouped_ids),
            )
        else:
            result = validate_arrangement(card_groups)

        who = "You" if player.is_human else player.name
        if result.is_valid:
            player.declared = True
            self._log(player, "declare", finish, f"{who} declared a valid hand!")
            points: Dict[str, int] = {}
            notes: Dict[str, str] = {}
            arrangements = {}
            for p in self.players:
                if p.id == player.id:
                    points[p.id] = 0
                    notes[p.id] = "Valid declaration"
                    continue
                arr = find_optimal_arrangement(p.hand)
                arrangements[p.id] = arr
                points[p.id] = min(FULL_HAND_CAP, arr.total_deadwood)
                notes[p.id] = "Ungrouped cards counted" if arr.has_valid_structure else "No valid sequences: full count"
            self._finish_round(
                outcome="declared",
                winner=player,
                points=points,
                notes=notes,
                message=f"{who} declared a valid hand.",
                declared_groups=card_groups,
            )
        else:
            self._log(player, "wrong_show", finish, f"{who} made a wrong show (+{WRONG_SHOW_PENALTY}).")
            others = [p for p in self.players if p.id != player.id]
            best = min(others, key=lambda p: find_optimal_arrangement(p.hand).total_deadwood)
            points = {p.id: 0 for p in self.players}
            points[player.id] = WRONG_SHOW_PENALTY
            self._finish_round(
                outcome="wrong_show",
                winner=best,
                points=points,
                notes={player.id: f"Wrong show (+{WRONG_SHOW_PENALTY})"},
                message=(
                    f"{'Your' if player.is_human else player.name + chr(39) + 's'} declaration was not valid: "
                    f"{(result.reason or '').rstrip('.')}. That is a wrong show, worth {WRONG_SHOW_PENALTY} points."
                ),
                declared_groups=card_groups,
            )
        return result

    # Ends the round as a draw when no cards are left to draw.
    def _end_round_stock_exhausted(self) -> None:
        if self.round_over:
            return
        self._log(self.current_player, "stock_empty", None, "No cards left to draw. Round ends with no winner.")
        self._finish_round(
            outcome="stock_exhausted",
            winner=None,
            points={p.id: 0 for p in self.players},
            notes={},
            message="The stock ran out. The round is a draw.",
        )

    # Scores the round, records every hand for the results screen and ends play.
    def _finish_round(
        self,
        outcome: str,
        winner: Optional[Player],
        points: Dict[str, int],
        notes: Dict[str, str],
        message: str,
        declared_groups: Optional[List[List[Card]]] = None,
    ) -> RoundResult:
        player_results: List[PlayerRoundResult] = []
        for p in self.players:
            p.score += points.get(p.id, 0)
            if declared_groups is not None and p.declared:
                groups = [
                    ResultGroup(meld_type=classify_group(g).meld_type.value, cards=g)
                    for g in declared_groups
                ]
                deadwood: List[Card] = []
            elif declared_groups is not None and outcome == "wrong_show" and self.current_player.id == p.id:
                groups = [
                    ResultGroup(meld_type=classify_group(g).meld_type.value, cards=g)
                    for g in declared_groups
                ]
                grouped = {c.id for g in declared_groups for c in g}
                deadwood = [c for c in p.hand if c.id not in grouped]
            else:
                arr = find_optimal_arrangement(p.hand)
                groups = (
                    [ResultGroup(meld_type=MeldType.PURE_SEQUENCE.value, cards=g) for g in arr.pure_sequences]
                    + [ResultGroup(meld_type=MeldType.IMPURE_SEQUENCE.value, cards=g) for g in arr.impure_sequences]
                    + [ResultGroup(meld_type=MeldType.SET.value, cards=g) for g in arr.sets]
                )
                deadwood = arr.deadwood_cards
            player_results.append(
                PlayerRoundResult(
                    player_id=p.id,
                    name=p.name,
                    is_human=p.is_human,
                    is_winner=winner is not None and winner.id == p.id,
                    points=points.get(p.id, 0),
                    total_score=p.score,
                    groups=groups,
                    deadwood=deadwood,
                    note=notes.get(p.id, ""),
                )
            )

        self.winner = winner
        self.turn_stage = TurnStage.ROUND_OVER
        self.round_result = RoundResult(
            round_number=self.round_number,
            outcome=outcome,
            winner_id=winner.id if winner else None,
            winner_name=winner.name if winner else None,
            message=message,
            players=player_results,
        )
        return self.round_result

    # ------------------------------------------------------------------
    # Bots
    # ------------------------------------------------------------------
    # Plays one full bot turn: draw, declare if possible, otherwise discard.
    def play_bot_turn(self) -> None:
        """Play exactly one full turn for the current bot player."""
        if self.round_over or self.current_player.is_human:
            return
        bot = self.current_player

        top_discard = self._peek_discard()
        draw_from_discard = False
        if top_discard is not None:
            if bot.difficulty == BotDifficulty.EASY:
                draw_from_discard = top_discard.is_any_joker
            else:
                draw_from_discard = recommend_pick(bot.hand, top_discard).should_pick

        try:
            self.draw("discard" if draw_from_discard else "stock")
        except ValueError:
            return  # stock exhausted -> round already finished

        # Can the bot go out? 13 cards fully grouped + 1 card to the finish slot.
        arr = find_optimal_arrangement(bot.hand)
        if arr.has_valid_structure and len(arr.deadwood_cards) == 1:
            groups = arr.pure_sequences + arr.impure_sequences + arr.sets
            self.declare(bot.id, groups, finish_card_id=arr.deadwood_cards[0].id)
            if self.round_over:
                return

        if bot.difficulty == BotDifficulty.EASY:
            # Easy bots throw away the highest-value card that is not in a meld.
            arr_cards = arr.deadwood_cards or bot.hand
            non_jokers = [c for c in arr_cards if not c.is_any_joker] or arr_cards
            choice = max(non_jokers, key=lambda c: c.points)
            self.discard(choice.id)
            return

        known = self.deck.discard_pile if bot.difficulty == BotDifficulty.HARD else None
        rec = recommend_discard(bot.hand, known_discards=known)
        self.discard(rec.best_discard.card.id)

    # Plays bot turns until it's the human's turn or the round ends.
    def play_bot_turns_until_human(self) -> None:
        """Play bot turns until it is the human's turn or the round ends."""
        guard = 0
        while not self.round_over and not self.current_player.is_human and guard < 20:
            guard += 1
            self.play_bot_turn()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    # Everything the UI may see (your hand, counts, log), hiding bot hands.
    def get_public_state(self) -> PublicGameState:
        human = self.players[0]
        return PublicGameState(
            game_id=self.game_id,
            turn_stage=self.turn_stage,
            current_player_id=self.current_player.id,
            current_player_name=self.current_player.name,
            is_human_turn=self.current_player.is_human and not self.round_over,
            round_number=self.round_number,
            cut_card=self.cut_card,
            wild_rank=self.wild_rank,
            discard_top=self._peek_discard(),
            discard_count=self.deck.remaining_discard_count(),
            cards_in_deck=self.deck.remaining_stock_count(),
            human_hand=human.hand,
            players_summary=[
                PlayerSummary(
                    id=p.id,
                    name=p.name,
                    card_count=len(p.hand),
                    is_human=p.is_human,
                    score=p.score,
                )
                for p in self.players
            ],
            events=self.events[-MAX_EVENTS_RETURNED:],
            last_event_seq=self._event_seq,
            can_drop=self.can_drop(human),
            drop_penalty=self.drop_penalty_for(human),
            round_result=self.round_result,
            winner_id=self.winner.id if self.winner else None,
            winner_name=self.winner.name if self.winner else None,
            difficulty=self.bot_difficulty,
        )
