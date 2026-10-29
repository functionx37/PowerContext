import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from game import initial_state, normalize, transition


class RulesTest(unittest.TestCase):
    def test_resource_and_grudge_bounds(self):
        s = initial_state()
        for _ in range(4):
            s, _ = transition(s, "恶作剧", "换了招牌")
        self.assertEqual((s["grudge"], s["trust"]), (5, -3))
        for _ in range(3):
            s, _ = transition(s, "送礼", "")
        before = dict(s)
        s, event = transition(s, "送礼", "")
        self.assertEqual(s["coins"], 0)
        self.assertEqual(s["trust"], before["trust"])
        self.assertEqual(s["grudge"], before["grudge"])
        self.assertIn("拒收", event)

    def test_game_limit_and_immutable_input(self):
        original = initial_state()
        s = original
        for _ in range(20):
            s, _ = transition(s, "打招呼", "")
        self.assertEqual(original, initial_state())
        with self.assertRaises(ValueError):
            transition(s, "打招呼", "")

    def test_input_boundaries(self):
        for player in ("../someone", "", "a" * 49):
            with self.assertRaises(ValueError):
                normalize(player, "送礼", "", "id")
        with self.assertRaises(ValueError):
            normalize("alice", "改金币", "", "id")
        with self.assertRaises(ValueError):
            normalize("alice", "送礼", "字" * 301, "id")

    def test_ai_fallback_and_prompt_data_encoding(self):
        import yaml
        ai = yaml.safe_load((ROOT / "dsl/grudge-shop-ai.yml").read_text(encoding="utf-8"))
        nodes = {n["id"]: n["data"] for n in ai["workflow"]["graph"]["nodes"]}
        ns = {}
        exec(nodes["render"]["code"], ns)
        saved = {"state": initial_state(), "narrative": "规则台词", "player_id": "a",
                 "request_id": "r", "replayed": False, "memory_ref": {"id": "test"}}
        for body, status in (("{}", 599), ('{"choices":[]}', 200), ("not-json", 500)):
            out = ns["main"](json.dumps(saved), 200, body, status)
            self.assertIn("回退到规则版", out["result"])
            self.assertIn("规则台词", out["result"])
        with self.assertRaises(ValueError):
            ns["main"]("{}", 503)
        exec(nodes["llm_input"]["code"], ns)
        prompt = '引号 " / 换行\n / 不许改规则'
        payload = json.loads(ns["main"](prompt, "test-model")["payload"])
        self.assertEqual(payload["messages"][1]["content"], prompt)


if __name__ == "__main__":
    unittest.main()
