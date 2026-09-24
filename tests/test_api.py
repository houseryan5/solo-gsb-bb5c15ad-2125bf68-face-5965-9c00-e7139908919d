"""HTTP 层集成测试（使用 FastAPI TestClient）。"""

import unittest

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class ApiTests(unittest.TestCase):
    def test_health_endpoints(self):
        for path in ("/", "/health"):
            resp = client.get(path)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "ok")

    def test_openapi_available(self):
        resp = client.get("/openapi.json")
        self.assertEqual(resp.status_code, 200)

    def test_align_full_example(self):
        payload = {
            "total_duration_ms": 500,
            "chars": [
                {"char": "你", "start_ms": 0, "end_ms": 100},
                {"char": "好", "start_ms": 100, "end_ms": 200},
                {"char": "世", "start_ms": 200, "end_ms": 300},
                {"char": "界", "start_ms": 300, "end_ms": 400},
            ],
            # 识别：你好世界 -> 修订：你好呀，世界！
            "revised_text": "你好呀，世界！",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["recognized_count"], 4)
        self.assertEqual(data["revised_count"], 7)

        items = data["items"]
        self.assertEqual([it["char"] for it in items], list("你好呀，世界！"))

        matched = {it["char"]: it for it in items if it["matched"]}
        self.assertEqual(matched["你"]["start_ms"], 0)
        self.assertEqual(matched["好"]["end_ms"], 200)
        self.assertEqual(matched["世"]["start_ms"], 200)
        self.assertEqual(matched["界"]["end_ms"], 400)

        inserted = [it for it in items if not it["matched"]]
        self.assertEqual([it["char"] for it in inserted], ["呀", "，", "！"])
        self.assertTrue(all(it["estimated"] for it in inserted))

        # 呀、， 平分 [好.end=200, 世.start=200] 的零宽空档
        self.assertEqual((items[2]["start_ms"], items[2]["end_ms"]), (200, 200))
        self.assertEqual((items[3]["start_ms"], items[3]["end_ms"]), (200, 200))
        # ！ 在录音尾部 [界.end=400, total=500]
        self.assertEqual((items[6]["start_ms"], items[6]["end_ms"]), (400, 500))

        # 顺序与录音范围不变量
        prev = 0
        for it in items:
            self.assertGreaterEqual(it["start_ms"], prev)
            self.assertGreaterEqual(it["end_ms"], it["start_ms"])
            self.assertLessEqual(it["end_ms"], 500)
            prev = it["end_ms"]

        self.assertEqual(
            data["stats"], {"matched": 4, "inserted": 3, "deleted": 0}
        )

    def test_repeated_char_uses_earliest_match(self):
        payload = {
            "total_duration_ms": 300,
            "chars": [
                {"char": "啊", "start_ms": 0, "end_ms": 100},
                {"char": "啊", "start_ms": 100, "end_ms": 200},
                {"char": "啊", "start_ms": 200, "end_ms": 300},
            ],
            "revised_text": "啊啊",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        items = resp.json()["items"]
        self.assertEqual(
            [(it["start_ms"], it["end_ms"]) for it in items],
            [(0, 100), (100, 200)],
        )

    def test_deleted_chars_not_output(self):
        payload = {
            "total_duration_ms": 300,
            "chars": [
                {"char": "嗯", "start_ms": 0, "end_ms": 100},
                {"char": "好", "start_ms": 100, "end_ms": 200},
                {"char": "的", "start_ms": 200, "end_ms": 300},
            ],
            "revised_text": "好",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual([it["char"] for it in data["items"]], ["好"])
        self.assertEqual(data["items"][0]["start_ms"], 100)
        self.assertEqual(data["stats"]["deleted"], 2)

    def test_end_before_start_error(self):
        payload = {
            "total_duration_ms": 100,
            "chars": [{"char": "a", "start_ms": 50, "end_ms": 10}],
            "revised_text": "a",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("end_ms=10 is earlier than start_ms=50", resp.json()["detail"])

    def test_exceeds_total_error(self):
        payload = {
            "total_duration_ms": 100,
            "chars": [{"char": "a", "start_ms": 0, "end_ms": 120}],
            "revised_text": "a",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("exceeds total_duration_ms=100", resp.json()["detail"])

    def test_overlap_error(self):
        payload = {
            "total_duration_ms": 300,
            "chars": [
                {"char": "a", "start_ms": 0, "end_ms": 120},
                {"char": "b", "start_ms": 80, "end_ms": 200},
            ],
            "revised_text": "ab",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("overlaps", resp.json()["detail"])

    def test_unsorted_error(self):
        payload = {
            "total_duration_ms": 300,
            "chars": [
                {"char": "b", "start_ms": 100, "end_ms": 200},
                {"char": "a", "start_ms": 0, "end_ms": 50},
            ],
            "revised_text": "ab",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("time-sorted", resp.json()["detail"])

    def test_multichar_item_rejected(self):
        payload = {
            "total_duration_ms": 100,
            "chars": [{"char": "ab", "start_ms": 0, "end_ms": 50}],
            "revised_text": "ab",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_negative_time_rejected(self):
        payload = {
            "total_duration_ms": 100,
            "chars": [{"char": "a", "start_ms": -1, "end_ms": 50}],
            "revised_text": "a",
        }
        resp = client.post("/align", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_payload_too_large_413(self):
        import app.main as main_module

        payload = {
            "total_duration_ms": 100,
            "chars": [
                {"char": "a", "start_ms": i, "end_ms": i + 1}
                for i in range(4)
            ],
            "revised_text": "b" * 4,
        }
        original = main_module.MAX_CHARS_PER_SIDE
        main_module.MAX_CHARS_PER_SIDE = 3
        try:
            resp = client.post("/align", json=payload)
        finally:
            main_module.MAX_CHARS_PER_SIDE = original
        self.assertEqual(resp.status_code, 413)
        self.assertIn("input too long", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
