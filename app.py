from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room, send
import eventlet # 或者 gevent
eventlet.monkey_patch() # 或者 gevent.monkey.patch_all() 放在最前面

# 從 game_logic.py 導入遊戲狀態和函式
from game_logic import GAME_ROOM, add_player_to_game, remove_player_from_game, \
                       start_new_round, handle_player_action, handle_showdown_or_win_by_fold, \
                       get_active_players_sids_in_order # (以及其他你需要的函式)


app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here!' # 非常重要，請修改
# cors_allowed_origins="*" 允許所有來源，開發時方便，生產環境應指定具體來源
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# --- 遊戲房間設定 (單房間) ---
SINGLE_ROOM_ID = "texas_holdem_room"

def get_game_state_for_player(player_sid=None):
    """
    產生要傳送給前端的遊戲狀態。
    player_sid: 如果提供，則包含該玩家的私有手牌。
    """
    state = {
        'players': [], # 公開的玩家資訊
        'community_cards': GAME_ROOM['community_cards'],
        'pot': GAME_ROOM['pot'],
        'current_turn_sid': GAME_ROOM['current_turn_sid'],
        'current_bet_to_match': GAME_ROOM['current_bet_to_match'],
        'game_phase': GAME_ROOM['game_phase'],
        'game_in_progress': GAME_ROOM['game_in_progress'],
        'dealer_sid': None, # 需要實現按鈕位邏輯來填充
        'last_action': None, # (可選) 上一個動作的描述
        'min_raise': GAME_ROOM.get('min_raise', GAME_ROOM.get('big_blind', 20)*2) # 確保有值
    }

    # 填充按鈕位玩家 SID
    player_sids_all = list(GAME_ROOM['players'].keys())
    if player_sids_all and GAME_ROOM['game_in_progress']:
        dealer_actual_sid = player_sids_all[GAME_ROOM['dealer_button_idx'] % len(player_sids_all)]
        state['dealer_sid'] = dealer_actual_sid


    for sid, player_data in GAME_ROOM['players'].items():
        public_player_data = {
            'sid': sid,
            'name': player_data['name'],
            'chips': player_data['chips'],
            'current_bet': player_data['current_bet'],
            'is_active': player_data['is_active'], # 是否參與本局
            'has_acted': player_data['has_acted_this_round'] # 本輪是否已行動
        }
        if player_sid == sid and GAME_ROOM['game_in_progress']: # 只給當前玩家看自己的手牌
            public_player_data['hand'] = player_data.get('hand', [])
        elif GAME_ROOM['game_phase'] == 'showdown' and player_data['is_active']: # 攤牌時顯示所有參與攤牌者的手牌
             public_player_data['hand'] = player_data.get('hand', [])
        state['players'].append(public_player_data)

    return state

def broadcast_game_state(message=None, event_name='game_update'):
    """廣播當前遊戲狀態給房間內所有玩家"""
    print(f"Broadcasting state for event: {event_name}")
    # 對每個連接的客戶端，單獨準備他們的狀態 (因為手牌是私有的)
    for sid_in_room in GAME_ROOM['players'].keys(): # 只廣播給在遊戲邏輯中註冊的玩家
        if request and request.sid == sid_in_room : # 如果是當前請求的發起者，他會直接收到emit的回應
             pass # emit to room already handles this
        player_specific_state = get_game_state_for_player(sid_in_room)
        if message:
            player_specific_state['message'] = message
        socketio.emit(event_name, player_specific_state, room=sid_in_room) # 單獨發送給每個玩家
    print(f"State broadcasted. Current pot: {GAME_ROOM['pot']}, Phase: {GAME_ROOM['game_phase']}")


@app.route('/')
def index():
    # (可選) 提供一個簡單的前端頁面
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"Client connected: {sid}")
    # 立即將玩家加入房間，但還不加入遊戲邏輯中的玩家列表
    join_room(SINGLE_ROOM_ID)
    emit('message', {'text': f"Welcome! You are connected with SID: {sid}"})
    # 可以發送當前房間人數等資訊
    # emit('room_status', {'num_players': len(GAME_ROOM['players'])}) # 這裡GAME_ROOM可能還沒此玩家


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"Client disconnected: {sid}")
    player_name = GAME_ROOM['players'].get(sid, {}).get('name', sid)
    was_removed = remove_player_from_game(sid)
    leave_room(SINGLE_ROOM_ID) # 確保從 SocketIO 房間離開
    if was_removed:
        print(f"Player {player_name} removed from game.")
        broadcast_game_state(message=f"Player {player_name} has left.")
        # 如果遊戲正在進行且玩家數不足，可能需要結束遊戲
        if GAME_ROOM['game_in_progress'] and len(get_active_players_sids_in_order()) < 2:
            print("Not enough players to continue, ending game.")
            # 這裡可以調用一個函數來處理遊戲提前結束，例如將底池分配給剩餘玩家
            showdown_results = handle_showdown_or_win_by_fold()
            broadcast_game_state(message="Game ended due to player leaving.", event_name='game_over')
            socketio.emit('showdown_result', showdown_results, room=SINGLE_ROOM_ID)
            GAME_ROOM['game_in_progress'] = False


