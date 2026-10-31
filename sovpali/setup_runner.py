import os, sys, runpy, threading, time
from pathlib import Path
from flask import Flask, request
from waitress import serve
import requests

TOKEN_FILE = Path('/tmp/sovpali_bot_token')
SETUP_SECRET = os.getenv('SETUP_SECRET','change-me')
PORT = int(os.getenv('PORT','10000'))

def launch_app(token: str):
    os.environ['BOT_TOKEN'] = token.strip()
    runpy.run_path('app.py', run_name='__main__')

def current_token():
    env = os.getenv('BOT_TOKEN','').strip()
    if env:
        return env
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding='utf-8').strip()
    return ''

def restart_self(token: str):
    time.sleep(1.2)
    os.environ['BOT_TOKEN'] = token
    os.execv(sys.executable, [sys.executable, 'setup_runner.py'])

env_token = bool(os.getenv('BOT_TOKEN','').strip())
file_token = TOKEN_FILE.exists()
token = current_token()
source = 'environment' if env_token else ('tmp' if file_token else 'missing')
print(f'[setup] token_source={source}; database_url={"present" if os.getenv("DATABASE_URL","").strip() else "absent"}', flush=True)

if token:
    launch_app(token)
else:
    app = Flask(__name__)

    @app.get('/')
    def root():
        return '<h2>Совпали</h2><p>Бот ещё не настроен.</p>'

    @app.route('/setup/'+SETUP_SECRET, methods=['GET','POST'])
    def setup():
        msg=''
        if request.method=='POST':
            token=request.form.get('token','').strip()
            if not token:
                msg='<p style="color:red">Вставьте токен</p>'
            else:
                try:
                    r=requests.get(f'https://api.telegram.org/bot{token}/getMe',timeout=10).json()
                    if not r.get('ok'):
                        raise ValueError('bad token')
                    TOKEN_FILE.write_text(token,encoding='utf-8')
                    threading.Thread(target=restart_self,args=(token,),daemon=True).start()
                    return '<h2>Готово ✅</h2><p>Токен принят. Бот запускается автоматически.</p><script>setTimeout(()=>location.href="/",3500)</script>'
                except Exception:
                    msg='<p style="color:red">Токен не подошёл. Скопируйте его заново из BotFather.</p>'
        return f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{{font-family:Arial;max-width:520px;margin:60px auto;padding:20px}}input{{width:100%;padding:12px;box-sizing:border-box}}button{{margin-top:12px;padding:12px 18px}}</style><h2>Настройка бота «Совпали»</h2><p>Вставьте токен из BotFather. Больше ничего настраивать не нужно.</p>{msg}<form method="post"><input name="token" type="password" placeholder="Токен Telegram-бота"><button>Запустить бота</button></form>'''

    @app.get('/health')
    def health():
        return {'ok': True, 'configured': False, 'token_source': source}

    serve(app, host='0.0.0.0', port=PORT, threads=4)
