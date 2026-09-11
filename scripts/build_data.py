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
import re
import statistics as st
import sys
from pathlib import Path
from urllib import error, parse, request

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")
ROOT = Path(__file__).resolve().parents[1]

# 進場時機權重（透明、未回測調參；故意笨而誠實，避免過度擬合）
W_VALUE, W_FUND, W_MARKET = 0.40, 0.25, 0.35

PER_DEFAULT_DAYS = 1825    # 本益比位階的預設比較區間（近 5 年）
PER_MIN_SAMPLES = 200      # 自訂區間的樣本下限（一年約 245 個交易日），不足就退回預設
SINCE_RE = re.compile(r"@since=(\d{4})-(\d{2})(?:-(\d{2}))?")


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
    """每行一檔：`CODE  # 名稱 [@since=YYYY-MM 理由]`；# 開頭整行為註解。

    @since 把「本益比位階」的比較起點釘死在某一天（預設是近 5 年的滾動區間）。
    只該用在業態真的變過、舊資料不可比的股票上。

    ［決策 2026-09-11｜需求人］@since 必須附理由，沒寫理由就不生效。
      前提：比較區間是「能把任何股票調到看起來便宜」的參數。實測 2026-09-11：
        全域從 5 年改 3 年，追蹤清單 8 檔「全部」變便宜、沒有一檔變貴
        （富喬 51→67 直接跨進「打折中」），而且跟是不是 AI 股無關——
        縮區間的實際效果是刪掉 2021–22 的低估值年代，不是校正業態。
      已知代價：想臨時試不同區間會很麻煩，得先寫個理由進 watchlist。這是刻意的摩擦。
      ⇒ 排錯線索：某檔位階看起來不合理時，先看卡片上標的區間是不是被改過。

    用固定起始日而非「近 N 年」：業態改變是事件，不是滾動窗。寫「近 3 年」的話
    明年會自動變成從隔年起算，基準會無聲漂移。

    回傳 [{code, name, since, why}, ...]
    """
    out = []
    path = ROOT / "watchlist.txt"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        code, _, comment = line.partition("#")
        code = code.strip()
        if not code:
            continue
        since = why = None
        m = SINCE_RE.search(comment)
        if m:
            name = comment[:m.start()].strip()
            why = comment[m.end():].strip()
            try:
                since = dt.date(int(m.group(1)), int(m.group(2)),
                                int(m.group(3) or 1)).isoformat()
            except ValueError:
                print(f"::warning::{code} 的 {m.group(0)} 不是有效日期，忽略")
                since = None
            if since and not why:
                print(f"::warning::{code} 設了 {m.group(0)} 但沒寫理由 → 不生效（理由必填）")
                since = None
        else:
            name = comment.strip()
        out.append({"code": code, "name": name, "since": since, "why": why})
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

    margin_note = margin_context()

    tag = "恐慌(機會)" if score >= 65 else "中性" if score >= 40 else "貪婪(該收手)"
    return {"score": score, "tag": tag, "close": round(c), "bias": round(bias, 1),
            "dd": round(dd, 1), "vol": round(vol, 1), "date": rows[-1]["date"],
            "margin_note": margin_note}


def margin_context():
    """融資餘額：近一年位階 ＋ 近一月變化。純顯示、不進任何分數。

    ［決策 2026-09-09｜需求人］不用「距某個基準日 +N%」的講法。
      前提：基準日若跟著產出日往前滑，百分比會混進「基準自己在動」的雜訊。
        實例：2026-09-03→09-09，融資餘額只從 5857 億變 5863 億（+0.1%），
        但舊寫法顯示的數字從 +161% 掉到 +158%，看起來像降溫、方向還是反的。
      已知代價：位階需要一整年的樣本，上市未滿一年或 FinMind 缺資料時就顯示不出來。
      ⇒ 排錯線索：這裡刻意「自己抓自己的區間」，不要再共用 market_fear() 的 start
        （舊版就是沿用那個 420 天視窗，才讓基準日變成沒有意義的『420 天前』）。
    """
    start = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    rows = _get("TaiwanStockTotalMarginPurchaseShortSale", None, start)
    if isinstance(rows, dict):
        return ""
    rows = sorted([r for r in rows if r.get("name") == "MarginPurchaseMoney"],
                  key=lambda x: x["date"])
    rows = [r for r in rows if r.get("TodayBalance")]
    if len(rows) < 60:
        return ""
    last = rows[-1]
    cut = (dt.date.fromisoformat(last["date"]) - dt.timedelta(days=365)).isoformat()
    win = [r["TodayBalance"] / 1e8 for r in rows if r["date"] >= cut]
    if len(win) < 200:          # 一年約 240 個交易日；樣本不足就別謊稱「近一年位階」
        return ""
    now = last["TodayBalance"] / 1e8
    pctl = round(sum(1 for v in win if v <= now) / len(win) * 100)
    # 用 " · " 分段，前端會拆成獨立區塊各自換行（不然「位階」和「91%」會被拆兩行）
    note = f"融資餘額 {now:.0f} 億 · 近一年位階 {pctl}%（{min(win):.0f}–{max(win):.0f}）"

    m1 = (dt.date.fromisoformat(last["date"]) - dt.timedelta(days=30)).isoformat()
    prior = [r for r in rows if r["date"] <= m1]
    if prior and prior[-1]["TodayBalance"]:
        chg = (last["TodayBalance"] / prior[-1]["TodayBalance"] - 1) * 100
        note += f" · 近一月 {chg:+.0f}%"
    return note


