"""Workshop payment boundary: ownership, mutual consent, exact amount and replay."""
import sqlite3,unittest
from contextlib import contextmanager
from flask import Flask
from coach_web import register_coach,coach_link
from web_workshop import register_workshop,paid,fulfill
from web_checkout_auth import register_web_checkout_auth
from web_product_access import ensure_schema,bind_order

class WorkshopTest(unittest.TestCase):
 def setUp(self):
    self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
    self.c.executescript('''CREATE TABLE communication_requests(requester_user_id INT,target_user_id INT,status TEXT);
      CREATE TABLE billing_web_orders(order_id TEXT,product_key TEXT,status TEXT,amount_kopecks INT,currency_code TEXT);
      INSERT INTO communication_requests VALUES(1,2,'accepted');''')
    @contextmanager
    def db():yield self.c
    self.db=db;ensure_schema(db)
    self.ns={'FLASK_SECRET':'workshop-test','db':db,'one':lambda q,a=():self.c.execute(q,a).fetchone(),
      'profile':lambda uid:{'user_id':uid,'name':'User'+str(uid),'goal':'Общение'},'user':lambda uid:{'id':uid,'is_banned':0},
      'score':lambda a,b:90,'reasons':lambda a,b:[],'web_checkout_ready':lambda:True}
    self.app=Flask(__name__);self.app.secret_key='test-cookie'
    register_web_checkout_auth(self.app,self.ns);register_coach(self.app,self.ns);register_workshop(self.app,self.ns)
    self.client=self.app.test_client();self.token=coach_link('https://test',1,2,'workshop-test').split('/coach/t/')[1]
 def tearDown(self):self.c.close()
 def order(self,status='pending',amount=50000):
    bind_order(self.db,'one',1,'workshop',target_id=2)
    self.c.execute('INSERT INTO billing_web_orders VALUES(?,?,?,?,?)',('one','workshop',status,amount,'643'))
 def test_unpaid_cannot_open_or_prepare(self):
    r=self.client.get('/coach/t/'+self.token);self.assertEqual(r.status_code,303)
    self.assertEqual(self.client.post('/coach/api/prepare/'+self.token,json={}).status_code,402)
    page=self.client.get(r.location);self.assertEqual(page.status_code,200);self.assertIn('500 ₽',page.text)
    self.assertEqual(self.client.get('/coach/demo').status_code,200)
 def test_exact_bank_payment_unlocks_same_pair_only(self):
    self.order();self.assertFalse(paid(self.db,1,2));self.assertFalse(fulfill(self.db,'one'))
    self.c.execute("UPDATE billing_web_orders SET status='paid',amount_kopecks=10000")
    self.assertFalse(paid(self.db,1,2))
    self.c.execute('UPDATE billing_web_orders SET amount_kopecks=50000')
    self.assertTrue(fulfill(self.db,'one'));self.assertTrue(fulfill(self.db,'one'));self.assertEqual(self.c.execute('SELECT COUNT(*) FROM web_product_grants').fetchone()[0],1)
    self.assertTrue(paid(self.db,1,2));self.assertFalse(paid(self.db,2,1));self.assertFalse(paid(self.db,1,3))
    self.assertEqual(self.client.get('/coach/t/'+self.token).status_code,200)
    p=self.client.get('/billing/workshop/'+self.token);self.assertIn('Открыть эмулятор',p.text);self.assertNotIn("<form",p.text)
    self.assertEqual(self.client.post('/coach/api/prepare/'+self.token,json={'intent':'talk','tempo':'slow','tone':'gentle'}).status_code,200)
 def test_unsigned_or_unaccepted_rejected(self):
    self.assertEqual(self.client.get('/billing/workshop/invalid').status_code,404)
    other=coach_link('https://test',2,1,'workshop-test').split('/coach/t/')[1]
    self.assertEqual(self.client.get('/billing/workshop/'+other).status_code,404)
 def test_checkout_uses_server_price_and_deduplicates(self):
    from unittest.mock import patch
    from ozon_web_checkout import register_ozon_web_checkout
    self.c.execute('DROP TABLE billing_web_orders')
    register_ozon_web_checkout(self.app,self.ns)
    with patch('ozon_web_checkout._sales_ready',return_value=True),patch.dict('os.environ',{'WEBHOOK_BASE_URL':'https://one2-1o22.onrender.com'}),patch('ozon_web_checkout._create',return_value=('https://checkout.ozon.ru/pay/test','provider','external')) as bank:
        self.client.get('/billing/workshop/'+self.token)
        with self.client.session_transaction() as session:csrf=session['billing_csrf']
        form={'csrf':csrf,'sku':'workshop','method':'card','amount':1,'buyer_user_id':99}
        r=self.client.post('/billing/create',data=form)
        self.assertEqual(r.status_code,303);self.assertEqual(bank.call_args.args[3],50000)
        row=self.c.execute('SELECT * FROM web_purchase_bindings').fetchone()
        self.assertEqual(row['buyer_user_id'],1);self.assertEqual(row['target_user_id'],2)
        self.assertFalse(paid(self.db,1,2))
        self.assertEqual(self.client.post('/billing/create',data=form).status_code,303)
        self.assertEqual(bank.call_count,1)
        self.assertEqual(self.client.post('/billing/create',data={**form,'csrf':'bad'}).status_code,403)

 def test_product_switch_rotates_nonce_but_retry_does_not(self):
    with self.client.session_transaction() as s:s['billing_nonce']='old';s['billing_product_context']='premium'
    self.client.get('/billing/workshop/'+self.token)
    with self.client.session_transaction() as s:new=s['billing_nonce']
    self.assertNotEqual(new,'old');self.client.get('/billing/workshop/'+self.token)
    with self.client.session_transaction() as s:self.assertEqual(new,s['billing_nonce'])

if __name__=='__main__':unittest.main()
