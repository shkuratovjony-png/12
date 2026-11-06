import os
import unittest
from unittest.mock import patch, MagicMock

from flask import Flask
import funnel


class FunnelSafetyTests(unittest.TestCase):
    def test_content_has_four_steps_per_course(self):
        self.assertIn("poehali", funnel.PRODUCTS)
        self.assertEqual(len(funnel.PRODUCTS["poehali"]["series"]), 4)
        self.assertEqual(len(funnel.DELAYS), 4)

    def test_welcome_is_free_and_optin_is_explicit(self):
        lead={"chat_id":12345, "product":"poehali", "ref":"x"*43,
              "purchased":False,"opted_in":False}
        message=funnel._welcome(lead)
        self.assertIn("бесплатная схема",message)
        buttons=funnel._buttons(lead,include_optin=True) if funnel._ROOT else None
        with patch.object(funnel,"_ROOT","https://poehali-checkout.onrender.com"):
            buttons=funnel._buttons(lead,include_optin=True)
        self.assertTrue(any("on:poehali" in str(row) for row in buttons))
        self.assertTrue(any("funnel=" in str(row) for row in buttons))
        self.assertTrue(any("?ft=" in str(row) for row in buttons))

    def test_unguessable_reference_required(self):
        with patch.object(funnel,"_INITIALIZED",True),patch.object(funnel,"_sql") as query:
            self.assertIsNone(funnel.lead_for_ref("short"))
            self.assertIsNone(funnel.lead_for_ref("<malicious>"))
            query.assert_not_called()

    def test_paid_order_stops_one_product_without_notifications(self):
        lead={"ref":"z"*43,"chat_id":12345,"product":"poehali"}
        with patch("funnel.lead_for_ref",return_value=lead),patch("funnel._sql",side_effect=[{"ref":"z"*43},None]) as query,patch("funnel._send") as outgoing:
            funnel.mark_paid({"funnel_ref":"z"*43})
            self.assertEqual(query.call_count,2)
            self.assertIn("WHERE ref=%s AND NOT purchased",query.call_args_list[0].args[0])
            outgoing.assert_not_called()

    def test_preview_steps_do_not_change_subscriptions(self):
        with patch("funnel._send") as sender,patch("funnel._sql") as query:
            funnel._preview(123,"poehali",0)
            text,buttons=sender.call_args.args[1:]
            self.assertIn("Предпросмотр сообщения 1/4",text)
            self.assertIn("preview:poehali:1",str(buttons))
            funnel._callback(123,{"data":"preview:poehali:3"})
            self.assertIn("Предпросмотр сообщения 4/4",sender.call_args.args[1])
            self.assertIsNone(sender.call_args.args[2])
            self.assertEqual(sender.call_count,2)
            query.assert_not_called()

    def test_no_paid_mark_without_attribution(self):
        with patch("funnel._sql") as query:
            funnel.mark_paid({"id":"ordered-no-bot"})
            query.assert_not_called()

    def test_paid_lead_is_suppressed_by_dispatch(self):
        lead={"ref":"z"*43,"chat_id":12345,"product":"poehali",
              "step":0,"stage":"landing"}
        with patch.dict(os.environ,{"TG_FUNNEL_BOT_TOKEN":"fake-token"}),\
             patch.object(funnel,"_INITIALIZED",True),\
             patch("funnel._claim_due",return_value=[lead]),\
             patch("funnel._sql",return_value={"id":"paid"}),\
             patch("funnel.mark_paid") as mark,\
             patch("funnel._send") as send:
            result=funnel.dispatch()
        self.assertEqual(result["sent"],0)
        self.assertEqual(result["suppressed"],1)
        mark.assert_called_once()
        send.assert_not_called()

    def test_stop_is_scoped_to_the_lead_product(self):
        with patch("funnel._sql") as query:
            funnel._stop(123,"poehali")
            self.assertEqual(query.call_count,1)
            self.assertIn("AND product=%s",query.call_args.args[0])
            self.assertEqual(query.call_args.args[1],(123,"poehali"))

    def test_telegram_webhook_cannot_be_called_without_bot_token(self):
        from app import app
        with patch.dict(os.environ,{"TG_FUNNEL_BOT_TOKEN":""}):
            response=app.test_client().post("/funnel/telegram/webhook",
                json={"update_id":1,"message":{"text":"/start poehali"}})
        self.assertEqual(response.status_code,503)

    def test_worker_without_github_oidc_cannot_send(self):
        from app import app
        with patch("funnel.dispatch") as worker:
            result=app.test_client().post("/funnel/dispatch")
        self.assertEqual(result.status_code,403)
        worker.assert_not_called()


if __name__=="__main__":
    unittest.main()
