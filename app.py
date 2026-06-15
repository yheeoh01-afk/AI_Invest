import os
import re
import json
import html
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st

APP_VERSION = "V11.4 Supply Diagnostic"
DATA_ROOT = os.environ.get("AI_INVEST_DATA_DIR", "user_data")
PORTFOLIO_COLUMNS = ["종목명", "종목코드", "수량", "평균매수가", "투자액"]
WATCHLIST_COLUMNS = ["그룹", "종목명", "종목코드", "메모"]

MANUAL_TICKER_MAP = {
    "엘지씨엔에스": "064400", "lg씨엔에스": "064400", "lgcns": "064400", "lg cns": "064400",
    "현대차": "005380", "lg이노텍": "011070", "엘지이노텍": "011070", "코오롱인더": "120110",
    "에스피지": "058610", "삼성전자": "005930", "posco홀딩스": "005490", "포스코홀딩스": "005490",
    "셀트리온": "068270", "한화솔루션": "009830", "naver": "035420", "네이버": "035420",
    "디아이씨": "092200", "lg에너지솔루션": "373220", "엘지에너지솔루션": "373220", "삼성전기": "009150",
    "브이티": "018290", "현대건설": "000720", "케이엠더블유": "032500", "현대모비스": "012330",
    "오이솔루션": "138080", "두산에너빌리티": "034020", "lg화학": "051910", "솔루스첨단소재": "336370",
    "jyp ent.": "035900", "jyp ent": "035900", "제이와이피": "035900", "기가비스": "420770",
    "뷰노": "338220", "제우스": "079370", "에코앤드림": "101360", "서진시스템": "178320",
    "하이비젼시스템": "126700", "심텍": "222800", "덕산네오룩스": "213420", "아비코전자": "036010",
    "현대오토에버": "307950", "텔레칩스": "054450",
}

st.set_page_config(page_title="AI 투자비서 Web", page_icon="📈", layout="wide")

# -----------------------------
# 공통 유틸
# -----------------------------
def safe_username(name: str) -> str:
    name = str(name).strip().lower()
    return re.sub(r"[^a-z0-9가-힣_-]+", "_", name)[:40] or "user"


def to_number(value):
    if pd.isna(value):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("원", "").strip()
    if not text:
        return 0
    try:
        return float(text)
    except Exception:
        return 0


def money(value):
    try:
        return f"{int(round(float(value))):,}원"
    except Exception:
        return "-"


def pct(value):
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "-"


def clean_html(text):
    text = html.unescape(str(text))
    text = re.sub(r"<.*?>", "", text)
    return text.strip()


