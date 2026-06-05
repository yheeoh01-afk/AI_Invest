import os

PORTFOLIO_FILE = "portfolio.csv"
WATCHLIST_FILE = "watchlist.csv"

# =========================
# CSV 자동 생성/정규화 설정
# =========================
PORTFOLIO_COLUMNS = ["종목명", "종목코드", "수량", "평균매수가", "투자액"]
WATCHLIST_COLUMNS = ["그룹", "종목명", "종목코드", "메모"]


def ensure_csv_file(file_path, columns):
    """
    CSV 파일이 없으면 빈 파일을 자동 생성합니다.
    파일이 있으면 필요한 컬럼을 보정합니다.
    """
    if not os.path.exists(file_path):
        df = pd.DataFrame(columns=columns)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return df

    try:
        df = pd.read_csv(file_path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=columns)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return df
    except Exception:
        # 인코딩 문제가 있을 때 보조 시도
        try:
            df = pd.read_csv(file_path, encoding="cp949")
        except Exception:
            df = pd.DataFrame(columns=columns)
            df.to_csv(file_path, index=False, encoding="utf-8-sig")
            return df

    for col in columns:
        if col not in df.columns:
            df[col] = "" if col in ["종목명", "종목코드", "그룹", "그룹명", "메모"] else 0

    df = df[columns].copy()
    df.to_csv(file_path, index=False, encoding="utf-8-sig")
    return df


def ensure_data_files():
    """
    앱 시작 시 데이터 파일이 없으면 자동 생성합니다.
    언니/가족에게 배포할 때 portfolio.csv, watchlist.csv를 빼고 보내도 됩니다.
    """
    ensure_csv_file(PORTFOLIO_FILE, PORTFOLIO_COLUMNS)
    ensure_csv_file(WATCHLIST_FILE, WATCHLIST_COLUMNS)

import re
import html
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
from pykrx import stock

# 종목명 고정표용 선택 라이브러리
try:
    from st_aggrid import AgGrid, GridOptionsBuilder
    AGGRID_AVAILABLE = True
except Exception:
    AGGRID_AVAILABLE = False


# =========================================================
# AI 투자비서 V9 Cloud.13
# 기능:
# - 포트폴리오 조회 / 추가 / 수정 / 삭제
# - CSV 저장
# - PyKRX 현재가 조회
# - 수익률 / 평가손익 / 포트폴리오 요약
# - 매수/매도 신호: 이동평균, RSI, MACD, 거래량, 수급 종합
# - 외국인/기관 수급 분석: 5일, 20일 순매수, 누적 추이 차트
# - 네이버 뉴스 최신 뉴스 표시
# =========================================================

st.set_page_config(
    page_title="AI 투자비서 V9 Cloud",
    page_icon="📈",
    layout="wide"
)



# =========================
# Streamlit Cloud 사용자 로그인/데이터 분리
# =========================
def get_cloud_users():
    """
    Streamlit Cloud Secrets에서 사용자 목록을 읽습니다.
    secrets.toml 예:
    [USERS]
    younghee = "비밀번호"
    sister = "비밀번호"
    """
    try:
        users = dict(st.secrets.get("USERS", {}))
        if users:
            return users
    except Exception:
        pass

    # 로컬 테스트용 기본값. 배포 전 Cloud Secrets에서 반드시 바꾸세요.
    return {
        "younghee": "1234",
        "sister": "1234",
    }


def require_login():
    users = get_cloud_users()

    if "auth_user" not in st.session_state:
        st.session_state["auth_user"] = None

    with st.sidebar:
        st.subheader("🔐 로그인")
        if st.session_state["auth_user"]:
            st.success(f"{st.session_state['auth_user']} 로그인 중")
            if st.button("로그아웃"):
                st.session_state["auth_user"] = None
                st.rerun()
        else:
            user_id = st.selectbox("사용자", list(users.keys()), key="login_user")
            password = st.text_input("비밀번호", type="password", key="login_password")
            if st.button("로그인"):
                if users.get(user_id) == password:
                    st.session_state["auth_user"] = user_id
                    st.rerun()
                else:
                    st.error("비밀번호가 맞지 않습니다.")

    if not st.session_state["auth_user"]:
        st.title("📈 AI 투자비서 V9 Cloud")
        st.info("왼쪽 사이드바에서 로그인하세요.")
        st.stop()

    return st.session_state["auth_user"]


CURRENT_USER = require_login()

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PORTFOLIO_FILE = os.path.join(DATA_DIR, f"{CURRENT_USER}_portfolio.csv")
WATCHLIST_FILE = os.path.join(DATA_DIR, f"{CURRENT_USER}_watchlist.csv")
CSV_FILE = PORTFOLIO_FILE

ensure_data_files()
# -----------------------------
# 기본 유틸
# -----------------------------
def to_number(value):
    """'286,500' 같은 문자열을 숫자로 변환"""
    if pd.isna(value):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("원", "").strip()
    if text == "":
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


def normalize_portfolio(df):
    """기존 CSV 컬럼명을 새 구조에 맞게 정리"""
    df = df.copy()

    rename_map = {
        "종목": "종목명",
        "평균가": "평균매수가",
        "평균단가": "평균매수가",
        "매수가": "평균매수가",
    }
    df = df.rename(columns=rename_map)

    for col in ["종목명", "종목코드", "수량", "평균매수가"]:
        if col not in df.columns:
            df[col] = "" if col in ["종목명", "종목코드"] else 0

    df = df[["종목명", "종목코드", "수량", "평균매수가"]].copy()
    df["종목명"] = df["종목명"].astype(str).str.strip()
    df["종목코드"] = (
        df["종목코드"]
        .fillna("")
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
        .str.zfill(6)
    )
    df.loc[df["종목코드"].isin(["000000", "nan", "None"]), "종목코드"] = ""
    df["수량"] = df["수량"].apply(to_number).astype(int)
    df["평균매수가"] = df["평균매수가"].apply(to_number)
    df = df[df["종목명"] != ""].reset_index(drop=True)
    df["투자액"] = df["수량"] * df["평균매수가"]

    return df


def load_portfolio():
    df = ensure_csv_file(PORTFOLIO_FILE, PORTFOLIO_COLUMNS)

    # 기존 구버전 CSV 호환: 종목/평균가 컬럼명 보정
    rename_map = {}
    if "종목" in df.columns and "종목명" not in df.columns:
        rename_map["종목"] = "종목명"
    if "평균가" in df.columns and "평균매수가" not in df.columns:
        rename_map["평균가"] = "평균매수가"
    if rename_map:
        df = df.rename(columns=rename_map)

    for col in PORTFOLIO_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ["종목명", "종목코드"] else 0

    df = df[PORTFOLIO_COLUMNS].copy()
    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    df["종목코드"] = (
        df["종목코드"]
        .fillna("")
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )
    df.loc[df["종목코드"].isin(["nan", "None", "000000"]), "종목코드"] = ""
    df.loc[df["종목코드"] != "", "종목코드"] = df.loc[df["종목코드"] != "", "종목코드"].str.zfill(6)

    df["수량"] = df["수량"].apply(to_number).astype(int)
    df["평균매수가"] = df["평균매수가"].apply(to_number)
    df = df[df["종목명"] != ""].reset_index(drop=True)
    df["투자액"] = df["수량"] * df["평균매수가"]

    df[PORTFOLIO_COLUMNS].to_csv(PORTFOLIO_FILE, index=False, encoding="utf-8-sig")
    return df


def save_portfolio(df):
    df = normalize_portfolio(df)
    df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    return df


# -----------------------------
# 관심그룹 CSV
# -----------------------------
def normalize_watchlist(df):
    """관심그룹 CSV 컬럼 정리: 그룹, 종목명, 종목코드, 메모"""
    df = df.copy()

    rename_map = {
        "종목": "종목명",
        "관심그룹": "그룹",
        "그룹명": "그룹",
        "비고": "메모",
    }
    df = df.rename(columns=rename_map)

    for col in WATCHLIST_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ["그룹", "종목명", "종목코드", "메모"] else 0

    df = df[WATCHLIST_COLUMNS].copy()
    df["그룹"] = df["그룹"].fillna("기본").astype(str).str.strip().replace("", "기본")
    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    df["종목코드"] = (
        df["종목코드"]
        .fillna("")
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )
    df.loc[df["종목코드"].isin(["nan", "None", "000000"]), "종목코드"] = ""
    df.loc[df["종목코드"] != "", "종목코드"] = df.loc[df["종목코드"] != "", "종목코드"].str.zfill(6)
    df["메모"] = df["메모"].fillna("").astype(str).replace("nan", "")
    df = df[df["종목명"] != ""].reset_index(drop=True)
    return df


def load_watchlist():
    df = ensure_csv_file(WATCHLIST_FILE, WATCHLIST_COLUMNS)

    # 구버전/다른 버전 호환: 그룹명 -> 그룹
    if "그룹명" in df.columns and "그룹" not in df.columns:
        df = df.rename(columns={"그룹명": "그룹"})

    for col in WATCHLIST_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ["그룹", "종목명", "종목코드", "메모"] else 0

    df = df[WATCHLIST_COLUMNS].copy()
    df["그룹"] = df["그룹"].fillna("").astype(str).str.strip().replace("", "기본")
    df["종목명"] = df["종목명"].fillna("").astype(str).str.strip()
    df["종목코드"] = (
        df["종목코드"]
        .fillna("")
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )
    df.loc[df["종목코드"].isin(["nan", "None", "000000"]), "종목코드"] = ""
    df.loc[df["종목코드"] != "", "종목코드"] = df.loc[df["종목코드"] != "", "종목코드"].str.zfill(6)
    df["메모"] = df["메모"].fillna("").astype(str)

    df = df[(df["그룹"] != "") & (df["종목명"] != "")].reset_index(drop=True)
    df[WATCHLIST_COLUMNS].to_csv(WATCHLIST_FILE, index=False, encoding="utf-8-sig")
    return df


def save_watchlist(df):
    df = normalize_watchlist(df)
    df[WATCHLIST_COLUMNS].to_csv(WATCHLIST_FILE, index=False, encoding="utf-8-sig")
    return df


def analyze_watch_stock(company, ticker_hint=None):
    """관심종목 1개에 대해 가격, 매수/매도, 수급 요약"""
    info = get_current_price_and_signal(company, ticker_hint)
    ticker = info.get("종목코드")
    price_df = info.get("가격데이터")
    supply_df = get_investor_trading_data(ticker, days=30) if ticker else pd.DataFrame()
    supply = analyze_supply_signal(supply_df)
    buy_grade, buy_details, buy_score = analyze_buy_signal(price_df, supply_df)
    sell_grade, sell_details = analyze_sell_signal(price_df, supply_df)

    return {
        "종목명": company,
        "종목코드": ticker or "",
        "현재가": info.get("현재가", 0),
        "매수신호": buy_grade,
        "매수점수": buy_score,
        "매수상세": ", ".join(buy_details) if buy_details else "-",
        "매도신호": sell_grade,
        "매도상세": ", ".join(sell_details) if sell_details else "-",
        "외국인5일": supply["외국인5일"],
        "기관5일": supply["기관5일"],
        "수급신호": supply["수급신호"],
                "주봉신호": analyze_weekly_signal(info["종목코드"])[0],
    }


