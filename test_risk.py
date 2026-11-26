import bybit_demo,spot_demo,market,paper_exec,sir_live,sir_paper,breakout_paper,sergey_paper
import unittest
import risk
class RiskTests(unittest.TestCase):
    def test_initial(self):
        s=risk.initial()
        self.assertTrue(risk.entry_allowed(s))
        self.assertTrue(risk.entry(s,"BTCUSDT",1,99.9,100,"test"))
        self.assertFalse(risk.entry_allowed(s))
        risk.mark(s,99,99.1)
        self.assertIsNone(s["position"])
        self.assertLess(s["balance"],1000)
        self.assertEqual(len(s["trades"]),1)
    def test_halt(self):
        s=risk.initial();s["equity"]=840
        self.assertFalse(risk.entry_allowed(s))
        self.assertTrue(s["halted"])
    def test_daily(self):
        s=risk.initial();s["equity"]=969
        self.assertFalse(risk.entry_allowed(s))
class CleanBaseTests(unittest.TestCase):
    def test_demo_disabled(self):
        self.assertFalse(bybit_demo.NEW_ENTRIES_ENABLED)
        self.assertEqual(bybit_demo.HOST,"https://api-demo.bybit.com")
    def test_spot_disabled(self):
        def denied(*a,**kw):raise AssertionError("unexpected request")
        s={"managed":{}}
        r=spot_demo.tick(s,denied,denied,0,False,1000,1000,0,allow_entry=False)
        self.assertEqual(r["submitted"],0)
    def test_paper_sir(self):
        sir_paper.selftest()
    def test_breakout(self):
        breakout_paper.selftest()
    def test_sergey(self):
        sergey_paper.selftest()
    def test_sir(self):
        sir_live.selftest()
    def test_foundation(self):
        paper_exec.selftest()
        spot_demo.selftest()
        market.feed_selftest()
        for cat in ("linear","spot"):
            self.assertFalse(any(t.startswith("publicTrade.") for t in market._topics(cat)))
if __name__=="__main__":unittest.main()
