import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  api,
  errorMessage,
  type Card,
  type CheckResponse,
  type CoachResponse,
  type Difficulty,
  type MeldValidation,
  type PublicGameState,
} from './api';
import { cardLabel, groupByRank, groupBySuit, orderMeld, wildRankLabel } from './cards';
import { Coach, type CoachStats, type MoveReview } from './components/Coach';
import { Hand } from './components/Hand';
import { Log } from './components/Log';
import { ConfirmDialog, DeclareDialog, HowToPlay, ResultsDialog } from './components/Modals';
import { PlayingCard } from './components/PlayingCard';
import { Table } from './components/Table';
import { isMuted, play, setMuted } from './sound';
import './App.css';

type Hint =
  | { kind: 'pick'; source: 'stock' | 'discard'; text: string }
  | { kind: 'discard'; cardId: string; text: string }
  | null;

type Dialog = 'rules' | 'declare' | 'newgame' | 'drop' | null;

export interface Flight {
  key: number;
  kind: 'deal' | 'draw';
  ids: string[];
  from: 'stock' | 'discard';
  step: number; // ms between dealt cards (deal only)
  players: number;
}

export interface DiscardOrigin {
  cardId: string;
  rect: DOMRect;
}

const OLD_BACKEND =
  'The game server is still running the old code. Stop the backend (Ctrl+C) and start it again with: uvicorn app.main:app --reload --port 8000';

// Throws a clear error if the server is running old code.
function assertNewBackend(s: PublicGameState) {
  if (!Array.isArray(s.events) || !Array.isArray(s.players_summary) || !('can_drop' in s)) {
    throw new Error(OLD_BACKEND);
  }
}

interface Toast {
  id: number;
  text: string;
  tone: 'error' | 'info';
}

const BOT_DELAY_MS = 950;
// Stable key for a group of card ids, used to cache meld labels.
const groupKey = (g: string[]) => g.join('|');

const HERO_CARDS: Card[] = [
  { id: 'h1', suit: 'S', rank: 'A', deck_no: 1, is_wild_joker: false },
  { id: 'h2', suit: 'H', rank: 'K', deck_no: 1, is_wild_joker: false },
  { id: 'h3', suit: 'JK', rank: 'PJ', deck_no: 1, is_wild_joker: false },
  { id: 'h4', suit: 'D', rank: 'Q', deck_no: 1, is_wild_joker: false },
  { id: 'h5', suit: 'C', rank: '7', deck_no: 1, is_wild_joker: true },
];