# -----------------------------
# PyKRX 데이터
# -----------------------------
MANUAL_TICKER_MAP = {
    # 사용자가 자주 입력하는 표기 / PyKRX 종목명 매칭 보정
    "엘지씨엔에스": "064400",
    "lg씨엔에스": "064400",
    "lgcns": "064400",
    "lg cns": "064400",
    "현대차": "005380",
    "lg이노텍": "011070",
    "엘지이노텍": "011070",
    "코오롱인더": "120110",
    "에스피지": "058610",
    "삼성전자": "005930",
    "posco홀딩스": "005490",
    "포스코홀딩스": "005490",
    "셀트리온": "068270",
    "한화솔루션": "009830",
    "naver": "035420",
    "네이버": "035420",
    "디아이씨": "092200",
    "lg에너지솔루션": "373220",
    "엘지에너지솔루션": "373220",
    "삼성전기": "009150",
    "브이티": "018290",
    "현대건설": "000720",
    "케이엠더블유": "032500",
    "현대모비스": "012330",
    "오이솔루션": "138080",
    "두산에너빌리티": "034020",
    "솔루스첨단소재": "336370",
    "jyp ent.": "035900",
    "jyp ent": "035900",
    "제이와이피": "035900",
    "기가비스": "420770",
    "뷰노": "338220",
    "제우스": "079370",
    "에코앤드림": "101360",
    "서진시스템": "178320",
    "하이비젼시스템": "126700",
    "심텍": "222800",
    "덕산네오룩스": "213420",
    "아비코전자": "036010",
    "현대오토에버": "307950",
    "텔레칩스": "054450",
}


@st.cache_data(ttl=60 * 60 * 12)
def get_all_ticker_name_map():
    """종목명 -> 종목코드 맵 생성"""
    result = {}

    for market in ["KOSPI", "KOSDAQ", "KONEX"]:
        try:
            tickers = stock.get_market_ticker_list(market=market)
            for ticker in tickers:
                name = stock.get_market_ticker_name(ticker)
                result[name.lower()] = ticker
                result[name.replace(" ", "").lower()] = ticker
        except Exception:
            pass

    aliases = {
        "엘지씨엔에스": "LG CNS",
        "엘지이노텍": "LG이노텍",
        "엘지에너지솔루션": "LG에너지솔루션",
        "포스코홀딩스": "POSCO홀딩스",
        "네이버": "NAVER",
    }

    for alias, real_name in aliases.items():
        ticker = result.get(real_name.lower())
        if ticker:
            result[alias.lower()] = ticker

    return result


def find_ticker(company_name):
    if not company_name:
        return None

    name = str(company_name).strip()
    compact = name.replace(" ", "").lower()

    # 종목코드를 직접 넣은 경우
    if compact.isdigit():
        return compact.zfill(6)

    # 수동 보정표를 먼저 확인: PyKRX 종목명 표기 차이, 영문/한글 혼용 보정
    if name.lower() in MANUAL_TICKER_MAP:
        return MANUAL_TICKER_MAP[name.lower()]
    if compact in MANUAL_TICKER_MAP:
        return MANUAL_TICKER_MAP[compact]

    mapping = get_all_ticker_name_map()

    ticker = mapping.get(name.lower())
    if ticker:
        return ticker

    ticker = mapping.get(compact)
    if ticker:
        return ticker

    for listed_name, ticker in mapping.items():
        if compact == listed_name.replace(" ", "").lower():
            return ticker

    return None


@st.cache_data(ttl=60 * 30)
def get_price_data(ticker, days=220):
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days * 2)

    df = stock.get_market_ohlcv_by_date(
        start_date.strftime("%Y%m%d"),
        end_date.strftime("%Y%m%d"),
        ticker
    )

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.index = pd.to_datetime(df.index)

    df["MA5"] = df["종가"].rolling(5).mean()
    df["MA10"] = df["종가"].rolling(10).mean()
    df["MA20"] = df["종가"].rolling(20).mean()
    df["MA60"] = df["종가"].rolling(60).mean()

    # 매수신호용 보조지표
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


