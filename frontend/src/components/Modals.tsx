import { useEffect, useRef, type ReactNode } from 'react';
import type { Card, CheckResponse, RoundResult } from '../api';
import { MELD_LABEL, cardLabel } from '../cards';
import { PlayingCard } from './PlayingCard';

// Base dialog: dark backdrop, focus trap, and Escape to close.
export function Modal({
  title,
  onClose,
  children,
  wide,
  tone,
}: {
  title: string;
  onClose?: () => void;
  children: ReactNode;
  wide?: boolean;
  tone?: 'win' | 'lose';
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>('[data-autofocus]') ?? el?.querySelector<HTMLElement>('button');
    first?.focus();
    // Closes on Escape and keeps Tab focus inside the dialog.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current?.();
      if (e.key === 'Tab' && el) {
        const items = el.querySelectorAll<HTMLElement>('button, [href], input, [tabindex]:not([tabindex="-1"])');
        if (!items.length) return;
        const a = items[0];
        const z = items[items.length - 1];
        if (e.shiftKey && document.activeElement === a) {
          e.preventDefault();
          z.focus();
        } else if (!e.shiftKey && document.activeElement === z) {
          e.preventDefault();
          a.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, []);

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div
        ref={ref}
        className={`modal ${wide ? 'modal-wide' : ''} ${tone ? `modal-${tone}` : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="modal-head">
          <h2 id="modal-title">{title}</h2>
          {onClose && (
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
              ✕
            </button>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

// The How to play dialog with rules, scoring and controls.
export function HowToPlay({ wildNote, onClose }: { wildNote: string | null; onClose: () => void }) {
  return (
    <Modal title="How to play" onClose={onClose} wide>
      <div className="rules">
        <p className="rules-lede">
          Arrange all 13 cards into sequences and sets, then declare before your opponents do.
        </p>
        <h3>Each turn</h3>
        <ol>
          <li>Draw one card: from the stock (face down) or the top of the discard pile.</li>
          <li>Select one card and press Discard. Your turn ends.</li>
        </ol>
        <h3>Melds</h3>
        <ul>
          <li>
            <b>Pure sequence</b>: 3 or more cards in a row of the same suit, no jokers. Example: 4♥ 5♥ 6♥.
          </li>
          <li>
            <b>Sequence with joker</b>: a run where a joker fills a gap. Example: 4♥ ★ 6♥.
          </li>
          <li>
            <b>Set</b>: 3 or 4 cards of the same rank in different suits. Example: 9♠ 9♦ 9♣.
          </li>
        </ul>
        <h3>Jokers</h3>
        <p>
          The printed jokers and every card of the wild rank can stand in for any card in a sequence with joker or a
          set. Wild cards in your hand carry a gold star.{wildNote ? ` This round: ${wildNote.toLowerCase()}.` : ''}
        </p>
        <h3>Declaring</h3>
        <p>
          You need at least two sequences, and one of them must be pure. Every other card must sit in a valid meld.
          After drawing, select your 14th card and press Declare: that card goes to the finish slot and the rest of
          your groups are checked.
        </p>
        <h3>Scoring</h3>
        <ul>
          <li>The winner scores 0. Other players score the value of their ungrouped cards (A, K, Q, J, 10 = 10 points; others face value; jokers 0), up to 80.</li>
          <li>Without a pure sequence and a second sequence, a hand counts in full (max 80).</li>
          <li>Wrong show: declaring an invalid hand costs 80 points.</li>
          <li>Drop: giving up before your first draw costs 20; later, 40.</li>
          <li>Points add up over rounds. Lowest total is ahead.</li>
        </ul>
        <h3>Controls</h3>
        <ul>
          <li>Click a card to select it. Drag cards between groups, or select several and press Group.</li>
          <li>Keyboard: Tab to a card, Enter to select it, then the arrow keys move it.</li>
          <li>Auto-arrange groups your hand for you. Hint highlights the coach’s pick on the table.</li>
        </ul>
        <h3>Coach</h3>
        <ul>
          <li>The Coach panel shows the best next move and explains why, every turn.</li>
          <li>After each move it grades you: Best move, Close, or Better option, with what the better move was.</li>
          <li>It lists the cards that would help you, and what each opponent has picked up so you know what not to throw.</li>
          <li>Turn on “Let me think first” to hide the answer until you choose your own move.</li>
        </ul>
      </div>
    </Modal>
  );
}

// Confirms a declaration and warns if the hand is not valid.
export function DeclareDialog({
  groups,
  finish,
  check,
  busy,
  onConfirm,
  onClose,
}: {
  groups: Card[][];
  finish: Card;
  check: CheckResponse | null;
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const valid = check?.declaration.is_valid ?? false;
  return (
    <Modal title="Declare your hand?" onClose={onClose} wide>
      <p className="modal-copy">
        {cardLabel(finish)} goes to the finish slot. These groups will be checked:
      </p>
      <div className="declare-groups">
        {groups.map((g, i) => {
          const res = check?.groups[i];
          return (
            <div key={i} className={`declare-group ${res ? (res.is_valid ? 'ok' : 'bad') : ''}`}>
              <div className="mini-row">
                {g.map((c) => (
                  <PlayingCard key={c.id} card={c} size="xs" />
                ))}
              </div>
              <span className="declare-tag">
                {!res ? 'Checking…' : res.is_valid ? `✓ ${MELD_LABEL[res.meld_type]}` : `✕ ${g.length < 3 ? 'Too few cards' : 'Not a meld'}`}
              </span>
            </div>
          );
        })}
      </div>
      {check && (
        <p className={`verdict ${valid ? 'verdict-ok' : 'verdict-bad'}`} role="status">
          {valid
            ? 'This hand is valid. Declaring wins the round.'
            : `This hand is not valid: ${(check.declaration.reason ?? 'some groups are not melds').replace(/\.$/, '')}. Declaring now is a wrong show and costs 80 points.`}
        </p>
      )}
      <div className="modal-actions">
        <button type="button" className="btn btn-ghost" onClick={onClose} data-autofocus={!valid || undefined}>
          Keep playing
        </button>
        <button
          type="button"
          className={`btn ${valid ? 'btn-primary' : 'btn-danger'}`}
          onClick={onConfirm}
          disabled={busy || !check}
          data-autofocus={valid || undefined}
        >
          {valid ? 'Declare' : 'Declare anyway (+80)'}
        </button>
      </div>
    </Modal>
  );
}

// End-of-round results: every hand, points this round and totals.
export function ResultsDialog({
  result,
  busy,
  onNext,
  onNewGame,
  coachLine,
}: {
  result: RoundResult;
  busy: boolean;
  onNext: () => void;
  onNewGame: () => void;
  coachLine?: string;
}) {
  const me = result.players.find((p) => p.is_human);
  const won = !!me?.is_winner;
  const title =
    result.outcome === 'stock_exhausted'
      ? `Round ${result.round_number} is a draw`
      : won
        ? `You won round ${result.round_number}`
        : `${result.winner_name ?? 'Nobody'} won round ${result.round_number}`;
  const leader = [...result.players].sort((a, b) => a.total_score - b.total_score)[0];

  return (
    <Modal title={title} wide tone={won ? 'win' : 'lose'}>
      <p className="modal-copy">
        {result.message}
      </p>
      <table className="score-table">
        <thead>
          <tr>
            <th scope="col">Player</th>
            <th scope="col">Hand</th>
            <th scope="col" className="num">This round</th>
            <th scope="col" className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {result.players.map((p) => (
            <tr key={p.player_id} className={p.is_winner ? 'is-winner' : ''}>
              <th scope="row">
                {p.name}
                {p.is_winner && <span className="winner-star" aria-label="winner"> ★</span>}
                {p.note && <span className="row-note">{p.note}</span>}
              </th>
              <td>
                <div className="result-hand">
                  {p.groups.map((g, i) => (
                    <div key={i} className={`result-group rg-${g.meld_type}`} title={MELD_LABEL[g.meld_type]}>
                      {g.cards.map((c) => (
                        <PlayingCard key={c.id} card={c} size="xs" />
                      ))}
                    </div>
                  ))}
                  {p.deadwood.length > 0 && (
                    <div className="result-group rg-deadwood" title="Ungrouped cards">
                      {p.deadwood.map((c) => (
                        <PlayingCard key={c.id} card={c} size="xs" />
                      ))}
                    </div>
                  )}
                </div>
              </td>
              <td className="num">{p.points}</td>
              <td className="num strong">{p.total_score}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="modal-foot-note">
        {leader.is_human ? 'You lead the table.' : `${leader.name} leads the table.`} Lowest total is ahead.
      </p>
      {coachLine && <p className="modal-coach-line">{coachLine}</p>}
      <div className="modal-actions">
        <button type="button" className="btn btn-ghost" onClick={onNewGame}>
          New game
        </button>
        <button type="button" className="btn btn-primary" onClick={onNext} disabled={busy} data-autofocus>
          Deal next round
        </button>
      </div>
    </Modal>
  );
}

// A simple yes/cancel confirmation dialog.
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="modal-copy">{body}</p>
      <div className="modal-actions">
        <button type="button" className="btn btn-ghost" onClick={onClose} data-autofocus>
          Cancel
        </button>
        <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
