import os
import unittest
from unittest.mock import patch

from app import app, hosted, check

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
            self.assertNotIn('900 ₽ подтверждена'.encode('utf-8'),response.data)

    def test_forged_return_without_order_is_rejected(self):
        self.assertEqual(self.client.get('/result?order=invalid').status_code,404)
    def test_cannot_approve_without_bank_credentials(self):
        order={'state':'pending','id':'0'*32,'provider_payment_id':'','orderext':'','extid':'poehali-'+'0'*32}
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(check(order))

if __name__=='__main__':
    unittest.main()
