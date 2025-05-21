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
# cors_allowed_origins="*" in SocketIO handles CORS for Socket.IO connections.
# For Flask routes (APIs), you might need Flask-CORS if they are called from a different origin.
# However, if your frontend and backend are served from the same origin, it might not be an issue.
# For simplicity, I'll assume SocketIO's CORS handling is sufficient for now, or you'll add Flask-CORS if needed.
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
    return render_template('index.html') # Passing active_rooms here is for initial server-side render if needed

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

    sid = data.get('sid') # Client needs to send its Socket.IO SID
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
    
    # Create game instance, creator (sid) is passed to be potentially added by game logic constructor
    game_instance = game_class(room_id, [sid], socketio, options) 
    # Explicitly add player with name, this also handles if player was already in by __init__
    game_instance.add_player(sid, {'name': player_name}) 

    active_rooms[room_id] = game_instance
    join_room(room_id, sid=sid) # Add the creator's socket to the Socket.IO room

    print(f"Room {room_id} (Type: {game_type}) created by {player_name} ({sid}). Options: {options}")

    # Broadcast lobby update to all clients
    lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
    socketio.emit('lobby_update', lobby_update_data, broadcast=True)
    
    # Respond to the API caller
    # Also emit a specific event to the creator so their UI can switch to the room view
    # Or, the client can use the API response to switch views and then request game state
    socketio.emit('room_created_socket_event', {'room_id': room_id, 'game_type': game_type, 'options': options, 'creator_sid': sid}, room=sid)
    # Send initial game state to creator
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

    sid = data.get('sid') # Client needs to send its Socket.IO SID
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
        # Player is already in the game logic, ensure they are in the Socket.IO room
        join_room(room_id, sid=sid) 
        game_instance.broadcast_state(specific_sid=sid) # Send current state
        return jsonify({'success': True, 'game_type': game_instance.get_game_type(), 'message': '您已在此房間中。'}), 200

    # TODO: Check if room is full based on game_instance.options.get('max_players')

    join_room(room_id, sid=sid) # Add player's socket to the Socket.IO room
    game_instance.add_player(sid, {'name': player_name}) # Game logic handles adding player and broadcasting state

    print(f"玩家 {player_name} ({sid}) 加入房間 {room_id}.")
    
    # game_instance.add_player should broadcast the state.
    # Send a specific success message to the joiner.
    socketio.emit('joined_room_success_socket_event', {'room_id': room_id, 'game_type': game_instance.get_game_type()}, room=sid)
    # Send initial game state to joiner
    game_instance.broadcast_state(specific_sid=sid)


    # Broadcast lobby update (optional, if add_player doesn't already trigger it via a cascade)
    # lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
    # socketio.emit('lobby_update', lobby_update_data, broadcast=True)

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
    # It's good practice to send SID to client, so it can use it in API calls
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
        # game_instance.remove_player will handle broadcasting game state changes
        result = game_instance_of_player.remove_player(sid) 
        # sio_leave_room(room_to_leave, sid=sid) # Ensure specific sid leaves the sio room
        # Note: Flask-SocketIO automatically removes disconnected sids from rooms they were in.
        # Explicitly calling sio_leave_room might be redundant or for clarity.

        if result == "ROOM_EMPTY" or game_instance_of_player.get_player_count() == 0:
            if not game_instance_of_player.is_game_in_progress :
                print(f"房間 {room_to_leave} 已空且遊戲未進行。正在從 active_rooms 移除。")
                if room_to_leave in active_rooms: del active_rooms[room_to_leave]
            elif game_instance_of_player.get_player_count() == 0 and game_instance_of_player.is_game_in_progress:
                print(f"房間 {room_to_leave} 已空但遊戲仍在進行。強制結束。")
                game_instance_of_player.end_game({"message": "所有玩家已離開，遊戲結束。"})
                if room_to_leave in active_rooms: del active_rooms[room_to_leave]
        
        # Broadcast lobby update
        lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
        socketio.emit('lobby_update', lobby_update_data, broadcast=True)

# 'get_lobby_info' is now an API: GET /api/lobby/rooms

@socketio.on('leave_room_request') # Kept as Socket.IO for simplicity with sid
def handle_leave_room_request(data):
    sid = request.sid
    room_id = data.get('room_id')
    print(f"Socket 事件: leave_room_request, SID={sid}, room_id={room_id}")

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': "找不到要離開的房間。"})
        return

    game_instance = active_rooms[room_id]
    if sid not in game_instance.players:
        sio_leave_room(room_id, sid=sid) # Ensure they are out of SocketIO room anyway
        emit('message', {'text': "您並未活躍在此遊戲房間中。"})
        return

    print(f"玩家 {sid} 請求離開房間 {room_id}.")
    result = game_instance.remove_player(sid) 
    sio_leave_room(room_id, sid=sid) 

    emit('left_room_success', {'room_id': room_id}, room=sid) # Notify the leaver

    if result == "ROOM_EMPTY" or game_instance.get_player_count() == 0:
        if not game_instance.is_game_in_progress:
            print(f"玩家離開後房間 {room_id} 已空。正在移除。")
            if room_id in active_rooms: del active_rooms[room_id]
    
    # Broadcast lobby update
    lobby_update_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items()}}
    socketio.emit('lobby_update', lobby_update_data, broadcast=True)


@socketio.on('start_game_request') 
def handle_start_game_request(data):
    sid = request.sid
    room_id = data.get('room_id')
    print(f"Socket 事件: start_game_request, SID={sid}, room_id={room_id}")

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': "找不到房間。"})
        return
    game_instance = active_rooms[room_id]
    # game_instance.start_game should handle broadcasting the new game state
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
    
    # game_instance.handle_action should handle broadcasting game state changes
    game_instance.handle_action(sid, action_type, payload)


if __name__ == '__main__':
    print("正在啟動多遊戲 Flask-SocketIO 伺服器...")
    # Consider using a different port if 5000 is often in use, e.g., 4000
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)