import streamlit as st
from pykrx import stock
import datetime
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from sqlalchemy import text

# --- 1. 페이지 설정 ---
st.set_page_config(page_title="아빠 힘내세요", layout="wide")

# --- 2. 데이터베이스 연결 및 초기화 ---
conn = st.connection("local_db", type="sql")

def init_db():
    with conn.session as s:
        # 사용자(user)별 구분을 위해 테이블 구조에 user 컬럼을 포함합니다.
        s.execute(text('CREATE TABLE IF NOT EXISTS portfolio (user TEXT, name TEXT, buy1 REAL, qty1 INTEGER)'))
        s.execute(text('CREATE TABLE IF NOT EXISTS trades (user TEXT, name TEXT, profit REAL, date TEXT)'))
        s.commit()

init_db()

# --- 3. 사용자 설정 (사이드바) ---
with st.sidebar:
    st.header("👤 개인 설정")
    user_id = st.text_input("사용자 이름을 입력하세요", value="나").strip()
    st.info(f"'{user_id}' 님의 장부에 접속 중입니다.")

# --- 4. 주요 함수 (에러 방지 로직 포함) ---

@st.cache_data
def get_ticker_map():
    """휴장일이나 데이터 지연 시에도 종목 리스트를 안전하게 가져옵니다."""
    try:
        tickers = stock.get_market_ticker_list(market="KOSPI")
        if not tickers:
            tickers = stock.get_market_ticker_list()
        return {stock.get_market_ticker_name(t): t for t in tickers}
    except Exception:
        # 에러 발생 시 확실히 데이터가 있는 3일 전 날짜를 참고
        target_date = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y%m%d")
        tickers = stock.get_market_ticker_list(date=target_date)
        return {stock.get_market_ticker_name(t): t for t in tickers}

def calculate_rsi(df, period=14):
    """주식 보조지표 RSI 계산"""
    delta = df['종가'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ⚠️ 에러 방지를 위해 변수를 미리 정의합니다.
ticker_map = get_ticker_map()
stock_names = list(ticker_map.keys())

# --- 5. 앱 레이아웃 및 기능 ---
st.title(f"📈 {user_id}님의 주식 대시보드")

tab1, tab2, tab3 = st.tabs(["📊 분석 및 추가", "💼 보유종목", "📈 수익통계"])

# [탭 1: 분석 및 추가]
with tab1:
    with st.form("search_form"):
        name = st.selectbox("종목 선택", stock_names)
        buy_price = st.number_input("매수 예정가 (0이면 현재가 기준)", value=0)
        submitted = st.form_submit_button("데이터 분석")

    if submitted:
        ticker = ticker_map.get(name)
        today = datetime.datetime.now().strftime("%Y%m%d")
        
        # 최신 가격 가져오기 시도
        df = stock.get_market_ohlcv(today, today, ticker)
        if df.empty or df['종가'].iloc[-1] == 0:
            start_7d = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y%m%d")
            df = stock.get_market_ohlcv(start_7d, today, ticker)
        
        if not df.empty:
            current_price = df['종가'].iloc[-1]
            # RSI 계산용 과거 데이터
            hist_start = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y%m%d")
            df_hist = stock.get_market_ohlcv(hist_start, today, ticker)
            rsi = calculate_rsi(df_hist).iloc[-1]
            
            st.metric(name, f"{int(current_price):,}원", f"{rsi:.1f} RSI")
            
            if st.button("➕ 내 포트폴리오에 추가"):
                with conn.session as s:
                    s.execute(text('INSERT INTO portfolio (user, name, buy1, qty1) VALUES (:u, :n, :b, :q)'),
                              {"u": user_id, "n": name, "b": buy_price if buy_price > 0 else current_price, "q": 1})
                    s.commit()
                st.success(f"'{user_id}'님의 장부에 저장되었습니다!")

# [탭 2: 보유 종목]
with tab2:
    # 현재 로그인된 user_id의 데이터만 불러옵니다.
    port_df = conn.query(f"SELECT *, rowid FROM portfolio WHERE user = '{user_id}'")
    
    if port_df is None or port_df.empty:
        st.info(f"'{user_id}'님의 이름으로 저장된 종목이 없습니다.")
    else:
        for i, row in port_df.iterrows():
            with st.container(border=True):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.subheader(row['name'])
                    st.write(f"평단가: {int(row['buy1']):,}원")
                with col_b:
                    if st.button("매도", key=f"sell_{row['rowid']}"):
                        with conn.session as s:
                            s.execute(text('INSERT INTO trades (user, name, profit, date) VALUES (:u, :n, :p, :d)'),
                                      {"u": user_id, "n": row['name'], "p": 0.0, "d": str(datetime.date.today())})
                            s.execute(text('DELETE FROM portfolio WHERE rowid = :rid'), {"rid": row['rowid']})
                            s.commit()
                        st.rerun()

# [탭 3: 수익 통계]
with tab3:
    trades_df = conn.query(f"SELECT * FROM trades WHERE user = '{user_id}'")
    if trades_df is not None and not trades_df.empty:
        st.dataframe(trades_df, use_container_width=True)
    else:
        st.write("매매 내역이 없습니다.")
