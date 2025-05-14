from flask import Flask, redirect, url_for, session, request, jsonify, g
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
import os
import requests
import sqlite3
from functools import wraps
import random

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# 啟用 CORS，允許來自 http://localhost:8000 的請求，並支持憑證
CORS(app, resources={r"/*": {"origins": "http://localhost:8000"}}, supports_credentials=True)

socketio = SocketIO(app, cors_allowed_origins="http://localhost:8000")

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
REDIRECT_URI = 'http://localhost:4000/callback'
FRONTEND_URL = 'http://localhost:8000/index.html'

# 記憶體中的遊戲數據
tables = {1: {'name': '主桌', 'max_players': 9}}
table_players = {1: []}
game_states = {}

# 資料庫初始化
def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                balance INTEGER DEFAULT 1000
            )
        ''')
        db.commit()

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('poker.db')
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

init_db()

# 登入檢查裝飾器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'error': '請先登入'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Google 登入路由
@app.route('/')
def index():
    if 'user' in session:
        return redirect(FRONTEND_URL)
    return '歡迎！<a href="/login">使用 Google 登錄</a>'

@app.route('/login')
def login():
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    state = session['state']
    if state != request.args.get('state'):
        return 'State 不匹配，登錄失敗', 400

    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    try:
        flow.fetch_token(authorization_response=request.url)
        userinfo = requests.get('https://www.googleapis.com/oauth2/v3/userinfo', headers={
            'Authorization': f'Bearer {flow.credentials.token}'
        })
        if userinfo.status_code != 200:
            return '無法獲取用戶資訊', 500
        user_info = userinfo.json()

        session['user'] = {'email': user_info['email'], 'name': user_info['name']}
        db = get_db()
        db.execute('INSERT OR REPLACE INTO users (email, name, balance) VALUES (?, ?, ?)',
                   (user_info['email'], user_info['name'], 1000))
        db.commit()
        return redirect(FRONTEND_URL)
    except Exception as e:
        return f'登錄失敗：{str(e)}', 500

@app.route('/logout', methods=['POST'])
def logout():
    if 'user' in session:
        email = session['user']['email']
        # 從所有桌子的 table_players 中移除該用戶
        for table_id in table_players:
            table_players[table_id] = [p for p in table_players[table_id] if p['email'] != email]
            # 通知桌子中的其他玩家
            socketio.emit('message', {'message': f'玩家 {email} 已離開桌子 {table_id}'}, room=str(table_id))
        # 如果該桌子正在遊戲中，移除遊戲狀態
        for table_id in list(game_states.keys()):
            if not any(p['email'] == email for p in table_players.get(table_id, [])):
                if table_id in game_states:
                    del game_states[table_id]
        session.pop('user', None)
    return jsonify({'message': '登出成功'})

@app.route('/user', methods=['GET'])
@login_required
def get_user():
    return jsonify(session['user'])

# 遊戲邏輯類
class PokerGame:
    def __init__(self, table_id):
        self.table_id = table_id
        self.deck = self.create_deck()
        self.community_cards = []
        self.pot = 0
        self.players = []

    def create_deck(self):
        suits = ['♠', '♥', '♦', '♣']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        deck = [rank + suit for suit in suits for rank in ranks]
        random.shuffle(deck)
        return deck

    def deal_hole_cards(self, players):
        self.players = [{'email': p['email'], 'hand': [self.deck.pop(), self.deck.pop()], 'chips': p['chips'], 'bet': 0} for p in players]
        return self.players

    def deal_community_cards(self, num_cards):
        self.community_cards.extend([self.deck.pop() for _ in range(num_cards)])
        return self.community_cards

    def place_bet(self, email, amount):
        for player in self.players:
            if player['email'] == email:
                if player['chips'] >= amount:
                    player['chips'] -= amount
                    player['bet'] += amount
                    self.pot += amount
                    return True
                return False
        return False

    def to_json(self):
        return {
            'table_id': self.table_id,
            'community_cards': self.community_cards,
            'pot': self.pot,
            'players': self.players
        }

# 遊戲 API 端點
@app.route('/tables', methods=['GET'])
@login_required
def list_tables():
    return jsonify([{'table_id': tid, 'name': t['name'], 'max_players': t['max_players']} for tid, t in tables.items()])

@app.route('/join_table/<int:table_id>', methods=['POST'])
@login_required
def join_table(table_id):
    email = session['user']['email']
    if table_id not in tables:
        return jsonify({'error': '桌子不存在'}), 404

    # 檢查用戶是否已經在桌子中
    if any(p['email'] == email for p in table_players.get(table_id, [])):
        return jsonify({'error': '你已經在這個桌子中'}), 400

    if len(table_players[table_id]) >= tables[table_id]['max_players']:
        return jsonify({'error': '桌子已滿'}), 400

    db = get_db()
    user = db.execute('SELECT balance FROM users WHERE email = ?', (email,)).fetchone()
    if user['balance'] < 100:
        return jsonify({'error': '籌碼不足'}), 400

    seat = len(table_players[table_id]) + 1
    table_players[table_id].append({'email': email, 'seat': seat, 'chips': 100})
    db.execute('UPDATE users SET balance = balance - 100 WHERE email = ?', (email,))
    db.commit()

    socketio.emit('message', {'message': f'玩家 {email} 加入桌子 {table_id}'}, room=str(table_id))
    return jsonify({'message': '成功加入桌子', 'table_id': table_id, 'seat': seat})

@app.route('/start_game/<int:table_id>', methods=['POST'])
@login_required
def start_game(table_id):
    if table_id not in tables:
        return jsonify({'error': '桌子不存在'}), 404

    players = table_players.get(table_id, [])
    if len(players) < 2:
        return jsonify({'error': '玩家不足，無法開始遊戲'}), 400

    game = PokerGame(table_id)
    game.deal_hole_cards(players)
    game.deal_community_cards(3)
    game_states[table_id] = game

    socketio.emit('game_state', game.to_json(), room=str(table_id))
    return jsonify(game.to_json())

@app.route('/bet/<int:table_id>', methods=['POST'])
@login_required
def bet(table_id):
    email = session['user']['email']
    amount = request.json.get('amount')
    if not amount or amount <= 0:
        return jsonify({'error': '無效的賭注金額'}), 400

    if table_id not in game_states:
        return jsonify({'error': '遊戲尚未開始'}), 400

    game = game_states[table_id]
    if game.place_bet(email, amount):
        db = get_db()
        db.execute('UPDATE users SET balance = balance - ? WHERE email = ?', (amount, email))
        db.commit()
        socketio.emit('game_state', game.to_json(), room=str(table_id))
        return jsonify(game.to_json())
    return jsonify({'error': '下注失敗，籌碼不足或無效玩家'}), 400

# Socket.IO 事件
@socketio.on('join_table')
def on_join_table(data):
    table_id = data['table_id']
    join_room(str(table_id))

if __name__ == '__main__':
    socketio.run(app, host='localhost', port=4000, debug=True)