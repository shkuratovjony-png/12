import json,sqlite3,time,hmac,hashlib,unittest
from contextlib import contextmanager
from urllib.parse import urlencode
from flask import Flask
from pair_cabinet import register_cabinet,enrich_pair

TOKEN='not-a-real-token'
def headers(uid=101):
    d={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid})}
    key=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
    d['hash']=hmac.new(key,'\n'.join(f'{k}={d[k]}' for k in sorted(d)).encode(),hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data':urlencode(d)}

class CabinetTest(unittest.TestCase):
 def setUp(self):
    self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
    self.c.executescript('''
      CREATE TABLE users(id INT,tg_id INT,is_banned INT,username TEXT);
      CREATE TABLE profiles(user_id INT,name TEXT,gender TEXT,looking_for TEXT,birth_date TEXT,birth_place TEXT,city TEXT,goal TEXT,priority TEXT,photo_file_id TEXT);
      CREATE TABLE match_pushes(recipient_user_id INT,candidate_user_id INT,status TEXT,sent_at TEXT);
      CREATE TABLE match_push_views(viewer_user_id INT,candidate_user_id INT,viewed_at TEXT);
      CREATE TABLE communication_requests(id INT,requester_user_id INT,target_user_id INT,status TEXT,created_at TEXT);
      CREATE TABLE communication_request_deliveries(request_id INT);
      CREATE TABLE match_offers(recipient_user_id INT,subject_user_id INT,status TEXT,offered_at TEXT);
      CREATE TABLE web_purchase_bindings(billing_order_id TEXT,buyer_user_id INT,target_user_id INT,sku TEXT,binding_status TEXT);
      CREATE TABLE billing_web_orders(order_id TEXT,status TEXT,created_at TEXT,amount_kopecks INT);
      CREATE TABLE web_premium_memberships(user_id INT,active_until TEXT);
      CREATE TABLE web_intro_credits(buyer_user_id INT,redeemed_for_order TEXT);
      INSERT INTO users VALUES(1,101,0,'viewer'),(2,102,0,'candidate'),(3,103,0,'other');
      INSERT INTO match_pushes VALUES(1,2,'sent','2026-01-01');
      INSERT INTO web_purchase_bindings VALUES('mine',1,2,'contact','delivered'),('other',2,1,'premium','delivered');
      INSERT INTO billing_web_orders VALUES('mine','paid','2026-01-01',10000),('other','paid','2026-01-02',120000);
    ''')
    for uid in (1,2,3):self.c.execute('INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,'Имя'+str(uid),'Мужчина','Женщина','01.01.1990','Город','Владивосток','Серьёзные отношения','Семья',None))
    @contextmanager
    def db():yield self.c
    def one(sql,args=()):return self.c.execute(sql,args).fetchone()
    def many(sql,args=()):return self.c.execute(sql,args).fetchall()
    self.views=[];self.saves=[]
    self.ns={'FLASK_SECRET':'test-secret','TOKEN':TOKEN,'db':db,'one':one,'many':many,
      'user':lambda uid:one('SELECT * FROM users WHERE id=?',(uid,)),
      'profile':lambda uid:one('SELECT * FROM profiles WHERE user_id=?',(uid,)),
      'eligible':lambda a,b:True,'score':lambda a,b:87,'reasons':lambda a,b:['общая цель'],
      'mp_candidates':lambda uid,n,excluded=None:[(87,one('SELECT * FROM profiles WHERE user_id=2'))] if uid==1 and 2 not in (excluded or set()) else [],
      'cr_between':lambda a,b:one('SELECT * FROM communication_requests WHERE (requester_user_id=? AND target_user_id=?) OR (requester_user_id=? AND target_user_id=?)',(a,b,b,a)),
      'web_premium_active':lambda uid:False,'web_contact_live':lambda:False,'web_contact_credit_available':lambda uid:False,
      'mp_record_view':lambda a,b:self.views.append((a,b)), 'ar_contact_url':lambda uid:'https://t.me/candidate',
      'save_profile':lambda uid,data:self.saves.append((uid,data))}
    self.app=Flask(__name__);register_cabinet(self.app,self.ns,lambda data:json.dumps(data));self.client=self.app.test_client()
 def tearDown(self):self.c.close()
 def test_auth_and_no_private_shell(self):
    self.assertEqual(self.client.post('/s/app/api/cabinet').status_code,401)
    self.assertEqual(self.client.post('/s/app/api/cabinet',headers=headers(999)).status_code,403)
    r=self.client.get('/s/app');self.assertNotIn('viewer',r.text)
 def test_scoped_history_purchases_and_no_view_side_effect(self):
    r=self.client.post('/s/app/api/cabinet',headers=headers());self.assertEqual(r.status_code,200)
    self.assertEqual([x['id'] for x in r.json['history']],[2]);self.assertEqual(len(r.json['purchases']),1)
    self.assertEqual(r.json['purchases'][0]['amount_kopecks'],10000);self.assertEqual(self.views,[])
    reverse=self.client.post('/s/app/api/cabinet',headers=headers(102));self.assertEqual(reverse.json['history'],[])
 def test_arbitrary_candidate_and_reverse_direction_blocked(self):
    self.assertEqual(self.client.post('/s/app/api/pair',json={'candidate_id':3},headers=headers()).status_code,404)
    class Engine:
      def pair_owner(self,a,b):return 2
    self.ns['MATCH_PUSH_ENGINE']=Engine()
    self.assertEqual(self.client.post('/s/app/api/pair',json={'candidate_id':2},headers=headers()).status_code,404)
    self.assertEqual(self.client.post('/s/app/api/cabinet',headers=headers()).json['suggestions'],[])
 def test_real_pair_reuses_score_and_records_only_explicit_open(self):
    r=self.client.post('/s/app/api/pair',json={'candidate_id':2},headers=headers())
    self.assertEqual(r.status_code,200);self.assertEqual(r.json['score'],87);self.assertEqual(self.views,[(1,2)])
    self.assertIsNone(r.json['contact_url']);self.assertNotIn('username',r.json['candidate'])
 def test_contact_initiator_only(self):
    self.c.execute("INSERT INTO communication_requests VALUES(1,1,2,'accepted','2026-01-01')")
    a=enrich_pair({'request_status':'accepted'},self.ns,1,2);b=enrich_pair({'request_status':'accepted'},self.ns,2,1)
    self.assertEqual(a['contact_url'],'https://t.me/candidate');self.assertIsNone(b['contact_url'])
    self.assertEqual(b['request_status'],'accepted_target')
 def test_paid_sending_is_not_offered_for_payment_again(self):
    self.c.execute("UPDATE web_purchase_bindings SET binding_status='sending' WHERE billing_order_id='mine'")
    data=enrich_pair({'request_status':'ready'},self.ns,1,2)
    self.assertEqual(data['request_status'],'processing')
 def test_manual_skip_is_scoped_and_does_not_send_or_bill(self):
    self.assertEqual(self.client.post('/s/app/api/browse/skip',json={'candidate_id':2}).status_code,401)
    self.assertEqual(self.client.post('/s/app/api/browse/skip',json={'candidate_id':3},headers=headers()).status_code,404)
    before=self.client.post('/s/app/api/cabinet',headers=headers()).json
    self.assertEqual([x['id'] for x in before['suggestions']],[2])
    skipped=self.client.post('/s/app/api/browse/skip',json={'candidate_id':2},headers=headers())
    self.assertEqual(skipped.status_code,200,skipped.json)
    after=self.client.post('/s/app/api/cabinet',headers=headers()).json
    self.assertEqual(after['suggestions'],[])
    self.assertEqual(after['history'],[],"Skipped unrequested history must not reappear in My Pairs")
    self.assertEqual(self.views,[],"Skip must not be recorded as pair opened")
    self.assertEqual(self.c.execute('SELECT COUNT(*) FROM billing_web_orders').fetchone()[0],2)
    self.assertEqual(self.c.execute('SELECT COUNT(*) FROM communication_requests').fetchone()[0],0)
    self.assertEqual(self.client.post('/s/app/api/cabinet',headers=headers(102)).json['suggestions'],[])
    self.assertEqual(self.c.execute('SELECT COUNT(*) FROM cabinet_skipped_candidates').fetchone()[0],1)
 def test_skip_rejects_active_introduction(self):
    self.c.execute("INSERT INTO communication_requests VALUES(99,1,2,'pending','2026-01-01')")
    self.assertEqual(self.client.post('/s/app/api/browse/skip',
      json={'candidate_id':2},headers=headers()).status_code,409)
    self.assertEqual(self.c.execute('SELECT COUNT(*) FROM cabinet_skipped_candidates').fetchone()[0],0)
 def test_profile_uses_existing_save_and_cannot_change_owner_or_gender(self):
    form={'name':'Новое имя','birth_date':'05.01.1990','birth_place':'Город','city':'Артём','goal':'Любовь и семья','priority':'Любовь'}
    r=self.client.post('/s/app/api/profile',json={**form,'user_id':2},headers=headers());self.assertEqual(r.status_code,400)
    r=self.client.post('/s/app/api/profile',json={**form,'birth_date':'01.01.2020'},headers=headers());self.assertEqual(r.status_code,400)
    r=self.client.post('/s/app/api/profile',json=form,headers=headers());self.assertEqual(r.status_code,200)
    self.assertEqual(self.saves[0][0],1);self.assertEqual(self.saves[0][1]['gender'],'Мужчина');self.assertIn('photo',self.saves[0][1])
    self.assertEqual(self.views,[])

if __name__=='__main__':unittest.main()
