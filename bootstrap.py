import os
from flask import Flask
from waitress import serve

if os.getenv('DATABASE_URL'):
    import runpy
    runpy.run_path('app.py', run_name='__main__')
else:
    app = Flask(__name__)

    @app.get('/')
    def root():
        return 'Sovpali is connected to Render. Database setup is pending.'

    @app.get('/health')
    def health():
        return {'ok': True, 'database': False}

    serve(app, host='0.0.0.0', port=int(os.getenv('PORT', '10000')), threads=4)
