#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
處理「新增追蹤」Issue：驗證代號 → 通過就加進 watchlist.txt。

由 add_ticker.yml 觸發，讀環境變數 ISSUE_TITLE / ISSUE_BODY，
把結果寫進 GITHUB_OUTPUT：added(true/false)、code、message。

驗證條件（依需求人指定）：① 讀得到代號 ② FinMind 抓得到這檔 ③ 還沒重複。
（允許本夢比股，只要 FinMind 有這檔就收。）
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib import parse, request

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")


def emit(added, code, message):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"added={added}\n")
            f.write(f"code={code}\n")
            f.write(f"message={message}\n")
    print(message)


def finmind(dataset, data_id=None):
    params = {"dataset": dataset}
    if data_id:
        params["data_id"] = data_id
    if TOKEN:
        params["token"] = TOKEN
    with request.urlopen(API + "?" + parse.urlencode(params), timeout=45) as r:
        return json.loads(r.read().decode("utf-8")).get("data", [])


def main():
    text = (os.environ.get("ISSUE_TITLE", "") + " " + os.environ.get("ISSUE_BODY", ""))
    m = re.search(r"\b(\d{4,6}[A-Za-z]?)\b", text)
    if not m:
        emit("false", "", "❌ 沒讀到股票代號。標題請用 `[add] 2454` 這種格式。")
        return
    code = m.group(1)

    wl = ROOT / "watchlist.txt"
    lines = wl.read_text(encoding="utf-8").splitlines()
    existing = {ln.partition("#")[0].strip() for ln in lines
                if ln.strip() and not ln.strip().startswith("#")}
    if code in existing:
        emit("false", code, f"ℹ️ {code} 已經在追蹤清單裡了，不用重複加。")
        return

    # ② FinMind 抓得到 → 用 TaiwanStockInfo 驗證存在並取名稱
    try:
        info = finmind("TaiwanStockInfo")
    except Exception as exc:  # noqa: BLE001
        emit("false", code, f"⚠️ FinMind 暫時連不上（{exc}），請稍後再送一次。")
        return
    name = next((r.get("stock_name") for r in info if r.get("stock_id") == code), None)
    if name is None:
        emit("false", code, f"❌ 查無代號 {code}（FinMind 沒有這檔）。請確認代號是否正確。")
        return

    with open(wl, "a", encoding="utf-8") as f:
        f.write(f"{code}  # {name}\n")
    emit("true", code, f"✅ 已加入追蹤：{code} {name}。網站幾分鐘後會多這一檔。")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
