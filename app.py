import eventlet
import logging
from dotenv import load_dotenv

# Patch and load configuration first
eventlet.monkey_patch()
load_dotenv()

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room as sio_leave_room
import uuid
import os

from games.texas_holdem.logic import TexasHoldemGame
from games.black_jack.logic import BlackJackGame

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_very_secret_multi_game_key!')
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

active_rooms = {}
email_to_sid = {}
sid_to_email = {}

REGISTERED_GAME_LOGIC = {
    "texas_holdem": TexasHoldemGame,
    "black_jack": BlackJackGame,
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/lobby/rooms', methods=['GET'])
def get_lobby_rooms_api():
    lobby_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items() if game}}
    return jsonify(lobby_data), 200

@app.route('/api/rooms', methods=['POST'])
def create_room_api():
    data = request.get_json()
    email = data.get('email')
    player_name = data.get('player_name', f"Player_{email[:4] if email else 'Anon'}")
    game_type = data.get('game_type')
    options = data.get('options', {})

    if not email or email not in email_to_sid:
        return jsonify({'success': False, 'message': 'Email not registered or missing.'}), 400
    if not game_type or game_type not in REGISTERED_GAME_LOGIC:
        return jsonify({'success': False, 'message': f"Invalid game type: {game_type}"}), 400

    sid = email_to_sid[email]
    room_id = str(uuid.uuid4())[:8]
    game_class = REGISTERED_GAME_LOGIC[game_type]
    game_instance = game_class(room_id, [email], socketio, options)
    game_instance.add_player(email, {'name': player_name})

    active_rooms[room_id] = game_instance
    join_room(room_id, sid=sid, namespace='/')

    socketio.emit('lobby_update', {'rooms': {r_id: g.get_game_type() for r_id, g in active_rooms.items()}}, broadcast=True)
    socketio.emit('room_created_socket_event', {
        'room_id': room_id,
        'game_type': game_type,
        'options': options,
        'creator_email': email
    }, room=sid)

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
    data = request.get_json()
    email = data.get('email')
    player_name = data.get('player_name', f"Player_{email[:4] if email else 'Anon'}")

    if not email or email not in email_to_sid:
        return jsonify({'success': False, 'message': '需要註冊 Email 才能加入房間。'}), 400
    if room_id not in active_rooms:
        return jsonify({'success': False, 'message': '找不到房間。'}), 404

    sid = email_to_sid[email]
    game_instance = active_rooms[room_id]

    if game_instance.is_game_in_progress and not game_instance.options.get('allow_join_in_progress', False):
        return jsonify({'success': False, 'message': '遊戲正在進行中，不允許新玩家加入。'}), 403
    if email in game_instance.players:
        join_room(room_id, sid=sid, namespace='/')
        game_instance.broadcast_state(specific_sid=sid)
        return jsonify({'success': True, 'game_type': game_instance.get_game_type(), 'message': '您已在此房間中。'}), 200

    join_room(room_id, sid=sid, namespace='/')
    game_instance.add_player(email, {'name': player_name})

    socketio.emit('joined_room_success_socket_event', {
        'room_id': room_id,
        'game_type': game_instance.get_game_type()
    }, room=sid)

    game_instance.broadcast_state(specific_sid=sid)

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

@socketio.on('register_email')
def handle_register_email(data):
    sid = request.sid
    email = data.get('email')

    if not email:
        emit('error_message', {'message': 'Missing email for registration'})
        return

    email_to_sid[email] = sid
    sid_to_email[sid] = email
    print(f"Registered email {email} to SID {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    email = sid_to_email.pop(sid, None)
    if email:
        email_to_sid.pop(email, None)
    print(f"客戶端已斷線: SID={sid}, Email={email}")

    for r_id, game in list(active_rooms.items()):
        if email in game.players:
            result = game.remove_player(email)
            if result == "ROOM_EMPTY" or game.get_player_count() == 0:
                if not game.is_game_in_progress:
                    del active_rooms[r_id]
                else:
                    game.end_game({"message": "所有玩家已離開，遊戲結束。"})
                    del active_rooms[r_id]

    socketio.emit('lobby_update', {'rooms': {r_id: g.get_game_type() for r_id, g in active_rooms.items()}}, broadcast=True)

@socketio.on('leave_room_request')
def handle_leave_room_request(data):
    sid = request.sid
    email = sid_to_email.get(sid)
    room_id = data.get('room_id')

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': "找不到要離開的房間。"})
        return

    game = active_rooms[room_id]
    if email not in game.players:
        sio_leave_room(room_id, sid=sid)
        emit('message', {'text': "您並未活躍在此遊戲房間中。"})
        return

    result = game.remove_player(email)
    sio_leave_room(room_id, sid=sid)
    emit('left_room_success', {'room_id': room_id}, room=sid)

    if result == "ROOM_EMPTY" or game.get_player_count() == 0:
        if not game.is_game_in_progress:
            del active_rooms[room_id]

    socketio.emit('lobby_update', {'rooms': {r_id: g.get_game_type() for r_id, g in active_rooms.items()}}, broadcast=True)

@socketio.on('start_game_request')
def handle_start_game_request(data):
    sid = request.sid
    email = sid_to_email.get(sid)
    room_id = data.get('room_id')

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': "找不到房間。"})
        return

    game = active_rooms[room_id]
    game.start_game(triggering_player_sid=email)

@socketio.on('game_action')
def on_game_action(data):
    sid = request.sid
    email = sid_to_email.get(sid)
    room_id = data.get('room_id')
    action_type = data.get('action_type')
    payload = data.get('payload', {})

    if not room_id or room_id not in active_rooms:
        emit('error_message', {'message': '找不到房間以執行動作。'})
        return

    game = active_rooms[room_id]
    if email not in game.players:
        emit('error_message', {'message': '您不是此遊戲房間的玩家。'})
        return

    game.handle_action(email, action_type, payload)

if __name__ == '__main__':
    print("正在啟動多遊戲 Flask-SocketIO 伺服器...")
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)
