#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
恐慌度警鈴 —— 讀 docs/data.json，判斷要不要叫，把 Issue 標題／內文寫出來給 Action 用。

為什麼要有這支：恐慌事件的窗口很短。20 年裡 ≥65 的日子共 379 天，
但它們擠在 10 個事件裡，事件長度中位數只有 22 個交易日（約 1 個月），
最短的一次（2024-08-05）只有 2 天。等於「不會等不到，但很容易錯過」——
所以需要主動叫人，而不是靠使用者自己想到要開網站看。

★ 遲滯（hysteresis）：升破門檻叫一次就閉嘴，掉回「重新上膛線」以下才會再叫。
  沒有這個的話，一次事件會連叫 22 天，然後使用者就開始無視它了。

不下單、不給投資建議，只負責在門檻被跨過時通知一次。stdlib only。
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data.json"
STATE = ROOT / "alert_state.json"

# (門檻, 名稱, 重新上膛線)：跌回上膛線以下，這個鈴才會重新武裝
BELLS = [
    (65, "進場鈴", 50),
    (50, "預備鈴", 40),
]

# 上一次 ≥65 的日期。首次建檔時用回測算出來的實際值當種子，
# 之後每次 65 響都會覆寫成當天。
SEED_LAST_65 = "2025-05-08"


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8")), False
    # 首次建檔：依當下分數決定上膛狀態，但「不叫」——避免建檔當天噴一則假警報
    return {"armed": {str(t): True for t, _, _ in BELLS},
            "last_score": None, "last_65": SEED_LAST_65, "log": []}, True


def months_since(iso):
    try:
        d = dt.date.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return (dt.date.today() - d).days / 30.44


def build_body(mk, level, name, stocks, last_65):
    since = months_since(last_65)
    since_txt = f"{since:.0f} 個月前（{last_65}）" if since is not None else "無紀錄"
    lines = [
        f"## 恐慌度 {mk['score']}　{mk.get('tag', '')}",
        "",
        f"**{name}（門檻 {level}）已觸發**　·　資料日 {mk.get('date', '?')}"
        f"　·　TAIEX {mk.get('close', '?')}",
        "",
        "| 分項 | 數值 | 說明 |",
        "|---|---|---|",
        f"| 乖離（權重 0.40） | {mk.get('bias')}% | 對 120 日均線，負值＝跌破均線 |",
        f"| 回檔（權重 0.30） | {mk.get('dd')}% | 距近一年最高點 |",
        f"| 波動（權重 0.30） | {mk.get('vol')}% | 20 日年化波動 |",
        "",
        f"上一次 ≥65：**{since_txt}**",
    ]
    if mk.get("margin_note"):
        lines += ["", f"融資：{mk['margin_note']}"]

    ranked = sorted([s for s in stocks if s.get("composite") is not None],
                    key=lambda s: -s["composite"])[:4]
    if ranked:
        lines += ["", "### 追蹤清單當下排序（進場時機高＝相對便宜）", "",
                  "| 代號 | 名稱 | 股價 | 估值位階 | 進場時機 | 標籤 |", "|---|---|---|---|---|---|"]
        for s in ranked:
            # 虧損過的股票會自動改用 PBR 算位階（見 build_data.value_band），標出來才不會誤讀
            m = "PBR" if s.get("metric") == "pbr" else "PER"
            lines.append(
                f"| {s['code']} | {s['name']} | {s.get('price')} | "
                f"{m} {s.get('metric_pctl')}% | **{s['composite']}** | {s.get('label', '')} |")

    lines += [
        "",
        "---",
        "",
        "**窗口提醒**：歷史上 ≥65 的事件長度中位數約 22 個交易日（1 個月），"
        "最短的一次只有 2 天。這則通知是收盤後發的，最快隔天早盤可以動作。",
        "",
        "決定做完（買了、或決定不買）就把這個 Issue 關掉。"
        "門檻掉回重新上膛線以下之前，不會再叫第二次。",
        "",
        "_自動產生自 `scripts/alert.py`。純資料通知，不是投資建議。_",
    ]
    return "\n".join(lines)


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    mk = data.get("market") or {}
    score = mk.get("score")
    if score is None:
        print("::warning::data.json 沒有 market.score，跳過")
        return

    state, first_run = load_state()
    armed = state.setdefault("armed", {})

    # ① 先處理重新上膛：掉回上膛線以下，鈴就重新武裝
    for th, name, rearm in BELLS:
        if score < rearm and not armed.get(str(th), True):
            armed[str(th)] = True
            print(f"重新上膛：{name}（{score} < {rearm}）")

    # ② 再判斷要不要響：只挑「有上膛且已跨過」的最高門檻，一次只響一個
    fire = None
    for th, name, _ in BELLS:                     # BELLS 由高到低
        if score >= th and armed.get(str(th), True):
            fire = (th, name)
            break

    if fire and not first_run:
        level, name = fire
        # 同時把「這一級以下」全部解除，避免 30→68 一次噴兩則
        for th, _, _ in BELLS:
            if th <= level:
                armed[str(th)] = False
        body = build_body(mk, level, name, data.get("stocks") or [], state.get("last_65"))
        title = f"[警鈴] 恐慌度 {score} 突破 {level}（{name}）· {mk.get('date', '')}"
        (ROOT / "alert_title.txt").write_text(title, encoding="utf-8")
        (ROOT / "alert_body.md").write_text(body, encoding="utf-8")
        if level >= 65:
            state["last_65"] = mk.get("date") or dt.date.today().isoformat()
        state.setdefault("log", []).append(
            {"date": mk.get("date"), "score": score, "level": level})
        state["log"] = state["log"][-40:]
        out = "true"
        print(f"::notice::警鈴響了 —— 恐慌度 {score} 突破 {level}（{name}）")
    else:
        out = "false"
        if first_run:
            print(f"首次建檔，恐慌度 {score}，本次不發通知（避免建檔當天的假警報）")
        else:
            print(f"恐慌度 {score}，未觸發。"
                  f"上膛狀態：{ {k: v for k, v in armed.items()} }")

    state["last_score"] = score
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")

    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"fire={out}\n")


if __name__ == "__main__":
    main()
