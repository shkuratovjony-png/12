import os
import unittest
from unittest.mock import patch

from app import app, hosted, check, PRICE

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

    def test_unlisted_buyer_cannot_open_test_payment(self):
        with patch('app.ready',return_value=True), patch('app.DB_OK',True), patch.dict(os.environ, {'POEHALI_TEST_BUYER_EMAIL':'owner@example.ru'}):
            with self.client.session_transaction() as sess:
                sess['csrf']='session-csrf'
                sess['nonce']='some_nonce'
            response=self.client.post('/checkout',data={'csrf':'session-csrf','email':'other@example.ru','method':'sbp','agree':'yes'})
            self.assertEqual(response.status_code,403)

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
