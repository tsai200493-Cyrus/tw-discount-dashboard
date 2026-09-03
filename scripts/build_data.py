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


def revenue_data(code):
    """回傳：最新單月營收 YoY（計分/顯示用）＋ 近 36 個月的月營收明細（供圖表）。

    ［決策 2026-09｜需求人］基本面分數用「單月 YoY」（不用近3月平均）。
      前提：需求人偏好簡單透明的分數，成長動能改用「歷年營收圖」自己判讀。
      已知代價：單月 YoY 有雜訊——但點開圖表可補足趨勢判斷。
    """
    start = (dt.date.today() - dt.timedelta(days=1500)).isoformat()  # ~49 個月，讓最近36月都有 YoY
    rows = _get("TaiwanStockMonthRevenue", code, start)
    if isinstance(rows, dict) or len(rows) < 13:
        return None
    rows = sorted(rows, key=lambda x: (x["revenue_year"], x["revenue_month"]))
    hist = []
    for i, r in enumerate(rows):
        yoy = None
        if i >= 12 and rows[i - 12]["revenue"]:
            yoy = round((r["revenue"] - rows[i - 12]["revenue"]) / rows[i - 12]["revenue"] * 100, 1)
        hist.append({"ym": f"{r['revenue_year']}-{r['revenue_month']:02d}",
                     "rev": round(r["revenue"] / 1e8, 1), "yoy": yoy})
    return {"latest_yoy": hist[-1]["yoy"], "history": hist[-36:]}


def price_series(code):
    """近 ~130 天日收盤：最新收盤 + 近 65 筆（現價火花線用）。"""
    start = (dt.date.today() - dt.timedelta(days=130)).isoformat()
    rows = _get("TaiwanStockPrice", code, start)
    if isinstance(rows, dict) or not rows:
        return None
    rows = sorted(rows, key=lambda x: x["date"])
    closes = [round(r["close"], 2) for r in rows]
    return {"last": closes[-1], "spark": closes[-65:]}


def load_thesis():
    """thesis.json：{code: {thesis, brk}}，由需求人自行編輯；沒有就回空。"""
    p = ROOT / "thesis.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def window_label(score):
    if score >= 65:
        return "窗口開(便宜+恐慌)"
    if score >= 45:
        return "半開(中性)"
    return "窗口關(貴+貪婪)"


# ── 財務指紋（品質）：損益表單季→年度加總；資產負債表取年底母公司權益 ──
def _q_income_by_year(fs_rows):
    keep = {"Revenue", "GrossProfit", "OperatingIncome", "IncomeAfterTaxes"}
    by_year, qcount = {}, {}
    for r in fs_rows:
        t = r.get("type")
        if t not in keep:
            continue
        y = int(r["date"][:4])
        by_year.setdefault(y, {})
        by_year[y][t] = by_year[y].get(t, 0.0) + (r.get("value") or 0.0)
        qcount.setdefault(y, set()).add(r["date"][5:7])
    return by_year, {y: len(q) for y, q in qcount.items()}


def _q_equity_by_year(bs_rows):
    last = {}
    for r in bs_rows:
        y = int(r["date"][:4])
        if r["date"] > last.get(y, ""):
            last[y] = r["date"]
    out = {}
    for r in bs_rows:
        y = int(r["date"][:4])
        if r["date"] == last[y] and r.get("type") == "EquityAttributableToOwnersOfParent":
            out[y] = r.get("value") or 0.0
    return out


