import axios, { AxiosError } from 'axios';

const API_BASE = '/api/game';

export type Suit = 'H' | 'D' | 'C' | 'S' | 'JK';

export interface Card {
  id: string;
  suit: Suit;
  rank: string;
  deck_no: number;
  is_wild_joker: boolean;
}

export interface PlayerSummary {
  id: string;
  name: string;
  card_count: number;
  is_human: boolean;
  score: number;
}

export type TurnStage = 'AWAITING_DRAW' | 'AWAITING_DISCARD' | 'ROUND_OVER' | 'ROUND_DECLARED' | 'GAME_OVER';
export type Difficulty = 'easy' | 'medium' | 'hard';

export interface GameEvent {
  seq: number;
  round_number: number;
  player_id: string;
  player_name: string;
  action: 'round_start' | 'draw_stock' | 'draw_discard' | 'discard' | 'declare' | 'wrong_show' | 'drop' | 'reshuffle' | 'stock_empty';
  card: Card | null;
  message: string;
}

export type MeldType = 'pure_sequence' | 'impure_sequence' | 'set' | 'invalid';

export interface ResultGroup {
  meld_type: MeldType;
  cards: Card[];
}

export interface PlayerRoundResult {
  player_id: string;
  name: string;
  is_human: boolean;
  is_winner: boolean;
  points: number;
  total_score: number;
  groups: ResultGroup[];
  deadwood: Card[];
  note: string;
}

export interface RoundResult {
  round_number: number;
  outcome: 'declared' | 'wrong_show' | 'drop' | 'stock_exhausted';
  winner_id: string | null;
  winner_name: string | null;
  message: string;
  players: PlayerRoundResult[];
}

export interface PublicGameState {
  game_id: string;
  turn_stage: TurnStage;
  current_player_id: string;
  current_player_name: string;
  is_human_turn: boolean;
  round_number: number;
  cut_card: Card | null;
  wild_rank: string | null;
  discard_top: Card | null;
  discard_count: number;
  cards_in_deck: number;
  human_hand: Card[];
  players_summary: PlayerSummary[];
  events: GameEvent[];
  last_event_seq: number;
  can_drop: boolean;
  drop_penalty: number;
  round_result: RoundResult | null;
  winner_id: string | null;
  winner_name: string | null;
  difficulty: Difficulty;
}

export interface MeldValidation {
  meld_type: MeldType;
  is_valid: boolean;
  card_ids: string[];
  reason: string | null;
}

export interface DeclarationResult {
  is_valid: boolean;
  reason: string | null;
  groups: MeldValidation[];
  pure_sequence_count: number;
  impure_sequence_count: number;
  set_count: number;
  total_cards: number;
}

export interface CheckResponse {
  groups: MeldValidation[];
  declaration: DeclarationResult;
}

export interface ArrangeResponse {
  groups: { meld_type: MeldType; card_ids: string[] }[];
  deadwood_ids: string[];
  deadwood_points: number;
  pure_sequences: number;
  total_sequences: number;
  summary: string;
  spare_id: string | null;
}

export interface DiscardOption {
  card: Card;
  resulting_deadwood: number;
  score: number;
  reasoning: string;
}

export interface DiscardHint {
  baseline_deadwood: number;
  recommended_discards: DiscardOption[];
  best_discard: DiscardOption;
}

export interface PickHint {
  should_pick: boolean;
  current_deadwood: number;
  expected_deadwood_after: number;
  reason: string;
}

export interface CoachOption {
  card: Card;
  cost: number;
  reasoning: string;
  danger: string | null;
}

export interface CoachResponse {
  stage: 'draw' | 'discard' | 'waiting' | 'over';
  headline: string;
  detail: string;
  action: {
    kind: 'take_discard' | 'draw_stock' | 'discard' | 'declare' | 'drop' | 'wait' | 'none';
    card_id: string | null;
    card_label: string | null;
  };
  options: CoachOption[];
  take_discard_card: Card | null;
  outs: { label: string; copies_left: number; effect: string }[];
  out_copies: number;
  unseen_cards: number;
  out_chance_pct: number;
  reads: { player_id: string; player_name: string; picked: string[]; text: string }[];
  tip: string;
  status: string;
}

// Turns any failed request into one readable sentence for the UI.
export function errorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
    if (!err.response) return "Can't reach the game server. Check that the backend is running on port 8000.";
    return `The server returned an error (${err.response.status}).`;
  }
  return err instanceof Error ? err.message : 'Something went wrong.';
}

// Sends a POST request and returns the parsed response body.
const post = async <T,>(url: string, body?: unknown) => (await axios.post<T>(url, body)).data;
// Sends a GET request and returns the parsed response body.
const get = async <T,>(url: string) => (await axios.get<T>(url)).data;

export const api = {
  // Starts a new game with the chosen number of players and difficulty.
  createGame: (numPlayers: number, difficulty: Difficulty) =>
    post<PublicGameState>(`${API_BASE}/new`, { num_players: numPlayers, difficulty }),
  // Fetches the current state of a game.
  getGame: (id: string) => get<PublicGameState>(`${API_BASE}/${id}`),
  // Draws a card from the stock or the discard pile.
  draw: (id: string, source: 'stock' | 'discard') => post<PublicGameState>(`${API_BASE}/${id}/draw`, { source }),
  // Discards a card from your hand, ending your turn.
  discard: (id: string, cardId: string) => post<PublicGameState>(`${API_BASE}/${id}/discard`, { card_id: cardId }),
  // Asks the server to play one bot turn.
  botTurn: (id: string) => post<PublicGameState>(`${API_BASE}/${id}/bot-turn`),
  // Drops out of the current round.
  drop: (id: string) => post<PublicGameState>(`${API_BASE}/${id}/drop`),
  // Deals the next round.
  nextRound: (id: string) => post<PublicGameState>(`${API_BASE}/${id}/next-round`),
  // Checks your card groups without any penalty.
  check: (id: string, groups: string[][]) => post<CheckResponse>(`${API_BASE}/${id}/check`, { groups }),
  // Declares your hand with one card in the finish slot.
  declare: (id: string, groups: string[][], finishCardId: string) =>
    post<{ declaration_result: DeclarationResult; game_state: PublicGameState }>(`${API_BASE}/${id}/declare`, {
      groups,
      finish_card_id: finishCardId,
    }),
  // Gets the best grouping of your hand and a progress summary.
  arrange: (id: string) => get<ArrangeResponse>(`${API_BASE}/${id}/assist/arrange`),
  // Gets the ranked discard suggestions for a 14-card hand.
  hintDiscard: (id: string) => get<DiscardHint>(`${API_BASE}/${id}/assist/discard`),
  // Gets advice on taking the top discard card.
  hintPick: (id: string) => get<PickHint>(`${API_BASE}/${id}/assist/pick`),
  // Gets the coach's best move and explanation for the current position.
  coach: (id: string) => get<CoachResponse>(`${API_BASE}/${id}/coach`),
};