@st.cache_data(ttl=60 * 30)
def get_investor_trading_data(ticker, days=45):
    """종목별 외국인/기관 순매수 수량 조회.

    PyKRX의 get_market_trading_volume_by_date를 사용합니다.
    반환 컬럼명은 PyKRX 버전에 따라 조금 다를 수 있어 외국인/기관 컬럼을 유연하게 찾습니다.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days * 2)

    try:
        df = stock.get_market_trading_volume_by_date(
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            ticker
        )
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.index = pd.to_datetime(df.index)

    foreign_col = None
    institution_col = None

    for col in df.columns:
        col_text = str(col)
        if "외국인" in col_text:
            foreign_col = col
        if "기관" in col_text:
            institution_col = col

    result = pd.DataFrame(index=df.index)
    result["외국인"] = df[foreign_col] if foreign_col is not None else 0
    result["기관"] = df[institution_col] if institution_col is not None else 0
    result["외국인_누적"] = result["외국인"].cumsum()
    result["기관_누적"] = result["기관"].cumsum()

    return result.tail(days)


def analyze_sell_signal(price_df, supply_df=None):
    """
    매도신호 4단계:
    🟢 양호  : 주요 이탈 없음, 정배열/상승 흐름
    🟡 주의  : 5일선 또는 10일선 이탈
    🟠 경고  : 20일선 이탈 또는 5/20 데드크로스
    🔴 매도  : 20일선<60일선 중기하락 + 약세 신호, 또는 외국인·기관 동반매도 + 약세 신호
    """
    if price_df is None or price_df.empty or len(price_df) < 60:
        return "데이터 부족", []

    latest = price_df.iloc[-1]
    prev = price_df.iloc[-2]

    close = latest.get("종가", 0)
    ma5 = latest.get("MA5")
    ma10 = latest.get("MA10")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")

    signals = []
    level = 0

    if pd.notna(ma5) and close < ma5:
        signals.append("5일선 이탈")
        level = max(level, 1)

    if pd.notna(ma10) and close < ma10:
        signals.append("10일선 이탈")
        level = max(level, 1)

    if pd.notna(ma20) and close < ma20:
        signals.append("20일선 이탈")
        level = max(level, 2)

    if (
        pd.notna(prev.get("MA5")) and pd.notna(prev.get("MA20"))
        and pd.notna(ma5) and pd.notna(ma20)
        and prev["MA5"] >= prev["MA20"]
        and ma5 < ma20
    ):
        signals.append("5/20 데드크로스")
        level = max(level, 2)

    if pd.notna(ma20) and pd.notna(ma60) and ma20 < ma60:
        signals.append("20일선 < 60일선")
        if level >= 2:
            level = max(level, 3)
        else:
            level = max(level, 2)

    if supply_df is not None and not supply_df.empty:
        try:
            foreign_5 = supply_df["외국인"].tail(5).sum()
            inst_5 = supply_df["기관"].tail(5).sum()
            foreign_20 = supply_df["외국인"].tail(20).sum()
            inst_20 = supply_df["기관"].tail(20).sum()

            if foreign_5 < 0 and inst_5 < 0:
                signals.append("외국인·기관 5일 동반매도")
                level = max(level, 2)

            if foreign_20 < 0 and inst_20 < 0:
                signals.append("외국인·기관 20일 동반매도")
                if level >= 2:
                    level = max(level, 3)
                else:
                    level = max(level, 2)
        except Exception:
            pass

    if level >= 3:
        return "🔴 매도", signals
    if level == 2:
        return "🟠 경고", signals
    if level == 1:
        return "🟡 주의", signals

    if pd.notna(ma5) and pd.notna(ma20) and pd.notna(ma60) and ma5 > ma20 > ma60:
        return "🟢 양호", ["정배열 유지"]

    return "🟢 양호", []



def analyze_buy_signal(price_df, supply_df=None):
    """가격/이동평균/RSI/MACD/거래량/수급을 종합해 매수 관심도를 계산"""
    if price_df is None or price_df.empty or len(price_df) < 60:
        return "데이터 부족", [], 0

    latest = price_df.iloc[-1]
    prev = price_df.iloc[-2]

    score = 0
    signals = []

    close = latest.get("종가", 0)
    ma5 = latest.get("MA5")
    ma10 = latest.get("MA10")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")
    rsi = latest.get("RSI")
    macd = latest.get("MACD")
    macd_signal = latest.get("MACD_SIGNAL")

    # 1) 단기 추세
    if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
        if close > ma5 > ma10:
            score += 20
            signals.append("단기 상승추세")
        if ma5 > ma10 > ma20:
            score += 20
            signals.append("이동평균 정배열")

    # 2) 골든크로스
    if (
        pd.notna(prev.get("MA5")) and pd.notna(prev.get("MA20"))
        and pd.notna(ma5) and pd.notna(ma20)
        and prev["MA5"] <= prev["MA20"]
        and ma5 > ma20
    ):
        score += 25
        signals.append("골든크로스")

    # 3) 중기 추세
    if pd.notna(ma20) and pd.notna(ma60) and ma20 > ma60:
        score += 15
        signals.append("20일선이 60일선 위")

    # 4) RSI: 과매도 반등 또는 안정적 상승 구간
    if pd.notna(rsi):
        if 30 <= rsi <= 55:
            score += 15
            signals.append("RSI 매수 관심 구간")
        elif rsi < 30:
            score += 10
            signals.append("RSI 과매도")
        elif rsi > 75:
            score -= 15
            signals.append("RSI 과열 주의")

    # 5) MACD
    if pd.notna(macd) and pd.notna(macd_signal):
        if macd > macd_signal:
            score += 15
            signals.append("MACD 상승 전환")

    # 6) 거래량 증가
    vol_avg20 = price_df["거래량"].tail(20).mean()
    if vol_avg20 > 0 and latest["거래량"] > vol_avg20 * 1.3:
        score += 10
        signals.append("거래량 증가")

    # 7) 수급 보조 확인
    if supply_df is not None and not supply_df.empty:
        foreign_5 = supply_df["외국인"].tail(5).sum()
        inst_5 = supply_df["기관"].tail(5).sum()
        foreign_20 = supply_df["외국인"].tail(20).sum()
        inst_20 = supply_df["기관"].tail(20).sum()

        if foreign_5 > 0 and inst_5 > 0:
            score += 20
            signals.append("외국인·기관 단기 동반매수")
        elif foreign_20 > 0 and inst_20 > 0:
            score += 15
            signals.append("외국인·기관 중기 동반매수")
        elif foreign_5 < 0 and inst_5 < 0:
            score -= 20
            signals.append("외국인·기관 동반매도 주의")

    if score >= 80:
        grade = "강한 매수 관심"
    elif score >= 55:
        grade = "매수 관심"
    elif score >= 35:
        grade = "관찰"
    elif score >= 15:
        grade = "약함"
    else:
        grade = "매수신호 없음"

    return grade, signals, score

def analyze_supply_signal(supply_df):
    if supply_df is None or supply_df.empty:
        return {
            "외국인5일": 0,
            "외국인20일": 0,
            "기관5일": 0,
            "기관20일": 0,
            "수급신호": "데이터 없음",
        }

    foreign_5 = supply_df["외국인"].tail(5).sum()
    foreign_20 = supply_df["외국인"].tail(20).sum()
    inst_5 = supply_df["기관"].tail(5).sum()
    inst_20 = supply_df["기관"].tail(20).sum()

    if foreign_5 > 0 and inst_5 > 0 and foreign_20 > 0 and inst_20 > 0:
        signal = "강한 매수"
    elif foreign_5 > 0 and inst_5 > 0:
        signal = "단기 동반매수"
    elif foreign_20 > 0 and inst_20 > 0:
        signal = "중기 동반매수"
    elif foreign_5 < 0 and inst_5 < 0:
        signal = "동반매도 주의"
    elif foreign_5 > 0 and inst_5 < 0:
        signal = "외국인 매수/기관 매도"
    elif foreign_5 < 0 and inst_5 > 0:
        signal = "기관 매수/외국인 매도"
    else:
        signal = "중립"

    return {
        "외국인5일": foreign_5,
        "외국인20일": foreign_20,
        "기관5일": inst_5,
        "기관20일": inst_20,
        "수급신호": signal,
    }


def get_current_price_and_signal(company_name, ticker_hint=None):
    ticker = str(ticker_hint).zfill(6) if ticker_hint and str(ticker_hint).strip() not in ["", "nan", "None"] else find_ticker(company_name)

    if not ticker:
        return {
            "종목코드": "",
            "현재가": 0,
            "신호": "종목코드 없음",
            "상세신호": [],
            "가격데이터": pd.DataFrame(),
        }

    try:
        price_df = get_price_data(ticker)
        if price_df.empty:
            return {
                "종목코드": ticker,
                "현재가": 0,
                "신호": "가격데이터 없음",
                "상세신호": [],
                "가격데이터": pd.DataFrame(),
            }

        current_price = float(price_df["종가"].iloc[-1])
        signal, details = analyze_sell_signal(price_df)

        return {
            "종목코드": ticker,
            "현재가": current_price,
            "신호": signal,
            "상세신호": details,
            "가격데이터": price_df,
        }

    except Exception as e:
        return {
            "종목코드": ticker,
            "현재가": 0,
            "신호": "조회오류",
            "상세신호": [str(e)],
            "가격데이터": pd.DataFrame(),
        }



# -----------------------------
# 종목 스크리너
# -----------------------------
@st.cache_data(ttl=60 * 60)
def get_market_ticker_table(markets):
    rows = []
    for market in markets:
        try:
            tickers = stock.get_market_ticker_list(market=market)
        except Exception:
            tickers = []
        for ticker in tickers:
            try:
                name = stock.get_market_ticker_name(ticker)
            except Exception:
                name = ""
            if name:
                rows.append({"시장": market, "종목코드": ticker, "종목명": name})
    return pd.DataFrame(rows)


def screen_one_stock(ticker, name, options):
    """스크리너용 단일 종목 분석. 조건 통과 여부와 점수를 반환."""
    price_df = get_price_data(ticker, days=260)
    if price_df is None or price_df.empty or len(price_df) < 60:
        return None

    latest = price_df.iloc[-1]
    prev = price_df.iloc[-2]
    supply_df = pd.DataFrame()
    supply_summary = {"외국인5일": 0, "기관5일": 0, "수급신호": "미조회"}

    need_supply = options.get("foreign_buy") or options.get("institution_buy") or options.get("use_supply_score")
    if need_supply:
        supply_df = get_investor_trading_data(ticker, days=45)
        supply_summary = analyze_supply_signal(supply_df)

    buy_grade, buy_details, buy_score = analyze_buy_signal(price_df, supply_df if not supply_df.empty else None)
    sell_grade, sell_details = analyze_sell_signal(price_df)

    close = float(latest.get("종가", 0))
    rsi = latest.get("RSI")
    ma5 = latest.get("MA5")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")
    macd = latest.get("MACD")
    macd_signal = latest.get("MACD_SIGNAL")

    vol_avg20 = price_df["거래량"].tail(20).mean()
    vol_ratio = float(latest.get("거래량", 0) / vol_avg20) if vol_avg20 else 0
    high_52w = price_df["고가"].tail(250).max() if "고가" in price_df.columns else price_df["종가"].tail(250).max()
    high_gap = ((high_52w - close) / high_52w * 100) if high_52w else 999

    pass_reasons = []
    fail = False

    if options.get("rsi_low"):
        threshold = options.get("rsi_threshold", 35)
        ok = pd.notna(rsi) and rsi <= threshold
        if ok:
            pass_reasons.append(f"RSI {rsi:.1f}")
        else:
            fail = True

    if options.get("ma_up"):
        ok = pd.notna(ma5) and pd.notna(ma20) and ma5 > ma20
        if ok:
            pass_reasons.append("5일선 > 20일선")
        else:
            fail = True

    if options.get("golden_cross"):
        ok = (
            pd.notna(prev.get("MA5")) and pd.notna(prev.get("MA20"))
            and pd.notna(ma5) and pd.notna(ma20)
            and prev["MA5"] <= prev["MA20"] and ma5 > ma20
        )
        if ok:
            pass_reasons.append("골든크로스")
        else:
            fail = True

    if options.get("macd_up"):
        ok = pd.notna(macd) and pd.notna(macd_signal) and macd > macd_signal
        if ok:
            pass_reasons.append("MACD 상승")
        else:
            fail = True

    if options.get("volume_spike"):
        threshold = options.get("volume_ratio", 1.5)
        ok = vol_ratio >= threshold
        if ok:
            pass_reasons.append(f"거래량 {vol_ratio:.1f}배")
        else:
            fail = True

    if options.get("near_high"):
        threshold = options.get("high_gap", 10)
        ok = high_gap <= threshold
        if ok:
            pass_reasons.append(f"52주 고점 {high_gap:.1f}% 이내")
        else:
            fail = True

    if options.get("foreign_buy"):
        ok = supply_summary.get("외국인5일", 0) > 0
        if ok:
            pass_reasons.append("외국인 5일 순매수")
        else:
            fail = True

    if options.get("institution_buy"):
        ok = supply_summary.get("기관5일", 0) > 0
        if ok:
            pass_reasons.append("기관 5일 순매수")
        else:
            fail = True

    if fail:
        return None

    return {
        "종목명": name,
        "종목코드": ticker,
        "현재가": close,
        "RSI": float(rsi) if pd.notna(rsi) else None,
        "MA5": float(ma5) if pd.notna(ma5) else None,
        "MA20": float(ma20) if pd.notna(ma20) else None,
        "MA60": float(ma60) if pd.notna(ma60) else None,
        "거래량배수": vol_ratio,
        "52주고점거리%": high_gap,
        "외국인5일": supply_summary.get("외국인5일", 0),
        "기관5일": supply_summary.get("기관5일", 0),
        "수급신호": supply_summary.get("수급신호", "미조회"),
        "매수신호": buy_grade,
        "매수점수": buy_score,
        "매수상세": ", ".join(buy_details),
        "매도신호": sell_grade,
        "매도상세": ", ".join(sell_details),
        "통과조건": ", ".join(pass_reasons) if pass_reasons else "기본 점수 기준",
    }

# -----------------------------
# 네이버 뉴스
# -----------------------------
def get_naver_keys():
    client_id = None
    client_secret = None

    try:
        client_id = st.secrets.get("NAVER_CLIENT_ID")
        client_secret = st.secrets.get("NAVER_CLIENT_SECRET")
    except Exception:
        pass

    return client_id, client_secret


@st.cache_data(ttl=60 * 30)
def get_news(company_name, display=5):
    client_id, client_secret = get_naver_keys()

    if not client_id or not client_secret:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    params = {
        "query": company_name,
        "display": display,
        "sort": "date"
    }
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    news = []
    for item in data.get("items", []):
        news.append({
            "제목": clean_html(item.get("title", "")),
            "링크": item.get("originallink") or item.get("link"),
            "날짜": item.get("pubDate", ""),
        })

    return news




# -----------------------------
# 백테스트
# -----------------------------
@st.cache_data(ttl=60 * 60)
def get_price_data_by_date(ticker, start_date, end_date):
    """백테스트용 기간 지정 가격 데이터"""
    try:
        df = stock.get_market_ohlcv_by_date(
            pd.to_datetime(start_date).strftime("%Y%m%d"),
            pd.to_datetime(end_date).strftime("%Y%m%d"),
            ticker
        )
    except Exception:
        return pd.DataFrame()

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

    return df.dropna(subset=["종가"])


def is_buy_signal(row, prev_row, strategy, buy_rsi=35, ai_score_threshold=70):
    """백테스트 매수 조건"""
    try:
        if strategy == "RSI 반등 전략":
            return pd.notna(row["RSI"]) and row["RSI"] <= buy_rsi

        if strategy == "MACD 골든크로스 전략":
            return (
                pd.notna(prev_row["MACD"]) and pd.notna(prev_row["MACD_SIGNAL"])
                and pd.notna(row["MACD"]) and pd.notna(row["MACD_SIGNAL"])
                and prev_row["MACD"] <= prev_row["MACD_SIGNAL"]
                and row["MACD"] > row["MACD_SIGNAL"]
            )

        if strategy == "5일/20일 골든크로스 전략":
            return (
                pd.notna(prev_row["MA5"]) and pd.notna(prev_row["MA20"])
                and pd.notna(row["MA5"]) and pd.notna(row["MA20"])
                and prev_row["MA5"] <= prev_row["MA20"]
                and row["MA5"] > row["MA20"]
            )

        if strategy == "AI 점수 전략":
            score = 0
            if pd.notna(row["MA5"]) and pd.notna(row["MA10"]) and pd.notna(row["MA20"]):
                if row["종가"] > row["MA5"] > row["MA10"]:
                    score += 20
                if row["MA5"] > row["MA10"] > row["MA20"]:
                    score += 20
            if pd.notna(row["MA20"]) and pd.notna(row["MA60"]) and row["MA20"] > row["MA60"]:
                score += 15
            if pd.notna(row["RSI"]):
                if 30 <= row["RSI"] <= 55:
                    score += 15
                elif row["RSI"] < 30:
                    score += 10
                elif row["RSI"] > 75:
                    score -= 15
            if pd.notna(row["MACD"]) and pd.notna(row["MACD_SIGNAL"]) and row["MACD"] > row["MACD_SIGNAL"]:
                score += 15
            return score >= ai_score_threshold
    except Exception:
        return False

    return False


def get_sell_reason(row, prev_row, buy_price, take_profit, stop_loss, use_macd_dead, use_ma_dead):
    """백테스트 매도 조건"""
    current = float(row["종가"])
    profit_rate = (current - buy_price) / buy_price * 100

    if profit_rate >= take_profit:
        return f"익절 {take_profit:.1f}%"
    if profit_rate <= -abs(stop_loss):
        return f"손절 -{abs(stop_loss):.1f}%"

    if use_macd_dead:
        try:
            if (
                pd.notna(prev_row["MACD"]) and pd.notna(prev_row["MACD_SIGNAL"])
                and pd.notna(row["MACD"]) and pd.notna(row["MACD_SIGNAL"])
                and prev_row["MACD"] >= prev_row["MACD_SIGNAL"]
                and row["MACD"] < row["MACD_SIGNAL"]
            ):
                return "MACD 데드크로스"
        except Exception:
            pass

    if use_ma_dead:
        try:
            if pd.notna(row["MA5"]) and pd.notna(row["MA20"]) and row["MA5"] < row["MA20"]:
                return "5일선/20일선 이탈"
        except Exception:
            pass

    return None


def run_backtest(price_df, strategy, initial_cash, buy_rsi, ai_score_threshold, take_profit, stop_loss, use_macd_dead, use_ma_dead, fee_rate):
    """단일 종목 단순 백테스트: 전액 매수/전액 매도"""
    if price_df is None or price_df.empty or len(price_df) < 80:
        return None

    cash = float(initial_cash)
    shares = 0
    buy_price = 0
    buy_date = None
    trades = []
    equity_rows = []

    for i in range(60, len(price_df)):
        date = price_df.index[i]
        row = price_df.iloc[i]
        prev = price_df.iloc[i - 1]
        close = float(row["종가"])

        if shares == 0:
            if is_buy_signal(row, prev, strategy, buy_rsi, ai_score_threshold):
                shares = int(cash // (close * (1 + fee_rate)))
                if shares > 0:
                    cost = shares * close * (1 + fee_rate)
                    cash -= cost
                    buy_price = close
                    buy_date = date
                    trades.append({
                        "일자": date.strftime("%Y-%m-%d"),
                        "구분": "매수",
                        "가격": close,
                        "수량": shares,
                        "수익률%": 0.0,
                        "사유": strategy,
                    })
        else:
            reason = get_sell_reason(row, prev, buy_price, take_profit, stop_loss, use_macd_dead, use_ma_dead)
            if reason:
                revenue = shares * close * (1 - fee_rate)
                cash += revenue
                profit_rate = (close - buy_price) / buy_price * 100 - (fee_rate * 2 * 100)
                trades.append({
                    "일자": date.strftime("%Y-%m-%d"),
                    "구분": "매도",
                    "가격": close,
                    "수량": shares,
                    "수익률%": profit_rate,
                    "사유": reason,
                })
                shares = 0
                buy_price = 0
                buy_date = None

        equity = cash + shares * close
        equity_rows.append({"일자": date, "자산": equity, "종가": close})

    # 마지막 날 보유 중이면 평가만 반영하고 거래내역에는 미실현 표시
    if shares > 0:
        last_date = price_df.index[-1]
        last_close = float(price_df["종가"].iloc[-1])
        unrealized = (last_close - buy_price) / buy_price * 100
        trades.append({
            "일자": last_date.strftime("%Y-%m-%d"),
            "구분": "보유중",
            "가격": last_close,
            "수량": shares,
            "수익률%": unrealized,
            "사유": "미실현 평가",
        })

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(trades)

    if equity_df.empty:
        return None

    final_equity = float(equity_df["자산"].iloc[-1])
    total_return = (final_equity - initial_cash) / initial_cash * 100

    sell_trades = trades_df[trades_df["구분"] == "매도"] if not trades_df.empty else pd.DataFrame()
    win_rate = 0
    avg_return = 0
    max_profit = 0
    max_loss = 0
    trade_count = 0

    if not sell_trades.empty:
        returns = sell_trades["수익률%"].astype(float)
        trade_count = len(returns)
        win_rate = (returns > 0).mean() * 100
        avg_return = returns.mean()
        max_profit = returns.max()
        max_loss = returns.min()

    equity_df["누적최고"] = equity_df["자산"].cummax()
    equity_df["낙폭%"] = (equity_df["자산"] - equity_df["누적최고"]) / equity_df["누적최고"] * 100
    max_drawdown = equity_df["낙폭%"].min()

    return {
        "equity_df": equity_df,
        "trades_df": trades_df,
        "final_equity": final_equity,
        "total_return": total_return,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "max_drawdown": max_drawdown,
    }



# -----------------------------
# 스마트 스크리너
# -----------------------------
SMART_PRESETS = {
    "균형형": {"quality": 40, "growth": 30, "supply": 20, "technical": 10},
    "버핏형": {"quality": 70, "growth": 20, "supply": 0, "technical": 10},
    "성장주형": {"quality": 0, "growth": 50, "supply": 30, "technical": 20},
    "수급형": {"quality": 0, "growth": 0, "supply": 60, "technical": 40},
    "AI/반도체형": {"quality": 20, "growth": 40, "supply": 30, "technical": 10},
}


def get_smart_grade(score):
    if score >= 90:
        return "🔥 최우선"
    if score >= 80:
        return "🟢 매수후보"
    if score >= 70:
        return "🟡 관심"
    if score >= 60:
        return "⚪ 관찰"
    return "❌ 제외"


def score_market_cap(market_cap):
    if market_cap >= 50_0000_0000_0000:
        return 10
    if market_cap >= 10_0000_0000_0000:
        return 8
    if market_cap >= 1_0000_0000_0000:
        return 6
    if market_cap >= 3000_0000_0000:
        return 4
    return 0


@st.cache_data(ttl=60 * 60 * 6)
def get_market_cap_table_safe():
    try:
        today = datetime.today().strftime("%Y%m%d")
        return stock.get_market_cap_by_ticker(today)
    except Exception:
        return pd.DataFrame()


def get_market_cap_safe(ticker):
    try:
        cap_df = get_market_cap_table_safe()
        if cap_df is not None and not cap_df.empty and ticker in cap_df.index:
            return float(cap_df.loc[ticker, "시가총액"])
    except Exception:
        pass
    return 0


def calculate_quality_score(market_cap, roe=None, debt_ratio=None, profit_positive=True):
    score = 0
    details = []

    mc_score = score_market_cap(market_cap)
    score += mc_score
    details.append(f"시총 {mc_score}/10")

    # 재무 데이터 자동화 전까지는 중립값. 다음 버전에서 PER/PBR/ROE 데이터 소스 연결 예정.
    roe_score = 6 if roe is None else (10 if roe >= 20 else 8 if roe >= 15 else 6 if roe >= 10 else 0)
    debt_score = 6 if debt_ratio is None else (10 if debt_ratio <= 50 else 8 if debt_ratio <= 100 else 5 if debt_ratio <= 200 else 0)
    profit_score = 10 if profit_positive else 0

    score += roe_score + debt_score + profit_score
    details.append(f"ROE {roe_score}/10")
    details.append(f"부채 {debt_score}/10")
    details.append(f"흑자/안정 {profit_score}/10")

    return min(score, 40), ", ".join(details)


def calculate_growth_score(price_df):
    if price_df is None or len(price_df) < 120:
        return 0, "데이터 부족"

    close = price_df["종가"]
    score = 0
    details = []

    try:
        ret_60 = close.iloc[-1] / close.iloc[-60] - 1
        ret_120 = close.iloc[-1] / close.iloc[-120] - 1
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]

        if ret_120 >= 0.30:
            score += 10
            details.append("120일 +30%")
        elif ret_120 >= 0.15:
            score += 7
            details.append("120일 +15%")

        if ret_60 >= 0.20:
            score += 10
            details.append("60일 +20%")
        elif ret_60 >= 0.10:
            score += 7
            details.append("60일 +10%")

        if ma20 > ma60 > ma120:
            score += 10
            details.append("중기 정배열")
        elif ma20 > ma60:
            score += 6
            details.append("단기 정배열")
    except Exception:
        return 0, "성장 계산 실패"

    return min(score, 30), ", ".join(details) if details else "성장 모멘텀 약함"


def calculate_supply_score(ticker):
    try:
        supply_df = get_investor_trading_data(ticker, days=45)
        if supply_df is None or supply_df.empty:
            return 0, "수급 데이터 없음", 0, 0

        foreign_5 = float(supply_df["외국인"].tail(5).sum())
        foreign_20 = float(supply_df["외국인"].tail(20).sum())
        inst_5 = float(supply_df["기관"].tail(5).sum())
        inst_20 = float(supply_df["기관"].tail(20).sum())

        score = 0
        details = []

        if foreign_20 > 0:
            score += 10
            details.append("외국인 20일 순매수")
        elif foreign_5 > 0:
            score += 5
            details.append("외국인 5일 순매수")

        if inst_20 > 0:
            score += 10
            details.append("기관 20일 순매수")
        elif inst_5 > 0:
            score += 5
            details.append("기관 5일 순매수")

        return min(score, 20), ", ".join(details) if details else "수급 약함", foreign_20, inst_20
    except Exception:
        return 0, "수급 계산 실패", 0, 0


def calculate_technical_score(price_df):
    if price_df is None or len(price_df) < 60:
        return 0, "데이터 부족"

    try:
        latest = price_df.iloc[-1]
        prev = price_df.iloc[-2]
        score = 0
        details = []

        rsi = latest.get("RSI")
        if pd.notna(rsi):
            if rsi <= 35:
                score += 5
                details.append("RSI 35 이하")
            elif rsi <= 40:
                score += 3
                details.append("RSI 40 이하")

        macd = latest.get("MACD")
        macd_signal = latest.get("MACD_SIGNAL")
        prev_macd = prev.get("MACD")
        prev_signal = prev.get("MACD_SIGNAL")

        if pd.notna(macd) and pd.notna(macd_signal):
            if pd.notna(prev_macd) and pd.notna(prev_signal) and prev_macd <= prev_signal and macd > macd_signal:
                score += 3
                details.append("MACD 골든크로스")
            elif macd > macd_signal:
                score += 2
                details.append("MACD 상승")

        if pd.notna(latest.get("MA5")) and pd.notna(latest.get("MA20")) and latest["MA5"] > latest["MA20"]:
            score += 2
            details.append("5일선 > 20일선")

        if pd.notna(latest.get("MA20")) and pd.notna(latest.get("MA60")) and latest["MA20"] > latest["MA60"]:
            score += 2
            details.append("20일선 > 60일선")

        return min(score, 10), ", ".join(details) if details else "기술 신호 약함"
    except Exception:
        return 0, "기술 계산 실패"


def weighted_score(raw_scores, preset_name):
    weights = SMART_PRESETS.get(preset_name, SMART_PRESETS["균형형"])
    max_map = {"quality": 40, "growth": 30, "supply": 20, "technical": 10}
    total = 0

    for key, raw in raw_scores.items():
        max_score = max_map[key]
        total += (raw / max_score * weights[key]) if max_score else 0

    return round(total, 1)


def run_smart_screener(markets, preset_name, max_count, min_market_cap, min_total_score, include_etf=False):
    rows = []
    checked = 0

    for market in markets:
        try:
            tickers = stock.get_market_ticker_list(market=market)
        except Exception:
            continue

        for ticker in tickers:
            if checked >= max_count:
                break

            try:
                name = stock.get_market_ticker_name(ticker)

                if not include_etf and any(x in name.upper() for x in ["ETF", "ETN", "TIGER", "KODEX", "ACE", "SOL ", "KBSTAR"]):
                    continue

                checked += 1

                price_df = get_price_data(ticker, days=260)
                if price_df is None or price_df.empty or len(price_df) < 60:
                    continue

                current_price = float(price_df["종가"].iloc[-1])
                market_cap = get_market_cap_safe(ticker)

                if market_cap < min_market_cap:
                    continue

                q_score, q_detail = calculate_quality_score(market_cap)
                g_score, g_detail = calculate_growth_score(price_df)
                s_score, s_detail, foreign_20, inst_20 = calculate_supply_score(ticker)
                t_score, t_detail = calculate_technical_score(price_df)

                total = weighted_score(
                    {
                        "quality": q_score,
                        "growth": g_score,
                        "supply": s_score,
                        "technical": t_score,
                    },
                    preset_name,
                )

                if total < min_total_score:
                    continue

                rows.append(
                    {
                        "종목명": name,
                        "종목코드": ticker,
                        "시장": market,
                        "현재가": int(current_price),
                        "시가총액": int(market_cap),
                        "총점": total,
                        "등급": get_smart_grade(total),
                        "품질": q_score,
                        "성장": g_score,
                        "수급": s_score,
                        "기술": t_score,
                        "외국인20일": int(foreign_20),
                        "기관20일": int(inst_20),
                        "품질상세": q_detail,
                        "성장상세": g_detail,
                        "수급상세": s_detail,
                        "기술상세": t_detail,
                    }
                )
            except Exception:
                continue

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    return result.sort_values(["총점", "수급", "기술"], ascending=False).reset_index(drop=True)




def analyze_weekly_signal(ticker):
    """
    주봉 기준 장기 추세 분석
    🟢 장기상승 : 10주 > 20주 > 40주
    🟡 장기조정 : 주가가 20주선 아래 또는 10주<20주
    🔴 장기하락 : 20주 < 40주
    """
    try:
        end = datetime.today()
        start = end - timedelta(days=800)
        df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)

        if df is None or len(df) < 200:
            return "데이터부족", []

        w = df.resample("W").last()
        w["W10"] = w["종가"].rolling(10).mean()
        w["W20"] = w["종가"].rolling(20).mean()
        w["W40"] = w["종가"].rolling(40).mean()

        last = w.iloc[-1]
        price = last["종가"]

        signals = []

        if last["W10"] > last["W20"] > last["W40"]:
            signals.append("10주>20주>40주")
            return "🟢 장기상승", signals

        if last["W20"] < last["W40"]:
            signals.append("20주선<40주선")
            return "🔴 장기하락", signals

        if price < last["W20"]:
            signals.append("주가<20주선")
            return "🟡 장기조정", signals

        if last["W10"] < last["W20"]:
            signals.append("10주선<20주선")
            return "🟡 장기조정", signals

        return "🟡 장기조정", signals
    except Exception:
        return "데이터부족", []



def make_final_decision(buy_signal, daily_sell_signal, weekly_signal):
    """
    매수신호 + 일봉 매도신호 + 주봉신호를 합친 종합판정.
    중장기 투자자는 주봉을 더 크게 반영합니다.
    """
    buy = str(buy_signal)
    daily = str(daily_sell_signal)
    weekly = str(weekly_signal)

    if "장기하락" in weekly and "매도" in daily:
        return "🔴 매도검토"

    if "장기하락" in weekly and ("경고" in daily or "주의" in daily):
        return "🟠 축소검토"

    if "장기조정" in weekly and "매도" in daily:
        return "🟠 축소검토"

    if "장기상승" in weekly and "매도" in daily:
        return "🟡 비중축소/관찰"

    if "장기상승" in weekly and ("경고" in daily or "주의" in daily):
        return "🟢 보유"

    if "장기상승" in weekly and ("매수 관심" in buy or "강한 매수" in buy):
        return "🔥 매수후보"

    if "장기상승" in weekly and "양호" in daily:
        return "🟢 보유"

    if "장기조정" in weekly and ("매수 관심" in buy or "관찰" in buy):
        return "🟡 관찰"

    if "장기조정" in weekly:
        return "🟡 관찰"

    return "⚪ 확인필요"




def sort_portfolio_dataframe(df, sort_by, ascending=False):
    """
    포트폴리오 표 정렬.
    종합판정/신호처럼 문자 등급은 사용자 기준 우선순위로 정렬합니다.
    """
    if df is None or df.empty or sort_by not in df.columns:
        return df

    df = df.copy()

    decision_rank = {
        "🔥 매수후보": 1,
        "🟢 보유": 2,
        "🟡 비중축소/관찰": 3,
        "🟡 관찰": 4,
        "🟠 축소검토": 5,
        "🔴 매도검토": 6,
        "⚪ 확인필요": 7,
    }

    daily_rank = {
        "🟢 양호": 1,
        "🟡 주의": 2,
        "🟠 경고": 3,
        "🔴 매도": 4,
        "데이터 부족": 5,
    }

    weekly_rank = {
        "🟢 장기상승": 1,
        "🟡 장기조정": 2,
        "🔴 장기하락": 3,
        "데이터부족": 4,
    }

    buy_rank = {
        "강한 매수 관심": 1,
        "매수 관심": 2,
        "관찰": 3,
        "약함": 4,
        "매수신호 없음": 5,
        "데이터 부족": 6,
    }

    if sort_by == "종합판정":
        df["_sort_key"] = df[sort_by].map(decision_rank).fillna(99)
        df = df.sort_values("_sort_key", ascending=ascending).drop(columns=["_sort_key"])
    elif sort_by == "일봉신호":
        df["_sort_key"] = df[sort_by].map(daily_rank).fillna(99)
        df = df.sort_values("_sort_key", ascending=ascending).drop(columns=["_sort_key"])
    elif sort_by == "주봉신호":
        df["_sort_key"] = df[sort_by].map(weekly_rank).fillna(99)
        df = df.sort_values("_sort_key", ascending=ascending).drop(columns=["_sort_key"])
    elif sort_by == "매수신호":
        df["_sort_key"] = df[sort_by].map(buy_rank).fillna(99)
        df = df.sort_values("_sort_key", ascending=ascending).drop(columns=["_sort_key"])
    else:
        df = df.sort_values(sort_by, ascending=ascending)

    return df.reset_index(drop=True)



def show_pinned_dataframe(df, key="pinned_grid", height=None):
    """
    포트폴리오 표:
    - 종목명 왼쪽 고정
    - 가로 스크롤 유지
    - 세로 스크롤 유지
    - 화면이 너무 길어지지 않도록 표 높이 선택 가능
    """
    if df is None or df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    safe_df = df.copy().fillna("")
    total_rows = len(safe_df)

    c1, c2 = st.columns([1, 2])
    table_height = c1.selectbox(
        "표 높이",
        ["작게", "보통", "크게", "전체에 가깝게"],
        index=1,
        key=f"{key}_height_select"
    )

    height_map = {
        "작게": 320,
        "보통": 480,
        "크게": 650,
        "전체에 가깝게": 850,
    }
    table_height_px = height_map.get(table_height, 480)

    c2.caption(f"전체 {total_rows}개 종목 표시 · 표 안에서 세로/가로 스크롤 가능")

    def esc(value):
        return html.escape(str(value))

    columns = list(safe_df.columns)

    table_html = []
    table_html.append(f'<div class="portfolio-scroll-wrap" style="max-height:{table_height_px}px;">')
    table_html.append('<table class="portfolio-table">')

    table_html.append("<thead><tr>")
    for col in columns:
        cls = "sticky-col" if col == "종목명" else ""
        table_html.append(f'<th class="{cls}">{esc(col)}</th>')
    table_html.append("</tr></thead>")

    table_html.append("<tbody>")
    for _, row in safe_df.iterrows():
        table_html.append("<tr>")
        for col in columns:
            cls = "sticky-col" if col == "종목명" else ""
            table_html.append(f'<td class="{cls}">{esc(row[col])}</td>')
        table_html.append("</tr>")
    table_html.append("</tbody></table></div>")

    st.markdown(
        """
        <style>
        .portfolio-scroll-wrap {
            width: 100%;
            overflow: auto;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            margin-top: 4px;
            margin-bottom: 16px;
        }
        .portfolio-table {
            border-collapse: separate;
            border-spacing: 0;
            min-width: 2400px;
            width: max-content;
            font-size: 14px;
        }
        .portfolio-table th,
        .portfolio-table td {
            white-space: nowrap;
            padding: 8px 12px;
            border-bottom: 1px solid #e5e7eb;
            border-right: 1px solid #f1f5f9;
            background: white;
            text-align: left;
        }
        .portfolio-table th {
            font-weight: 700;
            background: #f8fafc;
            position: sticky;
            top: 0;
            z-index: 4;
        }
        .portfolio-table .sticky-col {
            position: sticky;
            left: 0;
            z-index: 5;
            background: #ffffff;
            min-width: 150px;
            max-width: 180px;
            box-shadow: 2px 0 4px rgba(0,0,0,0.08);
        }
        .portfolio-table th.sticky-col {
            background: #f8fafc;
            z-index: 7;
        }
        .portfolio-scroll-wrap::-webkit-scrollbar {
            width: 13px;
            height: 13px;
        }
        .portfolio-scroll-wrap::-webkit-scrollbar-thumb {
            background: #94a3b8;
            border-radius: 8px;
        }
        .portfolio-scroll-wrap::-webkit-scrollbar-track {
            background: #e2e8f0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("".join(table_html), unsafe_allow_html=True)



def render_stock_detail(company_name, ticker_hint=None, key_prefix="detail"):
    """
    선택한 종목의 기술분석/수급분석/뉴스를 한 화면에서 보여줍니다.
    """
    if not company_name:
        st.info("종목을 선택하세요.")
        return

    info = get_current_price_and_signal(company_name, ticker_hint)
    ticker = info.get("종목코드", "")
    price_df = info.get("가격데이터", pd.DataFrame())

    if not ticker:
        st.error("종목코드를 찾지 못했습니다.")
        return

    supply_df = get_investor_trading_data(ticker, days=60)
    supply = analyze_supply_signal(supply_df)
    buy_grade, buy_details, buy_score = analyze_buy_signal(price_df, supply_df)
    daily_signal, daily_details = analyze_sell_signal(price_df, supply_df)
    weekly_signal, weekly_details = analyze_weekly_signal(ticker) if ticker else ("데이터부족", [])
    final_decision = make_final_decision(buy_grade, daily_signal, weekly_signal)

    st.markdown(f"### 🔎 {company_name} 상세분석")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("종목코드", ticker)
    c2.metric("현재가", money(info.get("현재가", 0)))
    c3.metric("종합판정", final_decision)
    c4.metric("매수신호", buy_grade, delta=f"점수 {buy_score}")
    c5.metric("일봉신호", daily_signal)
    c6.metric("주봉신호", weekly_signal)

    detail_tabs = st.tabs(["📈 기술분석", "🏦 수급분석", "📰 뉴스"])

    with detail_tabs[0]:
        left, right = st.columns(2)
        with left:
            st.write("**매수신호 상세**")
            if buy_details:
                st.success(" / ".join(buy_details))
            else:
                st.info("뚜렷한 매수신호가 없습니다.")

        with right:
            st.write("**일봉/주봉 상세**")
            if daily_details:
                if daily_signal == "🔴 매도":
                    st.error("일봉: " + " / ".join(daily_details))
                elif daily_signal in ["🟠 경고", "🟡 주의"]:
                    st.warning("일봉: " + " / ".join(daily_details))
                else:
                    st.success("일봉: " + " / ".join(daily_details))
            else:
                st.success("일봉: 주요 위험 신호 없음")

            if weekly_details:
                st.info("주봉: " + " / ".join(weekly_details))
            else:
                st.info("주봉: 주요 신호 없음")

        if price_df is None or price_df.empty:
            st.warning("가격 데이터를 불러오지 못했습니다.")
        else:
            chart_cols = [c for c in ["종가", "MA5", "MA10", "MA20", "MA60"] if c in price_df.columns]
            st.line_chart(price_df[chart_cols].dropna(), use_container_width=True)

            latest = price_df.iloc[-1]
            st.dataframe(
                pd.DataFrame([{
                    "종가": money(latest.get("종가", 0)),
                    "MA5": money(latest.get("MA5", 0)),
                    "MA10": money(latest.get("MA10", 0)),
                    "MA20": money(latest.get("MA20", 0)),
                    "MA60": money(latest.get("MA60", 0)),
                    "RSI": f"{float(latest['RSI']):.2f}" if pd.notna(latest.get("RSI")) else "-",
                    "MACD": f"{float(latest['MACD']):.2f}" if pd.notna(latest.get("MACD")) else "-",
                    "거래량": f"{int(latest.get('거래량', 0)):,}",
                }]),
                hide_index=True,
                use_container_width=True
            )

    with detail_tabs[1]:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("외국인 5일", number(supply["외국인5일"]))
        c2.metric("기관 5일", number(supply["기관5일"]))
        c3.metric("외국인 20일", number(supply["외국인20일"]))
        c4.metric("기관 20일", number(supply["기관20일"]))
        c5.metric("수급신호", supply["수급신호"])

        if supply_df.empty:
            st.warning("수급 데이터를 불러오지 못했습니다.")
        else:
            st.write("외국인·기관 누적 순매수 추이")
            st.line_chart(supply_df[["외국인_누적", "기관_누적"]], use_container_width=True)

            st.write("일별 순매수")
            st.bar_chart(supply_df[["외국인", "기관"]], use_container_width=True)

            display_supply = supply_df.tail(20).copy()
            display_supply.index = display_supply.index.strftime("%Y-%m-%d")
            st.dataframe(
                display_supply[["외국인", "기관", "외국인_누적", "기관_누적"]].style.format("{:,.0f}"),
                use_container_width=True
            )

    with detail_tabs[2]:
        client_id, client_secret = get_naver_keys()
        if not client_id or not client_secret:
            st.warning(".streamlit/secrets.toml에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET을 넣으면 뉴스가 표시됩니다.")

        news_items = get_news(company_name, display=10)
        if not news_items:
            st.info("뉴스가 없거나 네이버 API 설정/조회에 문제가 있습니다.")
        else:
            for item in news_items:
                st.markdown(f"**[{item['제목']}]({item['링크']})**")
                st.caption(item["날짜"])
                st.divider()



# -----------------------------
# 화면 시작
# -----------------------------
st.title("📈 AI 투자비서 V9 Cloud.13")
st.caption("포트폴리오 통합관리 · 선택종목 상세분석 · 관심그룹 · 스크리너 · 백테스트")

with st.sidebar:
    st.header("메뉴")
    refresh = st.button("🔄 데이터 새로고침")
    if refresh:
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.write("현재 사용자")
    st.code(CURRENT_USER)
    st.write("CSV 파일")
    st.code(CSV_FILE)
    st.write("관심그룹 CSV 파일")
    st.code(WATCHLIST_FILE)
    st.caption("외국인/기관 수급은 PyKRX 투자자별 순매수 수량 기준입니다.")

portfolio_df = load_portfolio()
watchlist_df = load_watchlist()

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 포트폴리오",
    "⭐ 관심그룹",
    "🔍 스크리너",
    "🧪 백테스트"
])


