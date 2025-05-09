import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room as sio_leave_room
from flask_cors import CORS
import uuid # 用於生成唯一的房間 ID

# from games.game_factory import create_game_instance # 如果使用工廠模式
from games.texas_holdem.logic import TexasHoldemGame # 直接導入或透過工廠
# from games.blackjack.logic import BlackjackGame

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_very_secret_multi_game_key!'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

active_rooms = {} # room_id -> GameInstance (例如 TexasHoldemGame 的實例)

# 遊戲類型註冊 (如果不使用工廠，可以在這裡手動管理)
REGISTERED_GAME_LOGIC = {
    "texas_holdem": TexasHoldemGame,
    # "blackjack": BlackjackGame,
}

@app.route('/')
def index():
    # 可以是一個顯示可用房間列表或創建房間選項的頁面
    return render_template('login.html', rooms=active_rooms) # 傳遞房間資訊給模板

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    emit('message', {'text': f"Welcome! You are connected with SID: {request.sid}"})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"Client disconnected: {sid}")
    # 遍歷所有房間，如果玩家在某個房間中，則將其移除
    room_to_leave = None
    game_instance_of_player = None
    for r_id, game_inst in list(active_rooms.items()): # 使用 list(active_rooms.items()) 以允許在迭代中删除元素
        if sid in game_inst.players:
            room_to_leave = r_id
            game_instance_of_player = game_inst
            break

    if game_instance_of_player and room_to_leave:
        print(f"Player {sid} was in room {room_to_leave}. Removing.")
        result = game_instance_of_player.remove_player(sid) # 遊戲內部處理移除邏輯並廣播
        sio_leave_room(room_to_leave) # SocketIO層面的離開房間

        if result == "ROOM_EMPTY" or game_instance_of_player.get_player_count() == 0:
            # 如果遊戲內部邏輯表示房間空了，或者實際玩家數為0
            if not game_instance_of_player.is_game_in_progress : # 確保遊戲沒在進行才清理
                print(f"Room {room_to_leave} is now empty and game not in progress. Removing from active_rooms.")
                del active_rooms[room_to_leave]
            elif game_instance_of_player.get_player_count() == 0 and game_instance_of_player.is_game_in_progress:
                print(f"Room {room_to_leave} is empty but game was in progress. Forcing end.")
                # 強制結束遊戲，例如清空底池，遊戲實例內部應處理這種情況
                game_instance_of_player.end_game({"message": "All players left, game ended."})
                if room_to_leave in active_rooms: #再次確認
                    del active_rooms[room_to_leave]


    # 更新大廳資訊 (如果有的話)
    socketio.emit('lobby_update', {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}, broadcast=True)


@socketio.on('create_room')
def handle_create_room(data):
    """
    玩家請求創建一個新遊戲房間。
    data = {'game_type': 'texas_holdem', 'player_name': 'Alice', 'options': {'buy_in': 500}}
    """
    sid = request.sid
    player_name = data.get('player_name', f"Player_{sid[:4]}")
    game_type = data.get('game_type')
    options = data.get('options', {}) # 遊戲的特定選項

    if not game_type or game_type not in REGISTERED_GAME_LOGIC:
        emit('error_message', {'message': f"Invalid game type: {game_type}"})
        return

    room_id = str(uuid.uuid4())[:8] # 生成一個唯一的房間 ID
    game_class = REGISTERED_GAME_LOGIC[game_type]
    # 創建遊戲實例時傳入 socketio 實例
    game_instance = game_class(room_id, [sid], socketio, options) # 創建者自動加入
    game_instance.add_player(sid, {'name': player_name}) # 確保創建者被正確加入其內部玩家列表

    active_rooms[room_id] = game_instance
    join_room(room_id) # Flask-SocketIO 的加入房間

    print(f"Room {room_id} (Type: {game_type}) created by {player_name} ({sid}). Options: {options}")
    emit('room_created', {'room_id': room_id, 'game_type': game_type, 'options': options, 'creator_sid': sid}, room=room_id)
    # 向創建者發送一次完整的遊戲狀態
    game_instance.broadcast_state(specific_sid=sid)
    # 更新大廳資訊
    socketio.emit('lobby_update', {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}, broadcast=True)


