"""Verify actual final security hook without importing a live Telegram bot."""
import ast
from pathlib import Path
from flask import Flask,request,make_response
source=ast.parse(Path('app.py').read_text())
node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='security_headers')
app=Flask(__name__);ns={'app':app,'request':request}
exec(compile(ast.Module(body=[node],type_ignores=[]),'headers-test','exec'),ns)
for path in ('/admin','/admin/login','/billing/contact/test','/billing/create'):
    with app.test_request_context(path):
        response=ns['security_headers'](make_response('test'))
        assert response.headers['X-Frame-Options']=='DENY'
for path in ('/s/app','/s/mini/test'):
    with app.test_request_context(path):
        response=ns['security_headers'](make_response('test'))
        assert 'X-Frame-Options' not in response.headers
        assert response.headers['Content-Security-Policy']=="frame-ancestors 'self' https://web.telegram.org"
with app.test_request_context('/s/m/demo'):
    assert ns['security_headers'](make_response('test')).headers['X-Frame-Options']=='SAMEORIGIN'
print('[test] Telegram frame allowlist; admin and payment frame protections unchanged PASS')