# -----------------------------
# TAB 1: 포트폴리오
# -----------------------------
with tab1:
    st.subheader("포트폴리오 현황")

    if portfolio_df.empty:
        st.info("아직 등록된 종목이 없습니다. '추가/수정/삭제' 탭에서 종목을 추가하세요.")
    else:
        rows = []
        progress = st.progress(0, text="현재가 및 수급 조회 중...")

        for i, row in portfolio_df.iterrows():
            company = row["종목명"]
            qty = int(row["수량"])
            avg = float(row["평균매수가"])
            invested = qty * avg

            info = get_current_price_and_signal(company, row.get("종목코드", ""))
            current = float(info["현재가"])
            eval_amount = qty * current if current > 0 else 0
            profit = eval_amount - invested if current > 0 else 0
            return_rate = ((current - avg) / avg * 100) if avg > 0 and current > 0 else 0
            detail_signal = ", ".join(info["상세신호"]) if info["상세신호"] else "-"

            supply_df = get_investor_trading_data(info["종목코드"]) if info["종목코드"] else pd.DataFrame()
            supply = analyze_supply_signal(supply_df)
            buy_grade, buy_details, buy_score = analyze_buy_signal(info["가격데이터"], supply_df)
            buy_detail_signal = ", ".join(buy_details) if buy_details else "-"
            sell_grade, sell_details = analyze_sell_signal(info["가격데이터"], supply_df)
            detail_signal = ", ".join(sell_details) if sell_details else "-"
            weekly_signal, weekly_details = analyze_weekly_signal(info["종목코드"]) if info["종목코드"] else ("데이터부족", [])
            weekly_detail_signal = ", ".join(weekly_details) if weekly_details else "-"
            final_decision = make_final_decision(buy_grade, sell_grade, weekly_signal)

            rows.append({
                "종목명": company,
                "종목코드": info["종목코드"],
                "수량": qty,
                "평균매수가": avg,
                "현재가": current,
                "투자금": invested,
                "평가금": eval_amount,
                "평가손익": profit,
                "수익률": return_rate,
                "종합판정": final_decision,
                "매수신호": buy_grade,
                "매수점수": buy_score,
                "매수상세": buy_detail_signal,
                "일봉신호": sell_grade,
                "일봉상세": detail_signal,
                "주봉신호": weekly_signal,
                "주봉상세": weekly_detail_signal,
                "외국인5일": supply["외국인5일"],
                "기관5일": supply["기관5일"],
                "수급신호": supply["수급신호"],
            })

            progress.progress((i + 1) / len(portfolio_df), text=f"{company} 조회 완료")

        progress.empty()
        result_df = pd.DataFrame(rows)

        total_invested = result_df["투자금"].sum()
        total_eval = result_df["평가금"].sum()
        total_profit = result_df["평가손익"].sum()
        total_return = (total_profit / total_invested * 100) if total_invested > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 투자금", money(total_invested))
        c2.metric("총 평가금", money(total_eval))
        c3.metric("총 손익", money(total_profit), delta=money(total_profit))
        c4.metric("총 수익률", pct(total_return), delta=pct(total_return))

        st.markdown("#### 포트폴리오 상세")

        sortable_cols = [
            "투자금", "평가금", "평가손익", "수익률",
            "종합판정", "매수점수", "매수신호", "일봉신호", "주봉신호",
            "외국인5일", "기관5일", "종목명"
        ]
        sortable_cols = [c for c in sortable_cols if c in result_df.columns]

        col_sort1, col_sort2 = st.columns([1, 1])
        sort_by = col_sort1.selectbox(
            "정렬 기준",
            sortable_cols,
            index=sortable_cols.index("투자금") if "투자금" in sortable_cols else 0,
            key="portfolio_sort_by"
        )

        sort_order_label = col_sort2.radio(
            "정렬 방향",
            ["큰 값/우선순위 먼저", "작은 값/낮은순 먼저"],
            horizontal=True,
            key="portfolio_sort_order"
        )

        ascending = sort_order_label == "작은 값/낮은순 먼저"
        sorted_result_df = sort_portfolio_dataframe(result_df, sort_by, ascending=ascending)

        display_df = sorted_result_df.copy()
        for col in ["평균매수가", "현재가", "투자금", "평가금", "평가손익"]:
            display_df[col] = display_df[col].apply(money)
        display_df["수익률"] = display_df["수익률"].apply(pct)
        display_df["외국인5일"] = display_df["외국인5일"].apply(number)
        display_df["기관5일"] = display_df["기관5일"].apply(number)

        preferred_cols = [
            "종목명", "종목코드", "수량", "평균매수가", "현재가",
            "투자금", "평가금", "평가손익", "수익률",
            "종합판정",
            "매수신호", "매수점수", "매수상세",
            "일봉신호", "일봉상세",
            "주봉신호", "주봉상세",
            "외국인5일", "기관5일", "수급신호"
        ]
        display_df = display_df[[c for c in preferred_cols if c in display_df.columns]]

        show_pinned_dataframe(display_df, key="portfolio_pinned_grid")

        st.subheader("종목별 평가금 비중")
        chart_df = result_df[result_df["평가금"] > 0][["종목명", "평가금"]].set_index("종목명")
        if not chart_df.empty:
            st.bar_chart(chart_df)