@socketio.on('join_game')
def handle_join_game(data):
    sid = request.sid
    player_name = data.get('name', f"Player_{sid[:4]}")

    if sid in GAME_ROOM['players']:
        emit('error_message', {'message': 'You are already in the game.'})
        # 重新發送一次狀態給他，以防萬一
        player_state = get_game_state_for_player(sid)
        emit('game_update', player_state)
        return

    if add_player_to_game(sid, player_name):
        print(f"Player {player_name} ({sid}) joined the game room: {SINGLE_ROOM_ID}")
        # 向所有玩家廣播更新後的遊戲狀態 (包括新玩家)
        broadcast_game_state(message=f"Player {player_name} has joined.")
    else:
        emit('error_message', {'message': 'Failed to join game (already in list, should not happen).'})


@socketio.on('start_game_request')
def handle_start_game_request():
    sid = request.sid
    if not GAME_ROOM['game_in_progress']:
        if len(GAME_ROOM['players']) >= 2: # 至少需要2個玩家
            print(f"Start game request from {sid}. Starting new round...")
            if start_new_round(): # game_logic 中的函式
                broadcast_game_state(message="New round started!")
            else:
                emit('error_message', {'message': 'Failed to start game (not enough active players with chips).'})
                broadcast_game_state() # 廣播一下當前狀態
        else:
            emit('error_message', {'message': 'Not enough players to start the game. Need at least 2.'})
            print(f"Start game failed: not enough players. Count: {len(GAME_ROOM['players'])}")
    else:
        emit('error_message', {'message': 'Game is already in progress.'})
        # 也許只發送當前狀態給請求者
        player_state = get_game_state_for_player(sid)
        emit('game_update', player_state)


@socketio.on('player_action')
def on_player_action(data):
    sid = request.sid
    action = data.get('action') # 'fold', 'check', 'call', 'bet', 'raise'
    amount = data.get('amount', 0)

    if not GAME_ROOM['game_in_progress']:
        emit('error_message', {'message': 'Game is not in progress.'})
        return

    if GAME_ROOM['current_turn_sid'] != sid:
        emit('error_message', {'message': "It's not your turn."})
        # 仍然發送一次狀態，讓客戶端同步
        player_state = get_game_state_for_player(sid)
        emit('game_update', player_state)
        return

    print(f"Player {GAME_ROOM['players'].get(sid,{}).get('name')} ({sid}) action: {action}, amount: {amount}")
    action_result = handle_player_action(sid, action, amount) # game_logic 中的函式

    if action_result and action_result.get('success'):
        last_action_description = f"{GAME_ROOM['players'][sid]['name']} {action}"
        if action in ['bet', 'raise', 'call'] and action_result.get('amount', 0) > 0:
            last_action_description += f" {action_result.get('amount')}"

        if GAME_ROOM['game_phase'] == 'showdown': # 遊戲因棄牌或 all-in 結束
            print("Game ended or moved to showdown due to player action.")
            showdown_results = handle_showdown_or_win_by_fold() # 確保執行攤牌邏輯
            broadcast_game_state(message=last_action_description, event_name='game_over') # 可能用 game_over 事件
            socketio.emit('showdown_result', showdown_results, room=SINGLE_ROOM_ID) # 單獨發送攤牌結果
            GAME_ROOM['game_in_progress'] = False # 確保標記結束
        else:
            broadcast_game_state(message=last_action_description)
    else:
        error_msg = action_result.get('message', "Invalid action.")
        emit('error_message', {'message': error_msg})
        # 重新發送遊戲狀態以同步前端
        player_state = get_game_state_for_player(sid)
        emit('game_update', player_state)

    print(f"After action, pot: {GAME_ROOM['pot']}, phase: {GAME_ROOM['game_phase']}, turn: {GAME_ROOM['current_turn_sid']}")


if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    # host='0.0.0.0' 讓區域網路內其他裝置可以訪問
    # debug=True 只在開發時使用
    socketio.run(app, host='0.0.0.0', port=4000, debug=True, use_reloader=True)
    # 注意：use_reloader=True 在 eventlet/gevent 下可能不穩定或行為異常，生產環境應設為 False