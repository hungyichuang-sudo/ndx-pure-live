#!/usr/bin/env python3
"""ndx-pure-live — 純 radj-150 Top-3(無cap)即時儀表板計算器
架構: 凍結歷史 seed.json(Sharadar PIT 2013-01→2026-06, pure2x 戰役三重驗證)
     + 即時延伸(yfinance; 決策即時記錄 = PIT-by-construction), 產出 docs/live.json
慣例(與 VPS 引擎一致): 月底收盤形成 Top-3 → 次月持有(月內 buy-hold 漂移權重);
20bps RT × 換手率, 月底乘法吸收; 2× = 月底重設, IBKR 融資假設 6.5%/yr 按日計提(僅借款部分)。
決策與已完成月份 append-only, 永不重算(PIT); 價格層可重抓(價格不變)。
"""
import json, math, os, sys, time, warnings, datetime as dt
from pathlib import Path
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

# ==== 成分清單: 每季手動對照官方 NDX-100 更新(README 有 SOP) ====
FALLBACK_NDX = ["ADBE","AMAT","CSCO","FAST","MSFT","PAYX","QCOM","ALAB","CRWV","NBIS",
"RKLB","TER","LITE","SNDK","WMT","ALNY","FER","MPWR","STX","WDC","TRI","SHOP",
"AXON","MSTR","PLTR","APP","ARM","LIN","CCEP","DASH","ROP","GEHC","BKR","FANG",
"WBD","CEG","ODFL","ABNB","FTNT","PANW","DDOG","CRWD","HON","AEP","NFLX","KDP",
"PDD","DXCM","CPRT","EXC","AMD","XEL","PEP","ASML","SNPS","TTWO","WDAY","MELI",
"IDXX","CSX","TMUS","PYPL","KHC","GOOG","NXPI","MAR","TSLA","EA","MRVL","REGN",
"META","ADI","MDLZ","TXN","AVGO","BKNG","ADP","ORLY","ROST","MNST","VRTX","ISRG",
"CDNS","GOOGL","ADSK","AMGN","LRCX","CMCSA","GILD","NVDA","AMZN","MCHP","SBUX",
"MU","INTU","AAPL","COST","CTAS","INTC","KLAC","PCAR"]
HARD_SEMI = {"NVDA","AMD","AVGO","QCOM","TXN","ADI","MU","AMAT","LRCX","KLAC","MRVL",
"NXPI","MCHP","MPWR","ARM","ASML","INTC","WDC","STX","SNDK","TER","ALAB"}
TWINS = [{"GOOGL","GOOG"}]
NDX, SEMI = list(FALLBACK_NDX), set(HARD_SEMI)  # main() 依每日自動抓取覆寫  # 同一發行人的雙類股, Top-3 去重(取 radj 較高者)

LOOKBACK, TOPN = 150, 3
COST_RT, MARGIN, LEV = 0.002, 0.065, 2.0
MC_SEED, MC_N, MC_H, MC_B = 42, 20000, 36, 3
FETCH_START = "2024-10-01"   # 首個延伸形成日(2026-06-30)前 400+ 交易日; 之後自動足夠
LIVE_ERA_FIRST_FORMATION = pd.Period("2026-06", "M")  # seed 最後持有月 = 2026-06

