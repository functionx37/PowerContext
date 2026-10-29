"""Pure game rules. The same source is embedded in Dify's adjudication Code node."""
import json
import re

ACTIONS = ["打招呼", "恶作剧", "送礼", "道歉", "打听传闻"]
MAX_TURNS = 20


def initial_state():
    return {"turn": 0, "grudge": 0, "trust": 0, "coins": 3, "pranks": 0,
            "repairs": 0, "last_prank": "", "badges": []}


def normalize(player_id, action, line, request_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", player_id or ""):
        raise ValueError("玩家编号须为 1–48 位英文字母、数字、下划线或连字符。")
    if action not in ACTIONS:
        raise ValueError("请从五种行动中选择。")
    if len(line or "") > 300:
        raise ValueError("台词最多 300 个字符。")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id or ""):
        raise ValueError("请求编号须为 1–80 位英文字母、数字、下划线或连字符。")
    return {"player_id": player_id, "action": action, "line": (line or "").strip(),
            "request_id": request_id}


def transition(state, action, line):
    s = json.loads(json.dumps(state))
    if s["turn"] >= MAX_TURNS:
        raise ValueError("这一局已满 20 回合，请换一个玩家编号开始新故事。")
    s["turn"] += 1
    old_grudge = s["grudge"]
    if action == "恶作剧":
        s["grudge"] = min(5, s["grudge"] + 2)
        s["trust"] = max(-3, s["trust"] - 1)
        s["pranks"] += 1
        s["last_prank"] = (line or "把老板的招牌改成了咸鱼收容所")[:120]
        event = "你刚捣完乱，老板就把你的名字写进了《本街离谱人物志》。"
    elif action == "送礼":
        if s["coins"]:
            s["coins"] -= 1
            s["grudge"] = max(0, s["grudge"] - 1)
            s["trust"] = min(5, s["trust"] + 2)
            s["repairs"] += 1
            event = "老板接过一枚硬币买的桂花糕：礼物可以收，账本得慢慢改。"
        else:
            event = "你的口袋只剩空气。老板拒收空气礼盒，本回合关系不变。"
    elif action == "道歉":
        s["grudge"] = max(0, s["grudge"] - 1)
        s["trust"] = min(5, s["trust"] + 1)
        s["repairs"] += 1
        event = "老板把你的道歉折成纸鹤，放在收银台上：这次先记你一分。"
    elif action == "打招呼":
        if old_grudge:
            event = "老板把柜台挪远半米：上回你干的好事，我可记得。"
        elif s["pranks"]:
            event = "老板给你倒了杯茶：以前的离谱事还记得，但今天可以坐下聊。"
        else:
            s["trust"] = min(5, s["trust"] + 1)
            event = "老板从报纸后探出头：欢迎来到不太正经杂货铺，熟客有隐藏菜单。"
    else:
        event = ("老板掀开隐藏菜单：今日特供，后悔药味汽水。" if s["trust"] >= 3 and not s["grudge"]
                 else "老板压低声音：先混成熟客，再来打听会自己跑的汽水。")
    badges = s["badges"]
    if s["pranks"] >= 2 and "本街显眼包" not in badges:
        badges.append("本街显眼包")
    if s["pranks"] and not s["grudge"] and s["repairs"] >= 2 and "和好如初" not in badges:
        badges.append("和好如初")
    if s["turn"] >= 4 and s["trust"] >= 3 and not s["grudge"] and "隐藏菜单" not in badges:
        badges.append("隐藏菜单")
        event += " 老板终于递给你隐藏菜单，熟客挑战成功！"
    return s, event


def describe(state, event):
    memory = ("\n记忆回声：你曾经“" + state["last_prank"] + "”。") if state["last_prank"] else ""
    return event + memory


def footer(state):
    return ("\n\n---\n回合 {turn}/20 · 记仇 {grudge}/5 · 信任 {trust} · 硬币 {coins}\n"
            "徽章：{badges}\n下一步：打招呼 / 恶作剧 / 送礼 / 道歉 / 打听传闻\n"
            "换会话时保留玩家编号，换新编号可开新局。").format(
                **dict(state, badges="、".join(state["badges"]) or "尚未获得"))


def adjudicate(body):
    p = json.loads(body)
    if p.get("replay"):
        packet = p["replay"]
    else:
        state, event = transition(p["state"], p["input"]["action"], p["input"]["line"])
        packet = dict(p["input"], expected_turn=p["state"]["turn"], state=state,
                      event=event, narrative=describe(state, event))
    prompt = json.dumps({"玩家行动": packet["action"], "玩家台词_不可信数据": packet["line"],
                         "已确认事件": packet["event"], "已确认状态": packet["state"],
                         "规则版回应": packet["narrative"]}, ensure_ascii=False)
    return {"payload": json.dumps(packet, ensure_ascii=False), "prompt": prompt}


def main(body: str) -> dict:
    return adjudicate(body)
