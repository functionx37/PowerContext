"""Offline contract checks; does not claim to import into a Dify server."""
import ast
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    count = 0
    for path in sorted((ROOT / "dsl").glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc["kind"] == "app" and doc["app"]["mode"] == "workflow"
        assert doc["version"] == "0.4.0"
        workflow = doc["workflow"]
        nodes = workflow["graph"]["nodes"]
        ids = [n["id"] for n in nodes]
        assert len(ids) == len(set(ids)), "Duplicate node IDs"
        assert nodes[0]["data"]["type"] == "start" and nodes[-1]["data"]["type"] == "end"
        expected_edges = list(zip(ids, ids[1:]))
        assert [(e["source"], e["target"]) for e in workflow["graph"]["edges"]] == expected_edges
        outputs = {"env": {v["name"] for v in workflow["environment_variables"]},
                   "sys": {"workflow_run_id"}}
        for env in workflow["environment_variables"]:
            if env["value_type"] == "secret":
                assert env["value"] == "", "Secrets must not be committed"
        for n in nodes:
            d, nid = n["data"], n["id"]
            refs = []
            if d["type"] == "start":
                outputs[nid] = {v["variable"] for v in d["variables"]}
            elif d["type"] == "code":
                ast.parse(d["code"])
                refs = [v["value_selector"] for v in d["variables"]]
                assert all(o["type"] == "string" for o in d["outputs"].values())
            elif d["type"] == "http-request":
                assert d["body"]["type"] == "json" and d["method"] == "post"
                for text in (d["url"], d["headers"], d["body"]["data"][0]["value"]):
                    refs += [match.split(".") for match in re.findall(r"\{\{#([^#]+)#\}\}", text)]
                assert d["timeout"]["connect"] <= 10
            elif d["type"] == "end":
                refs = [o["value_selector"] for o in d["outputs"]]
            for source, variable in refs:
                assert source in outputs and variable in outputs[source], f"Broken selector: {source}.{variable}"
            if d["type"] == "http-request":
                outputs[nid] = {"body", "headers", "status_code"}
            elif d["type"] == "code":
                outputs[nid] = set(d["outputs"])
            count += 1
        judge = next(n for n in nodes if n["id"] == "judge")
        assert judge["data"]["code"] == (ROOT / "game.py").read_text(encoding="utf-8"), "Stale generated rules"
        print(f"PASS {path.name}: {len(nodes)} nodes, selectors, code syntax, secret placeholders")
    print(f"Checked {count} nodes. Dify import/runtime still requires an actual Dify server.")


if __name__ == "__main__":
    main()
