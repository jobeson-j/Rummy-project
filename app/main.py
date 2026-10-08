from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.algorithms.assistant import (
    DiscardRecommendationResponse,
    PickRecommendationResponse,
    recommend_discard,
    recommend_pick,
)
from app.algorithms.coach import CoachResponse, coach
from app.algorithms.hand_partitioner import find_optimal_arrangement
from app.game.engine import BotDifficulty, PublicGameState, RummyGameEngine, _label
from app.game.rules import DeclarationResult, MeldType, MeldValidationResult, classify_group

app = FastAPI(title="Smart Rummy API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for active games
GAMES: Dict[str, RummyGameEngine] = {}
HUMAN_ID = "player-1"


class CreateGameRequest(BaseModel):
    num_players: int = 2
    difficulty: BotDifficulty = BotDifficulty.MEDIUM
    seed: Optional[int] = None


class DrawRequest(BaseModel):
    source: str  # "stock" or "discard"


class DiscardRequest(BaseModel):
    card_id: str


class GroupsRequest(BaseModel):
    groups: List[List[str]]  # card ids


class DeclareRequest(BaseModel):
    groups: List[List[str]]  # card ids, 13 cards in total
    finish_card_id: str      # the 14th card, placed in the finish slot


class CheckResponse(BaseModel):
    groups: List[MeldValidationResult]   # one entry per submitted group, same order
    declaration: DeclarationResult       # whole-hand validity of the submitted groups


class DeclareResponse(BaseModel):
    declaration_result: DeclarationResult
    game_state: PublicGameState


class ArrangeGroup(BaseModel):
    meld_type: str
    card_ids: List[str]


class ArrangeResponse(BaseModel):
    groups: List[ArrangeGroup]
    deadwood_ids: List[str]
    deadwood_points: int
    pure_sequences: int
    total_sequences: int
    summary: str
    spare_id: Optional[str] = None


# Looks up a game by id, or returns a 404 error if it doesn't exist.
def _engine(game_id: str) -> RummyGameEngine:
    engine = GAMES.get(game_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found. Start a new game.")
    return engine


# Wraps an error message in a 400 Bad Request HTTP error.
def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# Rejects the request unless the round is live and it's the human player's turn.
def _require_human_turn(engine: RummyGameEngine) -> None:
    if engine.round_over:
        raise HTTPException(status_code=400, detail="The round is over. Start the next round.")
    if not engine.current_player.is_human:
        raise HTTPException(status_code=400, detail=f"Wait for {engine.current_player.name} to finish their turn.")


# Health check: confirms the API is running.
@app.get("/")
def root():
    return {"message": "Smart Rummy API is running."}


# POST /new: starts a new game and returns its first public state.
@app.post("/api/game/new", response_model=PublicGameState)
def create_game(req: CreateGameRequest):
    try:
        engine = RummyGameEngine(num_players=req.num_players, bot_difficulty=req.difficulty, seed=req.seed)
    except ValueError as e:
        raise _bad(e)
    GAMES[engine.game_id] = engine
    return engine.get_public_state()


# GET /{id}: returns the current public state of a game.
@app.get("/api/game/{game_id}", response_model=PublicGameState)
def get_game_state(game_id: str):
    return _engine(game_id).get_public_state()


# POST /draw: the human draws from the stock or the discard pile.
@app.post("/api/game/{game_id}/draw", response_model=PublicGameState)
def draw_card(game_id: str, req: DrawRequest):
    engine = _engine(game_id)
    _require_human_turn(engine)
    try:
        engine.draw(req.source)
    except ValueError as e:
        raise _bad(e)
    return engine.get_public_state()


# POST /discard: the human discards a card, ending their turn.
@app.post("/api/game/{game_id}/discard", response_model=PublicGameState)
def discard_card(game_id: str, req: DiscardRequest):
    """Discard ends the human's turn. Bots then play via /bot-turn so the UI
    can show each opponent move as it happens."""
    engine = _engine(game_id)
    _require_human_turn(engine)
    try:
        engine.discard(req.card_id)
    except ValueError as e:
        raise _bad(e)
    return engine.get_public_state()


# POST /bot-turn: plays exactly one turn for the current bot.
@app.post("/api/game/{game_id}/bot-turn", response_model=PublicGameState)
def bot_turn(game_id: str):
    engine = _engine(game_id)
    if not engine.round_over and not engine.current_player.is_human:
        try:
            engine.play_bot_turn()
        except ValueError as e:
            raise _bad(e)
    return engine.get_public_state()


# POST /drop: the human gives up the round for a 20/40-point penalty.
@app.post("/api/game/{game_id}/drop", response_model=PublicGameState)
def drop(game_id: str):
    engine = _engine(game_id)
    _require_human_turn(engine)
    try:
        engine.drop(HUMAN_ID)
    except ValueError as e:
        raise _bad(e)
    return engine.get_public_state()


# POST /next-round: deals the next round, keeping running scores.
@app.post("/api/game/{game_id}/next-round", response_model=PublicGameState)
def next_round(game_id: str):
    engine = _engine(game_id)
    try:
        engine.start_round()
    except ValueError as e:
        raise _bad(e)
    return engine.get_public_state()


# POST /check: validates the human's card groups without any penalty.
@app.post("/api/game/{game_id}/check", response_model=CheckResponse)
def check_groups(game_id: str, req: GroupsRequest):
    """Validate a proposed grouping without any penalty (live feedback)."""
    engine = _engine(game_id)
    by_id = {c.id: c for c in engine.players[0].hand}
    per_group = [classify_group([by_id[i] for i in g if i in by_id]) for g in req.groups]
    return CheckResponse(groups=per_group, declaration=engine.check_groups(HUMAN_ID, req.groups))


# POST /declare: the human declares; a wrong show costs 80 points.
@app.post("/api/game/{game_id}/declare", response_model=DeclareResponse)
def declare_hand(game_id: str, req: DeclareRequest):
    engine = _engine(game_id)
    _require_human_turn(engine)
    try:
        result = engine.declare(HUMAN_ID, req.groups, finish_card_id=req.finish_card_id)
    except ValueError as e:
        raise _bad(e)
    return DeclareResponse(declaration_result=result, game_state=engine.get_public_state())


# GET /assist/discard: ranks the best cards to discard from a 14-card hand.
@app.get("/api/game/{game_id}/assist/discard", response_model=DiscardRecommendationResponse)
def get_discard_assistance(game_id: str):
    engine = _engine(game_id)
    human = engine.players[0]
    if len(human.hand) != 14:
        raise HTTPException(status_code=400, detail="Draw a card first to get a discard suggestion.")
    return recommend_discard(human.hand, known_discards=engine.deck.discard_pile)


# GET /assist/pick: says whether to take the top discard or draw from the stock.
@app.get("/api/game/{game_id}/assist/pick", response_model=PickRecommendationResponse)
def get_pick_assistance(game_id: str):
    engine = _engine(game_id)
    human = engine.players[0]
    top_discard = engine._peek_discard()
    if not top_discard:
        raise HTTPException(status_code=400, detail="The discard pile is empty.")
    if len(human.hand) != 13:
        raise HTTPException(status_code=400, detail="You have already drawn this turn.")
    return recommend_pick(human.hand, top_discard)


# GET /assist/arrange: best grouping of the hand plus a plain-language progress summary.
@app.get("/api/game/{game_id}/assist/arrange", response_model=ArrangeResponse)
def get_arrangement(game_id: str):
    """Best grouping of the human's current hand, plus how far it is from a
    valid declaration. With 14 cards (after drawing) the least useful card is
    set aside as the spare: the one to discard or put in the finish slot."""
    engine = _engine(game_id)
    hand = engine.players[0].hand
    spare = None
    if len(hand) == 14:
        spare = recommend_discard(hand, known_discards=engine.deck.discard_pile).best_discard.card
        hand = [c for c in hand if c.id != spare.id]
    arr = find_optimal_arrangement(hand)
    groups = (
        [ArrangeGroup(meld_type=MeldType.PURE_SEQUENCE.value, card_ids=[c.id for c in g]) for g in arr.pure_sequences]
        + [ArrangeGroup(meld_type=MeldType.IMPURE_SEQUENCE.value, card_ids=[c.id for c in g]) for g in arr.impure_sequences]
        + [ArrangeGroup(meld_type=MeldType.SET.value, card_ids=[c.id for c in g]) for g in arr.sets]
    )
    pure = len(arr.pure_sequences)
    seqs = pure + len(arr.impure_sequences)
    dead = len(arr.deadwood_cards)
    loose = arr.loose_points
    spare_label = _label(spare) if spare else ""
    lead = f"After discarding {spare_label}: " if spare else ""
    if arr.is_winning_hand and spare:
        summary = f"a complete hand! Put {spare_label} in the finish slot and declare."
    elif arr.is_winning_hand:
        summary = "a complete hand. Draw, then declare with your spare card."
    elif pure == 0:
        summary = (f"{lead}no pure sequence yet ({dead} loose cards, {loose} pts). "
                   "Aim for 3 cards in a row of one suit, without jokers.")
    elif seqs < 2:
        summary = (f"{lead}one pure sequence ({dead} loose cards, {loose} pts). "
                   "You still need a second sequence; jokers allowed.")
    else:
        summary = (f"{lead}both sequences done, {dead} loose card{'s' if dead != 1 else ''} "
                   f"worth {loose} pts.")
    return ArrangeResponse(
        groups=groups,
        deadwood_ids=[c.id for c in arr.deadwood_cards],
        deadwood_points=arr.total_deadwood,
        pure_sequences=pure,
        total_sequences=seqs,
        summary=summary,
        spare_id=spare.id if spare else None,
    )


# GET /coach: the coach's best move, outs, opponent reads and tip (cached per state).
@app.get("/api/game/{game_id}/coach", response_model=CoachResponse)
def get_coach(game_id: str):
    """The best next move with an explanation, outs, opponent reads and a tip.
    Cached per game state, since the UI asks after every move."""
    engine = _engine(game_id)
    key = (engine.round_number, engine.last_event_seq_value(), tuple(c.id for c in engine.players[0].hand))
    cached = getattr(engine, "_coach_cache", None)
    if cached and cached[0] == key:
        return cached[1]
    result = coach(engine)
    engine._coach_cache = (key, result)
    return result
