import type { GameEvent } from '../api';

const ICON: Record<GameEvent['action'], string> = {
  round_start: '◆',
  draw_stock: '↥',
  draw_discard: '↥',
  discard: '↧',
  declare: '★',
  wrong_show: '✕',
  drop: '⤓',
  reshuffle: '↻',
  stock_empty: '∅',
};

// The table log: every move this round, newest first.
export function Log({ events, round }: { events: GameEvent[]; round: number }) {
  const items = events.filter((e) => e.round_number === round).slice().reverse();
  return (
    <section className="log" aria-label="Table log">
      <h2 className="log-title">Table log</h2>
      <ol className="log-list" aria-live="polite" aria-relevant="additions">
        {items.map((e) => (
          <li key={e.seq} className={`log-item log-${e.action} ${e.player_id === 'player-1' ? 'is-you' : ''}`}>
            <span className="log-icon" aria-hidden="true">
              {ICON[e.action]}
            </span>
            <span>{e.message}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
