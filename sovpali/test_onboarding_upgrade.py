"""Mini App registration flow smoke test. Uses isolated SQLite; no Telegram or bank calls."""
import json,sqlite3,time,hmac,hashlib,unittest,io
from unittest.mock import patch
from PIL import Image
from contextlib import contextmanager
from urllib.parse import urlencode
from flask import Flask
from onboarding_upgrade import attach

TOKEN="not-live-token"
class Tests(unittest.TestCase):
 def setUp(self):
  self.conn=sqlite3.connect(":memory:")
  self.conn.row_factory=sqlite3.Row
  self.conn.executescript("""
  CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,is_banned INTEGER,first_name TEXT);
  CREATE TABLE profiles(user_id INTEGER PRIMARY KEY,name TEXT,gender TEXT,birth_date TEXT,birth_place TEXT,city TEXT,goal TEXT,priority TEXT,photo_file_id TEXT);
  INSERT INTO users VALUES(1,901,0,'Тест');
  """)
  @contextmanager
  def db():
   yield self.conn
   self.conn.commit()
  def one(query,args=()):
   return self.conn.execute(query,args).fetchone()
  def execute(query,args=()):
   self.conn.execute(query,args);self.conn.commit()
  def save(uid,data):
   self.conn.execute("INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?)",(uid,data["name"],data["gender"],data["birth_date"],data["birth_place"],data["city"],data["goal"],data["priority"],data.get("photo")))
   self.conn.commit()
  def profile(uid):return one("SELECT * FROM profiles WHERE user_id=?",(uid,))
  self.app=Flask(__name__)
  attach(self.app,{"TOKEN":TOKEN,"one":one,"execute":execute,"db":db,"profile":profile,"save_profile":save})
  self.client=self.app.test_client()
 def tearDown(self):self.conn.close()
 def headers(self):
  d={"auth_date":str(int(time.time())),"user":json.dumps({"id":901})}
  secret=hmac.new(b"WebAppData",TOKEN.encode(),hashlib.sha256).digest()
  d["hash"]=hmac.new(secret,"\n".join(f"{k}={d[k]}" for k in sorted(d)).encode(),hashlib.sha256).hexdigest()
  return {"X-Telegram-Init-Data":urlencode(d)}
 def test_onboard_and_extra(self):
  self.assertEqual(self.client.post("/s/app/api/onboarding").status_code,401)
  headers=self.headers()
  r=self.client.post("/s/app/api/onboarding",headers=headers)
  self.assertEqual(r.status_code,200)
  self.assertFalse(r.json["completed"])
  data={"name":"Тест","gender":"Мужчина","birth_date":"05.01.1990","birth_place":"Москва","birth_time":"04:30","city":"Самара","goal":"Серьёзные отношения","priority":"Ценности","lifestyle":"Баланс","relationship_style":"Спокойный диалог","family_plan":"Хочу семью и детей"}
  self.assertEqual(self.client.post("/s/app/api/onboarding/save",json=data,headers=headers).status_code,200)
  r=self.client.post("/s/app/api/onboarding/finish",json=data,headers=headers)
  self.assertEqual(r.status_code,200,r.json)
  self.assertTrue(r.json["completed"])
  self.assertEqual(self.client.post("/s/app/api/onboarding",headers=headers).json["completed"],True)
  r=self.client.post("/s/app/api/natal-extra",headers=headers)
  self.assertEqual(r.json["values"]["birth_time"],"04:30")
  update={"birth_time":"05:20","lifestyle":"Активный","relationship_style":"Нужно время","family_plan":"Пока не решил"}
  self.assertEqual(self.client.post("/s/app/api/natal-extra",json=update,headers=headers).status_code,200)
  self.assertEqual(self.client.post("/s/app/api/natal-extra",headers=headers).json["values"]["birth_time"],"05:20")
 def full_form(self,choice):
  return {"name":"Тест","gender":"Мужчина","birth_date":"05.01.1990","birth_place":"Москва","birth_time":"04:30","city":"Самара","goal":"Серьёзные отношения","priority":"Ценности","lifestyle":"Баланс","relationship_style":"Спокойный диалог","family_plan":"Хочу семью и детей","photo_choice":choice}
 def test_optional_uploaded_photo_and_delete(self):
  headers=self.headers()
  from photo_media import LOCAL_MARKER,get_local
  self.assertEqual(self.client.post("/s/app/api/photo/upload").status_code,401)
  test_img=io.BytesIO();Image.new("RGB",(150,150),(230,100,124)).save(test_img,format="PNG")
  test_img.seek(0)
  response=self.client.post("/s/app/api/photo/upload",data={"photo":(test_img,"portrait.png")},headers=headers)
  self.assertEqual(response.status_code,200,response.get_json())
  body=self.client.post("/s/app/api/onboarding/finish",json=self.full_form("local"),headers=headers)
  self.assertEqual(body.status_code,200,body.json)
  self.assertEqual(self.conn.execute("SELECT photo_file_id FROM profiles WHERE user_id=1").fetchone()[0],LOCAL_MARKER)
  image=self.conn.execute("SELECT image_bytes FROM profile_photo_uploads WHERE user_id=1").fetchone()[0]
  self.assertTrue(bytes(image).startswith(b"\\xff\\xd8"))
  deleted=self.client.post("/s/app/api/photo/choose",json={"choice":"skip"},headers=headers)
  self.assertEqual(deleted.status_code,200,deleted.json)
  self.assertIsNone(self.conn.execute("SELECT photo_file_id FROM profiles WHERE user_id=1").fetchone()[0])
 def test_telegram_avatar_option_and_skip(self):
  headers=self.headers()
  with patch("onboarding_upgrade.telegram_photo_id",return_value="telegram-file-id"):
   answer=self.client.post("/s/app/api/onboarding/finish",json=self.full_form("telegram"),headers=headers)
  self.assertEqual(answer.status_code,200,answer.json)
  self.assertEqual(self.conn.execute("SELECT photo_file_id FROM profiles WHERE user_id=1").fetchone()[0],"telegram-file-id")
 def test_no_photo_is_optional(self):
  headers=self.headers()
  answer=self.client.post("/s/app/api/onboarding/finish",json=self.full_form("skip"),headers=headers)
  self.assertEqual(answer.status_code,200,answer.json)
  self.assertIsNone(self.conn.execute("SELECT photo_file_id FROM profiles WHERE user_id=1").fetchone()[0])
if __name__=="__main__":
 unittest.main()
