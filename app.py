import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify # Added jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room as sio_leave_room
# from flask_cors import CORS # Not strictly necessary if SocketIO handles CORS with cors_allowed_origins
import uuid 

from games.texas_holdem.logic import TexasHoldemGame
from games.black_jack.logic import BlackJackGame # Assuming you have this file

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_very_secret_multi_game_key!'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

active_rooms = {} 

REGISTERED_GAME_LOGIC = {
    "texas_holdem": TexasHoldemGame,
    "black_jack": BlackJackGame,
}

# --- HTTP Routes (APIs) ---
@app.route('/')
def index():
    # Serves the main HTML page
    return render_template('index.html') 

@app.route('/api/lobby/rooms', methods=['GET'])
def get_lobby_rooms_api():
    """API endpoint to get the list of active game rooms."""
    print(f"API request: GET /api/lobby/rooms")
    lobby_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items() if game}}
    return jsonify(lobby_data), 200

@app.route('/api/rooms', methods=['POST'])
def create_room_api():
    """API endpoint to create a new game room."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request data.'}), 400

    sid = data.get('sid') 
    player_name = data.get('player_name', f"Player_{sid[:4] if sid else 'Anon'}")
    game_type = data.get('game_type')
    options = data.get('options', {})

    print(f"API request: POST /api/rooms, data: {data}")

    if not sid:
        return jsonify({'success': False, 'message': 'SID is required to create a room.'}), 400
    if not game_type or game_type not in REGISTERED_GAME_LOGIC:
        return jsonify({'success': False, 'message': f"Invalid game type: {game_type}"}), 400

    room_id = str(uuid.uuid4())[:8]
    game_class = REGISTERED_GAME_LOGIC[game_type]
    
    game_instance = game_class(room_id, [sid], socketio, options) 
    game_instance.add_player(sid, {'name': player_name}) 

    active_rooms[room_id] = game_instance
    # Explicitly provide namespace when calling from HTTP context
    join_room(room_id, sid=sid, namespace='/') 

    print(f"Room {room_id} (Type: {game_type}) created by {player_name} ({sid}). Options: {options}")

    lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
    socketio.emit('lobby_update', lobby_update_data) # MODIFIED: Removed broadcast=True

    socketio.emit('room_created_socket_event', {'room_id': room_id, 'game_type': game_type, 'options': options, 'creator_sid': sid}, room=sid)
    game_instance.broadcast_state(specific_sid=sid)

    return jsonify({
        'success': True, 
        'room_id': room_id, 
        'game_type': game_type, 
        'options': options,
        'message': f"房間 {room_id} 已創建。"
    }), 201


@app.route('/api/rooms/<room_id>/join', methods=['POST'])
def join_room_api(room_id):
    """API endpoint for a player to join an existing game room."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '無效的請求數據。'}), 400

    sid = data.get('sid') 
    player_name = data.get('player_name', f"Player_{sid[:4] if sid else 'Anon'}")
    
    print(f"API request: POST /api/rooms/{room_id}/join, data: {data}")

    if not sid:
        return jsonify({'success': False, 'message': '需要 SID 才能加入房間。'}), 400
    if room_id not in active_rooms:
        return jsonify({'success': False, 'message': '找不到房間。'}), 404

    game_instance = active_rooms[room_id]

    if game_instance.is_game_in_progress and not game_instance.options.get('allow_join_in_progress', False):
        return jsonify({'success': False, 'message': '遊戲正在進行中，不允許新玩家加入。'}), 403
    if sid in game_instance.players:
        join_room(room_id, sid=sid, namespace='/') 
        game_instance.broadcast_state(specific_sid=sid) 
        return jsonify({'success': True, 'game_type': game_instance.get_game_type(), 'message': '您已在此房間中。'}), 200

    join_room(room_id, sid=sid, namespace='/') 
    game_instance.add_player(sid, {'name': player_name}) 

    print(f"玩家 {player_name} ({sid}) 加入房間 {room_id}.")
    
    socketio.emit('joined_room_success_socket_event', {'room_id': room_id, 'game_type': game_instance.get_game_type()}, room=sid)
    game_instance.broadcast_state(specific_sid=sid)
    
    # Lobby update is usually triggered by game_instance.add_player if it calls broadcast_state
    # or if the game logic itself emits a lobby update.
    # If not, uncomment below:
    # lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
    # socketio.emit('lobby_update', lobby_update_data) # MODIFIED: Removed broadcast=True


    return jsonify({
        'success': True, 
        'game_type': game_instance.get_game_type(),
        'message': f"成功加入房間 {room_id}。"
    }), 200


