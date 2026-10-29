"""Acceptance scenario, either real Dify API or DSL Code + real bridge/PowerContext.

The local runner is deliberately labelled: it is NOT a Dify engine/import test.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import uuid

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]


class LocalRunner:
    mode = "dsl-code-and-real-http; NOT a Dify runtime test"

    def __init__(self, base, key, records):
        self.doc = yaml.safe_load((ROOT / "dsl/grudge-shop-rules.yml").read_text(encoding="utf-8"))
        self.env = {"SHOP_URL": base, "SHOP_API_KEY": key}
        self.client = httpx.Client(timeout=40, trust_env=False)
        self.records = records

    def turn(self, inp):
        values = {"start": inp, "env": self.env, "sys": {"workflow_run_id": str(uuid.uuid4())}}

        def select(sel):
            return values[sel[0]][sel[1]]

        def substitute(text):
            return re.sub(r"\{\{#([^#]+)#\}\}", lambda m: str(select(m[1].split("."))), text)

        for node in self.doc["workflow"]["graph"]["nodes"]:
            data, nid = node["data"], node["id"]
            if data["type"] == "start":
                continue
            if data["type"] == "code":
                namespace = {}
                exec(compile(data["code"], "DSL:" + nid, "exec"), namespace)
                values[nid] = namespace["main"](**{v["variable"]: select(v["value_selector"]) for v in data["variables"]})
                for name, spec in data["outputs"].items():
                    if spec["type"] == "string" and not isinstance(values[nid][name], str):
                        raise AssertionError(f"{nid}.{name}: invalid output type")
            elif data["type"] == "http-request":
                url = substitute(data["url"])
                headers = dict(line.split(":", 1) for line in substitute(data["headers"]).splitlines())
                body = json.loads(substitute(data["body"]["data"][0]["value"]))
                response = self.client.request(data["method"], url, json=body, headers=headers)
                self.records.append({"node": nid, "url": url, "request": body,
                                     "status_code": response.status_code, "response": response.json()})
                values[nid] = {"body": response.text, "status_code": response.status_code}
            elif data["type"] == "end":
                return {out["variable"]: select(out["value_selector"]) for out in data["outputs"]}
            else:
                raise AssertionError("Unsupported local node: " + data["type"])
        raise AssertionError("Missing end node")


class DifyRunner:
    mode = "real-dify-workflow-api"

    def __init__(self, base, key, records):
        self.base, self.key, self.records = base.rstrip("/"), key, records

    def turn(self, inp):
        # A new API user for each request excludes Dify conversation history as a memory source.
        response = httpx.post(self.base + "/workflows/run", timeout=180,
                             headers={"Authorization": "Bearer " + self.key},
                             json={"inputs": inp, "response_mode": "blocking", "user": "judge-" + uuid.uuid4().hex})
        response.raise_for_status()
        data = response.json()
        self.records.append(data)
        if data["data"]["status"] != "succeeded":
            raise AssertionError(json.dumps(data, ensure_ascii=False))
        return data["data"]["outputs"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--dify-url", help="Dify service API base, e.g. http://localhost/v1")
    parser.add_argument("--output", default=str(ROOT / "evidence/local-verification.json"))
    args = parser.parse_args()
    records, checks, turns = [], [], []
    if args.dify_url:
        key = os.environ.get("DIFY_API_KEY")
        if not key:
            parser.error("Set DIFY_API_KEY to the published Workflow API key.")
        runner = DifyRunner(args.dify_url, key, records)
    else:
        key = os.environ.get("SHOP_API_KEY")
        key_file = ROOT / ".runtime/shop-key.txt"
        if not key and key_file.exists():
            key = key_file.read_text().strip()
        if not key:
            parser.error("Start tools/run_local.py or set SHOP_API_KEY first.")
        runner = LocalRunner(args.base_url, key, records)
    player = "judge-" + uuid.uuid4().hex[:12]

    def play(action, line="", request_id=None):
        inp = {"player_id": player, "action": action, "line": line, "request_id": request_id or uuid.uuid4().hex}
        out = runner.turn(inp)
        state = json.loads(out["state"])
        turns.append({"input": inp, "output": out})
        print(f"{state['turn']}: {action} / grudge={state['grudge']} trust={state['trust']} coins={state['coins']}")
        return inp, out, state

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    first, out1, state1 = play("恶作剧", '把招牌改成“咸鱼收容所”\n老板说："别闹"')
    check("首次恶作剧写入：记仇 2、信任 -1", state1["grudge"] == 2 and state1["trust"] == -1)
    _, out2, state2 = play("打招呼")
    check("新请求从 PowerContext 召回具体恶作剧", state2["grudge"] == 2 and "咸鱼收容所" in out2["result"])
    duplicate = runner.turn(first)
    check("重复请求返回原回合且不重复扣资源", json.loads(duplicate["state"]) == state1)
    _, _, state3 = play("道歉", "我错了，这次真的。")
    check("重放旧请求不会回滚存档", state3["turn"] == 3 and state3["grudge"] == 1)
    _, _, state4 = play("送礼")
    check("关系修复及徽章：和好如初", state4["grudge"] == 0 and "和好如初" in state4["badges"] and state4["coins"] == 2)
    _, _, state5 = play("送礼")
    check("隐藏菜单解锁", "隐藏菜单" in state5["badges"] and state5["trust"] == 4)
    _, final, state6 = play("打听传闻")
    check("通关玩法反馈完整", state6["turn"] == 6 and bool(final["memory_ref"]))
    isolated = runner.turn({"player_id": player + "-other", "action": "打招呼", "line": "", "request_id": uuid.uuid4().hex})
    check("其他玩家独立初始状态", json.loads(isolated["state"])["pranks"] == 0 and "咸鱼收容所" not in isolated["result"])
    if isinstance(runner, LocalRunner):
        client = runner.client
        denied = client.post(args.base_url + "/v1/turns/prepare", json=first)
        check("未提供桥接密钥拒绝访问", denied.status_code == 401)
        collision = dict(first, action="送礼")
        response = client.post(args.base_url + "/v1/turns/prepare", json=collision, headers={"X-Shop-Key": key})
        check("重复请求编号绑定原始行动", response.status_code == 409)
        prepared = client.post(args.base_url + "/v1/turns/prepare", json=dict(first, request_id="stale-turn"), headers={"X-Shop-Key": key}).json()
        ns = {}
        exec((ROOT / "game.py").read_text(encoding="utf-8"), ns)
        packet = json.loads(ns["adjudicate"](json.dumps(prepared))["payload"])
        packet["expected_turn"] -= 1
        response = client.post(args.base_url + "/v1/turns/commit", json=packet, headers={"X-Shop-Key": key})
        check("过期回合禁止覆盖新存档", response.status_code == 409)
        actual = client.post(args.base_url + "/v1/turns/prepare", json=dict(first, request_id="inspect-final"), headers={"X-Shop-Key": key}).json()
        check("拒绝的写入没有改变真实记忆", actual["state"] == state6 and actual["recalled_turns"] == 6)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "execution_mode": runner.mode,
              "powercontext_version": importlib.metadata.version("powercontext"),
              "dify_runtime_verified": isinstance(runner, DifyRunner),
              "live_model_verified": isinstance(runner, DifyRunner) and all("AI 角色台词" in t["output"]["result"] for t in turns),
              "checks": checks, "player_id": player, "turns": turns, "records": records,
              "result": "passed"}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS {len(checks)} checks. Evidence: {path}")
    print("Execution:", runner.mode)


if __name__ == "__main__":
    main()
