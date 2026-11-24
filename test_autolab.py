import unittest
from unittest.mock import patch
import numpy as np
import autolab

class AutonomousLabTests(unittest.TestCase):
    @staticmethod
    def candles(n=850):
        x=np.arange(n,dtype=float)
        c=100+0.015*x+0.5*np.sin(x/13)+0.12*np.cos(x/7)
        o=c+0.04*np.cos(x/9)
        h=np.maximum(c,o)+0.22
        l=np.minimum(c,o)-0.22
        vol=1000+120*np.sin(x/19)
        return np.column_stack((x*900000,o,h,l,c,vol)).tolist()

    def test_candidates_are_constrained(self):
        rows=self.candles()
        _,f,valid=autolab.indicators(rows)
        rng=np.random.default_rng(13)
        train=np.arange(66,440)
        for _ in range(100):
            c=autolab.new_candidate(rng,f,train)
            self.assertTrue(autolab.validate(c))
            m=autolab.mutate(c,rng,f,train)
            self.assertTrue(autolab.validate(m))
        self.assertFalse(autolab.validate({"side":1,"all":[{"feature":"__import__('os')","direction":1,"threshold":0}]}))
        self.assertFalse(autolab.validate({"side":1,"all":[]}))
        self.assertEqual(len(autolab.signals(c,f,valid)),len(rows))

    def test_future_bars_cannot_change_past_signal(self):
        rows=self.candles()
        a,f,valid=autolab.indicators(rows)
        c={"side":1,"all":[{"feature":"mom4","direction":1,"threshold":0}]}
        initial=autolab.signals(c,f,valid)[200]
        copy=np.asarray(rows,dtype=float)
        copy[250:,1:5]*=1.3
        _,f2,v2=autolab.indicators(copy.tolist())
        self.assertEqual(initial,autolab.signals(c,f2,v2)[200])

    def test_missing_candles_do_not_generate_signals(self):
        rows=self.candles()
        rows[100][0]+=1000
        _,f,valid=autolab.indicators(rows)
        c={"side":-1,"all":[{"feature":"mom4","direction":1,"threshold":0}]}
        self.assertEqual(0,int(autolab.signals(c,f,valid)[110]))

    def test_research_persists_and_no_order_access(self):
        saved={"candles:BTCUSDT":self.candles()}
        def get(key,default=None):return saved.get(key,default)
        def put(key,value):saved[key]=value
        with patch.object(autolab.store,"get",side_effect=get),patch.object(autolab.store,"put",side_effect=put):
            result=autolab.research("BTCUSDT")
            self.assertGreater(result["candidates"],20)
            self.assertEqual(result["generation"],1)
            self.assertEqual(result["selected"],"autolab")
            self.assertIn("validation",result)
            self.assertIn("holdout",result)
            self.assertEqual(saved["autolab:BTCUSDT"]["generation"],1)
            self.assertIn("champion:BTCUSDT",saved)
            self.assertTrue(saved["research_history"])
            result2=autolab.research("BTCUSDT")
            self.assertEqual(result2["generation"],2)

    def test_market_features_no_future_and_missing(self):
        rows=self.candles()
        t=int(rows[200][0])
        history=[{"bar":t,"observed":t+100,"funding":.001},{"bar":t+900000,"observed":t+1800000,"funding":.99}]
        _,f,valid=autolab.indicators(rows,history)
        self.assertAlmostEqual(f["funding"][200],.001)
        self.assertTrue(np.isnan(f["funding"][201]))
        self.assertTrue(np.isnan(f["funding"][199]))
        edited=np.asarray(rows,dtype=float)
        edited[250:,1:5]*=1.5
        _,g,_=autolab.indicators(edited.tolist(),history)
        for key in autolab.market_lab.TECH:
            np.testing.assert_allclose(f[key][:250],g[key][:250],equal_nan=True)
        candidate={"side":1,"all":[{"feature":"funding","direction":1,"threshold":0}]}
        self.assertEqual(autolab.signals(candidate,f,valid)[199],0)
        self.assertEqual(autolab.signals(candidate,f,valid)[200],1)

    def test_tick_flow_causal(self):
        import tick_flow
        tick_flow.selftest()
        rows=self.candles()
        t=int(rows[200][0])
        history=[{"bar":t,"observed":t+900000+15000,"complete":True,"flow_delta":.5,"delta":3,"volume":6}]
        _,f,_=autolab.indicators(rows,flow=history)
        self.assertTrue(np.isnan(f["flow_delta"][200]))
        self.assertEqual(f["flow_delta"][201],.5)
        history[0]["complete"]=False
        _,f,_=autolab.indicators(rows,flow=history)
        self.assertTrue(np.isnan(f["flow_delta"][201]))

    def test_triangle_accounts_for_fees_and_depth(self):
        def q(b,a,size=1000):return dict(bid1Price=b,ask1Price=a,bid1Size=size,ask1Size=size)
        quotes={"BTCUSDT":q(99,100),"ETHBTC":q(.49,.5),"ETHUSDT":q(51,52)}
        out=autolab.market_lab.triangle(quotes)
        route=next(r for r in out if r["path"]==["USDT","BTC","ETH","USDT"])
        self.assertAlmostEqual(route["net_estimate"],1.02*(1-.0015)**3-1)
        quotes["BTCUSDT"]=q(99,100,.001)
        self.assertFalse(any(r["path"]==["USDT","BTC","ETH","USDT"] for r in autolab.market_lab.triangle(quotes)))

if __name__ == "__main__":
    unittest.main()
