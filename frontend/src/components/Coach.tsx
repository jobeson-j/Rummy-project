import { useState } from 'react';
import type { CoachResponse } from '../api';
import { cardLabel } from '../cards';

export type Grade = 'best' | 'good' | 'miss';

export interface MoveReview {
  key: number;
  grade: Grade;
  move: string; // what you did, e.g. "Discarded K♣"
  text: string; // what the coach thinks
}

export interface CoachStats {
  moves: number;
  best: number;
  good: number;
}

const STAGE_LABEL: Record<CoachResponse['stage'], string> = {
  draw: 'Your draw',
  discard: 'Your discard',
  waiting: 'Opponent’s turn',
  over: 'Round over',
};

const GRADE_LABEL: Record<Grade, string> = { best: 'Best move', good: 'Close', miss: 'Better option' };

interface Props {
  coach: CoachResponse | null;
  loading: boolean;
  review: MoveReview | null;
  stats: CoachStats;
  thinkFirst: boolean;
  revealed: boolean;
  onToggleThink: () => void;
  onReveal: () => void;
  onShowMe: () => void;
  variant?: 'panel' | 'strip';
  error?: string | null;
  onRetry?: () => void;
}

// The coach panel: best move, move grade, helpful cards, opponent reads and a lesson.
export function Coach({
  coach,
  loading,
  review,
  stats,
  thinkFirst,
  revealed,
  onToggleThink,
  onReveal,
  onShowMe,
  variant = 'panel',
  error,
  onRetry,
}: Props) {
  const [moreOpen, setMoreOpen] = useState(false);
  const yourMove = coach?.stage === 'draw' || coach?.stage === 'discard';
  const hidden = thinkFirst && yourMove && !revealed;
  const pct = stats.moves ? Math.round((100 * stats.best) / stats.moves) : null;

  const errorBlock = error && (
    <div className="coach-error" role="alert">
      <p>{error}</p>
      {onRetry && (
        <button type="button" className="btn btn-small btn-coach" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );

  const bestMove = !error && coach && (
    <div className={`coach-best ${yourMove ? 'is-yours' : ''} ${loading ? 'is-loading' : ''}`} aria-live="polite">
      <span className="coach-stage">{STAGE_LABEL[coach.stage]}</span>
      {hidden ? (
        <>
          <p className="coach-think">What would you do? Make your move, or reveal the coach’s pick.</p>
          <button type="button" className="btn btn-small btn-coach" onClick={onReveal}>
            Reveal best move
          </button>
        </>
      ) : (
        <>
          <p className="coach-headline">{coach.headline}</p>
          <p className="coach-detail">{coach.detail}</p>
          {yourMove && coach.action.kind !== 'none' && (
            <button type="button" className="btn btn-small btn-coach" onClick={onShowMe}>
              {coach.stage === 'draw' ? 'Show me the pile' : 'Select that card'}
            </button>
          )}
        </>
      )}
    </div>
  );

  const reviewBlock = review && (
    <div className={`coach-review grade-${review.grade}`} role="status">
      <span className="coach-grade">
        <span aria-hidden="true">{review.grade === 'best' ? '✓' : review.grade === 'good' ? '≈' : '!'}</span>{' '}
        {GRADE_LABEL[review.grade]}
      </span>
      <p>
        <b>{review.move}.</b> {review.text}
      </p>
    </div>
  );

  if (variant === 'strip') {
    return (
      <section className="coach coach-strip" aria-label="Coach">
        {errorBlock}
        {bestMove}
        {reviewBlock}
      </section>
    );
  }

  const others = coach?.stage === 'discard' ? coach.options.slice(1, 4) : [];

  return (
    <section className="coach" aria-label="Coach">
      <div className="coach-head">
        <h2 className="coach-title">Coach</h2>
        <label className="switch">
          <input type="checkbox" checked={thinkFirst} onChange={onToggleThink} />
          <span className="switch-track" aria-hidden="true" />
          Let me think first
        </label>
      </div>

      {errorBlock}
      {!coach && !error && (
        <p className="coach-detail">{loading ? 'Reading the table…' : 'The coach appears once cards are dealt.'}</p>
      )}
      {bestMove}
      {reviewBlock}

      {coach && !hidden && coach.status && <p className="coach-status">{coach.status}</p>}

      {coach && coach.outs.length > 0 && (
        <div className="coach-block">
          <h3>Cards that help you</h3>
          <p className="coach-sub">
            {coach.out_copies} of about {coach.unseen_cards} unseen cards improve your hand: roughly{' '}
            {Math.round(coach.out_chance_pct)}% per stock draw.
          </p>
          <ul className="outs">
            {coach.outs.map((o) => (
              <li key={o.label}>
                <span className="out-card">{o.label}</span>
                <span className="out-copies">×{o.copies_left}</span>
                <span className="out-effect">{o.effect}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {others.length > 0 && !hidden && (
        <div className="coach-block">
          <button type="button" className="coach-toggle" onClick={() => setMoreOpen(!moreOpen)} aria-expanded={moreOpen}>
            {moreOpen ? '▾' : '▸'} Compare other discards
          </button>
          {moreOpen && (
            <ul className="alt-list">
              {others.map((o) => (
                <li key={o.card.id}>
                  <b>{cardLabel(o.card)}</b>
                  <span className="alt-cost">
                    {o.cost === coach!.options[0].cost ? 'just as good' : `+${o.cost - coach!.options[0].cost} worse`}
                  </span>
                  {o.danger && <span className="alt-danger">{o.danger}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {coach && coach.reads.length > 0 && (
        <div className="coach-block">
          <h3>What opponents are collecting</h3>
          <ul className="reads">
            {coach.reads.map((r) => (
              <li key={r.player_id}>{r.text}</li>
            ))}
          </ul>
        </div>
      )}

      {coach?.tip && (
        <div className="coach-tip">
          <h3>Lesson</h3>
          <p>{coach.tip}</p>
        </div>
      )}

      <p className="coach-score">
        {stats.moves
          ? `You matched the coach on ${stats.best} of ${stats.moves} moves (${pct}%)${stats.good ? `, close on ${stats.good} more` : ''}.`
          : 'Each move you make is compared with the coach’s pick.'}
      </p>
    </section>
  );
}
