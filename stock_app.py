import streamlit as st
from pykrx import stock
import datetime
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt

# --- 페이지 설정 ---
st.set_page_config(page_title="아빠 힘내세요", layout="wide", initial_sidebar_state="collapsed")

# --- 데이터베이스 연결 (Streamlit 전용) ---
# 배포 후 Streamlit Cloud 설정에서 SQL 설정을 활성화하면 이 부분이 작동합니다.
# 로컬에서는 자동으로 임시 SQLite 파일에 저장됩니다.
conn = st.connection("local_db", type="sql")

def init_db():
    with conn.session as s:
        s.execute('CREATE TABLE IF NOT EXISTS portfolio (name TEXT, buy1 REAL, buy2 REAL, qty1 INTEGER, qty2 INTEGER)')
        s.execute('CREATE TABLE IF NOT EXISTS trades (name TEXT, profit REAL, date TEXT)')
        s.commit()

init_db()

# --- 세션 상태 초기화 ---
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# --- 주요 함수 ---
@st.cache_data
def get_ticker_map():
    tickers = stock.get_market_ticker_list()
    return {stock.get_market_ticker_name(t): t for t in tickers}

ticker_map = get_ticker_map()
stock_names = list(ticker_map.keys())

def calculate_rsi(df, period=14):
    delta = df['종가'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    return 100 - (100 / (1 + (avg_gain / avg_loss)))

def get_news(stock_name):
    try:
        url = f"https://search.naver.com/search.naver?where=news&query={stock_name}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, "html.parser")
        return [{"title": i['title'], "url": i['href']} for i in soup.select(".news_tit")[:3]]
    except: return []

# --- 앱 레이아웃 ---
st.title("📈 주식 관리 대시보드")

tab1, tab2, tab3 = st.tabs(["📊 분석 및 추가", "💼 보유종목", "📈 수익통계"])

# ------------------ 1. 분석 및 추가 ------------------
with tab1:
    with st.form("search_form"):
        name = st.selectbox("종목 선택", stock_names)
        buy_price = st.number_input("매수 예정가", value=0)
        submitted = st.form_submit_button("데이터 분석")

    if submitted:
        ticker = ticker_map.get(name)
        df = stock.get_market_ohlcv((datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y%m%d"), 
                                    datetime.datetime.now().strftime("%Y%m%d"), ticker)
        
        if not df.empty:
            current_price = df['종가'].iloc[-1]
            support = df['저가'].tail(20).min()
            rsi = calculate_rsi(df).iloc[-1]
            
            st.session_state.analysis_result = {
                "name": name, "curr": current_price, "supp": support, "rsi": rsi, "buy_p": buy_price if buy_price > 0 else current_price, "df": df
            }

    if st.session_state.analysis_result:
        res = st.session_state.analysis_result
        col1, col2 = st.columns([1, 1])
        with col1:
            st.metric(res['name'], f"{int(res['curr']):,}원", f"{res['rsi']:.1f} RSI")
            st.write(f"📍 지지선: {int(res['supp']):,}원")
            if st.button("➕ 포트폴리오에 추가"):
                with conn.session as s:
                    s.execute('INSERT INTO portfolio (name, buy1, buy2, qty1, qty2) VALUES (:name, :buy1, :buy2, :qty1, :qty2)',
                              {"name": res['name'], "buy1": res['buy_p'], "buy2": None, "qty1": 1, "qty2": 0})
                    s.commit()
                st.success("저장되었습니다!")
        
        with col2:
            st.write("📰 관련 뉴스")
            for n in get_news(res['name']):
                st.markdown(f"- [{n['title']}]({n['url']})")

# ------------------ 2. 보유 종목 (모바일 최적화) ------------------
with tab2:
    port_df = conn.query("SELECT * FROM portfolio")
    
    if port_df.empty:
        st.info("보유 중인 종목이 없습니다.")
    else:
        for i, row in port_df.iterrows():
            ticker = ticker_map.get(row['name'])
            # 현재가 가져오기
            curr_df = stock.get_market_ohlcv_by_date(datetime.datetime.now().strftime("%Y%m%d"), datetime.datetime.now().strftime("%Y%m%d"), ticker)
            curr = curr_df['종가'].iloc[-1] if not curr_df.empty else row['buy1']
            
            profit = ((curr - row['buy1']) / row['buy1']) * 100
            stop_loss = row['buy1'] * 0.90
            
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    if curr <= stop_loss:
                        st.error(f"🚨 {row['name']} 손절가 이탈!")
                    else:
                        st.subheader(f"{row['name']} ({profit:+.2f}%)")
                    st.write(f"현재: {int(curr):,} / 평단: {int(row['buy1']):,}")
                with c2:
                    if st.button("매도", key=f"sell_{i}"):
                        with conn.session as s:
                            s.execute('INSERT INTO trades (name, profit, date) VALUES (:n, :p, :d)',
                                      {"n": row['name'], "p": round(profit, 2), "d": str(datetime.date.today())})
                            s.execute('DELETE FROM portfolio WHERE rowid = (SELECT rowid FROM portfolio LIMIT 1 OFFSET :idx)', {"idx": i})
                            s.commit()
                        st.rerun()

# ------------------ 3. 수익 통계 ------------------
with tab3:
    trades_df = conn.query("SELECT * FROM trades")
    if not trades_df.empty:
        st.dataframe(trades_df, use_container_width=True)
        st.metric("평균 수익률", f"{trades_df['profit'].mean():.2f}%")
    else:
        st.write("매매 내역이 없습니다.")