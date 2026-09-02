#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
處理「新增／移除追蹤」Issue：依標題前綴改 watchlist.txt。

由 add_ticker.yml 觸發，讀環境變數 ISSUE_TITLE / ISSUE_BODY，
把結果寫進 GITHUB_OUTPUT：changed(true/false)、code、message。

  [add] 2454     → 驗證後加入。條件：① 讀得到代號 ② FinMind 抓得到這檔 ③ 還沒重複。
  [remove] 2454  → 從清單刪掉該代號那行（不在清單則無事）。

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


def emit(changed, code, message):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"changed={changed}\n")
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


def code_of(line):
    """回傳「代號行」的代號；註解行或空行回傳 ''。"""
    s = line.strip()
    if not s or s.startswith("#"):
        return ""
    return s.partition("#")[0].strip()


def main():
    title = os.environ.get("ISSUE_TITLE", "")
    body = os.environ.get("ISSUE_BODY", "")
    action = "remove" if title.lstrip().lower().startswith("[remove]") else "add"

    m = re.search(r"\b(\d{4,6}[A-Za-z]?)\b", title + " " + body)
    if not m:
        emit("false", "", "❌ 沒讀到股票代號。標題請用 `[add] 2454` 或 `[remove] 2454`。")
        return
    code = m.group(1)

    wl = ROOT / "watchlist.txt"
    lines = wl.read_text(encoding="utf-8").splitlines()
    existing = {code_of(ln) for ln in lines if code_of(ln)}

    if action == "remove":
        if code not in existing:
            emit("false", code, f"ℹ️ {code} 不在追蹤清單裡，沒有東西可移除。")
            return
        kept, removed_name = [], ""
        for ln in lines:
            if code_of(ln) == code:
                removed_name = ln.strip().partition("#")[2].strip()
                continue
            kept.append(ln)
        wl.write_text("\n".join(kept) + "\n", encoding="utf-8")
        emit("true", code, f"✅ 已移除追蹤：{code} {removed_name}。網站幾分鐘後會少這一檔。")
        return

    # action == "add"
    if code in existing:
        emit("false", code, f"ℹ️ {code} 已經在追蹤清單裡了，不用重複加。")
        return
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
