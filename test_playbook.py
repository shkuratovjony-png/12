import unittest
import numpy as np
from market import rank_tickers
from playbook import candidates,signals
class StrategyTests(unittest.TestCase):
    def setUp(self):
        times=np.arange(150,dtype=float)*900000
        price=100+.01*np.arange(150,dtype=float)
        self.rows=np.column_stack([times,price,price+.5,price-.5,price,np.ones(150)*500])
    def test_no_future_data(self):
        for p in candidates():
            indexes=np.array([55,65,90,125])
            original=signals(self.rows,indexes,p)
            changed=self.rows.copy()
            changed[130:,1:5]*=3
            changed[130:,5]*=100
            self.assertTrue(np.array_equal(original,signals(changed,indexes,p)))
    def test_missing_bar_skips_entry(self):
        rows=self.rows.copy();rows[51,0]+=1000
        self.assertEqual(0,int(signals(rows,[55],{"family":"momentum","lookback":24,"level":0})[0]))
    def test_liquid_universe(self):
        data=[{"symbol":"BTCUSDT","turnover24h":"100000000","bid1Price":"100","ask1Price":"100.01"},
              {"symbol":"BADUSDT","turnover24h":"50000000","bid1Price":"10","ask1Price":"11"},
              {"symbol":"TINYUSDT","turnover24h":"100000","bid1Price":"10","ask1Price":"10.01"}]
        self.assertEqual(rank_tickers(data,20000000,12)[0],[("BTCUSDT",100000000.0)])
if __name__=="__main__":unittest.main()
