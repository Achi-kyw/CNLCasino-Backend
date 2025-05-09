from flask import Flask, redirect, url_for, session, request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import requests

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # 設置 Flask session 密鑰
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # 允許本地測試（僅限開發）

# Google OAuth 2.0 配置
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
REDIRECT_URI = 'http://localhost:4000/callback'

@app.route('/')
def index():
    return '歡迎！<a href="/login">使用 Google 登錄</a>'

@app.route('/login')
def login():
    # 初始化 OAuth 流程
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    # 生成授權 URL 並重定向
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state  # 儲存 state 以驗證回調
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    # 驗證 state
    state = session['state']
    if state != request.args.get('state'):
        return 'State 不匹配，登錄失敗', 400

    # 初始化 OAuth 流程
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    # 交換授權碼以獲取存取令牌
    flow.fetch_token(authorization_response=request.url)

    credentials = Credentials(
        token=flow.credentials.token,
        refresh_token=flow.credentials.refresh_token,
        token_uri=flow.credentials.token_uri,
        client_id=flow.credentials.client_id,
        client_secret=flow.credentials.client_secret,
        scopes=flow.credentials.scopes
    )
    userinfo = requests.get('https://www.googleapis.com/oauth2/v3/userinfo', headers={
        'Authorization': f'Bearer {credentials.token}'
    }).json()
    user_info = {
        'email': userinfo['email'],
        'name': userinfo['name']
    }

    # # 獲取用戶資訊
    # credentials = flow.credentials
    # service = build('people', 'v1', credentials=credentials)
    # profile = service.people().get(resourceName='people/me', personFields='names,emailAddresses').execute()

    # # 提取用戶資料
    # user_info = {
    #     'email': profile['emailAddresses'][0]['value'],
    #     'name': profile['names'][0]['displayName']
    # }

    # 儲存用戶資訊到 session 或資料庫
    session['user'] = user_info
    return f'登錄成功！歡迎 {user_info["name"]} ({user_info["email"]})'

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run('localhost', 4000, debug=True)
