# import eventlet
# from dotenv import load_dotenv

# Patch and load configuration first
# eventlet.monkey_patch()
# load_dotenv()

from functools import wraps
import requests
import logging
from google_auth_oauthlib.flow import Flow
from flask_cors import CORS
import logging

from flask import Flask, redirect, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room as sio_leave_room
import uuid
import os

from games.texas_holdem.logic import TexasHoldemGame
from games.black_jack.logic import BlackJackGame

# 設置日誌
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# 配置 session cookie 的安全屬性
app.config.update(
    SESSION_COOKIE_SECURE=False,  # 本地使用 HTTP，設為 False；生產環境設為 True
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# 啟用 CORS
CORS(app, resources={r"/*": {"origins": "http://localhost:5173"}}, supports_credentials=True)

socketio = SocketIO(app, cors_allowed_origins="http://localhost:5173", logger=True, engineio_logger=False)

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
REDIRECT_URI = 'http://localhost:4000/callback'
FRONTEND_URL = 'http://localhost:5173/'

active_rooms = {}
email_to_sid = {}
sid_to_email = {}

REGISTERED_GAME_LOGIC = {
    "texas_holdem": TexasHoldemGame,
    "black_jack": BlackJackGame,
}

# Google 登入路由
@app.route('/')
def index():
    if 'user' in session:
        return redirect(FRONTEND_URL)
    return '歡迎！<a href="/login">使用 Google 登錄</a>'

@app.route('/login')
def login():
    logger.debug("Starting Google OAuth login")
    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
        session['state'] = state
        logger.debug(f"Redirecting to Google auth URL: {authorization_url}")
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

@app.route('/callback')
def callback():
    logger.debug("Handling Google OAuth callback")
    state = session.get('state')
    if state != request.args.get('state'):
        logger.error("State mismatch in callback")
        return jsonify({'error': 'State does not match'}), 400

    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        flow.fetch_token(authorization_response=request.url)
        userinfo = requests.get('https://www.googleapis.com/oauth2/v3/userinfo', headers={
            'Authorization': f'Bearer {flow.credentials.token}'
        })
        if userinfo.status_code != 200:
            logger.error(f"Failed to fetch user info: {userinfo.status_code}")
            return jsonify({'error': '無法獲取用戶資訊'}), 500
        user_info = userinfo.json()

        session['user'] = {'email': user_info['email'], 'name': user_info['name']}
        logger.debug(f"User logged in: {user_info['email']}")
        return redirect(FRONTEND_URL)
    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        return jsonify({'error': f'登錄失敗：{str(e)}'}), 500

@app.route('/logout', methods=['POST'])
def logout():
    if 'user' in session:
        email = session['user']['email']
        session.pop('user', None)
        logger.debug(f"User {email} logged out")
    return jsonify({'message': '登出成功'})

@app.route('/user', methods=['GET'])
def get_user():
    if 'user' not in session:
        return jsonify({'success': False, 'message': '請先登入'}), 401
    return jsonify(session['user'])

@app.route('/api/lobby/rooms', methods=['GET'])
def get_lobby_rooms_api():
    lobby_data = {'rooms': {r_id: game.get_game_type() for r_id, game in active_rooms.items() if game}}
    return jsonify(lobby_data), 200

@app.route('/api/rooms', methods=['POST'])
def create_room_api():
    if 'user' not in session:
        return jsonify({'success': False, 'message': '請先登入'}), 401
    data = request.get_json()
    email = session['user']['email']
    player_name = session['user']['name']
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

    # 發送 lobby_update 事件給所有連線的客戶端
    socketio.emit('lobby_update',
                  {'rooms': {r_id: g.get_game_type() for r_id, g in active_rooms.items()}},
                  namespace='/')  # 省略 to 參數表示廣播給所有客戶端

    # 發送 room_created_socket_event 給房間創建者（或房間內所有客戶端）
    socketio.emit('room_created_socket_event',
                  {
                      'room_id': room_id,
                      'game_type': game_type,
                      'options': options,
                      'creator_email': email
                  },
                  to=sid,  # 發送給創建者的 SID
                  namespace='/')

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
    email = session['user']['email']
    player_name = session['user']['name']

    if not email or email not in email_to_sid:
        return jsonify({'success': False, 'message': '需要註冊 Email 才能加入房間。'}), 400
    if room_id not in active_rooms:
        return jsonify({'success': False, 'message': '找不到房間。'}), 404

    sid = email_to_sid[email]
    game_instance = active_rooms[room_id]

    if game_instance.is_game_in_progress and not game_instance.options.get('allow_join_in_progress', False):
        return jsonify({'success': False, 'message': '遊戲正在進行中，不允許新玩家加入。'}), 403
    join_room(room_id, sid=sid, namespace='/')
    game_instance.add_player(email, {'name': player_name})

    socketio.emit('joined_room_success_socket_event', {
        'room_id': room_id,
        'game_type': game_instance.get_game_type()
    }, to=sid)

    game_instance.broadcast_state(specific_sid=sid)

    return jsonify({
        'success': True,
        'game_type': game_instance.get_game_type(),
        'message': f"成功加入房間 {room_id}。"
    }), 200

# --- Socket.IO Event Handlers ---
@socketio.on('connect')
def handle_connect():
    logger.debug(f"Connect attempt with SID={request.sid}, Session={session}")
    if 'user' not in session:
        logger.error(f"Connect failed: No user in session for SID={request.sid}")
        emit('error_message', {'message': '請先登入'})
        return False  # Disconnect the client explicitly
    sid = request.sid
    email = session['user']['email']
    player_name = session['user'].get('name', 'Unknown Player')
    logger.info(f"Client connected: SID={sid}, Email={email}")
    old_sid_for_email = email_to_sid.get(email)
    if old_sid_for_email and old_sid_for_email != sid:
        logger.info(f"Email {email} reconnected with new SID {sid}. Old SID was {old_sid_for_email}.")
        sid_to_email.pop(old_sid_for_email, None)

    email_to_sid[email] = sid
    sid_to_email[sid] = email
    logger.debug(f"Updated mappings: email_to_sid[{email}] = {sid}, sid_to_email[{sid}] = {email}")

    rejoined_a_room = False
    for room_id, game in active_rooms.items():
        if email in game.players:
            logger.info(f"User {email} was in room {room_id}. Attempting to rejoin with new SID {sid}.")
            join_room(room_id, sid=sid, namespace='/')
            if email in game.players and isinstance(game.players[email], dict):
                game.players[email]['name'] = player_name

            game.broadcast_state()

            socketio.emit('rejoined_room_success_socket_event', {
                'room_id': room_id,
                'game_type': game.get_game_type(),
                'message': f"歡迎回來！已重新加入房間 {room_id}。"
            }, to=sid)

            rejoined_a_room = True

    if rejoined_a_room:
        logger.info(f"User {email} (SID: {sid}) automatically rejoined their active game(s).")
    else:
        logger.info(f"User {email} (SID: {sid}) connected. No active games to rejoin automatically.")
    return True  # Explicitly allow the connection


@socketio.on('register_email')
def handle_register_email():
    if 'user' not in session:
        return jsonify({'success': False, 'message': '請先登入'}), 401

    sid = request.sid
    if 'user' not in session or 'email' not in session['user']:
        emit('error_message', {'message': 'Missing user email for registration.'})
        return

    email = session['user']['email']

    old_sid_for_email = email_to_sid.get(email)
    if old_sid_for_email and old_sid_for_email != sid:
        sid_to_email.pop(old_sid_for_email, None)

    email_to_sid[email] = sid
    sid_to_email[sid] = email
    logger.info(f"Explicitly registered email {email} to SID {sid} via 'register_email' event.")
    emit('email_registered', {'email': email, 'sid': sid})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    email = sid_to_email.pop(sid, None) # Remove current SID from reverse mapping

    if email:
        if email_to_sid.get(email) == sid:
            email_to_sid.pop(email, None)
            logger.info(f"User {email} (SID: {sid}) disconnected. Removed from active SID mapping.")
        else:
            logger.info(f"Old SID {sid} for user {email} disconnected. User may have already reconnected with a new SID.")
    else:
        logger.info(f"Client disconnected: SID={sid}. No email was actively associated with this SID (or already cleaned up).")

    if not email:
        return

    for r_id, game in list(active_rooms.items()):
        if email in game.players:
            logger.info(f"Processing disconnect for user {email} in room {r_id}.")
            result = game.disconnect_player(email)
            if result == "ROOM_EMPTY" or (hasattr(game, 'get_player_count') and game.get_player_count() == 0):
                logger.info(f"Room {r_id} is now empty or game logic determined cleanup after {email} left.")
                if not game.is_game_in_progress:
                    logger.info(f"Game in room {r_id} was not in progress. Deleting room.")
                    if r_id in active_rooms: del active_rooms[r_id]
                else:
                    logger.info(f"Game in room {r_id} was in progress. Ending game and deleting room due to all players leaving.")
                    if hasattr(game, 'end_game'):
                        game.end_game({"message": "所有玩家已離開或斷線，遊戲結束。"})
                    if r_id in active_rooms: del active_rooms[r_id]
    socketio.emit('lobby_update',
                  {'rooms': {r_id: g.get_game_type() for r_id, g in active_rooms.items()}},
                  namespace='/')
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

    socketio.emit('lobby_update', {'rooms': {r_id: g.get_game_type() for r_id, g in active_rooms.items()}}, namespace='/')

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
    return {'success': True}

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
    try:
        logger.debug("Starting Flask-SocketIO server on 127.0.0.1:4000")
        socketio.run(app, host='127.0.0.1', port=4000, debug=True, use_reloader=False)
    except Exception as e:
        logger.error(f"Server startup failed: {str(e)}")
        raise