with st.expander("➕ 포트폴리오 추가/수정/삭제", expanded=False):
    st.subheader("종목 추가")

    with st.form("add_stock_form", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        new_name = col1.text_input("종목명", placeholder="예: 삼성전자")
        new_code = col2.text_input("종목코드(선택)", placeholder="예: 005930")
        new_qty = col3.number_input("수량", min_value=0, step=1)
        new_avg = col4.number_input("평균매수가", min_value=0.0, step=100.0)

        add_submitted = st.form_submit_button("추가")

        if add_submitted:
            if not new_name.strip():
                st.error("종목명을 입력하세요.")
            elif new_qty <= 0 or new_avg <= 0:
                st.error("수량과 평균매수가는 0보다 커야 합니다.")
            else:
                new_row = pd.DataFrame([{
                    "종목명": new_name.strip(),
                    "종목코드": new_code.strip().zfill(6) if new_code.strip() else find_ticker(new_name.strip()) or "",
                    "수량": int(new_qty),
                    "평균매수가": float(new_avg),
                    "투자액": int(new_qty) * float(new_avg),
                }])
                portfolio_df = pd.concat([portfolio_df, new_row], ignore_index=True)
                save_portfolio(portfolio_df)
                st.success(f"{new_name} 추가 완료")
                st.rerun()

    st.divider()
    st.subheader("수정")

    edited_df = st.data_editor(
        portfolio_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="portfolio_editor"
    )

    col_save, col_download = st.columns([1, 1])

    with col_save:
        if st.button("💾 수정 내용 CSV 저장"):
            save_portfolio(edited_df)
            st.success("CSV 저장 완료")
            st.rerun()

    with col_download:
        csv_bytes = normalize_portfolio(edited_df).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "⬇️ CSV 다운로드",
            data=csv_bytes,
            file_name="portfolio.csv",
            mime="text/csv"
        )

    st.caption("삭제는 표에서 행을 지운 뒤 '수정 내용 CSV 저장'을 누르면 됩니다.")




    st.divider()
    st.subheader("선택 종목 상세분석")

    detail_source_df = sorted_result_df if "sorted_result_df" in locals() else result_df
    if not detail_source_df.empty:
        selected_detail_stock = st.selectbox(
                "상세분석 종목 선택",
                detail_source_df["종목명"].tolist(),
                key="portfolio_detail_select"
            )
        selected_detail_row = detail_source_df[detail_source_df["종목명"] == selected_detail_stock].iloc[0]
        render_stock_detail(
            selected_detail_stock,
            selected_detail_row.get("종목코드", ""),
            key_prefix="portfolio_detail"
        )

