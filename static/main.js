// 假設 socket 和 currentRoomId 已經定義
function sendPlayerAction(actionType, payload = {}) {
    if (!currentRoomId) {
        console.error("No room joined!");
        return;
    }
    socket.emit('game_action', {
        room_id: currentRoomId,
        action_type: actionType,
        payload: payload
    });
}

// sendPlayerAction('fold');
// sendPlayerAction('bet', { amount: 50 });

// 監聽特定遊戲更新
// socket.on('texas_holdem_update', (gameState) => { ... });
// socket.on('blackjack_update', (gameState) => { ... });
// 或如果 BaseGame.broadcast_state() 使用固定的 event_name, 但 get_state_for_player() 中包含 game_type
// socket.on('some_generic_game_update_event', (gameState) => {
//     if (gameState.game_type === 'texas_holdem') { /* render texas */ }
//     else if (gameState.game_type === 'blackjack') { /* render blackjack */ }
// });