def fetch_constituents(cache):
    """成分自動更新: Wikipedia(主源) → FMP(備援, env FMP_API_KEY) → 快取 → 硬編 fallback。
    回傳 (tickers, 自動叢集set, 來源, 變動dict或None)。護欄: 95≤n≤110 才接受。
    叢集自動判定: 產業子分類含 'semiconductor' 字樣(新進半導體自動抓);
    記憶體/儲存(WDC/STX/SNDK等)維持 HARD_SEMI 手動名單 —— ICB/GICS 把 AAPL
    和硬碟廠放同一子分類, 用 'storage' 關鍵字會誤標蘋果, 所以不用。"""
    import requests
    tick, auto_cl, src = None, set(), None
    try:
        from bs4 import BeautifulSoup
        html = requests.get("https://en.wikipedia.org/wiki/Nasdaq-100",
            headers={"User-Agent": "Mozilla/5.0 (ndx-pure-live dashboard)"}, timeout=30).text
        soup = BeautifulSoup(html, "lxml")
        for tb in soup.find_all("table"):
            head = tb.find("tr")
            if not head:
                continue
            cols = [c.get_text(strip=True).lower() for c in head.find_all(["th", "td"])]
            ti = next((i for i, c in enumerate(cols) if "ticker" in c or "symbol" in c), None)
            if ti is None:
                continue
            gi = next((i for i, c in enumerate(cols)
                       if "subsector" in c or "sub-industry" in c or "sub industry" in c), None)
            t_, g_ = [], {}
            for r in tb.find_all("tr")[1:]:
                cells = r.find_all(["td", "th"])
                if len(cells) <= ti:
                    continue
                t = cells[ti].get_text(strip=True).replace(".", "-")
                if not t or len(t) > 6 or not t.isupper():
                    continue
                t_.append(t)
                if gi is not None and len(cells) > gi:
                    g_[t] = cells[gi].get_text(strip=True)
            if 95 <= len(t_) <= 110:
                tick = list(dict.fromkeys(t_))
                auto_cl = {x for x, g in g_.items() if "semiconductor" in g.lower()}
                src = "wikipedia"
                break
    except Exception as e:
        print(f"[WARN] Wikipedia 成分抓取失敗: {type(e).__name__} {str(e)[:120]}", file=sys.stderr)
    if tick is None and os.environ.get("FMP_API_KEY"):
        try:
            r = requests.get("https://financialmodelingprep.com/api/v3/nasdaq_constituent",
                             params={"apikey": os.environ["FMP_API_KEY"]}, timeout=30).json()
            if isinstance(r, list) and 95 <= len(r) <= 110:
                tick = list(dict.fromkeys(d["symbol"].replace(".", "-") for d in r))
                auto_cl = {d["symbol"] for d in r
                           if "semiconductor" in str(d.get("subSector", "")).lower()}
                src = "fmp"
        except Exception as e:
            print(f"[WARN] FMP 成分備援失敗: {type(e).__name__} {str(e)[:120]}", file=sys.stderr)
    if tick is None:
        tick = cache.get("tickers") or list(FALLBACK_NDX)
        auto_cl = set(cache.get("cluster_auto") or [])
        src = (cache.get("source", "hardcoded")) + "(快取沿用)"
        print(f"[WARN] 兩源皆失敗, 沿用 {src} {len(tick)} 檔", file=sys.stderr)
    changed = None
    old = set(cache.get("tickers") or [])
    if old and set(tick) != old:
        changed = {"added": sorted(set(tick) - old), "removed": sorted(old - set(tick))}
    return tick, auto_cl, src, changed


def load_json(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default

def fetch_prices(tickers):
    last_err = None
    for attempt in range(3):
        try:
            px = yf.download(sorted(set(tickers)), start=FETCH_START,
                             auto_adjust=True, progress=False)["Close"]
            if isinstance(px, pd.Series):
                px = px.to_frame()
            px = px.dropna(how="all")
            if len(px) > 100:
                return px
        except Exception as e:
            last_err = e
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"yfinance 抓價失敗(重試3次): {last_err}")

def radj_table(px, asof):
    sub = px.loc[:asof]
    uni = set(NDX)
    rows = []
    for t in sub.columns:
        if t not in uni:
            continue
        s = sub[t].dropna()
        if len(s) < LOOKBACK + 1:
            continue
        ret = float(s.iloc[-1] / s.iloc[-(LOOKBACK + 1)] - 1.0)
        vol = float(s.pct_change().dropna().iloc[-LOOKBACK:].std() * math.sqrt(252))
        if not vol or math.isnan(vol) or vol <= 0:
            continue
        rows.append({"t": t, "radj": round(ret / vol, 4),
                     "ret150": round(ret * 100, 2), "cluster": t in SEMI})
    rows.sort(key=lambda r: r["radj"], reverse=True)
    return rows

