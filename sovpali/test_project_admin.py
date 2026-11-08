"""Admin boundaries; no Telegram or payment-provider network calls."""
import os
import unittest
from unittest.mock import patch, Mock
from flask import Flask
import project_admin

class AdminSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.secret_key='test-only'
        self.connection=Mock(side_effect=AssertionError('Unexpected database access'))
        with patch.object(project_admin.threading.Thread,'start'):
            project_admin.register(self.app,self.connection,'sovpali',console=True)
        self.client=self.app.test_client()
    def login(self):
        with self.client.session_transaction() as s:
            s['a']=1;s['project_admin_csrf']='csrf'
    def test_anonymous_cannot_read_or_send(self):
        self.assertEqual(self.client.get('/admin/projects').status_code,302)
        self.assertEqual(self.client.post('/admin/projects/api/sovpali/send',json={}).status_code,401)
    def test_csrf_rejects_write(self):
        self.login()
        self.assertEqual(self.client.post('/admin/projects/api/sovpali/send',json={}).status_code,403)
    def test_internal_secret_required(self):
        with patch.dict(os.environ,{'PROJECT_ADMIN_SECRET':'secret'}):
            self.assertEqual(self.client.post('/internal/project-admin/stats').status_code,403)
    def test_empty_secret_never_authenticates(self):
        with patch.dict(os.environ,{'PROJECT_ADMIN_SECRET':''}):
            self.assertEqual(self.client.post('/internal/project-admin/stats').status_code,403)
    def test_unknown_project_rejected(self):
        self.login()
        self.assertEqual(self.client.post('/admin/projects/api/other/stats',headers={'X-CSRF-Token':'csrf'},json={}).status_code,404)
    def test_invalid_filter_never_queries(self):
        self.login()
        for data in ({'days':-1},{'segment':"paid; DELETE FROM users"}):
            self.assertEqual(self.client.post('/admin/projects/api/sovpali/stats',headers={'X-CSRF-Token':'csrf'},json=data).status_code,400)
        self.connection.assert_not_called()
    def test_remote_token_is_server_only(self):
        self.login()
        with patch.dict(os.environ,{'PROJECT_ADMIN_SECRET':'secret'}),patch.object(project_admin.requests,'post') as post:
            post.return_value.status_code=200
            post.return_value.json.return_value={'project':'poehali'}
            r=self.client.post('/admin/projects/api/poehali/stats',headers={'X-CSRF-Token':'csrf'},json={})
            self.assertEqual(r.status_code,200)
            self.assertNotIn('secret',r.get_data(as_text=True))
            self.assertEqual(post.call_args.kwargs['headers']['X-Project-Admin'],'secret')
            self.assertEqual(r.headers['Cache-Control'],'no-store')
    def test_stages_are_readable_without_guessing_unknown_codes(self):
        self.assertEqual(project_admin.stage_label('welcome'),'Получил приветствие в боте')
        self.assertEqual(project_admin.stage_label('checkout_started'),'Начал оплату — ждём подтверждения')
        self.assertEqual(project_admin.stage_label('Анкета готова'),'Анкета готова')
        self.assertEqual(project_admin.stage_label('unknown_internal_code'),'Этап пока не определён')
    def test_actual_search_sql_keeps_empty_string_and_bound_parameters(self):
        import ast
        from pathlib import Path
        source=ast.parse(Path(project_admin.__file__).read_text())
        functions=[n for n in ast.walk(source) if isinstance(n,ast.FunctionDef)
                   and n.name in ('cte','filters','_stats')]
        captured=[]
        def query(sql,args=()):
            captured.append((sql,args))
            if 'SELECT COUNT(*) total' in sql: return [{'total':0}]
            if 'SELECT COALESCE(SUM(amount)' in sql: return [{'revenue':0}]
            if 'SELECT COUNT(*) n FROM people WHERE' in sql: return [{'n':0}]
            return []
        namespace=dict(vars(project_admin),query=query)
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<admin-test>','exec'),namespace)
        for project in ('sovpali','poehali'):
            namespace['project']=project
            for segment in project_admin.SEGMENTS:
                namespace['_stats']({'days':30,'segment':segment,'search':"@test_o'ne"})
        search_queries=[(q,a) for q,a in captured if 'ILIKE' in q]
        self.assertEqual(len(search_queries),16)
        for sql,args in search_queries:
            self.assertIn("COALESCE(username,'')",sql)
            self.assertEqual(sql.count('%s'),len(args))
            self.assertNotIn("test_o'ne",sql)

    def test_existing_payment_routes_untouched(self):
        rules=[str(r) for r in self.app.url_map.iter_rules()]
        self.assertFalse(any('checkout' in r or 'payment' in r for r in rules))
    def test_template_and_home(self):
        self.login()
        self.assertEqual(self.client.get('/admin').location,'/admin/projects')
        r=self.client.get('/admin/projects')
        self.assertEqual(r.status_code,200)
        self.assertIn('Совпали',r.get_data(as_text=True))
        self.assertIn('Поехали',r.get_data(as_text=True))

if __name__=='__main__':unittest.main()
