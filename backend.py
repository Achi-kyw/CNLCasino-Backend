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

# 配置 session cookie 的安全屬性
app.config.update(
    SESSION_COOKIE_SECURE=False,  # 本地使用 HTTP，設為 False；生產環境設為 True
    SESSION_COOKIE_HTTPONLY=True,  # 防止 JavaScript 訪問 cookie
    SESSION_COOKIE_SAMESITE='Lax',  # 防止 CSRF，允許跨域 POST
)

# 啟用 CORS，允許來自 http://localhost:8000 的請求，並支持憑證
CORS(app, resources={r"/*": {"origins": "http://localhost:8000"}}, supports_credentials=True)

socketio = SocketIO(app, cors_allowed_origins="http://localhost:8000")

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
REDIRECT_URI = 'http://localhost:4000/callback'
FRONTEND_URL = 'http://localhost:8000/index.html'

# 記憶體中的遊戲數據
tables = {1: {'name': '主桌', 'max_players': 9, 'game_type': 'texas_holdem'}, 
          2: {'name': '21點桌', 'max_players': 7, 'game_type': 'black_jack'}}
table_players = {1: [], 2: []}
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
        
        # 添加遊戲歷史記錄表
        db.execute('''
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_type TEXT NOT NULL,
                player_email TEXT NOT NULL,
                buy_in INTEGER NOT NULL,
                payout INTEGER NOT NULL,
                play_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (player_email) REFERENCES users (email)
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

@app.route('/user/balance', methods=['GET'])
@login_required
def get_balance():
    email = session['user']['email']
    db = get_db()
    user = db.execute('SELECT balance FROM users WHERE email = ?', (email,)).fetchone()
    if not user:
        return jsonify({'error': '用戶不存在'}), 404
    return jsonify({'balance': user['balance']})

@app.route('/user/history', methods=['GET'])
@login_required
def get_history():
    email = session['user']['email']
    db = get_db()
    history = db.execute('''
        SELECT game_type, buy_in, payout, play_time
        FROM game_history
        WHERE player_email = ?
        ORDER BY play_time DESC
        LIMIT 20
    ''', (email,)).fetchall()
    
    result = []
    for entry in history:
        result.append({
            'game_type': entry['game_type'],
            'buy_in': entry['buy_in'],
            'payout': entry['payout'],
            'profit': entry['payout'] - entry['buy_in'],
            'play_time': entry['play_time']
        })
    
    return jsonify(result)

# 遊戲邏輯類 - 基本牌局
class CardGame:
    def __init__(self, table_id):
        self.table_id = table_id
        self.deck = self.create_deck()
        self.pot = 0
        self.players = []

    def create_deck(self):
        suits = ['♠', '♥', '♦', '♣']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        deck = [{'rank': rank, 'suit': suit} for suit in suits for rank in ranks]
        random.shuffle(deck)
        return deck

    def deal_cards(self, num_cards):
        """從牌堆中抽取指定數量的牌"""
        return [self.deck.pop() for _ in range(num_cards)]

    def place_bet(self, email, amount):
        """玩家下注"""
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
        """返回遊戲狀態的JSON表示"""
        return {
            'table_id': self.table_id,
            'pot': self.pot,
            'players': self.players
        }

# 德州撲克遊戲
class PokerGame(CardGame):
    def __init__(self, table_id):
        super().__init__(table_id)
        self.community_cards = []
        self.game_type = 'texas_holdem'

    def deal_hole_cards(self, players):
        self.players = [{'email': p['email'], 'hand': self.deal_cards(2), 'chips': p['chips'], 'bet': 0} for p in players]
        return self.players

    def deal_community_cards(self, num_cards):
        self.community_cards.extend(self.deal_cards(num_cards))
        return self.community_cards

    def to_json(self):
        base_json = super().to_json()
        base_json['game_type'] = self.game_type
        base_json['community_cards'] = self.community_cards
        return base_json

# 21點遊戲
class BlackjackGame(CardGame):
    def __init__(self, table_id):
        super().__init__(table_id)
        self.dealer_hand = []
        self.dealer_value = 0
        self.game_phase = 'betting'  # betting, player_actions, dealer_actions, payout
        self.game_type = 'black_jack'
        
    def deal_initial_cards(self, players):
        # 清空上一局的牌
        self.dealer_hand = []
        
        # 給玩家發兩張牌
        self.players = [{'email': p['email'], 
                        'hand': self.deal_cards(2), 
                        'chips': p['chips'], 
                        'bet': 0,
                        'insurance': 0,
                        'has_stood': False,
                        'has_busted': False,
                        'has_blackjack': False} for p in players]
        
        # 給莊家發兩張牌
        self.dealer_hand = self.deal_cards(2)
        self.calculate_hand_values()
        
        # 檢查21點
        for player in self.players:
            player['has_blackjack'] = self.is_blackjack(player['hand'])
        
        # 檢查莊家是否露牌A，提供保險選項
        if self.dealer_hand[1]['rank'] == 'A':
            self.game_phase = 'insurance_option'
        else:
            self.game_phase = 'player_actions'
            
        return self.players
    
    def calculate_hand_values(self):
        """計算所有玩家和莊家的手牌值"""
        # 更新莊家手牌值
        self.dealer_value = self.calculate_hand_value(self.dealer_hand)
        
        # 更新玩家手牌值
        for player in self.players:
            player['hand_value'] = self.calculate_hand_value(player['hand'])
            player['has_busted'] = player['hand_value'] > 21
    
    def calculate_hand_value(self, cards):
        """計算一手牌的點數值"""
        value = 0
        aces = 0
        
        for card in cards:
            rank = card['rank']
            if rank in ['K', 'Q', 'J']:
                value += 10
            elif rank == 'A':
                aces += 1
                value += 1  # 先當作1點
            else:
                value += int(rank)
        
        # 考慮A可以當作11點
        while aces > 0 and value + 10 <= 21:
            value += 10
            aces -= 1
            
        return value
    
    def is_blackjack(self, cards):
        """檢查是否為21點"""
        return len(cards) == 2 and self.calculate_hand_value(cards) == 21
    
    def player_hit(self, email):
        """玩家要牌"""
        for player in self.players:
            if player['email'] == email:
                if player['has_stood'] or player['has_busted']:
                    return False
                
                # 發一張牌
                player['hand'].append(self.deck.pop())
                # 重新計算點數
                player['hand_value'] = self.calculate_hand_value(player['hand'])
                # 檢查是否爆牌
                player['has_busted'] = player['hand_value'] > 21
                return True
        return False
    
    def player_stand(self, email):
        """玩家停牌"""
        for player in self.players:
            if player['email'] == email:
                player['has_stood'] = True
                return True
        return False
    
    def player_double(self, email):
        """玩家加倍下注"""
        for player in self.players:
            if player['email'] == email:
                # 只能對初始兩張牌加倍
                if len(player['hand']) != 2 or player['has_stood'] or player['has_busted']:
                    return False
                
                # 檢查籌碼是否足夠
                if player['chips'] < player['bet']:
                    return False
                
                # 加倍下注
                player['chips'] -= player['bet']
                player['bet'] *= 2
                
                # 再發一張牌，然後自動停牌
                player['hand'].append(self.deck.pop())
                player['hand_value'] = self.calculate_hand_value(player['hand'])
                player['has_busted'] = player['hand_value'] > 21
                player['has_stood'] = True
                return True
        return False
    
    def player_insurance(self, email, amount):
        """玩家購買保險"""
        if self.game_phase != 'insurance_option':
            return False
            
        # 莊家的明牌必須是A
        if self.dealer_hand[1]['rank'] != 'A':
            return False
            
        for player in self.players:
            if player['email'] == email:
                # 保險金最多是原下注的一半
                max_insurance = player['bet'] / 2
                if amount > max_insurance or player['chips'] < amount:
                    return False
                
                player['chips'] -= amount
                player['insurance'] = amount
                return True
        return False
    
    def dealer_play(self):
        """莊家按規則要牌，直到17點或以上"""
        self.game_phase = 'dealer_actions'
        
        # 檢查是否所有玩家都已停牌或爆牌
        all_players_done = all(player['has_stood'] or player['has_busted'] for player in self.players)
        if not all_players_done:
            return False
        
        # 莊家要牌直到17點或以上
        while self.dealer_value < 17:
            self.dealer_hand.append(self.deck.pop())
            self.dealer_value = self.calculate_hand_value(self.dealer_hand)
        
        # 結算
        self.payout()
        return True
    
    def payout(self):
        """結算輸贏"""
        self.game_phase = 'payout'
        dealer_blackjack = self.is_blackjack(self.dealer_hand)
        dealer_busted = self.dealer_value > 21
        
        for player in self.players:
            # 玩家爆牌，輸掉賭注
            if player['has_busted']:
                continue  # 賭注已經下在桌上，不用操作
                
            # 處理保險
            if player['insurance'] > 0:
                if dealer_blackjack:
                    # 保險賠率2:1
                    player['chips'] += player['insurance'] * 3
                # 不是21點，保險金已經下在桌上，不用操作
            
            # 玩家有21點
            if player['has_blackjack']:
                if dealer_blackjack:
                    # 平局，還原賭注
                    player['chips'] += player['bet']
                else:
                    # 賠率3:2
                    player['chips'] += player['bet'] * 2.5
            # 莊家爆牌，玩家贏
            elif dealer_busted:
                player['chips'] += player['bet'] * 2
            # 比點數大小
            elif player['hand_value'] > self.dealer_value:
                player['chips'] += player['bet'] * 2
            elif player['hand_value'] == self.dealer_value:
                # 平局，還原賭注
                player['chips'] += player['bet']
            # 其他情況，莊家贏，賭注已經下在桌上，不用操作
    
    def to_json(self):
        base_json = super().to_json()
        base_json['game_type'] = self.game_type
        base_json['dealer_hand'] = self.dealer_hand
        base_json['dealer_value'] = self.dealer_value
        base_json['game_phase'] = self.game_phase
        
        # 如果不是最終結算階段，隱藏莊家的第一張牌
        if self.game_phase not in ['dealer_actions', 'payout']:
            base_json['dealer_hand'] = [{'rank': '?', 'suit': '?'}, self.dealer_hand[1]]
        
        return base_json

# 遊戲 API 端點
@app.route('/tables', methods=['GET'])
@login_required
def list_tables():
    return jsonify([{'table_id': tid, 'name': t['name'], 'max_players': t['max_players'], 'game_type': t.get('game_type', 'texas_holdem')} for tid, t in tables.items()])

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

    game_type = tables[table_id].get('game_type', 'texas_holdem')
    
    if game_type == 'texas_holdem':
        game = PokerGame(table_id)
        game.deal_hole_cards(players)
        game.deal_community_cards(3)
    elif game_type == 'black_jack':
        game = BlackjackGame(table_id)
        # 21點開始時處於下注階段，不立即發牌
        game.players = [{'email': p['email'], 'chips': p['chips'], 'bet': 0} for p in players]
    else:
        return jsonify({'error': '不支持的遊戲類型'}), 400
        
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

@app.route('/action/<int:table_id>', methods=['POST'])
@login_required
def player_action(table_id):
    email = session['user']['email']
    action = request.json.get('action')
    amount = request.json.get('amount', 0)
    
    if not action:
        return jsonify({'error': '未指定動作'}), 400

    if table_id not in game_states:
        return jsonify({'error': '遊戲尚未開始'}), 400

    game = game_states[table_id]
    game_type = game.game_type
    
    result = False
    if game_type == 'texas_holdem':
        # 德州撲克的動作處理
        if action == 'fold':
            # TODO: 棄牌邏輯
            pass
        elif action == 'check':
            # TODO: 過牌邏輯
            pass
        elif action == 'call':
            # TODO: 跟注邏輯
            pass
        elif action == 'raise':
            # TODO: 加注邏輯
            pass
    elif game_type == 'black_jack':
        # 21點的動作處理
        if action == 'hit':
            result = game.player_hit(email)
        elif action == 'stand':
            result = game.player_stand(email)
            # 檢查是否所有玩家都完成動作
            if all(p['has_stood'] or p['has_busted'] for p in game.players):
                game.dealer_play()
        elif action == 'double':
            result = game.player_double(email)
            # 加倍後自動停牌，同樣檢查是否所有玩家都完成
            if all(p['has_stood'] or p['has_busted'] for p in game.players):
                game.dealer_play()
        elif action == 'insurance':
            result = game.player_insurance(email, amount)
    
    if not result:
        return jsonify({'error': '動作執行失敗'}), 400
        
    socketio.emit('game_state', game.to_json(), room=str(table_id))
    return jsonify(game.to_json())

# Socket.IO 事件
@socketio.on('join_table')
def on_join_table(data):
    table_id = data['table_id']
    join_room(str(table_id))

if __name__ == '__main__':
    socketio.run(app, host='localhost', port=4000, debug=True)