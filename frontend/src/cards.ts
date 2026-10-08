import type { Card, MeldType } from './api';

export const SUIT_SYMBOL: Record<string, string> = { H: '♥', D: '♦', C: '♣', S: '♠', JK: '★' };
const SUIT_NAME: Record<string, string> = { H: 'hearts', D: 'diamonds', C: 'clubs', S: 'spades' };
const RANK_NAME: Record<string, string> = { A: 'Ace', J: 'Jack', Q: 'Queen', K: 'King' };
const RANK_ORDER: Record<string, number> = {
  A: 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, J: 11, Q: 12, K: 13, PJ: 99,
};
const SUIT_ORDER: Record<string, number> = { S: 0, H: 1, C: 2, D: 3, JK: 4 };

// True for hearts and diamonds.
export const isRed = (c: Card) => c.suit === 'H' || c.suit === 'D';
// True for a printed joker card.
export const isPrinted = (c: Card) => c.rank === 'PJ';
// True for a printed joker or a wild-rank card.
export const isJoker = (c: Card) => isPrinted(c) || c.is_wild_joker;

// Full rank name, e.g. "K" -> "King".
export const rankName = (rank: string) => RANK_NAME[rank] ?? rank;

// Short text label for a card, e.g. "10♥" or "Joker".
export function cardLabel(c: Card): string {
  if (isPrinted(c)) return 'Joker';
  return `${c.rank}${SUIT_SYMBOL[c.suit]}`;
}

// Spoken label for screen readers, e.g. "10 of hearts".
export function cardAria(c: Card): string {
  if (isPrinted(c)) return 'Printed joker';
  const base = `${rankName(c.rank)} of ${SUIT_NAME[c.suit]}`;
  return c.is_wild_joker ? `${base}, wild joker` : base;
}

// Numeric order of a card's rank (Ace low) for sorting.
export const rankValue = (c: Card) => RANK_ORDER[c.rank] ?? 0;

// Sort comparator: by rank, then by suit.
export function byRank(a: Card, b: Card) {
  return rankValue(a) - rankValue(b) || SUIT_ORDER[a.suit] - SUIT_ORDER[b.suit];
}

// Sort comparator: by suit, then by rank.
export function bySuit(a: Card, b: Card) {
  return SUIT_ORDER[a.suit] - SUIT_ORDER[b.suit] || rankValue(a) - rankValue(b);
}

// Splits a hand into one group per suit, with jokers in their own group.
export function groupBySuit(cards: Card[]): Card[][] {
  const jokers = cards.filter(isJoker).sort(byRank);
  const rest = cards.filter((c) => !isJoker(c));
  const groups: Card[][] = [];
  for (const s of ['S', 'H', 'C', 'D']) {
    const g = rest.filter((c) => c.suit === s).sort(byRank);
    if (g.length) groups.push(g);
  }
  if (jokers.length) groups.push(jokers);
  return groups;
}

// Groups cards of the same rank together (helps spot sets).
export function groupByRank(cards: Card[]): Card[][] {
  const sorted = [...cards].sort(byRank);
  const jokers = sorted.filter(isJoker);
  const rest = sorted.filter((c) => !isJoker(c));
  const groups: Card[][] = [];
  for (const c of rest) {
    const last = groups[groups.length - 1];
    if (last && last[0].rank === c.rank) last.push(c);
    else groups.push([c]);
  }
  // merge singletons so the hand doesn't explode into 13 tiny groups
  const merged: Card[][] = [];
  const loose: Card[] = [];
  for (const g of groups) {
    if (g.length >= 2) merged.push(g);
    else loose.push(...g);
  }
  if (loose.length) merged.push(loose);
  if (jokers.length) merged.push(jokers);
  return merged;
}

export const MELD_LABEL: Record<MeldType, string> = {
  pure_sequence: 'Pure sequence',
  impure_sequence: 'Sequence with joker',
  set: 'Set',
  invalid: 'Not a meld',
};

// Plural name of the wild rank, e.g. "9" -> "9s".
export function wildRankLabel(rank: string | null): string {
  if (!rank) return '';
  return `${rankName(rank)}s`;
}

// Orders a meld's cards the way a player would lay them down.
export function orderMeld(cards: Card[], meldType: MeldType): Card[] {
  const jokers = cards.filter(isJoker);
  const natural = cards.filter((c) => !isJoker(c));
  if (meldType === 'set') return [...natural.sort(bySuit), ...jokers];
  const aceHigh = natural.some((c) => c.rank === 'K') && natural.some((c) => c.rank === 'A');
  // Rank value used for ordering, with the Ace high in Q-K-A runs.
  const value = (c: Card) => (aceHigh && c.rank === 'A' ? 14 : rankValue(c));
  // pure sequences may contain a wild card used at its own rank: keep it in place
  if (meldType === 'pure_sequence') return [...cards].sort((a, b) => value(a) - value(b));
  return [...natural.sort((a, b) => value(a) - value(b)), ...jokers];
}
