import os
import re
import html
import unittest
from unittest.mock import patch

from app import app, hosted, check, PRICE, signed_result

class PaymentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()
    def test_health_not_live_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            data=self.client.get('/health').json
            self.assertFalse(data['checkout_ready'])
    def test_checkout_disabled_cannot_charge(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.client.get('/checkout').status_code,200)
            self.assertEqual(self.client.post('/checkout',data={'email':'a@b.ru','method':'card'}).status_code,503)
    def test_private_course_denies_unauthenticated(self):
        self.assertEqual(self.client.get('/course').status_code,303)
    def test_bank_checkout_host_restrictions(self):
        self.assertTrue(hosted('https://merchant.ozon.ru/pay/example'))
        self.assertFalse(hosted('http://merchant.ozon.ru/pay/example'))
        self.assertFalse(hosted('https://evil-ozon.ru/pay/example'))
        self.assertFalse(hosted('https://ozon.ru.evil.com/pay/example'))
    def test_bank_token_return_urls_exist_before_checkout(self):
        # Public Ozon token setup links may be opened manually with no order.
        for path in ('/result', '/result/success', '/result/fail'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertIn('Перейти к оформлению'.encode('utf-8'),response.data)
            self.assertNotIn('1 ₽ подтверждена'.encode('utf-8'),response.data)

    def test_forged_return_without_order_is_rejected(self):
        self.assertEqual(self.client.get('/result?order=invalid').status_code,404)
    def test_cannot_approve_without_bank_credentials(self):
        order={'state':'pending','id':'0'*32,'provider_payment_id':'','orderext':'','extid':'poehali-'+'0'*32}
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(check(order))


    def test_test_price_and_clear_payment_choices(self):
        response=self.client.get('/checkout')
        self.assertEqual(response.status_code,200)
        self.assertEqual(PRICE,100)
        self.assertIn('Тестовая цена 1 ₽'.encode('utf-8'),response.data)
        self.assertIn('name="method" value="sbp"'.encode(),response.data)
        self.assertIn('name="method" value="card"'.encode(),response.data)
        self.assertIn('Банковская карта'.encode('utf-8'),response.data)

    def _get_form_tokens(self, client):
        body=client.get('/checkout').get_data(as_text=True)
        csrf=re.search(r'name="csrf" value="([^"]+)"',body)
        signed=re.search(r'name="form_token" value="([^"]+)"',body)
        self.assertIsNotNone(csrf)
        self.assertIsNotNone(signed)
        return html.unescape(csrf.group(1)), html.unescape(signed.group(1))

    def test_unlisted_buyer_cannot_open_test_payment(self):
        with patch('app.ready',return_value=True), patch('app.DB_OK',True), patch.dict(os.environ, {'POEHALI_TEST_BUYER_EMAIL':'owner@example.ru'}):
            csrf,token=self._get_form_tokens(self.client)
            response=self.client.post('/checkout',data={'form_token':token,'csrf':csrf,'email':'other@example.ru','method':'sbp','agree':'yes','consent':'yes'})
            self.assertEqual(response.status_code,403)
            self.assertIn('email'.encode(),response.data)

    def test_mobile_checkout_without_browser_cookies_can_open_ozon(self):
        with patch('app.ready',return_value=True),patch('app.DB_OK',True),patch.dict(os.environ, {'POEHALI_TEST_BUYER_EMAIL':'owner@example.ru'}),patch('app.db',return_value=None) as query,patch('app.bank_create',return_value=('https://pay.ozon.ru/test123','pid','oid')):
            csrf,token=self._get_form_tokens(self.client)
            second_client=app.test_client()  # Simulate Telegram iOS dropping all session cookies.
            response=second_client.post('/checkout',data={'form_token':token,'csrf':csrf,'email':'owner@example.ru','method':'card','agree':'yes','consent':'yes'},headers={'Origin':'null'})
            self.assertEqual(response.status_code,303,response.get_data(as_text=True))
            self.assertEqual(response.headers['Location'],'https://pay.ozon.ru/test123')
            self.assertTrue(query.called)

    def test_invalid_signed_form_is_rejected_without_bank_request(self):
        with patch('app.ready',return_value=True),patch('app.DB_OK',True),patch('app.bank_create') as bank:
            response=self.client.post('/checkout',data={'form_token':'forged','csrf':'csrf','email':'owner@example.ru','method':'sbp','agree':'yes','consent':'yes'})
            self.assertEqual(response.status_code,403)
            bank.assert_not_called()

    def test_all_legal_pages_visible(self):
        for path in ('/terms','/privacy','/consent','/refund','/cookies','/contacts'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertIn('651000911363'.encode(),response.data)
            self.assertIn('e.m.shkuratov@ya.ru'.encode(),response.data)

    def test_separate_consent_and_offer_in_checkout(self):
        with patch('app.ready',return_value=True):
            response=self.client.get('/checkout')
        self.assertIn('name="agree"'.encode(),response.data)
        self.assertIn('name="consent"'.encode(),response.data)
        self.assertIn('href="/consent"'.encode(),response.data)

    def test_purchase_needs_separate_consent(self):
        with patch('app.ready',return_value=True),patch('app.DB_OK',True):
            csrf,token=self._get_form_tokens(self.client)
            response=self.client.post('/checkout',data={'form_token':token,'csrf':csrf,'email':'owner@example.ru','method':'sbp','agree':'yes'})
            self.assertEqual(response.status_code,400)

    def test_signed_bank_return_works_without_cookie(self):
        order={'id':'0'*32,'nonce':'a'*40,'state':'pending'}
        proof=signed_result(order)
        with patch('app.DB_OK',True),patch('app.get',return_value=order),patch('app.check',return_value=False):
            fresh=app.test_client()
            response=fresh.get('/result/success?order='+order['id']+'&proof='+proof)
            self.assertEqual(response.status_code,200)
            self.assertIn('Проверяем оплату'.encode('utf-8'),response.data)

    def test_wrong_sum_never_approves_payment(self):
        order={'state':'pending','id':'0'*32,'amount':100,
               'paymentid':None,'orderext':'poehali-order-'+'0'*32,
               'extid':'poehali-'+'0'*32}
        fake={'items':[{'status':'COMPLETED','amount':{'value':'90000','currencyCode':'643'}}]}
        with patch('app.flags',return_value={'bank':True}), patch('app.call',return_value=fake), patch('app.sign',return_value='signature'), patch('app.db') as query:
            self.assertFalse(check(order))
            query.assert_not_called()

    def test_exact_order_amount_is_required(self):
        order={'state':'pending','id':'0'*32,'amount':100,
               'paymentid':None,'orderext':'poehali-order-'+'0'*32,
               'extid':'poehali-'+'0'*32}
        fake={'items':[{'status':'COMPLETED','amount':{'value':'100','currencyCode':'643'}}]}
        with patch('app.flags',return_value={'bank':True}), patch('app.call',return_value=fake), patch('app.sign',return_value='signature'), patch('app.db') as query:
            self.assertTrue(check(order))
            self.assertTrue(query.called)

if __name__=='__main__':
    unittest.main()
