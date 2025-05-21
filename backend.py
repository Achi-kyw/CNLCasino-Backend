from flask import Flask, redirect, url_for, session, request, jsonify, g
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
import os
import requests
import sqlite3
from functools import wraps
import random
import logging

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

socketio = SocketIO(app, cors_allowed_origins="http://localhost:5173", logger=True, engineio_logger=True)

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
REDIRECT_URI = 'http://localhost:4000/callback'
FRONTEND_URL = 'http://localhost:5173/'

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
@login_required
def get_user():
    return jsonify(session['user'])

if __name__ == '__main__':
    try:
        logger.debug("Starting Flask-SocketIO server on 127.0.0.1:4000")
        socketio.run(app, host='127.0.0.1', port=4000, debug=True, use_reloader=False)
    except Exception as e:
        logger.error(f"Server startup failed: {str(e)}")
        raise