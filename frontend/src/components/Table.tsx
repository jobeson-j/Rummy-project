import { useLayoutEffect, useRef, type RefObject } from 'react';
import type { Card, GameEvent, PlayerSummary, PublicGameState } from '../api';
import type { DiscardOrigin, Flight } from '../App';
import { flash, flyFrom, ghostFly, rectOf } from '../fly';
import { cardLabel } from '../cards';
import { PlayingCard } from './PlayingCard';

// Describes a player's last move, e.g. "Drew from the stock, threw 9♠".
function lastMoveText(events: GameEvent[], playerId: string, round: number): string | null {
  const mine = events.filter((e) => e.player_id === playerId && e.round_number === round);
  const discard = [...mine].reverse().find((e) => e.action === 'discard');
  if (!discard) return null;
  const draw = [...mine].reverse().find((e) => e.seq < discard.seq && (e.action === 'draw_stock' || e.action === 'draw_discard'));
  const took =
    draw?.action === 'draw_discard' && draw.card ? `Took ${cardLabel(draw.card)} from the pile` : 'Drew from the stock';
  return `${took}, threw ${discard.card ? cardLabel(discard.card) : 'a card'}`;
}

// An opponent's seat: face-down fan, name, card count and status.
function OpponentSeat({
  player,
  active,
  move,
}: {
  player: PlayerSummary;
  active: boolean;
  move: string | null;
}) {
  const fan = Math.min(player.card_count, 13);
  return (
    <section data-seat={player.id} className={`seat ${active ? 'is-active' : ''}`} aria-label={`${player.name}, ${player.card_count} cards`}>
      <div className="seat-fan" aria-hidden="true">
        {Array.from({ length: fan }).map((_, i) => (
          <span
            key={i}
            className="seat-card"
            style={{ transform: `rotate(${(i - (fan - 1) / 2) * 6}deg)` }}
          />
        ))}
      </div>
      <div className="seat-info">
        <div>
          <div className="seat-name">
            {player.name} <span className="seat-count">{player.card_count} cards</span>
          </div>
          <div className="seat-status" aria-live="polite">
            {active ? (
              <span className="thinking">
                Thinking<span className="dots" aria-hidden="true"><i /><i /><i /></span>
              </span>
            ) : (
              move ?? 'Waiting'
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

interface TableProps {
  state: PublicGameState;
  busy: boolean;
  canDraw: boolean;
  pickHint: 'stock' | 'discard' | null;
  onDraw: (source: 'stock' | 'discard') => void;
  prompt: string;
  wildNote: string;
  onShowRules: () => void;
  flight: Flight | null;
  discardOriginRef: RefObject<DiscardOrigin | null>;
}

// The table: opponent seats, stock, discard pile, wild card and turn prompt.
export function Table({
  state,
  busy,
  canDraw,
  pickHint,
  onDraw,
  prompt,
  wildNote,
  onShowRules,
  flight,
  discardOriginRef,
}: TableProps) {
  const opponents = state.players_summary.filter((p) => !p.is_human);
  const top: Card | null = state.discard_top;
  const drawable = canDraw && !busy;

  // Deal: opponents' face-down cards leave the stock in turn with yours.
  useLayoutEffect(() => {
    if (!flight || flight.kind !== 'deal') return;
    const from = rectOf('.pile-btn.stock .stack-1');
    if (!from) return;
    opponents.forEach((p, j) => {
      document.querySelectorAll<HTMLElement>(`[data-seat="${p.id}"] .seat-card`).forEach((el, i) => {
        flyFrom(el, from, { delay: (i * flight.players + j + 1) * flight.step, duration: 380, rotate: 20 });
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flight?.key]);

  // Replay each new move as a card flight: draws go pile -> seat, discards
  // go from the player (seat or your hand) onto the discard pile.
  const seenSeq = useRef<{ game: string; seq: number } | null>(null);
  useLayoutEffect(() => {
    const prev = seenSeq.current;
    seenSeq.current = { game: state.game_id, seq: state.last_event_seq };
    if (!prev || prev.game !== state.game_id) return;
    const fresh = state.events.filter((e) => e.seq > prev.seq && e.round_number === state.round_number);
    let delay = 0;
    for (const e of fresh) {
      const seat = rectOf(`[data-seat="${e.player_id}"] .seat-fan`);
      if (e.player_id !== 'player-1') flash(`[data-seat="${e.player_id}"]`, 'just-moved', 1600);
      if (e.player_id !== 'player-1' && (e.action === 'draw_stock' || e.action === 'draw_discard') && seat) {
        const pile = rectOf(e.action === 'draw_stock' ? '.pile-btn.stock .stack-1' : '.pile-btn.discard');
        if (pile) ghostFly(pile, seat, { delay });
        delay += 380;
      }
      if (e.action === 'discard' && e.card && top && e.card.id === top.id) {
        const el = document.querySelector<HTMLElement>('.pile-btn.discard .pc');
        const origin = discardOriginRef.current;
        const from = e.player_id === 'player-1' ? (origin?.cardId === e.card.id ? origin.rect : rectOf('.hand')) : seat;
        if (el && from) flyFrom(el, from, { delay, duration: 440, rotate: e.player_id === 'player-1' ? -8 : 14 });
        if (el) window.setTimeout(() => flash('.pile-btn.discard .pc', 'just-landed', 1400), delay + 300);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.last_event_seq, state.game_id]);

  return (
    <div className="table">
      <div className="seats">
        {opponents.map((p) => (
          <OpponentSeat
            key={p.id}
            player={p}
            active={state.current_player_id === p.id && !state.round_result}
            move={lastMoveText(state.events, p.id, state.round_number)}
          />
        ))}
      </div>

      <div className="piles">
        <div className="pile">
          <button
            type="button"
            className={`pile-btn stock ${drawable ? 'is-drawable' : ''} ${pickHint === 'stock' ? 'is-hinted' : ''}`}
            onClick={() => onDraw('stock')}
            disabled={!drawable}
            aria-label={`Draw from the stock, ${state.cards_in_deck} cards left`}
          >
            <span className="stock-stack" aria-hidden="true">
              <PlayingCard faceDown size="lg" className="stack-3" />
              <PlayingCard faceDown size="lg" className="stack-2" />
              <PlayingCard faceDown size="lg" className="stack-1" />
            </span>
          </button>
          <span className="pile-caption">Stock, {state.cards_in_deck} left</span>
        </div>

        <div className="pile">
          <button
            type="button"
            className={`pile-btn discard ${drawable && top ? 'is-drawable' : ''} ${pickHint === 'discard' ? 'is-hinted' : ''}`}
            onClick={() => onDraw('discard')}
            disabled={!drawable || !top}
            aria-label={top ? `Pick up ${cardLabel(top)} from the discard pile` : 'Discard pile is empty'}
          >
            {top ? (
              <PlayingCard key={top.id} card={top} size="lg" className="discard-top" wildNote={wildNote} />
            ) : (
              <span className="pile-empty" />
            )}
          </button>
          <span className="pile-caption">Discard pile</span>
        </div>

        <div className="pile wild">
          <button type="button" className="wild-btn" onClick={onShowRules} aria-label={`${wildNote}. Open the rules`}>
            {state.cut_card && <PlayingCard card={state.cut_card} size="md" className="wild-card" />}
          </button>
          <span className="pile-caption wild-caption">{wildNote}</span>
        </div>
      </div>

      <p className={`prompt ${state.is_human_turn ? 'is-yours' : ''}`} aria-live="polite">
        {prompt}
      </p>
    </div>
  );
}
