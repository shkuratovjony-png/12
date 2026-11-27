import bybit_demo,spot_demo,market,paper_exec,sir_live,sir_paper,breakout_paper,sergey_paper,paper_feed
import short1042
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
    def test_short1042(self):
        short1042.selftest()
    def test_shared_feed(self):
        paper_feed.selftest()
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
class AdaptiveResearchTests(unittest.TestCase):
    def test_exit_direction_and_stop_first(self):
        import pandas as pd
        import impulse_adaptive as a
        ix=pd.date_range(a.START,periods=13,freq="5min")
        for side in (1,-1):
            bars=pd.DataFrame({"open":100.,"high":100.,"low":100.,"close":100.},index=ix)
            bars.iloc[0,bars.columns.get_loc("high")]=102.1 if side==1 else 100.5
            bars.iloc[0,bars.columns.get_loc("low")]=99.5 if side==1 else 97.9
            sig=[(0,side,100.,100.-side,1.,2.,True,True)]
            e=a.exits("TESTUSDT",bars,sig,{},hold=12)
            self.assertEqual(len(e),1)
            self.assertGreater(e[0][6],0)
            bars.iloc[0,bars.columns.get_loc("high")]=103.
            bars.iloc[0,bars.columns.get_loc("low")]=97.
            self.assertLess(a.exits("TESTUSDT",bars,sig,{},hold=12)[0][6],0)
    def test_regime_switch(self):
        import pandas as pd
        import impulse_adaptive as a
        ix=pd.date_range(a.START,periods=13,freq="5min")
        bars=pd.DataFrame({"open":100.,"high":100.,"low":100.,"close":100.},index=ix)
        sig=[(0,-1,100.,101.,1.,2.,False,True)]
        self.assertEqual(a.exits("TESTUSDT",bars,sig,{}),[])
        self.assertEqual(len(a.exits("TESTUSDT",bars,sig,{},aligned="switch")),1)
class DailyRiskTests(unittest.TestCase):
    def test_daily_budget_and_parity(self):
        import impulse_daily_risk as dr
        import impulse_research as old
        t=1440*20000
        events=[[t+2*i,0.,'TEST'+str(i),t+2*i+1,100.,1.,-1.,.12,0.] for i in range(6)]
        base=dr.replay(events)
        self.assertLessEqual(abs(base["balance"]-old.simulate(events)["balance"]),.011)
        self.assertEqual(base["trades"],6)
        soft=dr.replay(events,"soft")
        self.assertGreater(soft["balance"],base["balance"])
        self.assertEqual(soft["trades"],6)
        limited=dr.replay(events,"budget")
        self.assertGreaterEqual(limited["balance"],985.-.001)
    def test_daily_reset(self):
        import impulse_daily_risk as dr
        t=1440*20000
        events=[[t+2*i,0.,'TEST'+str(i),t+2*i+1,100.,1.,-1.,.12,0.] for i in range(6)]
        events.append([t+1440,0.,'NEXT',t+1441,100.,1.,2.,.12,0.])
        d=dr.replay(events,"budget")
        self.assertEqual(d["days"],2)
        self.assertEqual(d["positive_days"],1)
        self.assertEqual(d["negative_days"],1)
class HoldoutTests(unittest.TestCase):
    def test_frozen_configuration(self):
        import impulse_adaptive as a, impulse_holdout as h, impulse_daily_risk as dr
        self.assertEqual((h.END-h.START).days,31)
        self.assertEqual(a.VARIANTS[h.MODEL],(6,2,1,"switch"))
        self.assertEqual(dr.POLICIES["profit_lock"],(True,.015,(.0075,.005)))
        self.assertEqual(len(h.report({"events":[]})["daily"]),31)
    def test_funding_pages(self):
        from unittest.mock import patch
        import impulse_holdout as h
        lo=int(h.START.timestamp()*1000)
        stamps=[lo+i*3600000 for i in range(401)]
        def mock(path,**kw):
            xs=[t for t in stamps if kw["startTime"]<=t<=kw["endTime"]][-kw["limit"]:]
            return {"list":[{"fundingRateTimestamp":str(t),"fundingRate":"0.0001"} for t in reversed(xs)]}
        with patch.object(h.a,"get",side_effect=mock):
            self.assertEqual(len(h.funding("TESTUSDT")),401)
if __name__=="__main__":unittest.main()