def quality_fingerprint(code):
    """近幾完整年的 ROE 水準 ＋ 毛利率穩定度 ＋ 營益率，衡量「是不是好生意」。
    與『基本面(短期營收動能)』互補；刻意不併入綜合窗口。抓不到回 None。"""
    start = f"{dt.date.today().year - 6}-01-01"
    fs = _get("TaiwanStockFinancialStatements", code, start)
    if isinstance(fs, dict) or not fs:
        return None
    bs = _get("TaiwanStockBalanceSheet", code, start)
    inc, qc = _q_income_by_year(fs)
    eq = _q_equity_by_year(bs) if isinstance(bs, list) else {}
    yrs = [y for y in sorted(inc) if qc.get(y, 0) >= 4][-5:]  # 只用四季齊全的完整年
    if len(yrs) < 2:
        return None
    roe, gm, om, loss = [], [], [], False
    for y in yrs:
        rev = inc[y].get("Revenue", 0.0)
        ni = inc[y].get("IncomeAfterTaxes", 0.0)
        if rev:
            gm.append(inc[y].get("GrossProfit", 0.0) / rev * 100)
            om.append(inc[y].get("OperatingIncome", 0.0) / rev * 100)
        e = eq.get(y)
        if e:
            roe.append(ni / e * 100)
        if ni < 0:
            loss = True
    if not roe or not gm:
        return None
    roe_avg, gm_avg, om_avg = sum(roe) / len(roe), sum(gm) / len(gm), sum(om) / len(om)
    gm_std = st.pstdev(gm) if len(gm) > 1 else 0.0
    s_roe = clamp((roe_avg - 5) / 20 * 100)     # ROE 5%→0、25%+→100（護城河主要指紋）
    s_stab = clamp(100 - gm_std * 8)            # 毛利率越穩越高（定價權）
    s_op = clamp(om_avg / 20 * 100)             # 營益率水準
    score = round(0.5 * s_roe + 0.25 * s_stab + 0.25 * s_op)
    if loss:                                    # 近年有虧損 → 品質封頂
        score = min(score, 50)
    word = ("頂級" if score >= 80 else "優" if score >= 65 else
            "中上" if score >= 50 else "普通" if score >= 35 else "偏弱")
    return {"score": score, "word": word, "roe": round(roe_avg, 1),
            "gm": round(gm_avg, 1), "om": round(om_avg, 1), "years": len(yrs)}


def build_stock(code, name, mkf):
    per = per_band(code)
    rd = revenue_data(code)
    ps = price_series(code)
    price = ps["last"] if ps else None
    spark = ps["spark"] if ps else None              # 近65日收盤（火花線）
    quality = quality_fingerprint(code)              # 財務指紋（品質），與綜合窗口分開
    yoy = rd["latest_yoy"] if rd else None          # 單月 YoY（計分＋顯示）
    history = rd["history"] if rd else None          # 近36月明細（圖表用）
    if per is None:  # 無本益比 → 本夢比，排除評分
        return {"code": code, "name": name, "price": price, "per": None,
                "percentile": None, "val_cheap": None, "yoy": yoy,
                "revenue_history": history, "spark": spark, "quality": quality,
                "fund": None, "composite": None, "label": "資料不足(本夢比)"}
    val_cheap = 100 - per["percentile"]
    fund = None if yoy is None else round(clamp(45 + yoy * 1.2))
    composite = round(W_VALUE * val_cheap + W_FUND * (fund if fund is not None else 45)
                      + W_MARKET * mkf)
    return {"code": code, "name": name, "price": price, "per": per["now"],
            "percentile": per["percentile"], "per_min": per["min"],
            "per_median": per["median"], "per_max": per["max"],
            "val_cheap": val_cheap, "yoy": yoy, "revenue_history": history,
            "spark": spark, "quality": quality, "fund": fund, "composite": composite,
            "label": window_label(composite)}


def main():
    mk = market_fear()
    mkf = mk.get("score", 50)
    stocks = []
    thesis = load_thesis()
    for code, name in load_watchlist():
        try:
            st_ = build_stock(code, name, mkf)
        except Exception as exc:  # noqa: BLE001 — 單檔失敗不拖垮整批
            st_ = {"code": code, "name": name, "label": f"抓取失敗: {exc}"}
        t = thesis.get(code) or {}
        st_["thesis"] = t.get("thesis", "")
        st_["brk"] = t.get("brk", "")
        stocks.append(st_)
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
