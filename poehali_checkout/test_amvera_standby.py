"""Side-effect boundaries for the independent Amvera preview."""
import os
import unittest
from unittest.mock import patch, Mock
from werkzeug.test import Client
from werkzeug.wrappers import Response
from preview_gate import StandbyGate

class StandbyTests(unittest.TestCase):
    def test_gateway_blocks_integrations_before_application(self):
        downstream = Mock(return_value=[])
        client = Client(StandbyGate(downstream, 'preview', 'p' * 32), Response)
        for path in ('/ozon/notify', '/funnel/telegram/webhook', '/internal/project-admin/send'):
            self.assertEqual(client.post(path).status_code, 503)
        self.assertEqual(client.get('/checkout').status_code, 401)
        self.assertEqual(client.post('/checkout', auth=('preview','p'*32)).status_code,503)
        downstream.assert_not_called()

    def test_direct_bank_telegram_email_calls_blocked_with_live_flags(self):
        with patch.dict(os.environ, {'POEHALI_RUNTIME_MODE':'standby','OZON_PAY_MODE':'live'}):
            with patch('threading.Thread.start') as threads:
                import app
                import funnel
                threads.assert_not_called()
            with patch('requests.post') as network, patch('smtplib.SMTP') as smtp:
                with self.assertRaises(RuntimeError):app.call('/api', {})
                with self.assertRaises(RuntimeError):funnel._tg('sendMessage', {})
                self.assertFalse(app.email_access({'id':'a'*32}))
                network.assert_not_called()
                smtp.assert_not_called()

if __name__ == '__main__': unittest.main()