@socketio.on('join_room_request') # 改名以區分 SocketIO 的 join_room
def handle_join_room_request(data):
    """
    玩家請求加入一個已存在的遊戲房間。
    data = {'room_id': 'xxxx', 'player_name': 'Bob'}
    """
    sid = request.sid
    player_name = data.get('player_name', f"Player_{sid[:4]}")
    room_id = data.get('room_id')

    if room_id not in active_rooms:
        emit('error_message', {'message': "Room not found."})
        return

    game_instance = active_rooms[room_id]

    if game_instance.is_game_in_progress and not game_instance.options.get('allow_join_in_progress', False):
        emit('error_message', {'message': "Game is in progress and does not allow new players."})
        return

    if sid in game_instance.players:
        emit('error_message', {'message': "You are already in this room."})
        join_room(room_id) # 確保仍在SocketIO房間
        game_instance.broadcast_state(specific_sid=sid) # 發送當前狀態
        return

    # TODO: 檢查房間是否已滿 (根據 game_instance.options.get('max_players'))

    join_room(room_id) # Flask-SocketIO 的加入房間
    game_instance.add_player(sid, {'name': player_name}) # 遊戲邏輯處理新增玩家並廣播

    print(f"Player {player_name} ({sid}) joined room {room_id}.")
    # game_instance 內部會在 add_player 時廣播狀態，這裡不需要額外廣播給所有人
    # 但可以給剛加入的玩家發送一個確認訊息
    emit('joined_room_success', {'room_id': room_id, 'game_type': game_instance.get_game_type()}, room=sid)
    # 更新大廳資訊
    socketio.emit('lobby_update', {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}, broadcast=True)


@socketio.on('leave_room_request')
def handle_leave_room_request(data):
    sid = request.sid
    room_id = data.get('room_id')

    if room_id not in active_rooms:
        emit('error_message', {'message': "Room not found to leave."})
        return

    game_instance = active_rooms[room_id]
    if sid not in game_instance.players:
        # 可能玩家已經因為 disconnect 被移除了，但還是執行一下 sio_leave_room
        sio_leave_room(room_id)
        emit('message', {'text': "You were not actively in the game part of this room."})
        return

    print(f"Player {sid} requesting to leave room {room_id}.")
    result = game_instance.remove_player(sid) # 遊戲內部處理移除並廣播
    sio_leave_room(room_id) # SocketIO 層面離開

    emit('left_room_success', {'room_id': room_id}, room=sid)

    if result == "ROOM_EMPTY" or game_instance.get_player_count() == 0:
        if not game_instance.is_game_in_progress:
            print(f"Room {room_id} is now empty after player left. Removing.")
            if room_id in active_rooms: del active_rooms[room_id] # 清理房間
            # 更新大廳資訊
            socketio.emit('lobby_update', {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}, broadcast=True)


@socketio.on('start_game_request') # 通用的開始遊戲請求
def handle_start_game_request(data):
    """
    data = {'room_id': 'xxxx'}
    """
    sid = request.sid
    room_id = data.get('room_id')

    if room_id not in active_rooms:
        emit('error_message', {'message': "Room not found."})
        return

    game_instance = active_rooms[room_id]
    # TODO: 可以增加權限檢查，例如只有房主或達到一定人數才能開始遊戲
    game_instance.start_game(triggering_player_sid=sid) # 遊戲實例內部會廣播

@socketio.on('get_lobby_info')
def handle_get_lobby_info():
    sid = request.sid
    print(f"Client {sid} requested lobby info.")
    # 直接發送當前的房間列表給請求的客戶端
    lobby_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items() if game}} # 確保 game 實例存在
    emit('lobby_update', lobby_data, room=sid) # 只發送給請求者
    print(f"Sent lobby_update to {sid}: {lobby_data}")

@socketio.on('game_action') # 通用的遊戲動作事件
def on_game_action(data):
    """
    data = {
        'room_id': 'xxxx',
        'action_type': 'fold' (或 'bet', 'hit', 'stand' 等),
        'payload': {'amount': 100} (可選的動作數據)
    }
    """
    sid = request.sid
    room_id = data.get('room_id')
    action_type = data.get('action_type')
    payload = data.get('payload', {})

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': 'Room not found for action.'})
        return

    game_instance = active_rooms[room_id]
    if sid not in game_instance.players:
        emit('error_message', {'message': 'You are not a player in this game room.'})
        return

    print(f"Room {room_id}: Player {sid} action: {action_type} with payload: {payload}")
    # 將動作轉發給對應的遊戲實例處理
    action_result = game_instance.handle_action(sid, action_type, payload)

    # game_instance.handle_action 內部應該會調用 broadcast_state 或 send_error_to_player
    # 如果 action_result 有特定回饋給該玩家，可以在這裡處理
    if action_result and isinstance(action_result, dict) and action_result.get('private_feedback'):
        emit(f"{game_instance.get_game_type()}_action_feedback", action_result['private_feedback'], room=sid)


if __name__ == '__main__':
    print("Starting Multi-Game Flask-SocketIO server...")
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)