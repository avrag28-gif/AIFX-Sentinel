import os
import tempfile
import unittest
from fastapi.testclient import TestClient

tmp = tempfile.NamedTemporaryFile(delete=False)
os.environ["DB_PATH"] = tmp.name
os.environ["AIFX_BRIDGE_TOKEN"] = "t" * 40
from app import app

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.router.startup()

    def test_health_is_dry_run(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["execution"], "disabled")

    def test_rejects_bad_token(self):
        r = self.client.post("/v1/heartbeat", json={}, headers={"X-AIFX-Token": "bad"})
        self.assertEqual(r.status_code, 401)

    def test_accepts_candle(self):
        body = {"symbol":"EURUSD","timeframe":"M5","time":1700000000,
                "open":1.1,"high":1.2,"low":1.0,"close":1.15}
        r = self.client.post("/v1/candle", json=body, headers={"X-AIFX-Token":"t"*40})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json().get("trade_sent", False))

if __name__ == "__main__":
    unittest.main()
