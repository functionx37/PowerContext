"""Play the rules edition locally using exported DSL Code nodes and real memory."""
import argparse
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
from game import ACTIONS
from verify import LocalRunner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    key = os.getenv("SHOP_API_KEY") or (ROOT / ".runtime/shop-key.txt").read_text().strip()
    runner = LocalRunner(args.base_url, key, [])
    print("记仇杂货铺 · 本地规则体验（真实 PowerContext 记忆；Dify AI 版见 README）")
    print("玩家编号：", args.player, "。保留编号可以续玩，输入 q 退出。")
    while True:
        print(" / ".join(f"{i + 1} {action}" for i, action in enumerate(ACTIONS)))
        choice = input("行动 > ").strip()
        if choice.lower() == "q":
            break
        if choice not in ("1", "2", "3", "4", "5"):
            print("请输入 1–5。")
            continue
        line = input("想说的话（可留空）> ")
        inp = {"player_id": args.player, "action": ACTIONS[int(choice) - 1], "line": line, "request_id": uuid.uuid4().hex}
        try:
            print("\n" + runner.turn(inp)["result"] + "\n")
        except Exception as error:
            print("回合未完成：", error)
            print("若写入已发生，重试请使用原请求编号：", inp["request_id"])


if __name__ == "__main__":
    main()
