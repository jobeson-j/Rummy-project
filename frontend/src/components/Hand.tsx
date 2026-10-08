import { useLayoutEffect, useRef, useState, type CSSProperties, type DragEvent, type KeyboardEvent } from 'react';
import type { Card, MeldValidation } from '../api';
import type { Flight } from '../App';
import { flyFrom, rectOf } from '../fly';
import { play } from '../sound';
import { MELD_LABEL } from '../cards';
import { PlayingCard } from './PlayingCard';

interface Props {
  groups: Card[][];
  labels: (MeldValidation | null)[];
  selected: Set<string>;
  hintId: string | null;
  freshIds: Set<string>;
  wildNote: string;
  onToggle: (id: string) => void;
  onMove: (cardId: string, toGroup: number | 'new', toIndex: number) => void;
  onKeyMove: (cardId: string, dir: -1 | 1) => void;
  flight: Flight | null;
}

type DropTarget = { group: number | 'new'; index: number } | null;

const MIN_W = 46;

// Largest card width that still fits the table and hand in the window height.
function maxCardForHeight(vh: number): number {
  const pileW = Math.min(92, Math.max(58, vh * 0.095));
  // top bar, opponents row, captions, prompt, panel padding, toolbar; on
  // narrower screens the coach strip also sits inside the hand panel
  const chrome = 520 + (window.innerWidth <= 1180 ? 165 : 0);
  const room = vh - chrome - pileW * 1.42;
  return Math.round(Math.max(56, Math.min(92, room / 1.42)));
}
const GROUP_GAP = 26; // 22px flex gap + 2px group border + rounding slack

// Card width that fits the hand on one row without overflowing the panel.
/** Pick a card width so the whole hand fits on one row when possible, and
 *  never lets a single group run wider than the panel. */
function fitCardWidth(avail: number, sizes: number[], overlap: number, MAX_W: number): number {
  if (!avail || !sizes.length) return MAX_W;
  const visible = 1 - overlap;
  const units = sizes.reduce((n, k) => n + 1 + (k - 1) * visible, 0);
  const oneRow = (avail - GROUP_GAP * (sizes.length - 1)) / units;
  const largest = Math.max(...sizes);
  const groupFit = avail / (1 + (largest - 1) * visible);
  return Math.floor(Math.max(MIN_W, Math.min(MAX_W, oneRow, groupFit)));
}

// Label under a group: its meld type, or how many cards it still needs.
function GroupLabel({ label, size }: { label: MeldValidation | null; size: number }) {
  if (size < 3) {
    return <span className="grp-label grp-label-muted">{size === 1 ? 'Single card' : 'Needs 1 more card'}</span>;
  }
  if (!label) return <span className="grp-label grp-label-muted">Checking…</span>;
  const ok = label.is_valid;
  return (
    <span className={`grp-label ${ok ? `grp-ok grp-${label.meld_type}` : 'grp-bad'}`}>
      {ok ? (
        <>
          <span aria-hidden="true">✓</span> {MELD_LABEL[label.meld_type]}
        </>
      ) : (
        'No meld yet'
      )}
    </span>
  );
}