# -----------------------------
# TAB 2: 관심그룹
# -----------------------------
with tab2:
    st.subheader("관심그룹 관리 및 매수/매도 신호")
    st.caption("보유 포트폴리오와 별도로 관심종목을 그룹별로 관리합니다. 저장 파일은 watchlist.csv 입니다.")

    left_add, right_add = st.columns([1, 2])

    with left_add:
        st.write("**관심종목 추가**")
        with st.form("add_watch_stock_form", clear_on_submit=True):
            group_name = st.text_input("그룹명", value="기본", placeholder="예: 반도체, AI, 전력, 로봇")
            watch_name = st.text_input("종목명", placeholder="예: SK하이닉스")
            watch_memo = st.text_input("메모", placeholder="예: 조정 시 관심")
            add_watch = st.form_submit_button("관심종목 추가")

            if add_watch:
                if not watch_name.strip():
                    st.error("종목명을 입력하세요.")
                else:
                    new_row = pd.DataFrame([{
                        "그룹": group_name.strip() or "기본",
                        "종목명": watch_name.strip(),
                        "종목코드": find_ticker(watch_name.strip()) or "",
                        "메모": watch_memo.strip(),
                    }])
                    watchlist_df = pd.concat([watchlist_df, new_row], ignore_index=True)
                    save_watchlist(watchlist_df)
                    st.success(f"{watch_name} 관심그룹 추가 완료")
                    st.rerun()

    with right_add:
        st.write("**관심그룹 편집**")
        edited_watch_df = st.data_editor(
            watchlist_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="watchlist_editor"
        )

        col_wsave, col_wdown = st.columns([1, 1])
        with col_wsave:
            if st.button("💾 관심그룹 저장"):
                save_watchlist(edited_watch_df)
                st.success("watchlist.csv 저장 완료")
                st.rerun()

        with col_wdown:
            watch_csv = normalize_watchlist(edited_watch_df).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                "⬇️ 관심그룹 CSV 다운로드",
                data=watch_csv,
                file_name="watchlist.csv",
                mime="text/csv"
            )

        st.caption("삭제는 표에서 행을 지운 뒤 '관심그룹 저장'을 누르면 됩니다.")

    st.divider()
    st.subheader("관심그룹 신호 보기")

    current_watchlist = normalize_watchlist(edited_watch_df) if 'edited_watch_df' in locals() else watchlist_df

    if current_watchlist.empty:
        st.info("아직 관심종목이 없습니다. 위에서 관심종목을 추가하세요.")
    else:
        groups = ["전체"] + sorted(current_watchlist["그룹"].dropna().astype(str).unique().tolist())
        selected_group = st.selectbox("그룹 선택", groups, key="watch_group_select")

        if selected_group == "전체":
            target_watchlist = current_watchlist.copy()
        else:
            target_watchlist = current_watchlist[current_watchlist["그룹"] == selected_group].copy()

        if target_watchlist.empty:
            st.info("선택한 그룹에 관심종목이 없습니다.")
        else:
            rows = []
            progress = st.progress(0, text="관심종목 신호 조회 중...")

            for i, row in target_watchlist.reset_index(drop=True).iterrows():
                name = row["종목명"]
                analyzed = analyze_watch_stock(name, row.get("종목코드", ""))
                analyzed["그룹"] = row.get("그룹", "기본")
                analyzed["메모"] = row.get("메모", "")
                rows.append(analyzed)
                progress.progress((i + 1) / len(target_watchlist), text=f"{name} 조회 완료")

            progress.empty()
            watch_result_df = pd.DataFrame(rows)

            if not watch_result_df.empty:
                show_watch = watch_result_df.copy()
                show_watch["현재가"] = show_watch["현재가"].apply(money)
                show_watch["외국인5일"] = show_watch["외국인5일"].apply(number)
                show_watch["기관5일"] = show_watch["기관5일"].apply(number)

                cols = [
                    "그룹", "종목명", "종목코드", "현재가",
                    "매수신호", "매수점수", "매수상세",
                    "일봉신호", "일봉상세", "주봉신호", "주봉상세",
                    "외국인5일", "기관5일", "수급신호", "메모"
                ]
                st.dataframe(show_watch[[c for c in cols if c in show_watch.columns]], use_container_width=True, hide_index=True)

                st.write("관심그룹 매수점수 순위")
                rank_df = watch_result_df.sort_values("매수점수", ascending=False)[["종목명", "매수점수"]].set_index("종목명")
                st.bar_chart(rank_df, use_container_width=True)

                st.divider()
                st.subheader("관심종목 상세 차트")
                selected_watch_stock = st.selectbox(
                    "상세 차트 종목 선택",
                    target_watchlist["종목명"].tolist(),
                    key="watch_detail_select"
                )

                detail_info = get_current_price_and_signal(selected_watch_stock)
                detail_ticker = detail_info.get("종목코드")
                detail_price_df = detail_info.get("가격데이터")
                detail_supply_df = get_investor_trading_data(detail_ticker, days=30) if detail_ticker else pd.DataFrame()
                detail_buy_grade, detail_buy_details, detail_buy_score = analyze_buy_signal(detail_price_df, detail_supply_df)

                d1, d2, d3, d4 = st.columns(4)
                d1.metric("종목코드", detail_ticker or "-")
                d2.metric("현재가", money(detail_info.get("현재가", 0)))
                d3.metric("매수신호", detail_buy_grade, delta=f"점수 {detail_buy_score}")
                d4.metric("매도신호", detail_info.get("신호", "-"))

                if detail_buy_details:
                    st.success("매수상세: " + " / ".join(detail_buy_details))
                else:
                    st.info("현재 뚜렷한 매수신호가 없습니다.")

                if detail_info.get("상세신호"):
                    st.warning("매도상세: " + " / ".join(detail_info.get("상세신호")))
                else:
                    st.success("현재 주요 매도 신호가 없습니다.")

                if detail_price_df is not None and not detail_price_df.empty:
                    st.write("가격/이동평균 차트")
                    st.line_chart(detail_price_df[["종가", "MA5", "MA10", "MA20", "MA60"]].dropna(), use_container_width=True)

                if detail_supply_df is not None and not detail_supply_df.empty:
                    st.write("외국인·기관 누적 순매수 추이")
                    st.line_chart(detail_supply_df[["외국인_누적", "기관_누적"]], use_container_width=True)