def pick_top(rows):
    """Top-3, 無 cap; 僅同發行人雙類股去重(取 radj 較高的一類)。"""
    picked, used_twin = [], set()
    for r in rows:
        skip = False
        for tw in TWINS:
            if r["t"] in tw:
                if tw & used_twin:
                    skip = True
                else:
                    used_twin |= tw & {r["t"]} or set()
                    used_twin |= {x for x in tw}
        if skip:
            continue
        picked.append(r["t"])
        if len(picked) == TOPN:
            break
    return picked

def month_ends(px):
    idx = px.index
    return idx.to_series().groupby(idx.to_period("M")).max()

def month_paths(px, holdings, formation, hold_period, prev_holdings, upto=None):
    """月內 buy-hold 漂移: eq1_t = mean(P_t/P_f0); 成本月底乘法吸收; 2× 逐日追蹤。
    upto: 若給(進行中月份), 只算到該日且不套成本。回傳 dict。"""
    P0 = px.loc[formation, holdings]
    if P0.isna().any():
        raise RuntimeError(f"{hold_period} 形成日缺價: {list(P0[P0.isna()].index)}")
    days = px.index[(px.index.to_period("M") == hold_period) & (px.index > formation)]
    if upto is not None:
        days = days[days <= upto]
    if len(days) == 0:
        return None
    rel = (px.loc[days, holdings] / P0).mean(axis=1)          # eq1(毛)路徑, 起點=1 於形成日
    gross = float(rel.iloc[-1] - 1.0)
    turnover = len(set(holdings) - set(prev_holdings)) / TOPN
    complete = upto is None
    e1 = rel.copy()
    net1 = gross
    if complete:
        net1 = (1 + gross) * (1 - COST_RT * turnover) - 1
        e1.iloc[-1] = 1 + net1                                  # 成本月底吸收
    # 2×: pos 跟隨 e1 路徑 ×2, debt 按交易日計息
    nday = np.arange(1, len(e1) + 1)
    debt = (1 + MARGIN / 252) ** nday
    pos = 2.0 * e1.values
    e2 = pos - debt
    drift = float(np.max(pos / np.maximum(e2, 1e-9)))
    return {"month": str(hold_period), "holdings": holdings,
            "cluster": [t in SEMI for t in holdings],
            "naked": all(t in SEMI for t in holdings),
            "gross": round(gross, 6), "turnover": round(turnover, 4),
            "net1": round(net1, 6), "net2": round(float(e2[-1] - 1), 6),
            "complete": complete, "max_drift": round(drift, 3),
            "dates": [d.strftime("%Y-%m-%d") for d in days],
            "e1": [round(float(x), 6) for x in e1.values],
            "e2": [round(float(x), 6) for x in e2]}