def per_band(code, since=None):
    """本益比位階。since 有給就從那天起算，否則用預設的近 5 年。

    樣本不足 PER_MIN_SAMPLES 就退回預設區間並警告——樣本太少的百分位是雜訊。
    回傳的 since 是「實際生效」的起算日；退回預設時為 None，前端才不會標錯。
    """
    default_start = (dt.date.today() - dt.timedelta(days=PER_DEFAULT_DAYS)).isoformat()
    rows = _get("TaiwanStockPER", code, min(since, default_start) if since else default_start)
    if isinstance(rows, dict) or not rows:
        return None
    rows = sorted(rows, key=lambda x: x["date"])
    good = [r for r in rows if r.get("PER") not in (None, 0)]
    if not good:
        return None
    now = good[-1]["PER"]          # 取最後一筆「有效」的，不是最後一筆（那筆可能是 0/None）

    start, eff = (since or default_start), since
    vals = [r["PER"] for r in good if r["date"] >= start]
    if since and len(vals) < PER_MIN_SAMPLES:
        print(f"::warning::{code} 自 {since} 起只有 {len(vals)} 筆本益比"
              f"（低於 {PER_MIN_SAMPLES}），退回近 5 年")
        start, eff = default_start, None
        vals = [r["PER"] for r in good if r["date"] >= start]
    if not vals:
        return None
    below = sum(1 for v in vals if v <= now)
    return {"now": round(now, 2), "percentile": round(below / len(vals) * 100),
            "min": round(min(vals), 1), "median": round(sorted(vals)[len(vals) // 2], 1),
            "max": round(max(vals), 1), "since": eff, "n": len(vals)}


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


def load_prev(mk_date):
    """讀「上一份」docs/data.json，取出各檔 composite 與市場分數，供網站顯示 ▲▼ 變化量。

    同一交易日重跑（例如改了 watchlist 觸發 Action）時，沿用舊檔自己的 prev，
    不要拿「今天早上的自己」當基準——否則變化量會被洗成 0，等於失去昨天的比較點。
    抓不到就回空的，前端會自動不顯示變化量。
    """
    p = ROOT / "docs" / "data.json"
    if not p.exists():
        return {}
    try:
        old = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 舊檔壞掉不該擋住這次產出
        return {}
    old_date = (old.get("market") or {}).get("date")
    if old_date and mk_date and old_date == mk_date:
        return old.get("prev") or {}
    return {
        "date": old_date,
        "market": (old.get("market") or {}).get("score"),
        "stocks": {s["code"]: s["composite"] for s in old.get("stocks", [])
                   if s.get("code") and s.get("composite") is not None},
    }


def window_label(score):
    if score >= 65:
        return "時機佳（便宜＋恐慌）"
    if score >= 45:
        return "普通（中性）"
    return "時機差（貴＋貪婪）"


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
    與『基本面(短期營收動能)』互補；刻意不併入進場時機。抓不到回 None。"""
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


def build_stock(code, name, mkf, since=None, why=None):
    per = per_band(code, since)
    rd = revenue_data(code)
    ps = price_series(code)
    price = ps["last"] if ps else None
    spark = ps["spark"] if ps else None              # 近65日收盤（火花線）
    quality = quality_fingerprint(code)              # 財務指紋（品質），與進場時機分開
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
            "per_since": per["since"], "per_why": why if per["since"] else None,
            "per_n": per["n"],
            "val_cheap": val_cheap, "yoy": yoy, "revenue_history": history,
            "spark": spark, "quality": quality, "fund": fund, "composite": composite,
            "label": window_label(composite)}


def main():
    mk = market_fear()
    mkf = mk.get("score", 50)
    prev = load_prev(mk.get("date"))   # 先讀，等一下才會覆寫 data.json
    stocks = []
    thesis = load_thesis()
    for item in load_watchlist():
        code, name = item["code"], item["name"]
        try:
            st_ = build_stock(code, name, mkf, item["since"], item["why"])
        except Exception as exc:  # noqa: BLE001 — 單檔失敗不拖垮整批
            st_ = {"code": code, "name": name, "label": f"抓取失敗: {exc}"}
        t = thesis.get(code) or {}
        st_["thesis"] = t.get("thesis", "")
        st_["brk"] = t.get("brk", "")
        stocks.append(st_)
    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "market": mk,
        "prev": prev,
        "stocks": stocks,
        "weights": {"value": W_VALUE, "fund": W_FUND, "market": W_MARKET},
        "disclaimer": "溫度計不是買賣訊號。沒有模型能可靠擇時；它只給情境傾向。非投資建議，決策與風險自負。",
    }
    out = ROOT / "docs" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    base = prev.get("date") or "無（第一次產出）"
    print(f"wrote {out}  (市場恐慌 {mkf}, {len(stocks)} 檔, 變化量基準 {base}, "
          f"token={'yes' if TOKEN else 'no'})")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
