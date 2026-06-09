# app.py - AI 투자비서 Web / Streamlit Cloud 버전
# 기준: AI_Invest_V4/V8 계열 기능 유지 + 로그인 + 사용자별 포트폴리오 분리 + 모바일 대응

import os
import re
import html
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

try:
    from pykrx import stock
except Exception as e:
    stock = None
    PYKRX_IMPORT_ERROR = e
else:
    PYKRX_IMPORT_ERROR = None

try:
    import plotly.graph_objects as go
except Exception:
    go = None

# =========================================================
# 기본 설정
# =========================================================
st.set_page_config(
    page_title="AI 투자비서 Web",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_VERSION = "AI 투자비서 Web Cloud v1.0"
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

PORTFOLIO_COLUMNS = ["종목명", "종목코드", "수량", "평균매수가", "투자액"]
WATCHLIST_COLUMNS = ["그룹", "종목명", "종목코드", "메모"]

MANUAL_TICKER_MAP = {
    "엘지씨엔에스": "064400", "lg씨엔에스": "064400", "lgcns": "064400", "lg cns": "064400",
    "현대차": "005380", "lg이노텍": "011070", "엘지이노텍": "011070", "코오롱인더": "120110",
    "에스피지": "058610", "삼성전자": "005930", "posco홀딩스": "005490", "포스코홀딩스": "005490",
    "셀트리온": "068270", "한화솔루션": "009830", "naver": "035420", "네이버": "035420",
    "디아이씨": "092200", "lg에너지솔루션": "373220", "엘지에너지솔루션": "373220",
    "삼성전기": "009150", "브이티": "018290", "현대건설": "000720", "케이엠더블유": "032500",
    "현대모비스": "012330", "오이솔루션": "138080", "두산에너빌리티": "034020",
    "lg화학": "051910", "엘지화학": "051910", "솔루스첨단소재": "336370",
    "jyp ent.": "035900", "jyp ent": "035900", "제이와이피": "035900",
    "기가비스": "420770", "뷰노": "338220", "제우스": "079370", "에코앤드림": "101360",
    "서진시스템": "178320", "하이비젼시스템": "126700", "심텍": "222800", "덕산네오룩스": "213420",
    "아비코전자": "036010", "현대오토에버": "307950", "텔레칩스": "054450", "ls electric": "010120",
    "ls일렉트릭": "010120", "한국전력": "015760", "한전kps": "051600", "한전기술": "052690",
}

# =========================================================
# 모바일/웹 UI CSS
# =========================================================
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {background:#ffffff; border:1px solid #e5e7eb; padding:12px; border-radius:12px;}
    .small-caption {font-size:0.85rem; color:#64748b;}
    .mobile-card {border:1px solid #e5e7eb; border-radius:14px; padding:12px 14px; margin-bottom:10px; background:#fff;}
    @media (max-width: 768px) {
      .block-container {padding-left:0.8rem; padding-right:0.8rem;}
      div[data-testid="stHorizontalBlock"] {gap:0.4rem;}
      div[data-testid="stMetric"] {padding:8px;}
      .stTabs [data-baseweb="tab-list"] {overflow-x:auto; white-space:nowrap;}
      .stDataFrame {font-size:12px;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# 로그인 / 사용자별 파일
# =========================================================
def _hash(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def get_users_from_secrets():
    """
    Streamlit Cloud secrets 예시:

    [users.younghee]
    name = "Younghee"
    password = "원하는비밀번호"

    또는 SHA256 해시를 쓰려면:
    password_hash = "..."
    """
    try:
        users = st.secrets.get("users", {})
        if users:
            return dict(users)
    except Exception:
        pass

    # secrets가 없을 때 임시 로그인. 배포 후 반드시 secrets로 바꾸세요.
    return {
        "younghee": {"name": "Younghee", "password": "1234"},
        "demo": {"name": "Demo", "password": "demo"},
    }


def verify_user(username, password):
    users = get_users_from_secrets()
    user = users.get(username)
    if not user:
        return False, None

    plain = str(user.get("password", ""))
    hashed = str(user.get("password_hash", ""))
    ok = False
    if plain and password == plain:
        ok = True
    if hashed and _hash(password) == hashed:
        ok = True
    return ok, user


def login_screen():
    st.title("📈 AI 투자비서 Web")
    st.caption("사용자별 포트폴리오가 분리되는 Streamlit Cloud용 웹앱")
    with st.form("login_form"):
        username = st.text_input("아이디", value="younghee")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")

    if submitted:
        ok, user = verify_user(username.strip(), password)
        if ok:
            st.session_state["logged_in"] = True
            st.session_state["username"] = username.strip()
            st.session_state["display_name"] = user.get("name", username.strip())
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 맞지 않습니다.")


def current_user_id():
    raw = st.session_state.get("username", "guest")
    return re.sub(r"[^a-zA-Z0-9가-힣_-]", "_", raw).strip("_") or "guest"


def user_file(kind):
    uid = current_user_id()
    return DATA_DIR / f"{uid}_{kind}.csv"


def require_login():
    if not st.session_state.get("logged_in"):
        login_screen()
        st.stop()

# =========================================================
# 유틸
# =========================================================
def to_number(value):
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("원", "").replace("주", "").strip()
    if text == "" or text.lower() == "nan":
        return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def money(value):
    try:
        return f"{int(round(float(value))):,}원"
    except Exception:
        return "-"


def number(value):
    try:
        return f"{int(round(float(value))):,}"
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


def ensure_csv(path, columns):
    path = Path(path)
    if not path.exists():
        df = pd.DataFrame(columns=columns)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return df
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="cp949")
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=columns)
    except Exception:
        df = pd.DataFrame(columns=columns)
    for col in columns:
        if col not in df.columns:
            df[col] = "" if col in ["종목명", "종목코드", "그룹", "메모"] else 0
    return df[columns].copy()


def normalize_portfolio(df):
    df = df.copy()
    df = df.rename(columns={"종목": "종목명", "평균가": "평균매수가", "평균단가": "평균매수가", "매수가": "평균매수가"})
    for col in ["종목명", "종목코드", "수량", "평균매수가"]:
        if col not in df.columns:
            df[col] = "" if col in ["종목명", "종목코드"] else 0
    df = df[["종목명", "종목코드", "수량", "평균매수가"]].copy()
    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    df["종목코드"] = df["종목코드"].fillna("").astype(str).str.replace(".0", "", regex=False).str.strip()
    df.loc[df["종목코드"].isin(["nan", "None", "000000"]), "종목코드"] = ""
    df.loc[df["종목코드"] != "", "종목코드"] = df.loc[df["종목코드"] != "", "종목코드"].str.zfill(6)
    df["수량"] = df["수량"].apply(to_number).astype(int)
    df["평균매수가"] = df["평균매수가"].apply(to_number)
    df = df[df["종목명"] != ""].reset_index(drop=True)
    df["투자액"] = df["수량"] * df["평균매수가"]
    return df[PORTFOLIO_COLUMNS]


def load_portfolio():
    return normalize_portfolio(ensure_csv(user_file("portfolio"), PORTFOLIO_COLUMNS))


def save_portfolio(df):
    df = normalize_portfolio(df)
    df.to_csv(user_file("portfolio"), index=False, encoding="utf-8-sig")
    return df


def normalize_watchlist(df):
    df = df.copy().rename(columns={"종목": "종목명", "관심그룹": "그룹", "그룹명": "그룹", "비고": "메모"})
    for col in WATCHLIST_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col != "그룹" else "기본"
    df = df[WATCHLIST_COLUMNS].copy()
    df["그룹"] = df["그룹"].fillna("기본").astype(str).str.strip().replace("", "기본")
    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    df["종목코드"] = df["종목코드"].fillna("").astype(str).str.replace(".0", "", regex=False).str.strip()
    df.loc[df["종목코드"].isin(["nan", "None", "000000"]), "종목코드"] = ""
    df.loc[df["종목코드"] != "", "종목코드"] = df.loc[df["종목코드"] != "", "종목코드"].str.zfill(6)
    df["메모"] = df["메모"].fillna("").astype(str)
    return df[df["종목명"] != ""].reset_index(drop=True)


def load_watchlist():
    return normalize_watchlist(ensure_csv(user_file("watchlist"), WATCHLIST_COLUMNS))


def save_watchlist(df):
    df = normalize_watchlist(df)
    df.to_csv(user_file("watchlist"), index=False, encoding="utf-8-sig")
    return df

# =========================================================
# PyKRX 데이터 / 분석
# =========================================================
def pykrx_ready():
    if stock is None:
        st.error(f"PyKRX 로딩 실패: {PYKRX_IMPORT_ERROR}")
        st.info("Streamlit Cloud의 requirements.txt에 pykrx, setuptools를 반드시 넣으세요.")
        return False
    return True


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def get_all_ticker_name_map():
    result = {}
    if stock is None:
        return result
    for market in ["KOSPI", "KOSDAQ", "KONEX"]:
        try:
            tickers = stock.get_market_ticker_list(market=market)
            for ticker in tickers:
                name = stock.get_market_ticker_name(ticker)
                result[name.lower()] = ticker
                result[name.replace(" ", "").lower()] = ticker
        except Exception:
            pass
    result.update({k.lower(): v for k, v in MANUAL_TICKER_MAP.items()})
    return result


def find_ticker(company_name, ticker_hint=""):
    ticker_hint = str(ticker_hint or "").replace(".0", "").strip()
    if ticker_hint and ticker_hint.lower() != "nan":
        return ticker_hint.zfill(6)
    name = str(company_name or "").strip()
    if not name:
        return None
    mapping = get_all_ticker_name_map()
    candidates = [name.lower(), name.replace(" ", "").lower()]
    for c in candidates:
        if c in mapping:
            return mapping[c]
    compact = name.replace(" ", "").lower()
    for listed_name, ticker in mapping.items():
        if compact == listed_name.replace(" ", "").lower():
            return ticker
    return None


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_price_data(ticker, days=420):
    if stock is None or not ticker:
        return pd.DataFrame()
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days * 2)
    try:
        df = stock.get_market_ohlcv_by_date(start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"), ticker)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    for n in [5, 10, 20, 60, 120]:
        df[f"MA{n}"] = df["종가"].rolling(n).mean()
    delta = df["종가"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    df["RSI"] = 100 - (100 / (1 + rs))
    df["MACD"] = df["종가"].ewm(span=12, adjust=False).mean() - df["종가"].ewm(span=26, adjust=False).mean()
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["VMA20"] = df["거래량"].rolling(20).mean()
    return df.dropna(how="all")


def get_current_price_and_signal(company, ticker_hint=""):
    ticker = find_ticker(company, ticker_hint)
    if not ticker:
        return {"종목코드": "", "현재가": 0, "신호": "종목코드 없음", "상세신호": [], "가격데이터": pd.DataFrame()}
    df = get_price_data(ticker)
    if df.empty:
        return {"종목코드": ticker, "현재가": 0, "신호": "가격조회 실패", "상세신호": [], "가격데이터": df}
    sell_signal, sell_details = analyze_sell_signal(df)
    return {"종목코드": ticker, "현재가": float(df["종가"].iloc[-1]), "신호": sell_signal, "상세신호": sell_details, "가격데이터": df}


def analyze_sell_signal(price_df, supply_df=None):
    if price_df is None or price_df.empty or len(price_df) < 30:
        return "데이터 부족", []
    latest, prev = price_df.iloc[-1], price_df.iloc[-2]
    signals = []
    if pd.notna(latest.get("MA5")) and latest["종가"] < latest["MA5"]:
        signals.append("5일선 이탈")
    if pd.notna(latest.get("MA10")) and latest["종가"] < latest["MA10"]:
        signals.append("10일선 이탈")
    if pd.notna(prev.get("MA5")) and pd.notna(prev.get("MA20")) and prev["MA5"] >= prev["MA20"] and latest["MA5"] < latest["MA20"]:
        signals.append("5/20 데드크로스")
    if pd.notna(latest.get("RSI")) and latest["RSI"] >= 75:
        signals.append("RSI 과열")
    if supply_df is not None and not supply_df.empty:
        s = analyze_supply_signal(supply_df)
        if s["외국인5일"] < 0 and s["기관5일"] < 0:
            signals.append("외국인·기관 동반매도")
    if len(signals) >= 3:
        return "🔴 강한 매도주의", signals
    if len(signals) >= 1:
        return "🟡 일부 매도주의", signals
    return "🟢 보유 가능", ["주요 매도신호 없음"]


def analyze_buy_signal(price_df, supply_df=None):
    if price_df is None or price_df.empty or len(price_df) < 60:
        return "데이터 부족", [], 0
    latest, prev = price_df.iloc[-1], price_df.iloc[-2]
    score, signals = 0, []
    if latest["종가"] > latest.get("MA20", 10**18):
        score += 15; signals.append("20일선 위")
    if latest.get("MA5", 0) > latest.get("MA20", 10**18):
        score += 15; signals.append("5일선>20일선")
    if prev.get("MACD", 0) <= prev.get("MACD_SIGNAL", 0) and latest.get("MACD", 0) > latest.get("MACD_SIGNAL", 0):
        score += 20; signals.append("MACD 골든크로스")
    if 35 <= float(latest.get("RSI", 50)) <= 65:
        score += 10; signals.append("RSI 안정권")
    if latest.get("거래량", 0) > latest.get("VMA20", 10**18) * 1.3:
        score += 10; signals.append("거래량 증가")
    if supply_df is not None and not supply_df.empty:
        s = analyze_supply_signal(supply_df)
        if s["외국인5일"] > 0:
            score += 10; signals.append("외국인 5일 순매수")
        if s["기관5일"] > 0:
            score += 10; signals.append("기관 5일 순매수")
    if score >= 70:
        grade = "강한 매수 관심"
    elif score >= 50:
        grade = "매수 관심"
    elif score >= 30:
        grade = "관찰"
    else:
        grade = "매수신호 없음"
    return grade, signals or ["뚜렷한 매수신호 없음"], score


def analyze_weekly_signal(ticker):
    df = get_price_data(ticker, days=900)
    if df.empty or len(df) < 120:
        return "데이터부족", []
    w = df.resample("W").agg({"종가": "last"}).dropna()
    w["W10"] = w["종가"].rolling(10).mean()
    w["W20"] = w["종가"].rolling(20).mean()
    w["W40"] = w["종가"].rolling(40).mean()
    if len(w) < 45:
        return "데이터부족", []
    last = w.iloc[-1]
    if last["종가"] > last["W20"] and last["W10"] > last["W20"]:
        return "🟢 장기상승", ["주가>20주선", "10주선>20주선"]
    if last["W20"] < last["W40"]:
        return "🔴 장기하락", ["20주선<40주선"]
    return "🟡 장기조정", []


@st.cache_data(ttl=60 * 60, show_spinner=False)
def get_investor_trading_data(ticker, days=30):
    if stock is None or not ticker:
        return pd.DataFrame()
    end_date = datetime.today()
    start_date = end_date - timedelta(days=max(days * 3, 45))
    try:
        df = stock.get_market_trading_value_by_date(start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"), ticker)
    except Exception:
        try:
            df = stock.get_market_trading_volume_by_date(start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"), ticker)
        except Exception:
            return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy().tail(days)
    df.index = pd.to_datetime(df.index)
    return df


def _sum_col(df, col, n):
    return float(df[col].tail(n).sum()) if col in df.columns else 0.0


def analyze_supply_signal(df):
    if df is None or df.empty:
        return {"외국인5일": 0, "기관5일": 0, "개인5일": 0, "외국인20일": 0, "기관20일": 0, "개인20일": 0, "수급신호": "수급 데이터 없음"}
    f5, i5, p5 = _sum_col(df, "외국인", 5), _sum_col(df, "기관합계", 5), _sum_col(df, "개인", 5)
    f20, i20, p20 = _sum_col(df, "외국인", 20), _sum_col(df, "기관합계", 20), _sum_col(df, "개인", 20)
    if f5 > 0 and i5 > 0:
        sig = "🟢 외국인·기관 동반매수"
    elif f5 > 0 or i5 > 0:
        sig = "🟡 일부 순매수"
    elif f5 < 0 and i5 < 0:
        sig = "🔴 동반매도"
    else:
        sig = "⚪ 혼조"
    return {"외국인5일": f5, "기관5일": i5, "개인5일": p5, "외국인20일": f20, "기관20일": i20, "개인20일": p20, "수급신호": sig}

# =========================================================
# 뉴스
# =========================================================
def get_naver_keys():
    try:
        return st.secrets.get("NAVER_CLIENT_ID", ""), st.secrets.get("NAVER_CLIENT_SECRET", "")
    except Exception:
        return "", ""


@st.cache_data(ttl=60 * 20, show_spinner=False)
def get_news(company_name, display=10):
    client_id, client_secret = get_naver_keys()
    if not client_id or not client_secret:
        return []
    url = "https://openapi.naver.com/v1/search/news.json"
    params = {"query": company_name, "display": display, "sort": "date"}
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
    except Exception:
        return []
    return [{"제목": clean_html(x.get("title", "")), "링크": x.get("originallink") or x.get("link"), "날짜": x.get("pubDate", "")} for x in data.get("items", [])]


def score_news(news):
    pos = ["수주", "계약", "호실적", "흑자", "성장", "증설", "AI", "상향", "배당", "공급", "실적", "신규"]
    neg = ["적자", "감소", "하향", "소송", "악화", "유상증자", "하락", "부진", "리콜", "감자"]
    score = 0
    for item in news:
        title = item.get("제목", "")
        score += sum(3 for p in pos if p in title)
        score -= sum(3 for n in neg if n in title)
    return score

# =========================================================
# 표/차트/백테스트/스크리너
# =========================================================
def make_portfolio_analysis(portfolio_df):
    rows = []
    total = len(portfolio_df)
    progress = st.progress(0, text="현재가·수급 조회 중...") if total else None
    for idx, row in portfolio_df.iterrows():
        company, qty, avg = row["종목명"], int(row["수량"]), float(row["평균매수가"])
        info = get_current_price_and_signal(company, row.get("종목코드", ""))
        ticker, current, price_df = info["종목코드"], float(info["현재가"]), info["가격데이터"]
        supply_df = get_investor_trading_data(ticker, days=30) if ticker else pd.DataFrame()
        supply = analyze_supply_signal(supply_df)
        buy_grade, buy_details, buy_score = analyze_buy_signal(price_df, supply_df)
        sell_grade, sell_details = analyze_sell_signal(price_df, supply_df)
        weekly, _ = analyze_weekly_signal(ticker) if ticker else ("데이터부족", [])
        invested = qty * avg
        eval_amount = qty * current if current > 0 else 0
        profit = eval_amount - invested if current > 0 else 0
        rr = ((current - avg) / avg * 100) if avg > 0 and current > 0 else 0
        decision = "🟢 보유/관심"
        if "강한 매도" in sell_grade or rr <= -20:
            decision = "🔴 점검필요"
        elif "매수 관심" in buy_grade and supply["외국인5일"] + supply["기관5일"] > 0:
            decision = "🟢 긍정"
        elif "일부 매도" in sell_grade:
            decision = "🟡 관찰"
        rows.append({
            "종목명": company, "종목코드": ticker, "수량": qty, "평균매수가": avg, "현재가": current,
            "투자액": invested, "평가금액": eval_amount, "평가손익": profit, "수익률": rr,
            "종합판정": decision, "매수신호": buy_grade, "매수점수": buy_score, "매도신호": sell_grade,
            "주봉신호": weekly, "수급신호": supply["수급신호"], "외국인5일": supply["외국인5일"], "기관5일": supply["기관5일"],
            "상세신호": ", ".join(sell_details or buy_details),
        })
        if progress:
            progress.progress((idx + 1) / total, text=f"조회 중: {company}")
    if progress:
        progress.empty()
    return pd.DataFrame(rows)


def display_portfolio_table(df):
    if df.empty:
        st.info("등록된 종목이 없습니다.")
        return
    show = df.copy()
    for c in ["평균매수가", "현재가", "투자액", "평가금액", "평가손익", "외국인5일", "기관5일"]:
        if c in show.columns:
            show[c] = show[c].apply(money if c not in ["외국인5일", "기관5일"] else number)
    if "수익률" in show.columns:
        show["수익률"] = show["수익률"].apply(pct)
    st.dataframe(show, use_container_width=True, hide_index=True)


def show_price_chart(df, company):
    if df is None or df.empty:
        st.warning("가격 데이터가 없습니다.")
        return
    chart_df = df.tail(180).copy()
    if go:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["종가"], name="종가"))
        for ma in ["MA5", "MA20", "MA60"]:
            if ma in chart_df:
                fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df[ma], name=ma))
        fig.update_layout(title=f"{company} 가격 차트", height=420, margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.line_chart(chart_df[["종가", "MA5", "MA20", "MA60"]])


def show_supply_chart(df):
    if df is None or df.empty:
        st.warning("수급 데이터가 없습니다. 종목코드가 맞는지, PyKRX가 정상 동작하는지 확인하세요.")
        return
    cols = [c for c in ["외국인", "기관합계", "개인"] if c in df.columns]
    st.line_chart(df[cols].cumsum())
    st.dataframe(df[cols].tail(20), use_container_width=True)


def run_backtest(price_df):
    if price_df is None or price_df.empty or len(price_df) < 80:
        return {}
    df = price_df.copy().dropna(subset=["MA20", "MA60"])
    cash, shares, initial = 10_000_000, 0, 10_000_000
    trades = []
    equity = []
    for dt, row in df.iterrows():
        price = row["종가"]
        buy = row["MA20"] > row["MA60"] and shares == 0
        sell = row["MA20"] < row["MA60"] and shares > 0
        if buy:
            shares = int(cash // price)
            cash -= shares * price
            trades.append({"일자": dt.date(), "구분": "매수", "가격": price, "수량": shares})
        elif sell:
            cash += shares * price
            trades.append({"일자": dt.date(), "구분": "매도", "가격": price, "수량": shares})
            shares = 0
        equity.append({"일자": dt, "평가금액": cash + shares * price})
    final = equity[-1]["평가금액"] if equity else initial
    return {"equity_df": pd.DataFrame(equity).set_index("일자") if equity else pd.DataFrame(), "trades_df": pd.DataFrame(trades), "total_return": (final / initial - 1) * 100, "final_equity": final}


def screen_companies(companies):
    rows = []
    for company in companies:
        company = company.strip()
        if not company:
            continue
        info = get_current_price_and_signal(company)
        ticker, df = info["종목코드"], info["가격데이터"]
        supply_df = get_investor_trading_data(ticker, days=30) if ticker else pd.DataFrame()
        buy_grade, buy_details, buy_score = analyze_buy_signal(df, supply_df)
        news = get_news(company, 5)
        nscore = score_news(news)
        supply = analyze_supply_signal(supply_df)
        total_score = buy_score + nscore + (10 if supply["외국인5일"] > 0 else 0) + (10 if supply["기관5일"] > 0 else 0)
        rows.append({"종목명": company, "종목코드": ticker, "현재가": info["현재가"], "매수신호": buy_grade, "기술점수": buy_score, "뉴스점수": nscore, "수급신호": supply["수급신호"], "종합점수": total_score, "상세": ", ".join(buy_details)})
    return pd.DataFrame(rows).sort_values("종합점수", ascending=False) if rows else pd.DataFrame()

# =========================================================
# 화면
# =========================================================
require_login()

with st.sidebar:
    st.title("📈 AI 투자비서")
    st.caption(APP_VERSION)
    st.success(f"{st.session_state.get('display_name')}님 로그인")
    if st.button("로그아웃"):
        st.session_state.clear(); st.rerun()
    st.divider()
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear(); st.rerun()
    st.caption("사용자별 저장 파일")
    st.code(str(user_file("portfolio")))
    st.code(str(user_file("watchlist")))
    st.divider()
    st.caption("Naver API는 Streamlit Cloud secrets에 입력합니다.")

if not pykrx_ready():
    st.stop()

st.title("📈 AI 투자비서 Web")
st.caption("포트폴리오 · 사용자 로그인 · CSV 업로드/다운로드 · 상세분석 · 뉴스 · 외국인/기관 수급 · 모바일 지원")

portfolio_df = load_portfolio()
watchlist_df = load_watchlist()

tabs = st.tabs(["📊 포트폴리오", "➕ 추가/수정/삭제", "📈 상세분석", "🏦 수급분석", "📰 뉴스", "⭐ 관심그룹", "🔍 스크리너", "🧪 백테스트", "⚙️ 배포설정"])

with tabs[0]:
    st.subheader("포트폴리오 현황")
    uploaded = st.file_uploader("포트폴리오 CSV 업로드", type=["csv"], key="portfolio_upload")
    if uploaded is not None:
        try:
            new_df = pd.read_csv(uploaded)
            save_portfolio(new_df)
            st.success("업로드한 CSV를 현재 사용자 포트폴리오로 저장했습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"CSV 업로드 실패: {e}")

    if portfolio_df.empty:
        st.info("아직 등록된 종목이 없습니다. 추가/수정/삭제 탭에서 입력하거나 CSV를 업로드하세요.")
    else:
        analysis_df = make_portfolio_analysis(portfolio_df)
        total_invested = analysis_df["투자액"].sum()
        total_eval = analysis_df["평가금액"].sum()
        total_profit = total_eval - total_invested
        total_rate = (total_profit / total_invested * 100) if total_invested else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 투자액", money(total_invested))
        c2.metric("총 평가액", money(total_eval))
        c3.metric("평가손익", money(total_profit))
        c4.metric("수익률", pct(total_rate))
        display_portfolio_table(analysis_df)
        st.download_button("📥 내 포트폴리오 CSV 다운로드", data=portfolio_df.to_csv(index=False, encoding="utf-8-sig"), file_name=f"portfolio_{current_user_id()}.csv", mime="text/csv")

with tabs[1]:
    st.subheader("추가 / 수정 / 삭제")
    with st.form("add_form"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("종목명")
        ticker = c2.text_input("종목코드", placeholder="자동매칭 가능")
        qty = c3.number_input("수량", min_value=0, step=1)
        avg = c4.number_input("평균매수가", min_value=0.0, step=100.0)
        submitted = st.form_submit_button("저장/추가")
    if submitted and name:
        ticker = find_ticker(name, ticker) or ""
        new_row = pd.DataFrame([{"종목명": name, "종목코드": ticker, "수량": qty, "평균매수가": avg, "투자액": qty * avg}])
        df = portfolio_df.copy()
        mask = df["종목명"].str.lower() == name.lower()
        if mask.any():
            df.loc[mask, ["종목코드", "수량", "평균매수가", "투자액"]] = [ticker, qty, avg, qty * avg]
        else:
            df = pd.concat([df, new_row], ignore_index=True)
        save_portfolio(df)
        st.success("저장했습니다.")
        st.rerun()

    edited = st.data_editor(portfolio_df, num_rows="dynamic", use_container_width=True, key="portfolio_editor")
    c1, c2 = st.columns(2)
    if c1.button("수정내용 저장"):
        save_portfolio(edited)
        st.success("수정내용을 저장했습니다.")
        st.rerun()
    delete_name = c2.selectbox("삭제할 종목", [""] + portfolio_df["종목명"].tolist())
    if delete_name and c2.button("선택 종목 삭제"):
        save_portfolio(portfolio_df[portfolio_df["종목명"] != delete_name])
        st.success("삭제했습니다.")
        st.rerun()

with tabs[2]:
    st.subheader("종목 클릭/선택 상세분석")
    options = portfolio_df["종목명"].tolist() or ["삼성전자"]
    selected = st.selectbox("상세분석할 종목", options)
    row = portfolio_df[portfolio_df["종목명"] == selected].iloc[0] if selected in portfolio_df["종목명"].tolist() else {}
    info = get_current_price_and_signal(selected, row.get("종목코드", "") if isinstance(row, pd.Series) else "")
    supply_df = get_investor_trading_data(info["종목코드"], 30) if info["종목코드"] else pd.DataFrame()
    buy_grade, buy_details, buy_score = analyze_buy_signal(info["가격데이터"], supply_df)
    sell_grade, sell_details = analyze_sell_signal(info["가격데이터"], supply_df)
    weekly, weekly_details = analyze_weekly_signal(info["종목코드"]) if info["종목코드"] else ("데이터부족", [])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("종목코드", info["종목코드"] or "-")
    c2.metric("현재가", money(info["현재가"]))
    c3.metric("매수신호", buy_grade)
    c4.metric("매도신호", sell_grade)
    st.write("**매수 상세:**", ", ".join(buy_details))
    st.write("**매도 상세:**", ", ".join(sell_details))
    st.write("**주봉 흐름:**", weekly, ", ".join(weekly_details))
    show_price_chart(info["가격데이터"], selected)

with tabs[3]:
    st.subheader("외국인/기관 수급분석")
    selected = st.selectbox("수급분석 종목", portfolio_df["종목명"].tolist() or ["삼성전자"], key="supply_select")
    ticker = find_ticker(selected)
    days = st.slider("조회일수", 10, 90, 30)
    df = get_investor_trading_data(ticker, days)
    s = analyze_supply_signal(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("수급신호", s["수급신호"])
    c2.metric("외국인 5일", number(s["외국인5일"]))
    c3.metric("기관 5일", number(s["기관5일"]))
    c4.metric("개인 5일", number(s["개인5일"]))
    show_supply_chart(df)

with tabs[4]:
    st.subheader("네이버 뉴스")
    selected = st.selectbox("뉴스 종목", portfolio_df["종목명"].tolist() or ["삼성전자"], key="news_select")
    news = get_news(selected, 10)
    if not news:
        st.warning("뉴스가 표시되지 않습니다. Streamlit secrets의 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET을 확인하세요.")
    else:
        st.metric("뉴스점수", score_news(news))
        for item in news:
            st.markdown(f"- [{item['제목']}]({item['링크']})  \n  <span class='small-caption'>{item['날짜']}</span>", unsafe_allow_html=True)

with tabs[5]:
    st.subheader("관심그룹")
    uploaded_w = st.file_uploader("관심그룹 CSV 업로드", type=["csv"], key="watch_upload")
    if uploaded_w is not None:
        try:
            save_watchlist(pd.read_csv(uploaded_w))
            st.success("관심그룹 CSV를 저장했습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"업로드 실패: {e}")
    edited_w = st.data_editor(watchlist_df, num_rows="dynamic", use_container_width=True, key="watch_editor")
    if st.button("관심그룹 저장"):
        save_watchlist(edited_w)
        st.success("저장했습니다.")
        st.rerun()
    if not watchlist_df.empty:
        group = st.selectbox("그룹 선택", sorted(watchlist_df["그룹"].unique()))
        companies = watchlist_df[watchlist_df["그룹"] == group]["종목명"].tolist()
        if st.button("선택 그룹 분석"):
            st.dataframe(screen_companies(companies), use_container_width=True, hide_index=True)
    st.download_button("📥 관심그룹 CSV 다운로드", data=watchlist_df.to_csv(index=False, encoding="utf-8-sig"), file_name=f"watchlist_{current_user_id()}.csv", mime="text/csv")

with tabs[6]:
    st.subheader("종목 스크리너")
    default = "삼성전자,현대차,LG이노텍,셀트리온,NAVER,LS ELECTRIC"
    text = st.text_area("분석할 종목명 comma 구분", value=default, height=100)
    if st.button("스크리닝 실행"):
        companies = [x.strip() for x in text.split(",") if x.strip()]
        st.dataframe(screen_companies(companies), use_container_width=True, hide_index=True)

with tabs[7]:
    st.subheader("간단 백테스트: 20일선/60일선 전략")
    selected = st.selectbox("백테스트 종목", portfolio_df["종목명"].tolist() or ["삼성전자"], key="bt_select")
    ticker = find_ticker(selected)
    result = run_backtest(get_price_data(ticker, days=900)) if ticker else {}
    if not result:
        st.warning("백테스트 데이터가 부족합니다.")
    else:
        st.metric("전략 수익률", pct(result["total_return"]))
        st.line_chart(result["equity_df"])
        st.dataframe(result["trades_df"], use_container_width=True, hide_index=True)

with tabs[8]:
    st.subheader("Streamlit Cloud 배포 설정")
    st.code('''# requirements.txt
streamlit
pandas
requests
pykrx
setuptools
plotly
''')
    st.code('''# .streamlit/secrets.toml
NAVER_CLIENT_ID = "네이버_클라이언트_ID"
NAVER_CLIENT_SECRET = "네이버_클라이언트_SECRET"

[users.younghee]
name = "Younghee"
password = "원하는비밀번호"

[users.sister]
name = "Sister"
password = "다른비밀번호"
''')
    st.info("Cloud에서는 사용자별 CSV가 data/아이디_portfolio.csv로 분리됩니다. 장기 보관은 다운로드 백업을 권장합니다.")