# --- Socket.IO Event Handlers ---
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"客戶端已連接: {sid}")
    emit('your_sid', {'sid': sid}) 
    emit('message', {'text': f"歡迎! 您的 SID 是: {sid}"})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"客戶端已斷線: {sid}")
    room_to_leave = None
    game_instance_of_player = None
    for r_id, game_inst in list(active_rooms.items()):
        if sid in game_inst.players: 
            room_to_leave = r_id
            game_instance_of_player = game_inst
            break

    if game_instance_of_player and room_to_leave:
        print(f"玩家 {sid} 曾在房間 {room_to_leave}。正在移除。")
        result = game_instance_of_player.remove_player(sid) 

        if result == "ROOM_EMPTY" or game_instance_of_player.get_player_count() == 0:
            if not game_instance_of_player.is_game_in_progress :
                print(f"房間 {room_to_leave} 已空且遊戲未進行。正在從 active_rooms 移除。")
                if room_to_leave in active_rooms: del active_rooms[room_to_leave]
            elif game_instance_of_player.get_player_count() == 0 and game_instance_of_player.is_game_in_progress:
                print(f"房間 {room_to_leave} 已空但遊戲仍在進行。強制結束。")
                game_instance_of_player.end_game({"message": "所有玩家已離開，遊戲結束。"})
                if room_to_leave in active_rooms: del active_rooms[room_to_leave]
        
        lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
        socketio.emit('lobby_update', lobby_update_data) # MODIFIED: Removed broadcast=True


@socketio.on('leave_room_request') 
def handle_leave_room_request(data):
    sid = request.sid
    room_id = data.get('room_id')
    print(f"Socket 事件: leave_room_request, SID={sid}, room_id={room_id}")

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': "找不到要離開的房間。"})
        return

    game_instance = active_rooms[room_id]
    if sid not in game_instance.players:
        sio_leave_room(room_id, sid=sid) 
        emit('message', {'text': "您並未活躍在此遊戲房間中。"})
        return

    print(f"玩家 {sid} 請求離開房間 {room_id}.")
    result = game_instance.remove_player(sid) 
    sio_leave_room(room_id, sid=sid) 

    emit('left_room_success', {'room_id': room_id}, room=sid) 

    if result == "ROOM_EMPTY" or game_instance.get_player_count() == 0:
        if not game_instance.is_game_in_progress:
            print(f"玩家離開後房間 {room_id} 已空。正在移除。")
            if room_id in active_rooms: del active_rooms[room_id]
    
    lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
    socketio.emit('lobby_update', lobby_update_data) # MODIFIED: Removed broadcast=True


@socketio.on('start_game_request') 
def handle_start_game_request(data):
    sid = request.sid
    room_id = data.get('room_id')
    print(f"Socket 事件: start_game_request, SID={sid}, room_id={room_id}")

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': "找不到房間。"})
        return
    game_instance = active_rooms[room_id]
    game_instance.start_game(triggering_player_sid=sid) 

@socketio.on('game_action') 
def on_game_action(data):
    sid = request.sid
    room_id = data.get('room_id')
    action_type = data.get('action_type')
    payload = data.get('payload', {})
    print(f"Socket 事件: game_action, SID={sid}, room_id={room_id}, action={action_type}, payload={payload}")

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': '找不到房間以執行動作。'})
        return
    game_instance = active_rooms[room_id]
    if sid not in game_instance.players:
        emit('error_message', {'message': '您不是此遊戲房間的玩家。'})
        return
    
    game_instance.handle_action(sid, action_type, payload)


if __name__ == '__main__':
    print("正在啟動多遊戲 Flask-SocketIO 伺服器...")
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)