def run_mc(net2_series):
    rets = np.asarray(net2_series)
    rng = np.random.default_rng(MC_SEED)
    starts = rng.integers(0, len(rets) - MC_B + 1, size=(MC_N, MC_H // MC_B))
    paths = rets[(starts[:, :, None] + np.arange(MC_B)[None, None, :]).reshape(MC_N, MC_H)]
    eq = np.concatenate([np.ones((MC_N, 1)), np.cumprod(1 + paths, axis=1)], axis=1)
    dd = eq / np.maximum.accumulate(eq, axis=1) - 1
    mdd, term = dd.min(axis=1), eq[:, -1]
    fan = {p: [round(float(x), 4) for x in np.percentile(eq, p, axis=0)]
           for p in (5, 25, 50, 75, 95)}
    return {"median": round(float(np.median(term)), 3),
            "p_loss3y": round(float((term < 1).mean()), 4),
            "p_halve": round(float((mdd <= -0.50).mean()), 4),
            "p_barrier45": round(float((mdd <= -0.45).mean()), 4),
            "med_mdd": round(float(np.median(mdd)), 4),
            "n_months_input": int(len(rets)), "fan": fan,
            "note": "月頻 block-bootstrap(block=3,20k,seed=42)下界; 與 VPS 原版同法, RNG 實作差 ±1pp 級"}

def main():
    global NDX, SEMI
    seed = json.load(open(DOCS / "seed.json"))
    prev = load_json(DOCS / "live.json", {})
    uni_prev = prev.get("universe", {})
    NDX, auto_cl, uni_src, uni_changed = fetch_constituents(uni_prev)
    SEMI = set(HARD_SEMI) | auto_cl
    uni_log = list(uni_prev.get("log", []))
    if uni_changed:
        uni_log.append({"date": dt.date.today().isoformat(), **uni_changed})
    decisions = prev.get("extension", {}).get("decisions", [])
    months = [m for m in prev.get("extension", {}).get("months", []) if m.get("complete")]

    need = set(NDX)
    for d in decisions:
        need |= set(d["holdings"])
    for m in months:
        need |= set(m["holdings"])
    px = fetch_prices(need)
    excluded = [t for t in NDX if t not in px.columns or px[t].dropna().shape[0] < LOOKBACK + 1]
    me = month_ends(px)
    last_day = px.index[-1]
    cur_period = last_day.to_period("M")

    # 1) 決策(append-only, PIT): 對每個已「翻月」的月底補記形成決策
    have = {d["formation"] for d in decisions}
    for per, d in me.items():
        if per < LIVE_ERA_FIRST_FORMATION or per >= cur_period:
            continue  # 只有下月已開盤才確定 d 是該月最後交易日
        key = d.strftime("%Y-%m-%d")
        if key in have:
            continue
        rows = radj_table(px, d)
        h = pick_top(rows)
        decisions.append({"formation": key, "holdings": h,
                          "cluster": [t in SEMI for t in h],
                          "logged_at": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")})
        have.add(key)
    decisions.sort(key=lambda x: x["formation"])

    # 2) 已完成月份(append-only): 決策的持有月已整月結束 → 落格
    done = {m["month"] for m in months}
    seed_last_hold = seed["trades"][-1]["holdings"]
    for i, dec in enumerate(decisions):
        f = pd.Timestamp(dec["formation"])
        hold_per = f.to_period("M") + 1
        if str(hold_per) in done or hold_per >= cur_period:
            continue
        prev_h = months[-1]["holdings"] if months else seed_last_hold
        rec = month_paths(px, dec["holdings"], f, hold_per, prev_h)
        if rec:
            months.append(rec)
            done.add(rec["month"])
    months.sort(key=lambda m: m["month"])

    # 3) 進行中月份(每日刷新, 不入 append-only)
    mtd = None
    decs_past = [d for d in decisions if pd.Timestamp(d["formation"]).to_period("M") + 1 == cur_period]
    if decs_past:
        dec = decs_past[-1]
        prev_h = months[-1]["holdings"] if months else seed_last_hold
        mtd = month_paths(px, dec["holdings"], pd.Timestamp(dec["formation"]),
                          cur_period, prev_h, upto=last_day)
        if mtd:
            mtd["formation"] = dec["formation"]

    # 4) 全期統計(凍結底 + 延伸)
    st = dict(seed["stats"])
    T1, T2 = st["terminal1"], st["terminal2"]
    ext_dates, ext_e1, ext_e2 = [], [], []
    peak1, peak2 = T1, T2
    mdd1, mdd2 = st["mdd1"], st["mdd2"]
    trough_live = None
    for m in months + ([mtd] if mtd else []):
        base1, base2 = (ext_e1[-1] if ext_e1 else T1), (ext_e2[-1] if ext_e2 else T2)
        for j, dtt in enumerate(m["dates"]):
            v1, v2 = base1 * m["e1"][j], base2 * m["e2"][j]
            ext_dates.append(dtt); ext_e1.append(round(v1, 4)); ext_e2.append(round(v2, 4))
            peak1, peak2 = max(peak1, v1), max(peak2, v2)
            d2 = v2 / peak2 - 1
            if d2 < mdd2:
                mdd2, trough_live = d2, dtt
            mdd1 = min(mdd1, v1 / peak1 - 1)
    last1 = ext_e1[-1] if ext_e1 else T1
    last2 = ext_e2[-1] if ext_e2 else T2
    end_date = ext_dates[-1] if ext_dates else seed["labels"][-1]
    years = (pd.Timestamp(end_date) - pd.Timestamp(seed["labels"][0])).days / 365.25
    st.update({"cagr1": round(last1 ** (1 / years) - 1, 4),
               "cagr2": round(last2 ** (1 / years) - 1, 4),
               "mdd1": round(mdd1, 4), "mdd2": round(mdd2, 4),
               "terminal1_now": round(last1, 2), "terminal2_now": round(last2, 2),
               "years": round(years, 2),
               "worst_month2": round(min([st["worst_month2"]] + [m["net2"] for m in months]), 4),
               "max_drift": round(max([st["max_drift"]] + [m["max_drift"] for m in months]), 3),
               "naked_months": sum(t["naked"] for t in seed["trades"]) + sum(m["naked"] for m in months),
               "mdd2_span": st["mdd2_span"] if trough_live is None else f"live→{trough_live}"})

    # 5) MC(全序列)  6) 當前排名
    mc = run_mc([t["net2"] for t in seed["trades"]] + [m["net2"] for m in months])
    rows_now = radj_table(px, last_day)
    top3_now = pick_top(rows_now)
    current = {"price_date": last_day.strftime("%Y-%m-%d"),
               "rank20": rows_now[:20], "top3_now": top3_now,
               "top3_cluster": sum(t in SEMI for t in top3_now),
               "naked_now": all(t in SEMI for t in top3_now),
               "holdings": (mtd or {}).get("holdings") or (decs_past[-1]["holdings"] if decs_past else None),
               "holdings_formation": (mtd or {}).get("formation"),
               "holdings_naked": bool((mtd or {}).get("naked")),
               "mtd1": round(((mtd or {}).get("e1") or [1])[-1] - 1, 4),
               "mtd2": round(((mtd or {}).get("e2") or [1])[-1] - 1, 4)}

    live = {"as_of": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "stats": st, "mc": mc, "current": current,
            "extension": {"decisions": decisions, "months": months,
                          "curve": {"dates": ext_dates, "e1": ext_e1, "e2": ext_e2}},
            "universe": {"count": len(NDX), "source": uni_src,
                         "checked": dt.date.today().isoformat(),
                         "tickers": NDX, "cluster_auto": sorted(auto_cl),
                         "hard_semi": sorted(HARD_SEMI), "log": uni_log},
            "excluded_tickers": excluded,
            "seam": "2026-06 以前=Sharadar PIT(凍結, 含下市股); 2026-07 起=yfinance 即時口徑(決策即時記錄=PIT)"}
    json.dump(live, open(DOCS / "live.json", "w"), ensure_ascii=False)
    print(f"[OK] 成分 {len(NDX)}檔({uni_src}) 自動叢集 {len(auto_cl)}檔 | 變動 {uni_changed or '無'}")
    print(f"[OK] live.json | 價格日 {current['price_date']} | 持倉 {current['holdings']}"
          f" MTD2× {current['mtd2']*100:+.2f}% | 今日Top3 {top3_now} 叢集 {current['top3_cluster']}/3"
          f" | CAGR2× {st['cagr2']*100:.1f}% MDD2× {st['mdd2']*100:.1f}% | MC腰斬 {mc['p_halve']*100:.1f}%")
    if excluded:
        print(f"[WARN] 資料不足排除: {excluded}", file=sys.stderr)

if __name__ == "__main__":
    main()