// Your hand: groups of overlapping cards you can select, drag and reorder.
export function Hand({ groups, labels, selected, hintId, freshIds, wildNote, onToggle, onMove, onKeyMove, flight }: Props) {
  const [dragId, setDragId] = useState<string | null>(null);
  const [target, setTarget] = useState<DropTarget>(null);
  const ref = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(0);
  const [vh, setVh] = useState(() => window.innerHeight);
  useLayoutEffect(() => {
    // Tracks the window height so cards can shrink to fit.
    const onResize = () => setVh(window.innerHeight);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setAvail(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Fly newly dealt / drawn cards in from the pile they came from.
  useLayoutEffect(() => {
    if (!flight) return;
    const from = rectOf(flight.from === 'stock' ? '.pile-btn.stock .stack-1' : '.pile-btn.discard');
    if (!from) return;
    flight.ids.forEach((id, i) => {
      const el = document.querySelector<HTMLElement>(`[data-card-id="${id}"] .pc`);
      if (!el) return;
      if (flight.kind === 'deal') {
        // round-robin: you get card i at slot i * players
        const delay = i * flight.players * flight.step;
        flyFrom(el, from, { delay, duration: 420, rotate: -24, onStart: i % 2 === 0 ? () => play('draw') : undefined });
      } else {
        flyFrom(el, from, { duration: 480, rotate: flight.from === 'stock' ? -10 : 8 });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flight?.key]);

  const overlap = avail && avail < 520 ? 0.58 : 0.5;
  const cardW = fitCardWidth(avail - 8, groups.map((g) => g.length), overlap, maxCardForHeight(vh));

  // Starts dragging a card.
  const startDrag = (e: DragEvent, id: string) => {
    setDragId(id);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', id);
  };
  // Clears the drag state when dragging stops.
  const endDrag = () => {
    setDragId(null);
    setTarget(null);
  };
  // Works out where a dragged card would land when it's over another card.
  const overCard = (e: DragEvent, g: number, i: number) => {
    if (!dragId) return;
    e.preventDefault();
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    // Cards overlap, so only the visible left part counts as "before".
    const before = e.clientX < rect.left + rect.width * 0.3;
    const index = before ? i : i + 1;
    if (!target || target.group !== g || target.index !== index) setTarget({ group: g, index });
  };
  // Targets the end of a group (or a new group) while dragging.
  const overGroup = (e: DragEvent, g: number | 'new', len: number) => {
    if (!dragId) return;
    e.preventDefault();
    if (!target || target.group !== g) setTarget({ group: g, index: len });
  };
  // Moves the dragged card to the chosen spot.
  const drop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation(); // the card and its group both listen; handle the drop once
    if (dragId && target) onMove(dragId, target.group, target.index);
    endDrag();
  };

  // Lets the arrow keys move a selected card.
  const keyDown = (e: KeyboardEvent<HTMLButtonElement>, id: string) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      if (selected.has(id) && selected.size === 1) {
        e.preventDefault();
        onKeyMove(id, e.key === 'ArrowLeft' ? -1 : 1);
      }
    }
  };

  return (
    <div
      ref={ref}
      className={`hand ${dragId ? 'is-dragging' : ''}`}
      role="group"
      aria-label="Your hand, arranged in groups"
      style={{ '--card-w': `${cardW}px`, '--card-overlap': overlap } as CSSProperties}
    >
      {groups.map((group, g) => (
        <div
          key={`g-${g}-${group[0]?.id ?? 'empty'}`}
          className={`grp ${target?.group === g ? 'is-drop-target' : ''}`}
          onDragOver={(e) => overGroup(e, g, group.length)}
          onDrop={drop}
        >
          <div className="grp-cards">
            {group.map((card, i) => {
              const showGap = dragId && target?.group === g && target.index === i && card.id !== dragId;
              return (
                <div
                  key={card.id}
                  data-card-id={card.id}
                  className={`slot ${showGap ? 'has-gap' : ''} ${dragId === card.id ? 'is-ghost' : ''}`}
                  style={{ zIndex: i + 1 }}
                >
                  <PlayingCard
                    card={card}
                    size="lg"
                    selected={selected.has(card.id)}
                    hinted={hintId === card.id}
                    fresh={freshIds.has(card.id)}
                    wildNote={wildNote}
                    onClick={() => onToggle(card.id)}
                    onKeyDown={(e) => keyDown(e, card.id)}
                    draggable
                    onDragStart={(e) => startDrag(e, card.id)}
                    onDragEnd={endDrag}
                    onDragOver={(e) => overCard(e, g, i)}
                    onDrop={drop}
                  />
                </div>
              );
            })}
            {dragId && target?.group === g && target.index === group.length && <div className="slot-end-gap" />}
          </div>
          <GroupLabel label={labels[g] ?? null} size={group.length} />
        </div>
      ))}
      {dragId && (
        <div
          className={`grp grp-new ${target?.group === 'new' ? 'is-drop-target' : ''}`}
          onDragOver={(e) => overGroup(e, 'new', 0)}
          onDrop={drop}
        >
          <span>Drop here to start a new group</span>
        </div>
      )}
    </div>
  );
}