// The whole game screen: start screen, table, hand, coach and dialogs.
export default function App() {
  const [game, setGame] = useState<PublicGameState | null>(null);
  const [groups, setGroups] = useState<string[][]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [labelMap, setLabelMap] = useState<Record<string, MeldValidation>>({});
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState<Hint>(null);
  // ---- coach
  const [coach, setCoach] = useState<(CoachResponse & { forSeq: number }) | null>(null);
  const [review, setReview] = useState<MoveReview | null>(null);
  const [stats, setStats] = useState<CoachStats>({ moves: 0, best: 0, good: 0 });
  const [roundStats, setRoundStats] = useState<CoachStats>({ moves: 0, best: 0, good: 0 });
  const [thinkFirst, setThinkFirst] = useState<boolean>(() => {
    try {
      return localStorage.getItem('smart-rummy-think-first') === '1';
    } catch {
      return false;
    }
  });
  const [revealedSeq, setRevealedSeq] = useState(-1);
  const [coachError, setCoachError] = useState<{ key: string; text: string } | null>(null);
  const [coachRetry, setCoachRetry] = useState(0);
  const reviewSeqRef = useRef(0);
  const [summary, setSummary] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [declareCheck, setDeclareCheck] = useState<CheckResponse | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [muted, setMutedState] = useState(isMuted());
  const [opponents, setOpponents] = useState(1);
  const [difficulty, setDifficulty] = useState<Difficulty>('medium');
  const [botFailures, setBotFailures] = useState(0);
  const [flight, setFlight] = useState<Flight | null>(null);
  const dealEndRef = useRef(0);
  const discardOriginRef = useRef<DiscardOrigin | null>(null);
  const roundRef = useRef(0);
  const groupsRef = useRef<string[][]>([]);
  useEffect(() => {
    groupsRef.current = groups;
  }, [groups]);

  // ---------------------------------------------------------------- helpers
  // Shows a short message at the top of the screen.
  const toast = useCallback((text: string, tone: Toast['tone'] = 'error') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, text, tone }]);
    if (tone === 'error') play('error');
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), Math.max(4500, text.length * 70));
  }, []);

  // Applies a new server state while keeping your card arrangement.
  const applyState = useCallback((next: PublicGameState): string[] => {
    const ids = next.human_hand.map((c) => c.id);
    let addedIds: string[] = [];
    if (next.round_number !== roundRef.current) {
      roundRef.current = next.round_number;
      const dealt = groupBySuit(next.human_hand).map((g) => g.map((c) => c.id));
      setGroups(dealt);
      setSelected(new Set());
      setFresh(new Set());
      // Deal animation: cards leave the stock one at a time, round-robin.
      const players = next.players_summary.length;
      const step = Math.max(45, Math.min(85, 2000 / (13 * players)));
      dealEndRef.current = Date.now() + 13 * players * step + 500;
      setFlight({ key: Date.now(), kind: 'deal', ids: dealt.flat(), from: 'stock', step, players });
      window.setTimeout(() => play('turn'), 13 * players * step + 300);
    } else {
      const present = new Set(ids);
      const kept = groupsRef.current.map((g) => g.filter((id) => present.has(id))).filter((g) => g.length);
      const known = new Set(kept.flat());
      const added = ids.filter((id) => !known.has(id));
      addedIds = added;
      setGroups(added.length ? [...kept, added] : kept);
      setSelected((s) => new Set([...s].filter((id) => present.has(id))));
      if (added.length) {
        setFresh(new Set(added));
        window.setTimeout(() => setFresh(new Set()), 1800);
      }
    }
    setGame(next);
    return addedIds;
  }, []);

  // Runs a server call once at a time and shows any error as a toast.
  const run = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
      if (busy) return undefined;
      setBusy(true);
      try {
        return await fn();
      } catch (err) {
        toast(errorMessage(err));
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [busy, toast],
  );

  const cardsById = useMemo(() => {
    const m = new Map<string, Card>();
    game?.human_hand.forEach((c) => m.set(c.id, c));
    return m;
  }, [game?.human_hand]);

  const cardGroups = useMemo(
    () => groups.map((g) => g.map((id) => cardsById.get(id)).filter((c): c is Card => !!c)),
    [groups, cardsById],
  );

  // ------------------------------------------------------- live meld labels
  useEffect(() => {
    if (!game) return;
    const missing = groups.filter((g) => g.length >= 3 && !labelMap[groupKey(g)]);
    if (!missing.length) return;
    const t = window.setTimeout(async () => {
      try {
        const res = await api.check(game.game_id, missing);
        setLabelMap((m) => {
          const next = { ...m };
          missing.forEach((g, i) => (next[groupKey(g)] = res.groups[i]));
          return next;
        });
      } catch {
        /* labels are a convenience; ignore failures */
      }
    }, 150);
    return () => window.clearTimeout(t);
  }, [groups, game, labelMap]);

  const labels = groups.map((g) => labelMap[groupKey(g)] ?? null);

  // --------------------------------------------- distance-to-declare summary
  const handKey = game ? `${game.game_id}:${game.last_event_seq}:${game.human_hand.map((c) => c.id).sort().join(',')}` : '';
  useEffect(() => {
    if (!game || game.round_result) return;
    let alive = true;
    api
      .arrange(game.game_id)
      .then((r) => alive && setSummary(r.summary))
      .catch(() => alive && setSummary(null));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handKey]);

  // ---------------------------------------------------------- coach
  const coachKey = game && !game.round_result ? `${game.game_id}:${game.last_event_seq}:${game.human_hand.length}` : '';
  useEffect(() => {
    if (!game || game.round_result) return;
    let alive = true;
    const seq = game.last_event_seq;
    api
      .coach(game.game_id)
      .then((c) => {
        if (!alive) return;
        setCoach({ ...c, forSeq: seq });
        setCoachError(null);
      })
      .catch((err) => {
        if (!alive) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
        setCoachError({
          key: coachKey,
          text:
            status === 404
              ? 'The game server is running old code without the coach. Stop the backend (Ctrl+C) and start it again with: uvicorn app.main:app --reload --port 8000'
              : `The coach couldn't analyse this position: ${errorMessage(err)}`,
        });
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coachKey, coachRetry]);

  // Records how your move compared with the coach's pick.
  const grade = (g: MoveReview['grade'], move: string, text: string) => {
    reviewSeqRef.current += 1;
    setReview({ key: reviewSeqRef.current, grade: g, move, text });
    // Adds one move (and its grade) to a running tally.
    const bump = (x: CoachStats) => ({
      moves: x.moves + 1,
      best: x.best + (g === 'best' ? 1 : 0),
      good: x.good + (g === 'good' ? 1 : 0),
    });
    setStats(bump);
    setRoundStats(bump);
  };
  const coachFailed = coachError && coachError.key === coachKey ? coachError.text : null;
  const coachLoading = !!game && !game.round_result && !coachFailed && coach?.forSeq !== game.last_event_seq;
  // The coach's advice, only if it matches the current game state.
  const currentCoach = () => (coach && game && coach.forSeq === game.last_event_seq ? coach : null);

  // Grades your draw against the coach's advice.
  const reviewDraw = (source: 'stock' | 'discard') => {
    const c = currentCoach();
    if (!c || c.stage !== 'draw' || !game) return;
    const top = game.discard_top ? cardLabel(game.discard_top) : 'the top card';
    const move = source === 'stock' ? 'You drew from the stock' : `You took ${top}`;
    const wanted = c.action.kind === 'take_discard' ? 'discard' : 'stock';
    if (wanted === source) grade('best', move, 'That matches the coach.');
    else if (source === 'discard' && c.detail.includes('would only'))
      grade('good', move, `It helps a little, but taking it shows opponents what you collect. ${c.detail}`);
    else if (wanted === 'discard') grade('miss', move, `The coach would take ${top}. ${c.detail}`);
    else grade('miss', move, `The coach would draw from the stock. ${c.detail}`);
  };

  // Grades your discard against the coach's ranked options.
  const reviewDiscard = (cardId: string) => {
    const c = currentCoach();
    if (!c || c.stage !== 'discard' || !c.options.length) return;
    const mine = c.options.find((o) => o.card.id === cardId);
    const best = c.options[0];
    if (!mine) return;
    const move = `You discarded ${cardLabel(mine.card)}`;
    if (c.action.kind === 'declare') {
      grade('miss', move, `You could have declared! ${c.detail}`);
    } else if (mine.card.id === best.card.id || (mine.cost === best.cost && !(mine.danger && !best.danger))) {
      grade('best', move, mine.card.id === best.card.id ? 'That matches the coach.' : `Just as good as ${cardLabel(best.card)}.`);
    } else if (mine.cost - best.cost <= 3 && !mine.danger) {
      grade('good', move, `${cardLabel(best.card)} was slightly better. ${best.reasoning}`);
    } else {
      const diff = mine.cost - best.cost;
      const cost = mine.card.rank === 'PJ' || mine.card.is_wild_joker
        ? 'Never throw a joker: it can stand in for any card you are missing.'
        : `Throwing ${cardLabel(mine.card)} left your hand about ${diff} points worse off than throwing ${cardLabel(best.card)}.`;
      grade('miss', move, `${cost} ${mine.danger ?? ''} Why ${cardLabel(best.card)}: ${best.reasoning}`.replace(/\s+/g, ' '));
    }
  };

  // Highlights the coach's pick on the table or selects the card.
  const showMe = () => {
    const c = currentCoach();
    if (!c) return;
    setRevealedSeq(c.forSeq);
    if (c.stage === 'draw') setHint({ kind: 'pick', source: c.action.kind === 'take_discard' ? 'discard' : 'stock', text: '' });
    else if (c.action.card_id) {
      setHint({ kind: 'discard', cardId: c.action.card_id, text: '' });
      setSelected(new Set([c.action.card_id]));
    }
  };

  // Turns "Let me think first" on or off and remembers it.
  const toggleThink = () => {
    const v = !thinkFirst;
    setThinkFirst(v);
    try {
      localStorage.setItem('smart-rummy-think-first', v ? '1' : '0');
    } catch {
      /* per-session only */
    }
  };

  // ---------------------------------------------------------- bot turns
  useEffect(() => {
    if (!game || game.is_human_turn || game.round_result || botFailures >= 3) return;
    const wait = Math.max(BOT_DELAY_MS, dealEndRef.current - Date.now() + 400);
    const t = window.setTimeout(async () => {
      try {
        const next = await api.botTurn(game.game_id);
        applyState(next);
        play('draw');
        window.setTimeout(() => play('discard'), 380);
        if (next.is_human_turn) window.setTimeout(() => play('turn'), 700);
        setBotFailures(0);
      } catch (err) {
        setBotFailures((n) => n + 1);
        toast(`${game.current_player_name}'s turn failed: ${errorMessage(err)}`);
      }
    }, wait);
    return () => window.clearTimeout(t);
  }, [game, botFailures, applyState, toast]);

  // round end sound
  const resultRound = game?.round_result?.round_number;
  useEffect(() => {
    if (!game?.round_result) return;
    const me = game.round_result.players.find((p) => p.is_human);
    play(me?.is_winner ? 'win' : 'lose');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resultRound]);

  // ---------------------------------------------------------- actions
  // Starts a new game with the chosen opponents and difficulty.
  const startGame = () =>
    run(async () => {
      const s = await api.createGame(opponents + 1, difficulty);
      assertNewBackend(s);
      roundRef.current = 0;
      setLabelMap({});
      setHint(null);
      setReview(null);
      setCoach(null);
      setStats({ moves: 0, best: 0, good: 0 });
      setRoundStats({ moves: 0, best: 0, good: 0 });
      setBotFailures(0);
      applyState(s);
    });

  const canDraw = !!game && game.is_human_turn && game.turn_stage === 'AWAITING_DRAW';
  const canDiscard = !!game && game.is_human_turn && game.turn_stage === 'AWAITING_DISCARD';
  const single = selected.size === 1 ? cardsById.get([...selected][0]) ?? null : null;

  // Draws from the stock or discard pile and animates the new card in.
  const draw = (source: 'stock' | 'discard') =>
    run(async () => {
      if (!game) return;
      const s = await api.draw(game.game_id, source);
      reviewDraw(source);
      setHint(null);
      const added = applyState(s);
      if (added.length) setFlight({ key: Date.now(), kind: 'draw', ids: added, from: source, step: 0, players: 1 });
      play('draw');
    });

  // Discards the selected card and flies it onto the pile.
  const discard = () => {
    if (!game) return;
    if (!canDiscard) return toast('Draw a card first: click the stock or the discard pile.', 'info');
    if (!single) return toast('Select exactly one card to discard.', 'info');
    const rect = document.querySelector(`[data-card-id="${single.id}"] .pc`)?.getBoundingClientRect();
    if (rect) discardOriginRef.current = { cardId: single.id, rect };
    return run(async () => {
      const s = await api.discard(game.game_id, single.id);
      reviewDiscard(single.id);
      setHint(null);
      setSelected(new Set());
      applyState(s);
      play('discard');
    });
  };

  // Selects or deselects a card in your hand.
  const toggle = (id: string) => {
    play('select');
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  // Moves a dragged card to a position in a group, or into a new group.
  const moveCard = (cardId: string, toGroup: number | 'new', toIndex: number) => {
    setGroups((prev) => {
      const fromG = prev.findIndex((g) => g.includes(cardId));
      if (fromG < 0) return prev;
      const fromI = prev[fromG].indexOf(cardId);
      const next = prev.map((g) => [...g]);
      next[fromG].splice(fromI, 1);
      if (toGroup === 'new' || !next[toGroup]) next.push([cardId]);
      else {
        let idx = toIndex;
        if (fromG === toGroup && fromI < toIndex) idx -= 1;
        next[toGroup].splice(idx, 0, cardId);
      }
      return next.filter((g) => g.length);
    });
  };

  // Moves the selected card one place left or right with the arrow keys.
  const keyMove = (cardId: string, dir: -1 | 1) => {
    setGroups((prev) => {
      const g = prev.findIndex((x) => x.includes(cardId));
      const i = prev[g].indexOf(cardId);
      const next = prev.map((x) => [...x]);
      next[g].splice(i, 1);
      const j = i + dir;
      if (j >= 0 && j <= prev[g].length - 1) next[g].splice(j, 0, cardId);
      else if (dir < 0 && g > 0) next[g - 1].push(cardId);
      else if (dir > 0 && g < prev.length - 1) next[g + 1].unshift(cardId);
      else next[g].splice(i, 0, cardId);
      return next.filter((x) => x.length);
    });
    requestAnimationFrame(() =>
      document.querySelector<HTMLButtonElement>(`[data-card-id="${cardId}"] button`)?.focus(),
    );
  };

  // Puts all selected cards into a new group.
  const groupSelected = () => {
    if (!selected.size) return toast('Select the cards you want to group first.', 'info');
    const order = groups.flat().filter((id) => selected.has(id));
    setGroups((prev) => [...prev.map((g) => g.filter((id) => !selected.has(id))).filter((g) => g.length), order]);
    setSelected(new Set());
  };

  // Regroups your hand by suit or by rank.
  const sortBy = (mode: 'suit' | 'rank') => {
    if (!game) return;
    const fn = mode === 'suit' ? groupBySuit : groupByRank;
    setGroups(fn(game.human_hand).map((g) => g.map((c) => c.id)));
  };

  // Groups your hand into its best melds, with the spare card last.
  const autoArrange = () =>
    run(async () => {
      if (!game) return;
      const r = await api.arrange(game.game_id);
      const next = r.groups.map((g) =>
        orderMeld(
          g.card_ids.map((id) => cardsById.get(id)).filter((c): c is Card => !!c),
          g.meld_type,
        ).map((c) => c.id),
      );
      // loose cards go in by suit, so near-misses sit next to each other
      const loose = game.human_hand.filter((c) => r.deadwood_ids.includes(c.id));
      next.push(...groupBySuit(loose).map((g) => g.map((c) => c.id)));
      // the spare (14th) card goes last, on its own, ready to discard/finish
      if (r.spare_id) next.push([r.spare_id]);
      setGroups(next);
      setSummary(r.summary);
    });

  // Shows the coach's pick on the table (the Hint button).
  const askHint = () => {
    if (!game?.is_human_turn) return toast('Hints are available on your turn.', 'info');
    if (!currentCoach()) return toast('The coach is still thinking. Try again in a moment.', 'info');
    showMe();
  };

  // Opens the declare dialog and checks your groups first.
  const openDeclare = () => {
    if (!game) return;
    if (!canDiscard) return toast('Draw a card first. Then select the card for the finish slot and press Declare.', 'info');
    if (!single) return toast('Select the one card to place in the finish slot, then press Declare.', 'info');
    const rest = groups.map((g) => g.filter((id) => id !== single.id)).filter((g) => g.length);
    setDeclareCheck(null);
    setDialog('declare');
    api
      .check(game.game_id, rest)
      .then(setDeclareCheck)
      .catch((err) => toast(errorMessage(err)));
  };

  // Sends your declaration to the server.
  const confirmDeclare = () =>
    run(async () => {
      if (!game || !single) return;
      const rest = groups.map((g) => g.filter((id) => id !== single.id)).filter((g) => g.length);
      const r = await api.declare(game.game_id, rest, single.id);
      const c = currentCoach();
      if (c && c.action.kind === 'declare' && r.declaration_result.is_valid)
        grade('best', `You declared with ${cardLabel(single)} in the finish slot`, 'Exactly right.');
      setDialog(null);
      setSelected(new Set());
      applyState(r.game_state);
    });

  // Drops out of the round after you confirm.
  const confirmDrop = () =>
    run(async () => {
      if (!game) return;
      setDialog(null);
      applyState(await api.drop(game.game_id));
    });

  // Deals the next round and resets the round's coach tally.
  const nextRound = () =>
    run(async () => {
      if (!game) return;
      setHint(null);
      setLabelMap({});
      setReview(null);
      setRoundStats({ moves: 0, best: 0, good: 0 });
      const s = await api.nextRound(game.game_id);
      assertNewBackend(s);
      applyState(s);
    });

  // Turns sound effects on or off.
  const toggleMute = () => {
    setMuted(!muted);
    setMutedState(!muted);
  };

  // ---------------------------------------------------------- start screen
  if (!game) {
    return (
      <main className="start">
        <div className="start-fan" aria-hidden="true">
          {HERO_CARDS.map((c, i) => (
            <span key={c.id} className="start-fan-card" style={{ ['--i' as string]: i - 2 }}>
              <PlayingCard card={c} size="lg" />
            </span>
          ))}
        </div>
        <h1 className="start-title">Smart Rummy</h1>
        <p className="start-sub">
          13-card Indian rummy against computer players. Ask for a hint any time and see why it is the right move.
        </p>

        <form
          className="start-form"
          onSubmit={(e) => {
            e.preventDefault();
            void startGame();
          }}
        >
          <fieldset className="seg">
            <legend>Opponents</legend>
            {[1, 2, 3].map((n) => (
              <label key={n} className={opponents === n ? 'is-on' : ''}>
                <input type="radio" name="opp" checked={opponents === n} onChange={() => setOpponents(n)} />
                {n}
              </label>
            ))}
          </fieldset>
          <fieldset className="seg">
            <legend>Difficulty</legend>
            {(['easy', 'medium', 'hard'] as Difficulty[]).map((d) => (
              <label key={d} className={difficulty === d ? 'is-on' : ''}>
                <input type="radio" name="diff" checked={difficulty === d} onChange={() => setDifficulty(d)} />
                {d[0].toUpperCase() + d.slice(1)}
              </label>
            ))}
          </fieldset>
          <div className="start-actions">
            <button type="submit" className="btn btn-primary btn-big" disabled={busy}>
              {busy ? 'Dealing…' : 'Deal cards'}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setDialog('rules')}>
              How to play
            </button>
          </div>
        </form>

        {dialog === 'rules' && <HowToPlay wildNote={null} onClose={() => setDialog(null)} />}
        <Toasts toasts={toasts} />
      </main>
    );
  }

  // ---------------------------------------------------------- game screen
  const wildNote = game.wild_rank ? `All ${wildRankLabel(game.wild_rank)} are jokers this round` : 'Wild joker';
  const top = game.discard_top;
  const prompt = game.round_result
    ? 'Round over.'
    : canDraw
      ? `Your turn. Draw from the stock${top ? ` or pick up ${cardLabel(top)}` : ''}.`
      : canDiscard
        ? single
          ? `Discard ${cardLabel(single)}, or declare with it in the finish slot.`
          : 'Now select one card to discard.'
        : `${game.current_player_name} is thinking…`;

  const validLabels = labels.filter((l, i) => l?.is_valid && groups[i].length >= 3) as MeldValidation[];
  const pure = validLabels.filter((l) => l.meld_type === 'pure_sequence').length;
  const seqs = validLabels.filter((l) => l.meld_type !== 'set').length;
  const ungrouped = groups.reduce((n, g, i) => n + (labels[i]?.is_valid && g.length >= 3 ? 0 : g.length), 0);
  const me = game.players_summary.find((p) => p.is_human);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">Smart Rummy</span>
          <span className="brand-round">Round {game.round_number}</span>
        </div>
        <ol className="scores" aria-label="Scores, lower is better">
          {game.players_summary.map((p) => (
            <li key={p.id} className={p.id === game.current_player_id && !game.round_result ? 'is-turn' : ''}>
              <span>{p.is_human ? 'You' : p.name}</span>
              <b>{p.score}</b>
            </li>
          ))}
        </ol>
        <div className="topbar-actions">
          <button type="button" className="icon-btn" onClick={() => setDialog('rules')} aria-label="How to play" title="How to play">
            ?
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={toggleMute}
            aria-label={muted ? 'Turn sound on' : 'Turn sound off'}
            aria-pressed={!muted}
            title={muted ? 'Sound off' : 'Sound on'}
          >
            {muted ? '🔇' : '🔊'}
          </button>
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setDialog('newgame')}>
            New game
          </button>
        </div>
      </header>

      <div className="layout">
        <main className="felt">
          <Table
            state={game}
            busy={busy}
            canDraw={canDraw}
            pickHint={hint?.kind === 'pick' ? hint.source : null}
            onDraw={draw}
            prompt={prompt}
            wildNote={wildNote}
            onShowRules={() => setDialog('rules')}
            flight={flight}
            discardOriginRef={discardOriginRef}
          />

          <section className={`hand-panel ${game.is_human_turn ? 'is-yours' : ''}`} aria-label="Your hand">
            <div className="hand-head">
              <h1 className="hand-title">Your hand</h1>
              <ul className="progress" aria-label="Progress toward a valid declaration">
                <li className={pure ? 'done' : ''}>{pure ? '✓' : '○'} Pure sequence</li>
                <li className={seqs >= 2 ? 'done' : ''}>{seqs >= 2 ? '✓' : '○'} Second sequence</li>
                <li className={ungrouped <= (game.human_hand.length === 14 ? 1 : 0) ? 'done' : ''}>
                  {ungrouped} ungrouped
                </li>
              </ul>
            </div>

            <Coach
              variant="strip"
              coach={coach}
              loading={coachLoading}
              review={review}
              stats={stats}
              thinkFirst={thinkFirst}
              revealed={coach?.forSeq === revealedSeq}
              onToggleThink={toggleThink}
              onReveal={() => coach && setRevealedSeq(coach.forSeq)}
              onShowMe={showMe}
              error={coachFailed}
              onRetry={() => setCoachRetry((n) => n + 1)}
            />

            <Hand
              groups={cardGroups}
              labels={labels}
              selected={selected}
              hintId={hint?.kind === 'discard' ? hint.cardId : null}
              freshIds={fresh}
              wildNote={wildNote}
              onToggle={toggle}
              onMove={moveCard}
              onKeyMove={keyMove}
              flight={flight}
            />

            {summary && (
              <p className="summary" key={summary}>
                <b>Best possible with these cards:</b> {summary}
              </p>
            )}

            <div className="toolbar">
              <div className="tool-group" role="group" aria-label="Arrange">
                <button type="button" className="btn btn-quiet" onClick={() => sortBy('suit')}>
                  Sort by suit
                </button>
                <button type="button" className="btn btn-quiet" onClick={() => sortBy('rank')}>
                  Sort by rank
                </button>
                <button type="button" className="btn btn-quiet" onClick={autoArrange} disabled={busy}>
                  Auto-arrange
                </button>
                <button type="button" className="btn btn-quiet" onClick={groupSelected} disabled={!selected.size}>
                  Group{selected.size ? ` (${selected.size})` : ''}
                </button>
              </div>
              <div className="tool-group" role="group" aria-label="Turn actions">
                <button type="button" className="btn btn-quiet" onClick={askHint} disabled={busy || !game.is_human_turn}>
                  Hint
                </button>
                {game.can_drop && (
                  <button type="button" className="btn btn-quiet btn-warn" onClick={() => setDialog('drop')}>
                    Drop ({game.drop_penalty})
                  </button>
                )}
                <button type="button" className="btn btn-ghost" onClick={openDeclare} disabled={!canDiscard || busy}>
                  Declare
                </button>
                <button
                  type="button"
                  className={`btn btn-primary ${single && canDiscard && !busy ? 'is-ready' : ''}`}
                  onClick={discard}
                  disabled={!canDiscard || !single || busy}
                >
                  {single && canDiscard ? `Discard ${cardLabel(single)}` : 'Discard'}
                </button>
              </div>
            </div>
          </section>
        </main>

        <aside className="side">
          <Coach
            coach={coach}
            loading={coachLoading}
            review={review}
            stats={stats}
            thinkFirst={thinkFirst}
            revealed={coach?.forSeq === revealedSeq}
            onToggleThink={toggleThink}
            onReveal={() => coach && setRevealedSeq(coach.forSeq)}
            onShowMe={showMe}
            error={coachFailed}
            onRetry={() => setCoachRetry((n) => n + 1)}
          />
          <Log events={game.events} round={game.round_number} />
        </aside>
      </div>

      {dialog === 'rules' && <HowToPlay wildNote={wildNote} onClose={() => setDialog(null)} />}
      {dialog === 'declare' && single && (
        <DeclareDialog
          groups={cardGroups.map((g) => g.filter((c) => c.id !== single.id)).filter((g) => g.length)}
          finish={single}
          check={declareCheck}
          busy={busy}
          onConfirm={confirmDeclare}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'drop' && (
        <ConfirmDialog
          title="Drop this round?"
          body={`You give up this round and take ${game.drop_penalty} points. ${me ? `Your total becomes ${me.score + game.drop_penalty}.` : ''}`}
          confirmLabel={`Drop (+${game.drop_penalty})`}
          danger
          onConfirm={confirmDrop}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'newgame' && (
        <ConfirmDialog
          title="Start a new game?"
          body="Scores from this game will be cleared."
          confirmLabel="Start new game"
          onConfirm={() => {
            setDialog(null);
            setGame(null);
            setHint(null);
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {game.round_result && dialog === null && (
        <ResultsDialog
          result={game.round_result}
          busy={busy}
          onNext={nextRound}
          onNewGame={() => setDialog('newgame')}
          coachLine={
            roundStats.moves
              ? `Coach check: you made the best move ${roundStats.best} of ${roundStats.moves} times this round${roundStats.good ? ` and were close on ${roundStats.good} more` : ''}.`
              : undefined
          }
        />
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}

// Renders the stack of short messages at the top of the screen.
function Toasts({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toasts" aria-live="assertive">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.tone}`} role={t.tone === 'error' ? 'alert' : 'status'}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
