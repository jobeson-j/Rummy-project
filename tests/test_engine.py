from app.game import engine
import pytest
from app.game.engine import RummyGameEngine, TurnStage, BotDifficulty


def test_game_initialization():
    engine = RummyGameEngine(num_players=3, seed=42)
    assert len(engine.players) == 3
    assert engine.players[0].is_human is True
    assert engine.players[1].is_human is False
    assert len(engine.players[0].hand) == 13
    assert len(engine.players[1].hand) == 13
    assert engine.cut_card is not None
    assert engine.turn_stage == TurnStage.AWAITING_DRAW
    assert engine._peek_discard() is not None


def test_human_draw_and_discard_flow():
    engine = RummyGameEngine(num_players=2, seed=123)

    # 1. Human draws from stock deck
    drawn_card = engine.draw("stock")
    assert len(engine.players[0].hand) == 14
    assert engine.turn_stage == TurnStage.AWAITING_DISCARD

    # 2. Human discards drawn card
    engine.discard(drawn_card.id)
    assert len(engine.players[0].hand) == 13

    # Turn should have advanced to Bot
    assert engine.current_player_index == 1
    assert engine.turn_stage == TurnStage.AWAITING_DRAW


def test_bot_turn_automation():
    engine = RummyGameEngine(
        num_players=2, bot_difficulty=BotDifficulty.MEDIUM, seed=99)

    # Human completes turn
    c = engine.draw("stock")
    engine.discard(c.id)

    # Trigger bots until it cycles back to Human
    engine.play_bot_turns_until_human()

    # Should be Human's turn again
    assert engine.current_player.is_human is True
    assert engine.turn_stage == TurnStage.AWAITING_DRAW
