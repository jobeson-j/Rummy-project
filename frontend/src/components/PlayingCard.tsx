import type { DragEvent, KeyboardEvent, ReactNode } from 'react';
import type { Card } from '../api';
import { SUIT_SYMBOL, cardAria, isPrinted, isRed } from '../cards';

export type CardSize = 'lg' | 'md' | 'sm' | 'xs';

interface Props {
  card?: Card | null;
  size?: CardSize;
  faceDown?: boolean;
  selected?: boolean;
  hinted?: boolean;
  fresh?: boolean;
  dimmed?: boolean;
  wildNote?: string;
  onClick?: () => void;
  onKeyDown?: (e: KeyboardEvent<HTMLButtonElement>) => void;
  draggable?: boolean;
  onDragStart?: (e: DragEvent) => void;
  onDragEnd?: (e: DragEvent) => void;
  onDragOver?: (e: DragEvent) => void;
  onDrop?: (e: DragEvent) => void;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
  children?: ReactNode;
}

// Draws a card's face: corner indexes and the centre pip or letter.
export function CardFace({ card }: { card: Card }) {
  if (isPrinted(card)) {
    return (
      <span className="pc-face pc-printed" aria-hidden="true">
        <span className="pc-index">
          <span className="pc-rank">★</span>
        </span>
        <span className="pc-joker-word">Joker</span>
        <span className="pc-index pc-index-bottom">
          <span className="pc-rank">★</span>
        </span>
      </span>
    );
  }
  const sym = SUIT_SYMBOL[card.suit];
  const face = ['J', 'Q', 'K'].includes(card.rank);
  return (
    <span className="pc-face" aria-hidden="true">
      <span className="pc-index">
        <span className="pc-rank">{card.rank}</span>
        <span className="pc-suit">{sym}</span>
      </span>
      <span className={`pc-pip ${face ? 'pc-pip-face' : ''}`}>{face ? card.rank : sym}</span>
      <span className="pc-index pc-index-bottom">
        <span className="pc-rank">{card.rank}</span>
        <span className="pc-suit">{sym}</span>
      </span>
    </span>
  );
}

// One playing card, clickable or static, face up or face down.
export function PlayingCard({
  card,
  size = 'md',
  faceDown,
  selected,
  hinted,
  fresh,
  dimmed,
  wildNote,
  onClick,
  onKeyDown,
  draggable,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  ariaLabel,
  disabled,
  className = '',
  children,
}: Props) {
  const tone = card && !faceDown ? (isRed(card) ? 'pc-red' : 'pc-black') : '';
  const joker = card && !faceDown && (card.is_wild_joker || isPrinted(card));
  const classes = [
    'pc',
    `pc-${size}`,
    faceDown ? 'pc-back' : tone,
    joker ? 'pc-joker' : '',
    selected ? 'is-selected' : '',
    hinted ? 'is-hinted' : '',
    fresh ? 'is-fresh' : '',
    dimmed ? 'is-dimmed' : '',
    onClick ? 'is-interactive' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const content = (
    <>
      {faceDown || !card ? <span className="pc-back-pattern" aria-hidden="true" /> : <CardFace card={card} />}
      {joker && card?.is_wild_joker && (
        <span className="pc-wild-badge" aria-hidden="true" title={wildNote}>
          ★
        </span>
      )}
      {children}
    </>
  );

  const label = ariaLabel ?? (card && !faceDown ? cardAria(card) : 'Face-down card');

  if (onClick) {
    return (
      <button
        type="button"
        className={classes}
        onClick={onClick}
        onKeyDown={onKeyDown}
        aria-label={label}
        aria-pressed={selected}
        disabled={disabled}
        draggable={draggable}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDragOver={onDragOver}
        onDrop={onDrop}
        title={joker && wildNote ? wildNote : undefined}
      >
        {content}
      </button>
    );
  }
  return (
    <span className={classes} role="img" aria-label={label} title={joker && wildNote ? wildNote : undefined}>
      {content}
    </span>
  );
}