# -----------------------------
# TAB 3: 스크리너
# -----------------------------
with tab3:
    st.subheader("🔍 종목 스크리너")
    st.caption("코스피/코스닥 전체에서 조건에 맞는 종목을 찾습니다. 전체 조회는 시간이 걸릴 수 있어 처음에는 100~300개로 테스트하세요.")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        market_choice = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
        max_count = st.number_input("최대 검색 종목 수", min_value=20, max_value=2500, value=200, step=20)
    with col_b:
        sort_by = st.selectbox("정렬 기준", ["매수점수", "RSI", "거래량배수", "52주고점거리%", "외국인5일", "기관5일"])
        ascending = st.checkbox("오름차순 정렬", value=False)
    with col_c:
        name_filter = st.text_input("종목명 포함 검색", placeholder="예: LG, 삼성, 현대")
        min_buy_score = st.slider("최소 매수점수", 0, 120, 0, 5)

    st.write("조건 선택")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        cond_rsi = st.checkbox("RSI 기준 이하", value=False)
        rsi_threshold = st.slider("RSI 기준", 20, 60, 35, 1)
        cond_ma = st.checkbox("5일선 > 20일선", value=True)
    with c2:
        cond_golden = st.checkbox("골든크로스", value=False)
        cond_macd = st.checkbox("MACD 상승", value=True)
        cond_volume = st.checkbox("거래량 증가", value=False)
        volume_ratio = st.slider("거래량 배수", 1.0, 5.0, 1.5, 0.1)
    with c3:
        cond_foreign = st.checkbox("외국인 5일 순매수", value=False)
        cond_inst = st.checkbox("기관 5일 순매수", value=False)
        use_supply_score = st.checkbox("수급 점수 반영", value=True)
    with c4:
        cond_high = st.checkbox("52주 신고가 근접", value=False)
        high_gap = st.slider("52주 고점 대비 거리(%)", 1, 30, 10, 1)

    run_screen = st.button("🔎 스크리너 실행", type="primary")

    if run_screen:
        if not market_choice:
            st.warning("시장을 1개 이상 선택하세요.")
        else:
            ticker_table = get_market_ticker_table(market_choice)
            if name_filter.strip():
                ticker_table = ticker_table[ticker_table["종목명"].str.contains(name_filter.strip(), case=False, na=False)]
            ticker_table = ticker_table.head(int(max_count)).reset_index(drop=True)

            if ticker_table.empty:
                st.info("검색 대상 종목이 없습니다.")
            else:
                options = {
                    "rsi_low": cond_rsi,
                    "rsi_threshold": rsi_threshold,
                    "ma_up": cond_ma,
                    "golden_cross": cond_golden,
                    "macd_up": cond_macd,
                    "volume_spike": cond_volume,
                    "volume_ratio": volume_ratio,
                    "foreign_buy": cond_foreign,
                    "institution_buy": cond_inst,
                    "use_supply_score": use_supply_score,
                    "near_high": cond_high,
                    "high_gap": high_gap,
                }

                results = []
                progress = st.progress(0, text="종목 스크리닝 중...")
                status = st.empty()

                for i, row in ticker_table.iterrows():
                    name = row["종목명"]
                    ticker = row["종목코드"]
                    status.caption(f"조회 중: {name} ({i + 1}/{len(ticker_table)})")
                    try:
                        result = screen_one_stock(ticker, name, options)
                        if result and result.get("매수점수", 0) >= min_buy_score:
                            result["시장"] = row["시장"]
                            results.append(result)
                    except Exception:
                        pass
                    progress.progress((i + 1) / len(ticker_table), text=f"{i + 1}/{len(ticker_table)}개 조회 완료")

                progress.empty()
                status.empty()

                if not results:
                    st.info("조건을 통과한 종목이 없습니다. 조건을 조금 완화해 보세요.")
                else:
                    result_df = pd.DataFrame(results)
                    if sort_by in result_df.columns:
                        result_df = result_df.sort_values(sort_by, ascending=ascending)

                    st.success(f"조건 통과 종목: {len(result_df)}개")

                    display_df = result_df.copy()
                    for col in ["현재가", "외국인5일", "기관5일"]:
                        if col in display_df.columns:
                            display_df[col] = display_df[col].apply(number if col != "현재가" else money)
                    for col in ["RSI", "거래량배수", "52주고점거리%"]:
                        if col in display_df.columns:
                            display_df[col] = display_df[col].apply(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")

                    cols = [
                        "시장", "종목명", "종목코드", "현재가", "매수신호", "매수점수", "매도신호",
                        "RSI", "거래량배수", "52주고점거리%", "외국인5일", "기관5일", "수급신호", "통과조건", "매수상세"
                    ]
                    st.dataframe(display_df[[c for c in cols if c in display_df.columns]], use_container_width=True, hide_index=True)

                    st.download_button(
                        "⬇️ 스크리너 결과 CSV 다운로드",
                        data=result_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                        file_name="screener_result.csv",
                        mime="text/csv"
                    )

                    st.subheader("관심그룹에 추가")
                    add_col1, add_col2 = st.columns([2, 1])
                    with add_col1:
                        add_names = st.multiselect("추가할 종목", result_df["종목명"].tolist())
                    with add_col2:
                        add_group = st.text_input("그룹명", value="스크리너")

                    if st.button("⭐ 선택 종목 관심그룹 추가"):
                        if not add_names:
                            st.warning("추가할 종목을 선택하세요.")
                        else:
                            current = load_watchlist()
                            new_rows = pd.DataFrame({
                                "그룹": [add_group.strip() or "스크리너"] * len(add_names),
                                "종목명": add_names,
                                "메모": [f"스크리너 통과 {datetime.today().strftime('%Y-%m-%d')}"] * len(add_names),
                            })
                            combined = pd.concat([current, new_rows], ignore_index=True)
                            combined = combined.drop_duplicates(subset=["그룹", "종목명"], keep="last")
                            save_watchlist(combined)
                            st.success(f"{len(add_names)}개 종목을 관심그룹에 추가했습니다.")

                    st.subheader("스크리너 종목 상세 차트")
                    selected_screen_stock = st.selectbox("상세 차트 종목", result_df["종목명"].tolist(), key="screener_detail_select")
                    selected_row = result_df[result_df["종목명"] == selected_screen_stock].iloc[0]
                    detail_price = get_price_data(selected_row["종목코드"])
                    if not detail_price.empty:
                        chart_cols = ["종가", "MA5", "MA20", "MA60"]
                        st.line_chart(detail_price[[c for c in chart_cols if c in detail_price.columns]].tail(120))
                        st.write("매수상세:", selected_row.get("매수상세", ""))
                        st.write("매도상세:", selected_row.get("매도상세", ""))



# -----------------------------
# TAB 4: 백테스트
# -----------------------------
with tab4:
    st.subheader("🧪 백테스트")
    st.caption("선택한 종목에 대해 과거 가격 데이터로 매수/매도 조건을 검증합니다. 결과는 참고용이며 실제 수익을 보장하지 않습니다.")

    candidate_names = []
    if not portfolio_df.empty and "종목명" in portfolio_df.columns:
        candidate_names += portfolio_df["종목명"].dropna().astype(str).tolist()
    if not watchlist_df.empty and "종목명" in watchlist_df.columns:
        candidate_names += watchlist_df["종목명"].dropna().astype(str).tolist()
    candidate_names = sorted(list(dict.fromkeys(candidate_names)))

    bt_col1, bt_col2, bt_col3 = st.columns([1.2, 1, 1])
    with bt_col1:
        input_mode = st.radio("종목 선택 방식", ["보유/관심 종목에서 선택", "직접 입력"], horizontal=True)
        if input_mode == "보유/관심 종목에서 선택" and candidate_names:
            bt_name = st.selectbox("백테스트 종목", candidate_names)
        else:
            bt_name = st.text_input("종목명 직접 입력", value="삼성전자")
    with bt_col2:
        start_date = st.date_input("시작일", value=datetime.today().date() - timedelta(days=365 * 3))
    with bt_col3:
        end_date = st.date_input("종료일", value=datetime.today().date())

    opt1, opt2, opt3 = st.columns(3)
    with opt1:
        strategy = st.selectbox(
            "매수 전략",
            ["RSI 반등 전략", "MACD 골든크로스 전략", "5일/20일 골든크로스 전략", "AI 점수 전략"]
        )
        initial_cash = st.number_input("초기자금", min_value=100000, value=10000000, step=100000)
        fee_rate = st.number_input("매매비용/슬리피지 비율", min_value=0.0, max_value=0.01, value=0.0015, step=0.0005, format="%.4f")
    with opt2:
        buy_rsi = st.slider("RSI 매수 기준", 10, 50, 35)
        ai_score_threshold = st.slider("AI 점수 매수 기준", 40, 100, 70)
    with opt3:
        take_profit = st.slider("익절 기준 %", 3, 50, 20)
        stop_loss = st.slider("손절 기준 %", 3, 30, 10)
        use_macd_dead = st.checkbox("MACD 데드크로스 매도", value=True)
        use_ma_dead = st.checkbox("5일/20일선 이탈 매도", value=False)

    if st.button("🧪 백테스트 실행", type="primary"):
        ticker = find_ticker(bt_name)
        if not ticker:
            st.error("종목코드를 찾지 못했습니다. 종목명을 정확히 입력해 주세요.")
        elif start_date >= end_date:
            st.error("시작일은 종료일보다 빨라야 합니다.")
        else:
            with st.spinner("백테스트 계산 중..."):
                price_df = get_price_data_by_date(ticker, start_date, end_date)
                result = run_backtest(
                    price_df=price_df,
                    strategy=strategy,
                    initial_cash=initial_cash,
                    buy_rsi=buy_rsi,
                    ai_score_threshold=ai_score_threshold,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    use_macd_dead=use_macd_dead,
                    use_ma_dead=use_ma_dead,
                    fee_rate=fee_rate,
                )

            if result is None:
                st.warning("백테스트에 필요한 데이터가 부족합니다. 기간을 늘리거나 다른 종목을 선택해 보세요.")
            else:
                st.success(f"{bt_name} / {strategy} 백테스트 완료")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("최종 자산", money(result["final_equity"]), f"{result['total_return']:.2f}%")
                m2.metric("총 거래", f"{result['trade_count']}회")
                m3.metric("승률", f"{result['win_rate']:.1f}%")
                m4.metric("최대 낙폭", f"{result['max_drawdown']:.2f}%")

                m5, m6, m7 = st.columns(3)
                m5.metric("평균 수익률", f"{result['avg_return']:.2f}%")
                m6.metric("최대 수익", f"{result['max_profit']:.2f}%")
                m7.metric("최대 손실", f"{result['max_loss']:.2f}%")

                st.subheader("자산곡선")
                equity_chart = result["equity_df"].copy()
                equity_chart = equity_chart.set_index("일자")
                st.line_chart(equity_chart[["자산"]])

                st.subheader("종가와 이동평균")
                price_chart = price_df[[c for c in ["종가", "MA5", "MA20", "MA60"] if c in price_df.columns]].copy()
                st.line_chart(price_chart)

                st.subheader("거래내역")
                trades_df = result["trades_df"].copy()
                if trades_df.empty:
                    st.info("해당 기간에 거래가 발생하지 않았습니다.")
                else:
                    show_trades = trades_df.copy()
                    show_trades["가격"] = show_trades["가격"].apply(money)
                    show_trades["수익률%"] = show_trades["수익률%"].apply(lambda x: f"{float(x):.2f}%")
                    st.dataframe(show_trades, use_container_width=True, hide_index=True)

                    st.download_button(
                        "⬇️ 거래내역 CSV 다운로드",
                        data=trades_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                        file_name=f"backtest_{bt_name}_{strategy}.csv",
                        mime="text/csv"
                    )

                with st.expander("백테스트 조건 요약"):
                    st.write({
                        "종목": bt_name,
                        "종목코드": ticker,
                        "기간": f"{start_date} ~ {end_date}",
                        "매수전략": strategy,
                        "초기자금": money(initial_cash),
                        "RSI 기준": buy_rsi,
                        "AI 점수 기준": ai_score_threshold,
                        "익절": f"{take_profit}%",
                        "손절": f"-{stop_loss}%",
                        "MACD 데드크로스 매도": use_macd_dead,
                        "5일/20일선 이탈 매도": use_ma_dead,
                        "매매비용/슬리피지": fee_rate,
                    })



# -----------------------------
# 스마트 스크리너
# -----------------------------
with tab3:
    st.divider()
    with st.expander("🧠 스마트 스크리너", expanded=False):
        st.subheader("🧠 스마트 스크리너")
        st.caption("기업 품질 + 성장성 + 수급 + 기술 신호를 합산해서 종목을 발굴합니다.")

        col_a, col_b, col_c = st.columns(3)
        preset_name = col_a.selectbox(
            "투자 스타일",
            list(SMART_PRESETS.keys()),
            index=0,
            help="균형형은 품질 40 / 성장 30 / 수급 20 / 기술 10 기준입니다."
        )

        market_choice = col_b.multiselect(
            "시장",
            ["KOSPI", "KOSDAQ"],
            default=["KOSPI", "KOSDAQ"],
            key="smart_market_choice"
        )

        max_count = col_c.number_input(
            "최대 검색 종목 수",
            min_value=20,
            max_value=2500,
            value=200,
            step=50,
            help="처음에는 100~200개로 테스트하세요. 전체 검색은 시간이 오래 걸립니다.",
            key="smart_max_count"
        )

        col_d, col_e, col_f = st.columns(3)
        min_market_cap_uk = col_d.number_input(
            "최소 시가총액(억원)",
            min_value=0,
            value=3000,
            step=500,
            key="smart_min_market_cap"
        )
        min_total_score = col_e.slider(
            "최소 총점",
            min_value=0,
            max_value=100,
            value=60,
            step=5,
            key="smart_min_score"
        )
        include_etf = col_f.checkbox("ETF/ETN 포함", value=False, key="smart_include_etf")

        st.markdown("#### 점수 가중치")
        weight_df = pd.DataFrame([SMART_PRESETS[preset_name]]).rename(
            columns={"quality": "품질", "growth": "성장", "supply": "수급", "technical": "기술"}
        )
        st.dataframe(weight_df, use_container_width=True, hide_index=True)

        st.info("현재 V8.1은 시가총액은 자동 반영하고, PER/PBR/ROE는 자동화 전이라 ROE·부채비율은 중립값을 사용합니다. 다음 단계에서 재무 데이터 소스를 붙이면 됩니다.")

        if st.button("🧠 스마트 스크리너 실행", type="primary", key="run_smart_screener_btn"):
            if not market_choice:
                st.warning("시장을 하나 이상 선택하세요.")
            else:
                with st.spinner("스마트 스크리너 실행 중입니다. 종목 수가 많으면 시간이 걸립니다."):
                    result = run_smart_screener(
                        markets=market_choice,
                        preset_name=preset_name,
                        max_count=int(max_count),
                        min_market_cap=float(min_market_cap_uk) * 100000000,
                        min_total_score=float(min_total_score),
                        include_etf=include_etf,
                    )

                if result.empty:
                    st.warning("조건에 맞는 종목이 없습니다. 최소 총점이나 시가총액 기준을 낮춰보세요.")
                else:
                    st.session_state["smart_screener_result"] = result
                    st.success(f"{len(result)}개 종목을 찾았습니다.")

        result = st.session_state.get("smart_screener_result", pd.DataFrame())
        if result is not None and not result.empty:
            show_cols = [
                "종목명", "종목코드", "시장", "현재가", "시가총액", "총점", "등급",
                "품질", "성장", "수급", "기술", "외국인20일", "기관20일"
            ]
            show_result = result[show_cols].copy()
            show_result["현재가"] = show_result["현재가"].apply(money)
            show_result["시가총액"] = show_result["시가총액"].apply(money)
            show_result["외국인20일"] = show_result["외국인20일"].apply(number)
            show_result["기관20일"] = show_result["기관20일"].apply(number)

            st.dataframe(show_result, use_container_width=True, hide_index=True)

            csv = result.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                "📥 스마트 스크리너 결과 CSV 다운로드",
                data=csv,
                file_name="smart_screener_result.csv",
                mime="text/csv",
                key="smart_csv_download"
            )

            st.markdown("#### 상위 종목 상세")
            selected_name = st.selectbox("상세 확인 종목", result["종목명"].tolist(), key="smart_detail_select")
            selected_row = result[result["종목명"] == selected_name].iloc[0]

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("총점", selected_row["총점"])
            c2.metric("품질", selected_row["품질"])
            c3.metric("성장", selected_row["성장"])
            c4.metric("수급", selected_row["수급"])
            c5.metric("기술", selected_row["기술"])

            st.write("품질:", selected_row["품질상세"])
            st.write("성장:", selected_row["성장상세"])
            st.write("수급:", selected_row["수급상세"])
            st.write("기술:", selected_row["기술상세"])

            st.markdown("#### 관심그룹에 추가")
            group_name = st.text_input("추가할 관심그룹명", value="스마트 스크리너", key="smart_watch_group")
            memo = f"{preset_name} / 총점 {selected_row['총점']} / {selected_row['등급']}"
            if st.button("⭐ 선택 종목 관심그룹 추가", key="smart_add_watch"):
                watch_df = load_watchlist()
                new_row = pd.DataFrame([{
                    "그룹": group_name,
                    "종목명": selected_row["종목명"],
                    "종목코드": selected_row["종목코드"],
                    "메모": memo,
                }])
                watch_df = pd.concat([watch_df, new_row], ignore_index=True)
                watch_df = watch_df.drop_duplicates(subset=["그룹", "종목명", "종목코드"], keep="last")
                save_watchlist(watch_df)
                st.success(f"{selected_row['종목명']}을(를) {group_name} 그룹에 추가했습니다.")