def read_csv_any(file_or_path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(file_or_path, encoding=enc)
        except UnicodeDecodeError:
            if hasattr(file_or_path, "seek"):
                file_or_path.seek(0)
            continue
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    if hasattr(file_or_path, "seek"):
        file_or_path.seek(0)
    return pd.read_csv(file_or_path)


def lazy_stock():
    # 앱 시작 속도를 위해 pykrx는 분석 버튼을 누를 때만 import합니다.
    try:
        from pykrx import stock
        return stock
    except ModuleNotFoundError as e:
        if "pkg_resources" in str(e):
            raise RuntimeError("requirements.txt에 setuptools==69.5.1 이 설치되어야 합니다. Streamlit Cloud에서 Clear cache 후 Reboot 해주세요.")
        raise


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def get_all_ticker_name_map():
    stock = lazy_stock()
    result = {}
    for market in ["KOSPI", "KOSDAQ", "KONEX"]:
        try:
            tickers = stock.get_market_ticker_list(market=market)
            for ticker in tickers:
                name = stock.get_market_ticker_name(ticker)
                result[str(name).lower()] = ticker
                result[str(name).replace(" ", "").lower()] = ticker
        except Exception:
            pass
    for k, v in MANUAL_TICKER_MAP.items():
        result[k.lower()] = v
        result[k.replace(" ", "").lower()] = v
    return result


def find_ticker(company_name, ticker_hint=""):
    ticker_hint = str(ticker_hint).replace(".0", "").strip()
    if ticker_hint and ticker_hint.lower() not in ["nan", "none", "000000"]:
        return ticker_hint.zfill(6) if ticker_hint.isdigit() else ticker_hint
    if not company_name:
        return ""
    name = str(company_name).strip()
    compact = name.replace(" ", "").lower()
    if compact.isdigit():
        return compact.zfill(6)
    if name.lower() in MANUAL_TICKER_MAP:
        return MANUAL_TICKER_MAP[name.lower()]
    if compact in MANUAL_TICKER_MAP:
        return MANUAL_TICKER_MAP[compact]
    try:
        mapping = get_all_ticker_name_map()
        return mapping.get(name.lower()) or mapping.get(compact) or ""
    except Exception:
        return ""


def normalize_portfolio(df):
    df = df.copy() if df is not None else pd.DataFrame()
    rename_map = {"종목": "종목명", "평균가": "평균매수가", "평균단가": "평균매수가", "매수가": "평균매수가"}
    df = df.rename(columns=rename_map)
    for col in PORTFOLIO_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ["종목명", "종목코드"] else 0
    df = df[PORTFOLIO_COLUMNS].copy()
    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    df["종목코드"] = df["종목코드"].fillna("").astype(str).str.replace(".0", "", regex=False).str.strip()
    df.loc[df["종목코드"].isin(["nan", "None", "000000"]), "종목코드"] = ""
    # 빠른 보정: 수동표 우선, 전체 시장 조회는 저장/업로드 시 한 번만 필요할 때 실행
    for idx, row in df.iterrows():
        if not str(row["종목코드"]).strip():
            t = find_ticker(row["종목명"])
            if t:
                df.at[idx, "종목코드"] = t
    df.loc[df["종목코드"] != "", "종목코드"] = df.loc[df["종목코드"] != "", "종목코드"].astype(str).str.zfill(6)
    df["수량"] = df["수량"].apply(to_number).astype(int)
    df["평균매수가"] = df["평균매수가"].apply(to_number)
    df = df[df["종목명"] != ""].reset_index(drop=True)
    df["투자액"] = df["수량"] * df["평균매수가"]
    return df[PORTFOLIO_COLUMNS]


def normalize_watchlist(df):
    df = df.copy() if df is not None else pd.DataFrame()
    df = df.rename(columns={"종목": "종목명", "관심그룹": "그룹", "그룹명": "그룹", "비고": "메모"})
    for col in WATCHLIST_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[WATCHLIST_COLUMNS].copy()
    df["그룹"] = df["그룹"].fillna("기본").astype(str).str.strip().replace("", "기본")
    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    df["종목코드"] = df["종목코드"].fillna("").astype(str).str.replace(".0", "", regex=False).str.strip()
    for idx, row in df.iterrows():
        if not str(row["종목코드"]).strip():
            t = find_ticker(row["종목명"])
            if t:
                df.at[idx, "종목코드"] = t
    df.loc[df["종목코드"] != "", "종목코드"] = df.loc[df["종목코드"] != "", "종목코드"].astype(str).str.zfill(6)
    df["메모"] = df["메모"].fillna("").astype(str)
    return df[df["종목명"] != ""].reset_index(drop=True)


def user_paths():
    user = safe_username(st.session_state.get("user_id", "default"))
    user_dir = os.path.join(DATA_ROOT, user)
    os.makedirs(user_dir, exist_ok=True)
    return user, user_dir, os.path.join(user_dir, "portfolio.csv"), os.path.join(user_dir, "watchlist.csv")


def ensure_file(path, columns, root_fallback=None):
    """사용자별 CSV가 없으면 생성합니다.
    GitHub 루트에 portfolio.csv/watchlist.csv가 있으면 최초 1회 복사해 초기 데이터로 사용합니다.
    """
    if os.path.exists(path):
        return
    if root_fallback and os.path.exists(root_fallback):
        try:
            df = read_csv_any(root_fallback)
            df.to_csv(path, index=False, encoding="utf-8-sig")
            return
        except Exception:
            pass
    pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def load_portfolio():
    _, _, path, _ = user_paths()
    ensure_file(path, PORTFOLIO_COLUMNS, root_fallback="portfolio.csv")
    df = read_csv_any(path)
    return normalize_portfolio(df)


def save_portfolio(df):
    _, _, path, _ = user_paths()
    df = normalize_portfolio(df)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    st.cache_data.clear()
    return df


def load_watchlist():
    _, _, _, path = user_paths()
    ensure_file(path, WATCHLIST_COLUMNS, root_fallback="watchlist.csv")
    return normalize_watchlist(read_csv_any(path))


def save_watchlist(df):
    _, _, _, path = user_paths()
    df = normalize_watchlist(df)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    st.cache_data.clear()
    return df

# -----------------------------
# 로그인
# -----------------------------
def get_login_users():
    users = {}
    try:
        raw = st.secrets.get("USERS", None)
        if raw:
            users.update(json.loads(raw) if isinstance(raw, str) else dict(raw))
        if "users" in st.secrets:
            users.update(dict(st.secrets["users"]))
    except Exception:
        pass
    return {str(k): str(v) for k, v in (users or {"admin": "1234"}).items()}


def login_gate():
    if st.session_state.get("logged_in"):
        return
    st.title("📈 AI 투자비서 웹버전 V11.2")
    st.caption("CSV 전용 빠른 안정버전입니다. 앱 시작 때 무거운 분석을 하지 않습니다.")
    with st.form("login_form"):
        user_id = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
    if submitted:
        users = get_login_users()
        if user_id in users and users[user_id] == str(password):
            st.session_state.logged_in = True
            st.session_state.user_id = user_id
            st.rerun()
        st.error("아이디 또는 비밀번호가 맞지 않습니다.")
    st.info("Streamlit Cloud의 App settings → Secrets에 USERS와 NAVER API 키를 넣어주세요.")
    st.stop()

# -----------------------------
# 분석 함수: 버튼 누를 때만 실행
# -----------------------------
@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_price_data(ticker, days=220):
    stock = lazy_stock()
    end = datetime.today()
    start = end - timedelta(days=days * 2)
    df = stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df["MA5"] = df["종가"].rolling(5).mean()
    df["MA10"] = df["종가"].rolling(10).mean()
    df["MA20"] = df["종가"].rolling(20).mean()
    df["MA60"] = df["종가"].rolling(60).mean()
    delta = df["종가"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    df["RSI"] = 100 - (100 / (1 + rs))
    ema12 = df["종가"].ewm(span=12, adjust=False).mean()
    ema26 = df["종가"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    return df


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_supply_data(ticker, days=45):
    """외국인/기관 순매수 데이터.
    V11.3: PyKRX에서 detail=True를 우선 사용합니다.
    일부 환경에서 기본 호출은 외국인/기관 컬럼이 빠지거나 0으로 내려오는 경우가 있어
    상세 투자자별 데이터를 받아서 기관 합계를 직접 계산합니다.
    """
    stock = lazy_stock()
    end = datetime.today()
    start = end - timedelta(days=days * 4)
    start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    candidates = []

    # 1순위: 거래량, 상세 투자자별. 가장 안정적입니다.
    try:
        df = stock.get_market_trading_volume_by_date(start_s, end_s, ticker, detail=True)
        if df is not None and not df.empty:
            candidates.append(df.copy())
    except Exception:
        pass

    # 2순위: 거래량, 기본 합계형
    try:
        df = stock.get_market_trading_volume_by_date(start_s, end_s, ticker)
        if df is not None and not df.empty:
            candidates.append(df.copy())
    except Exception:
        pass

    # 3순위: 거래대금, 상세 투자자별
    try:
        df = stock.get_market_trading_value_by_date(start_s, end_s, ticker, detail=True)
        if df is not None and not df.empty:
            candidates.append(df.copy())
    except Exception:
        pass

    # 4순위: 거래대금, 기본 합계형
    try:
        df = stock.get_market_trading_value_by_date(start_s, end_s, ticker)
        if df is not None and not df.empty:
            candidates.append(df.copy())
    except Exception:
        pass

    if not candidates:
        return pd.DataFrame()

    def clean_num(series):
        return pd.to_numeric(
            series.astype(str)
            .str.replace(",", "", regex=False)
            .str.replace(" ", "", regex=False)
            .str.replace("−", "-", regex=False),
            errors="coerce"
        ).fillna(0)

    def normalize_one(df):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        cols = list(df.columns)
        col_text = {c: str(c).replace(" ", "") for c in cols}

        def find_col(names):
            names = [str(n).replace(" ", "") for n in names]
            for target in names:
                for c, t in col_text.items():
                    if t == target:
                        return c
            for target in names:
                for c, t in col_text.items():
                    if target in t:
                        return c
            return None

        # 외국인은 상세형에서는 외국인, 기본형에서는 외국인합계로 내려옵니다.
        foreign_col = find_col(["외국인합계", "외국인"])

        # 기본형에는 기관합계가 있을 수 있습니다.
        inst_col = find_col(["기관합계", "기관"])

        out = pd.DataFrame(index=df.index)
        out["외국인"] = clean_num(df[foreign_col]) if foreign_col is not None else 0

        if inst_col is not None:
            out["기관"] = clean_num(df[inst_col])
        else:
            # 상세형에서는 기관합계가 없어서 기관 구성 항목을 직접 합산합니다.
            inst_names = [
                "금융투자", "보험", "투신", "사모", "은행", "기타금융",
                "연기금", "연기금등", "연기금 등", "국가지자체", "국가·지자체",
            ]
            inst_sum = pd.Series(0, index=df.index, dtype="float64")
            used = set()
            for name in inst_names:
                c = find_col([name])
                if c is not None and c not in used:
                    inst_sum = inst_sum + clean_num(df[c])
                    used.add(c)
            out["기관"] = inst_sum

        out["외국인_누적"] = out["외국인"].cumsum()
        out["기관_누적"] = out["기관"].cumsum()
        return out.tail(days)

    # 후보 중 실제 수급값이 있는 첫 데이터를 사용합니다.
    normalized = [normalize_one(df) for df in candidates]
    for out in normalized:
        if out is not None and not out.empty and (out["외국인"].abs().sum() > 0 or out["기관"].abs().sum() > 0):
            return out

    # 값이 전부 0이면 첫 후보라도 반환해서 빈 데이터와 구분합니다.
    return normalized[0] if normalized else pd.DataFrame()


def analyze_sell_signal(price_df, supply_df=None):
    if price_df is None or len(price_df) < 60:
        return "데이터 부족", []
    latest = price_df.iloc[-1]
    prev = price_df.iloc[-2]
    close, ma5, ma10, ma20, ma60 = latest.get("종가"), latest.get("MA5"), latest.get("MA10"), latest.get("MA20"), latest.get("MA60")
    level, signals = 0, []
    if pd.notna(ma5) and close < ma5:
        level = max(level, 1); signals.append("5일선 이탈")
    if pd.notna(ma10) and close < ma10:
        level = max(level, 1); signals.append("10일선 이탈")
    if pd.notna(ma20) and close < ma20:
        level = max(level, 2); signals.append("20일선 이탈")
    if pd.notna(prev.get("MA5")) and pd.notna(prev.get("MA20")) and pd.notna(ma5) and pd.notna(ma20) and prev["MA5"] >= prev["MA20"] and ma5 < ma20:
        level = max(level, 2); signals.append("5/20 데드크로스")
    if pd.notna(ma20) and pd.notna(ma60) and ma20 < ma60:
        level = max(level, 3 if level >= 2 else 2); signals.append("20일선 < 60일선")
    if supply_df is not None and not supply_df.empty:
        f5, i5 = supply_df["외국인"].tail(5).sum(), supply_df["기관"].tail(5).sum()
        if f5 < 0 and i5 < 0:
            level = max(level, 2); signals.append("외국인·기관 5일 동반매도")
    if level >= 3: return "🔴 매도", signals
    if level == 2: return "🟠 경고", signals
    if level == 1: return "🟡 주의", signals
    if pd.notna(ma5) and pd.notna(ma20) and pd.notna(ma60) and ma5 > ma20 > ma60:
        return "🟢 양호", ["정배열 유지"]
    return "🟢 양호", []


def analyze_buy_signal(price_df, supply_df=None):
    if price_df is None or len(price_df) < 60:
        return "데이터 부족", [], 0
    latest = price_df.iloc[-1]
    prev = price_df.iloc[-2]
    score, signals = 0, []
    close, ma5, ma10, ma20, ma60 = latest.get("종가"), latest.get("MA5"), latest.get("MA10"), latest.get("MA20"), latest.get("MA60")
    rsi, macd, macd_signal = latest.get("RSI"), latest.get("MACD"), latest.get("MACD_SIGNAL")
    if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
        if close > ma5 > ma10: score += 20; signals.append("단기 상승추세")
        if ma5 > ma10 > ma20: score += 20; signals.append("이동평균 정배열")
    if pd.notna(prev.get("MA5")) and pd.notna(prev.get("MA20")) and pd.notna(ma5) and pd.notna(ma20) and prev["MA5"] <= prev["MA20"] and ma5 > ma20:
        score += 25; signals.append("골든크로스")
    if pd.notna(ma20) and pd.notna(ma60) and ma20 > ma60:
        score += 15; signals.append("20일선이 60일선 위")
    if pd.notna(rsi):
        if 30 <= rsi <= 55: score += 15; signals.append("RSI 매수 관심 구간")
        elif rsi < 30: score += 10; signals.append("RSI 과매도")
        elif rsi > 75: score -= 15; signals.append("RSI 과열 주의")
    if pd.notna(macd) and pd.notna(macd_signal) and macd > macd_signal:
        score += 15; signals.append("MACD 상승 전환")
    if supply_df is not None and not supply_df.empty:
        f5, i5 = supply_df["외국인"].tail(5).sum(), supply_df["기관"].tail(5).sum()
        f20, i20 = supply_df["외국인"].tail(20).sum(), supply_df["기관"].tail(20).sum()
        if f5 > 0 and i5 > 0: score += 20; signals.append("외국인·기관 단기 동반매수")
        elif f20 > 0 and i20 > 0: score += 15; signals.append("외국인·기관 중기 동반매수")
        elif f5 < 0 and i5 < 0: score -= 20; signals.append("외국인·기관 동반매도 주의")
    grade = "강한 매수 관심" if score >= 80 else "매수 관심" if score >= 55 else "관찰" if score >= 35 else "약함" if score >= 15 else "매수신호 없음"
    return grade, signals, score


def supply_summary(supply_df):
    if supply_df is None or supply_df.empty:
        return 0, 0, "데이터 없음"
    f5, i5 = supply_df["외국인"].tail(5).sum(), supply_df["기관"].tail(5).sum()
    f20, i20 = supply_df["외국인"].tail(20).sum(), supply_df["기관"].tail(20).sum()
    if f5 > 0 and i5 > 0 and f20 > 0 and i20 > 0: sig = "강한 매수"
    elif f5 > 0 and i5 > 0: sig = "단기 동반매수"
    elif f5 < 0 and i5 < 0: sig = "동반매도 주의"
    elif f5 > 0 and i5 < 0: sig = "외국인 매수/기관 매도"
    elif f5 < 0 and i5 > 0: sig = "기관 매수/외국인 매도"
    else: sig = "중립"
    return f5, i5, sig


def analyze_portfolio(df, include_supply=True):
    rows = []
    progress = st.progress(0)
    total = max(len(df), 1)
    for n, (_, row) in enumerate(df.iterrows(), start=1):
        name = str(row.get("종목명", ""))
        ticker = find_ticker(name, row.get("종목코드", ""))
        price_df = get_price_data(ticker) if ticker else pd.DataFrame()
        supply_df = get_supply_data(ticker) if include_supply and ticker else pd.DataFrame()
        current = float(price_df["종가"].iloc[-1]) if price_df is not None and not price_df.empty else 0
        qty = int(to_number(row.get("수량", 0)))
        avg = float(to_number(row.get("평균매수가", 0)))
        invest = qty * avg
        eval_amt = qty * current
        pl = eval_amt - invest
        pl_pct = (pl / invest * 100) if invest else 0
        buy_grade, buy_detail, buy_score = analyze_buy_signal(price_df, supply_df)
        sell_grade, sell_detail = analyze_sell_signal(price_df, supply_df)
        f5, i5, s_sig = supply_summary(supply_df)
        rows.append({
            "종목명": name, "종목코드": ticker, "수량": qty, "평균매수가": int(avg), "현재가": int(current),
            "투자액": int(invest), "평가금액": int(eval_amt), "평가손익": int(pl), "수익률%": round(pl_pct, 2),
            "매수신호": buy_grade, "매수점수": buy_score, "매도신호": sell_grade,
            "외국인5일": int(f5) if include_supply else "-", "기관5일": int(i5) if include_supply else "-", "수급신호": s_sig if include_supply else "수급 미분석",
            "매수상세": ", ".join(buy_detail), "매도상세": ", ".join(sell_detail),
        })
        progress.progress(n / total)
    progress.empty()
    return pd.DataFrame(rows)

# -----------------------------
# 뉴스
# -----------------------------
def get_naver_keys():
    try:
        return st.secrets.get("NAVER_CLIENT_ID"), st.secrets.get("NAVER_CLIENT_SECRET")
    except Exception:
        return None, None


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_news(company_name, display=5):
    cid, secret = get_naver_keys()
    if not cid or not secret:
        return []
    try:
        res = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret},
            params={"query": company_name, "display": display, "sort": "date"}, timeout=10,
        )
        res.raise_for_status()
        return [{"제목": clean_html(i.get("title", "")), "링크": i.get("originallink") or i.get("link"), "날짜": i.get("pubDate", "")} for i in res.json().get("items", [])]
    except Exception:
        return []

# -----------------------------
# UI
# -----------------------------
login_gate()
user, user_dir, portfolio_path, watchlist_path = user_paths()

with st.sidebar:
    st.subheader("메뉴")
    st.success(f"로그인: {user}")
    if st.button("🚪 로그아웃"):
        st.session_state.clear(); st.rerun()
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear(); st.rerun()
    st.divider()
    st.caption("CSV 파일")
    st.code(portfolio_path)
    st.caption("관심그룹 CSV 파일")
    st.code(watchlist_path)
    st.caption("V11은 Supabase를 사용하지 않습니다. 앱 시작 속도를 위해 분석은 버튼을 누를 때만 실행합니다.")



def supply_raw_diagnostics(ticker, days=45):
    """Streamlit Cloud에서 PyKRX 수급 원본이 어떻게 내려오는지 확인하는 진단 함수."""
    stock = lazy_stock()
    end = datetime.today()
    start = end - timedelta(days=days * 4)
    start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    tests = [
        ("거래량 detail=True", "get_market_trading_volume_by_date", {"detail": True}),
        ("거래량 기본", "get_market_trading_volume_by_date", {}),
        ("거래대금 detail=True", "get_market_trading_value_by_date", {"detail": True}),
        ("거래대금 기본", "get_market_trading_value_by_date", {}),
    ]
    results = []
    for label, fn_name, kwargs in tests:
        item = {"label": label, "fn": fn_name, "kwargs": kwargs}
        try:
            fn = getattr(stock, fn_name)
            df = fn(start_s, end_s, ticker, **kwargs)
            if df is None:
                item.update({"ok": False, "error": "반환값 None", "df": pd.DataFrame()})
            elif df.empty:
                item.update({"ok": True, "empty": True, "shape": df.shape, "columns": list(map(str, df.columns)), "df": df})
            else:
                df2 = df.copy()
                try:
                    df2.index = pd.to_datetime(df2.index)
                except Exception:
                    pass
                item.update({
                    "ok": True,
                    "empty": False,
                    "shape": df2.shape,
                    "columns": list(map(str, df2.columns)),
                    "df": df2,
                })
        except Exception as e:
            item.update({"ok": False, "error": repr(e), "df": pd.DataFrame()})
        results.append(item)
    return results


def summarize_supply_raw(df):
    """원본 수급 DF의 숫자 합계를 보기 쉽게 요약."""
    if df is None or df.empty:
        return pd.DataFrame()
    tmp = df.copy()
    rows = []
    for col in tmp.columns:
        ser = pd.to_numeric(
            tmp[col].astype(str)
            .str.replace(",", "", regex=False)
            .str.replace(" ", "", regex=False)
            .str.replace("−", "-", regex=False),
            errors="coerce"
        ).fillna(0)
        rows.append({"컬럼명": str(col), "최근5일합": ser.tail(5).sum(), "최근20일합": ser.tail(20).sum(), "전체합": ser.sum()})
    return pd.DataFrame(rows)

st.title(f"📈 AI 투자비서 Web {APP_VERSION}")
st.caption("Supabase 제거 · 사용자별 CSV 저장 · 포트폴리오 즉시 표시 · 분석은 버튼 실행")

tab_port, tab_watch, tab_stock, tab_news, tab_diag = st.tabs(["📊 포트폴리오", "⭐ 관심그룹", "🔍 종목분석", "📰 뉴스", "🧪 수급진단"])

with tab_port:
    st.subheader("포트폴리오 현황")
    portfolio_df = load_portfolio()
    if portfolio_df.empty:
        st.info("아직 등록된 종목이 없습니다. 아래에서 추가하거나 CSV를 업로드하세요.")
    else:
        show_df = portfolio_df.copy()
        show_df["투자액"] = show_df["투자액"].astype(int)
        st.dataframe(show_df, use_container_width=True, hide_index=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("종목 수", f"{len(portfolio_df)}개")
        c2.metric("총 투자액", money(portfolio_df["투자액"].sum()))
        c3.download_button("⬇️ portfolio.csv 다운로드", portfolio_df.to_csv(index=False, encoding="utf-8-sig"), "portfolio.csv", "text/csv")

    with st.expander("➕ 포트폴리오 추가/수정/삭제", expanded=portfolio_df.empty):
        st.markdown("### 종목 추가")
        with st.form("add_portfolio"):
            col1, col2, col3, col4 = st.columns(4)
            name = col1.text_input("종목명", placeholder="예: 삼성전자")
            ticker = col2.text_input("종목코드(선택)", placeholder="예: 005930")
            qty = col3.number_input("수량", min_value=0, step=1)
            avg = col4.number_input("평균매수가", min_value=0.0, step=100.0)
            submitted = st.form_submit_button("추가")
        if submitted:
            if not name.strip():
                st.warning("종목명을 입력하세요.")
            else:
                t = find_ticker(name, ticker)
                new = pd.DataFrame([{"종목명": name.strip(), "종목코드": t, "수량": qty, "평균매수가": avg, "투자액": qty * avg}])
                save_portfolio(pd.concat([portfolio_df, new], ignore_index=True))
                st.success("추가했습니다."); st.rerun()

        st.markdown("### 표에서 직접 수정")
        edited = st.data_editor(portfolio_df, num_rows="dynamic", use_container_width=True, hide_index=True, key="portfolio_editor")
        col_save, col_del = st.columns([1, 3])
        if col_save.button("💾 수정내용 저장"):
            save_portfolio(edited)
            st.success("저장했습니다."); st.rerun()

        st.markdown("### CSV 업로드")
        uploaded = st.file_uploader("포트폴리오 CSV 업로드", type=["csv"], key="portfolio_upload")
        if uploaded is not None:
            try:
                up_df = normalize_portfolio(read_csv_any(uploaded))
                save_portfolio(up_df)
                st.success("업로드한 포트폴리오 CSV를 현재 로그인 사용자 계정에 저장했습니다.")
                st.rerun()
            except Exception as e:
                st.error(f"CSV 업로드 실패: {e}")

    st.divider()
    st.subheader("포트폴리오 분석")
    st.caption("외국인/기관 수급은 항상 함께 분석합니다. 종목 수가 많으면 시간이 조금 걸릴 수 있습니다.")
    if st.button("📊 포트폴리오 분석 실행", type="primary", disabled=portfolio_df.empty):
        with st.spinner("현재가, 외국인/기관 수급, 매수·매도 신호를 분석 중입니다. 종목 수에 따라 시간이 걸릴 수 있습니다."):
            result_df = analyze_portfolio(portfolio_df, include_supply=True)
        st.session_state["analysis_result"] = result_df
    if "analysis_result" in st.session_state and not st.session_state["analysis_result"].empty:
        result_df = st.session_state["analysis_result"]
        st.dataframe(result_df, use_container_width=True, hide_index=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("평가금액", money(result_df["평가금액"].sum()))
        c2.metric("평가손익", money(result_df["평가손익"].sum()))
        invest_sum = result_df["투자액"].sum()
        total_pct = result_df["평가손익"].sum() / invest_sum * 100 if invest_sum else 0
        c3.metric("총 수익률", pct(total_pct))

with tab_watch:
    st.subheader("관심그룹")
    watch_df = load_watchlist()
    edited_watch = st.data_editor(watch_df, num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("💾 관심그룹 저장"):
        save_watchlist(edited_watch)
        st.success("관심그룹을 저장했습니다."); st.rerun()
    up_watch = st.file_uploader("관심그룹 CSV 업로드", type=["csv"], key="watch_upload")
    if up_watch is not None:
        save_watchlist(read_csv_any(up_watch))
        st.success("관심그룹 CSV를 저장했습니다."); st.rerun()
    st.download_button("⬇️ watchlist.csv 다운로드", load_watchlist().to_csv(index=False, encoding="utf-8-sig"), "watchlist.csv", "text/csv")

with tab_stock:
    st.subheader("단일 종목 분석")
    single_name = st.text_input("종목명 또는 종목코드", placeholder="예: LG이노텍")
    if st.button("🔍 분석", disabled=not single_name.strip()):
        ticker = find_ticker(single_name)
        if not ticker:
            st.error("종목코드를 찾지 못했습니다. 종목코드를 직접 입력해보세요.")
        else:
            with st.spinner("분석 중입니다."):
                price_df = get_price_data(ticker)
                supply_df = get_supply_data(ticker)
                buy_grade, buy_detail, buy_score = analyze_buy_signal(price_df, supply_df)
                sell_grade, sell_detail = analyze_sell_signal(price_df, supply_df)
            if price_df.empty:
                st.warning("가격 데이터를 불러오지 못했습니다.")
            else:
                current = price_df["종가"].iloc[-1]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("종목코드", ticker)
                c2.metric("현재가", money(current))
                c3.metric("매수점수", buy_score)
                c4.metric("매도신호", sell_grade)
                st.write("매수신호:", buy_grade, "/", ", ".join(buy_detail) if buy_detail else "-")
                st.write("매도상세:", ", ".join(sell_detail) if sell_detail else "-")
                st.line_chart(price_df[["종가", "MA5", "MA20", "MA60"]].dropna())
                if not supply_df.empty:
                    st.line_chart(supply_df[["외국인_누적", "기관_누적"]])

with tab_news:
    st.subheader("네이버 뉴스")
    news_query = st.text_input("뉴스 검색 종목명", placeholder="예: 삼성전자")
    if st.button("📰 뉴스 조회", disabled=not news_query.strip()):
        news = get_news(news_query.strip(), display=10)
        if not news:
            st.info("뉴스가 없거나 NAVER API 키가 설정되지 않았습니다.")
        for item in news:
            st.markdown(f"- [{item['제목']}]({item['링크']})  \n  <small>{item['날짜']}</small>", unsafe_allow_html=True)


with tab_diag:
    st.subheader("🧪 PyKRX 수급 원본 진단")
    st.caption("여기서 나오는 원본 컬럼과 값으로 웹앱 수급 오류 원인을 확인합니다. 삼성전자(005930)부터 테스트하세요.")
    col_a, col_b, col_c = st.columns([2, 1, 1])
    diag_input = col_a.text_input("진단할 종목명 또는 종목코드", value="삼성전자", key="diag_stock_input")
    diag_days = col_b.number_input("조회일수", min_value=10, max_value=120, value=45, step=5)
    run_diag = col_c.button("수급 원본 진단 실행", type="primary")

    if run_diag:
        ticker = find_ticker(diag_input)
        if not ticker:
            st.error("종목코드를 찾지 못했습니다. 예: 005930 처럼 직접 입력해보세요.")
        else:
            st.info(f"진단 종목코드: {ticker}")
            with st.spinner("PyKRX 수급 원본 데이터를 조회 중입니다..."):
                raw_results = supply_raw_diagnostics(ticker, days=int(diag_days))
                normalized = get_supply_data(ticker, days=int(diag_days))

            st.markdown("### 1) 앱이 최종 변환한 수급 데이터")
            if normalized.empty:
                st.warning("get_supply_data() 최종 결과가 비어 있습니다.")
            else:
                st.write("컬럼:", list(normalized.columns))
                st.dataframe(normalized.tail(20), use_container_width=True)
                st.write("최근 5일 외국인 합:", int(normalized["외국인"].tail(5).sum()))
                st.write("최근 5일 기관 합:", int(normalized["기관"].tail(5).sum()))

            st.markdown("### 2) PyKRX 원본 호출 결과")
            for item in raw_results:
                label = item.get("label")
                with st.expander(f"{label} / {item.get('fn')} / {item.get('kwargs')}", expanded=True):
                    if not item.get("ok"):
                        st.error(item.get("error", "알 수 없는 오류"))
                        continue
                    st.write("shape:", item.get("shape"))
                    st.write("columns:", item.get("columns"))
                    df = item.get("df", pd.DataFrame())
                    if df.empty:
                        st.warning("원본 DataFrame이 비어 있습니다.")
                    else:
                        st.markdown("**최근 10행 원본**")
                        st.dataframe(df.tail(10), use_container_width=True)
                        st.markdown("**컬럼별 합계 요약**")
                        st.dataframe(summarize_supply_raw(df), use_container_width=True, hide_index=True)

            st.markdown("### 3) 다음 조치")
            st.info("이 화면에서 'columns'와 최근 10행 원본 캡처를 보내주면, 어떤 컬럼을 외국인/기관으로 계산해야 하는지 바로 맞출 수 있습니다.")
