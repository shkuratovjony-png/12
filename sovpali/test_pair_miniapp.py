import hashlib,hmac,json,time,unittest
from urllib.parse import urlencode
from unittest.mock import patch
from flask import Flask
from pair_miniapp import validate_init_data,pair_button
from pair_motion import register_pair_motion

TOKEN='test-only-token'
def signed(uid=123,age=0):
    data={'user':json.dumps({'id':uid}),'auth_date':str(int(time.time())-age),'query_id':'demo'}
    secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(secret,'\n'.join(f'{k}={data[k]}' for k in sorted(data)).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)

class MiniAppTest(unittest.TestCase):
    def test_signature(self):
        self.assertEqual(validate_init_data(signed(),TOKEN),123)
        for raw in (signed().replace('demo','changed'),signed(age=4000),signed(age=-90),signed()+'&query_id=duplicate'):
            with self.assertRaises(ValueError): validate_init_data(raw,TOKEN)
    def test_button_keeps_signed_pair(self):
        b=pair_button('✨ Совместимость','https://example.org/s/m/signed.token?x=1')
        self.assertIsNone(b.url)
        self.assertEqual(b.web_app.url,'https://example.org/s/mini/signed.token?x=1')
        self.assertEqual(pair_button('Оплата','https://example.org/billing/contact/token').url,'https://example.org/billing/contact/token')
    def test_shell_has_no_profile(self):
        app=Flask(__name__);register_pair_motion(app,{'TOKEN':TOKEN,'FLASK_SECRET':'test'})
        r=app.test_client().get('/s/mini/test-token')
        self.assertEqual(r.status_code,200)
        self.assertIn(b'miniapp_auth_path',r.data)
        self.assertNotIn(b'candidate',r.data)
        self.assertIn('no-store',r.headers['Cache-Control'])
    def test_viewer_binding(self):
        app=Flask(__name__);ns={'TOKEN':TOKEN,'FLASK_SECRET':'test','user':lambda uid:{'tg_id':123},'cr_between':lambda *a:None,'one':lambda *a:None}
        register_pair_motion(app,ns);client=app.test_client()
        with patch('pair_motion._pair_rows',return_value=({}, {}, 1,2)),patch('pair_motion._data_for_pair',return_value={'score':88,'request_status':'ready'}):
            self.assertEqual(client.post('/s/mini/auth/token',json={'init_data':signed(456)}).status_code,403)
            self.assertEqual(client.post('/s/mini/auth/token',json={'init_data':'fake'}).status_code,401)
            r=client.post('/s/mini/auth/token',json={'init_data':signed()})
            self.assertEqual(r.status_code,200);self.assertEqual(r.json['score'],88)

if __name__=='__main__':unittest.main()
