from test_autolab import AutonomousLabTests
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
if __name__=="__main__":unittest.main()
