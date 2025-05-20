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

// 德州撲克特定操作
function pokerAction(action, amount = null) {
    let payload = {};
    if (['bet', 'raise'].includes(action) && amount !== null) {
        payload.amount = amount;
    }
    sendPlayerAction(action, payload);
}

// 21點特定操作
function blackjackAction(action, amount = null) {
    let payload = {};
    if (['bet', 'insurance'].includes(action) && amount !== null) {
        payload.amount = amount;
    }
    sendPlayerAction(action, payload);
}

// 21點相關函數
// 計算手牌總點數
function calculateHandValue(cards) {
    if (!cards || !Array.isArray(cards) || cards.length === 0) return 0;
    
    // 第一次加總，A算1點
    let total = 0;
    let aceCount = 0;
    
    for (const card of cards) {
        if (card.rank === 'A') {
            aceCount++;
            total += 1;
        } else if (['K', 'Q', 'J'].includes(card.rank)) {
            total += 10;
        } else {
            total += parseInt(card.rank);
        }
    }
    
    // 然後檢查是否有A可以算11點
    while (aceCount > 0 && total + 10 <= 21) {
        total += 10;
        aceCount--;
    }
    
    return total;
}

// 檢查是否爆牌
function isBusted(cards) {
    return calculateHandValue(cards) > 21;
}

// 檢查是否為21點
function isBlackjack(cards) {
    return cards.length === 2 && calculateHandValue(cards) === 21;
}

// 渲染21點手牌
function renderBlackjackHand(cards, hideFirstCard = false) {
    if (!cards || cards.length === 0) return '無牌';
    
    if (hideFirstCard && cards.length > 0) {
        return `? + ${cards.slice(1).map(c => `${c.rank}${c.suit}`).join(' ')}`;
    }
    
    return cards.map(c => `${c.rank}${c.suit}`).join(' ');
}

// 處理21點遊戲階段UI調整
function updateBlackjackUI(gameState) {
    // 隱藏所有動作按鈕
    document.querySelectorAll('#black-jack-actions button').forEach(btn => {
        btn.classList.add('hidden');
    });
    
    const phase = gameState.game_phase;
    const isMyTurn = gameState.current_turn_sid === socket.id;
    
    if (!isMyTurn) return;
    
    // 根據遊戲階段顯示對應按鈕
    if (phase === 'betting') {
        document.querySelector('#black-jack-actions [data-action="bet"]').classList.remove('hidden');
    } else if (phase === 'player_actions') {
        document.querySelector('#black-jack-actions [data-action="hit"]').classList.remove('hidden');
        document.querySelector('#black-jack-actions [data-action="stand"]').classList.remove('hidden');
        
        // 只有初始兩張牌時才能加倍
        const myPlayer = gameState.players.find(p => p.sid === socket.id);
        if (myPlayer && myPlayer.hand && myPlayer.hand.length === 2 && !myPlayer.has_doubled) {
            document.querySelector('#black-jack-actions [data-action="double"]').classList.remove('hidden');
        }
    } else if (phase === 'insurance_option') {
        document.querySelector('#black-jack-actions [data-action="insurance"]').classList.remove('hidden');
        document.querySelector('#black-jack-actions [data-action="decline_insurance"]').classList.remove('hidden');
    }
}

// 監聽特定遊戲更新
// socket.on('texas_holdem_update', (gameState) => { 
//     // 更新德州撲克UI邏輯
// });

// socket.on('black_jack_update', (gameState) => { 
//     // 更新21點UI邏輯
//     updateBlackjackUI(gameState);
// });

// 或如果 BaseGame.broadcast_state() 使用固定的 event_name, 但 get_state_for_player() 中包含 game_type
// socket.on('some_generic_game_update_event', (gameState) => {
//     if (gameState.game_type === 'texas_holdem') { /* render texas */ }
//     else if (gameState.game_type === 'black_jack') { 
//         updateBlackjackUI(gameState);
//     }
// });