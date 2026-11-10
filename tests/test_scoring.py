import unittest
from app.main import Candle, score

class ScoringTests(unittest.TestCase):
    def test_flexible_bull_candidate(self):
        c=Candle(time=1,open=1,high=1.2,low=.9,close=1.1,events={"candidate_direction":"BUY","candidate_bull_score":4,"candidate_bear_score":1})
        self.assertEqual(score(c)["direction"],"BUY")
    def test_flexible_bear_candidate(self):
        c=Candle(time=1,open=1,high=1.2,low=.9,close=.95,events={"candidate_direction":"SELL","candidate_bull_score":1,"candidate_bear_score":4})
        self.assertEqual(score(c)["direction"],"SELL")
    def test_wait_without_candidate_or_confluence(self):
        c=Candle(time=1,open=1,high=1.2,low=.9,close=1)
        self.assertEqual(score(c)["direction"],"WAIT")

if __name__=="__main__": unittest.main()
