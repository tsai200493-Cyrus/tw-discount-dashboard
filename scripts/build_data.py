#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打折窗口溫度計 —— 資料產生器（GitHub Action 在雲端跑這支，產出 docs/data.json）。

純讀取 FinMind，不下單、非投資建議、非買賣訊號。stdlib only（無外部相依）。

★ 同步提醒（[決策] 給未來的你）：
  這支是 ~/.claude/skills/tw-value-investing 裡 fetch_*.py / discount_window.py 的「獨立複本」，
  因為 GitHub Action 在雲端跑、碰不到你本機的 skill。
  前提：兩邊算法要一致才有意義。
  已知代價：skill 改了算法，這支「不會自動跟上」——要手動同步過來。
  ⇒ 排錯線索：若網站分數跟本機 skill 對不上，先懷疑這裡是舊版、需要同步。

市場恐慌度用「方向性/絕對值」，不用歷史位階——位階在多頭趨勢會失真（原型實測踩過的坑）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics as st
import sys
from pathlib import Path
from urllib import error, parse, request

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")
ROOT = Path(__file__).resolve().parents[1]

# 綜合窗口權重（透明、未回測調參；故意笨而誠實，避免過度擬合）
W_VALUE, W_FUND, W_MARKET = 0.40, 0.25, 0.35


def _get(dataset, data_id, start_date):
    params = {"dataset": dataset, "start_date": start_date}
    if data_id:
        params["data_id"] = data_id
    if TOKEN:
        params["token"] = TOKEN
    url = API + "?" + parse.urlencode(params)
    try:
        with request.urlopen(url, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        return {"_error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}
    if payload.get("status") != 200:
        return {"_error": payload.get("msg", "unknown")}
    return payload.get("data", [])


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def load_watchlist():
    """每行一檔：`CODE  # 名稱`；# 開頭整行為註解。回傳 [(code, name), ...]。"""
    out = []
    path = ROOT / "watchlist.txt"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        code, _, comment = line.partition("#")
        code = code.strip()
        name = comment.strip()
        if code:
            out.append((code, name))
    return out


def market_fear():
    start = (dt.date.today() - dt.timedelta(days=420)).isoformat()
    rows = _get("TaiwanStockPrice", "TAIEX", start)
    if isinstance(rows, dict) or len(rows) < 130:
        return {"error": "TAIEX 資料不足", "score": 50}
    rows = sorted(rows, key=lambda x: x["date"])
    closes = [r["close"] for r in rows]
    c = closes[-1]
    ma120 = sum(closes[-120:]) / 120
    bias = (c - ma120) / ma120 * 100
    hi = max(closes[-250:]) if len(closes) >= 250 else max(closes)
    dd = (c - hi) / hi * 100
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    vol = st.pstdev(rets[-20:]) * (252 ** 0.5) * 100
    f_bias = clamp(50 - bias * 3.3)
    f_dd = clamp(-dd * 2.5)
    f_vol = clamp((vol - 12) / 26 * 100)
    score = round(0.4 * f_bias + 0.3 * f_dd + 0.3 * f_vol)

    margin_note = ""
    mg = _get("TaiwanStockTotalMarginPurchaseShortSale", None, start)
    if isinstance(mg, list):
        mg = sorted([r for r in mg if r.get("name") == "MarginPurchaseMoney"],
                    key=lambda x: x["date"])
        if len(mg) >= 2:
            chg = (mg[-1]["TodayBalance"] / mg[0]["TodayBalance"] - 1) * 100
            margin_note = f"融資餘額 {mg[-1]['TodayBalance']/1e8:.0f} 億（{mg[0]['date']} 起 {chg:+.0f}%）"

    tag = "恐慌(機會)" if score >= 65 else "中性" if score >= 40 else "貪婪(該收手)"
    return {"score": score, "tag": tag, "close": round(c), "bias": round(bias, 1),
            "dd": round(dd, 1), "vol": round(vol, 1), "date": rows[-1]["date"],
            "margin_note": margin_note}


def per_band(code):
    start = (dt.date.today() - dt.timedelta(days=365 * 5)).isoformat()
    rows = _get("TaiwanStockPER", code, start)
    if isinstance(rows, dict) or not rows:
        return None
    rows = sorted(rows, key=lambda x: x["date"])
    vals = [r["PER"] for r in rows if r.get("PER") not in (None, 0)]
    if not vals:
        return None
    now = rows[-1].get("PER")
    below = sum(1 for v in vals if v <= now)
    return {"now": round(now, 2), "percentile": round(below / len(vals) * 100),
            "min": round(min(vals), 1), "median": round(sorted(vals)[len(vals) // 2], 1),
            "max": round(max(vals), 1)}


def revenue_yoy(code):
    start = (dt.date.today() - dt.timedelta(days=500)).isoformat()
    rows = _get("TaiwanStockMonthRevenue", code, start)
    if isinstance(rows, dict) or len(rows) < 13:
        return None
    rows = sorted(rows, key=lambda x: (x["revenue_year"], x["revenue_month"]))
    if not rows[-13]["revenue"]:
        return None
    return round((rows[-1]["revenue"] - rows[-13]["revenue"]) / rows[-13]["revenue"] * 100, 1)


def latest_close(code):
    start = (dt.date.today() - dt.timedelta(days=14)).isoformat()
    rows = _get("TaiwanStockPrice", code, start)
    if isinstance(rows, dict) or not rows:
        return None
    return sorted(rows, key=lambda x: x["date"])[-1].get("close")


def window_label(score):
    if score >= 65:
        return "窗口開(便宜+恐慌)"
    if score >= 45:
        return "半開(中性)"
    return "窗口關(貴+貪婪)"


def build_stock(code, name, mkf):
    per = per_band(code)
    yoy = revenue_yoy(code)
    price = latest_close(code)
    if per is None:  # 無本益比 → 本夢比，排除評分
        return {"code": code, "name": name, "price": price, "per": None,
                "percentile": None, "val_cheap": None, "yoy": yoy, "fund": None,
                "composite": None, "label": "資料不足(本夢比)"}
    val_cheap = 100 - per["percentile"]
    fund = None if yoy is None else round(clamp(45 + yoy * 1.2))
    composite = round(W_VALUE * val_cheap + W_FUND * (fund if fund is not None else 45)
                      + W_MARKET * mkf)
    return {"code": code, "name": name, "price": price, "per": per["now"],
            "percentile": per["percentile"], "per_min": per["min"],
            "per_median": per["median"], "per_max": per["max"],
            "val_cheap": val_cheap, "yoy": yoy, "fund": fund,
            "composite": composite, "label": window_label(composite)}


def main():
    mk = market_fear()
    mkf = mk.get("score", 50)
    stocks = []
    for code, name in load_watchlist():
        try:
            stocks.append(build_stock(code, name, mkf))
        except Exception as exc:  # noqa: BLE001 — 單檔失敗不拖垮整批
            stocks.append({"code": code, "name": name, "label": f"抓取失敗: {exc}"})
    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "market": mk,
        "stocks": stocks,
        "weights": {"value": W_VALUE, "fund": W_FUND, "market": W_MARKET},
        "disclaimer": "溫度計不是買賣訊號。沒有模型能可靠擇時；它只給情境傾向。非投資建議，決策與風險自負。",
    }
    out = ROOT / "docs" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}  (市場恐慌 {mkf}, {len(stocks)} 檔, token={'yes' if TOKEN else 'no'})")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
