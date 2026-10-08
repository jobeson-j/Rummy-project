// Add this interface near your others
export interface BotTurnResponse {
    action_message: string;
    game_state: PublicGameState;
}

// Add this inside your exported `api` object
playBotStep: async (gameId: string) => {
    const res = await axios.post<BotTurnResponse>(`${API_BASE}/${gameId}/bot-step`);
    return res.data;
}