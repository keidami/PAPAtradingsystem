import streamlit as st
from pykrx import stock
import datetime
import pandas as pd
from sqlalchemy import text

# --- 1. 페이지 설정 ---
st.set_page_config(page_title="아빠 힘내세요", page_icon="📈", layout="wide")

# --- 2. 데이터베이스 연결 및 초기화 ---
conn = st.connection("local_db", type="sql")

def init_db():
    with conn.session as s:
        s.execute(text('CREATE TABLE IF NOT EXISTS portfolio (user TEXT, name TEXT, buy1 REAL, qty1 INTEGER)'))
        s.execute(text('CREATE TABLE IF NOT EXISTS trades (user TEXT, name TEXT, profit REAL, date TEXT)'))
        s.commit()

init_db()

# --- 3. 사용자 설정 (사이드바) ---
with st.sidebar:
    st.header("👤 개인 설정")
    user_id = st.text_input("사용자 이름을 입력하세요", value="나").strip()
    st.info(f"'{user_id}' 님의 장부에 접속 중입니다.")

# --- 4. 주요 함수 ---

@st.cache_data(ttl=3600) # 1시간마다 캐시 갱신
def get_ticker_map():
    try:
        # 코스피/코스닥 종목 리스트 통합
        tickers = stock.get_market_ticker_list(market="ALL")
        return {stock.get_market_ticker_name(t): t for t in tickers}
    except Exception:
        # 에러 발생 시 안전하게 3일 전 날짜 데이터 참조
        target_date = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y%m%d")
        tickers = stock.get_market_ticker_list(date=target_date, market="ALL")
        return {stock.get_market_ticker_name(t): t for t in tickers}

def calculate_rsi(df, period=14):
    delta = df['종가'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# 앱 시작 시 리스트 로딩 (로딩 중 메시지 표시)
with st.spinner('종목 리스트를 불러오는 중입니다... 잠시만 기다려주세요.'):
    ticker_map = get_ticker_map()

# --- 5. 앱 레이아웃 ---
st.title(f"👨‍💻 {user_id}님의 '아빠 힘내세요' 주식 앱")

tab1, tab2, tab3 = st.tabs(["📊 분석 및 추가", "💼 보유종목", "📈 수익통계"])

# [탭 1: 분석 및 추가]
with tab1:
    with st.form("search_form"):
        search_name = st.text_input("종목명을 입력하세요", placeholder="예: 삼성전자, 카카오")
        buy_price = st.number_input("매수 예정가 (0이면 현재가 기준)", value=0)
        submitted = st.form_submit_button("데이터 분석 시작")

    if submitted:
        search_name = search_name.strip()
        
        if not ticker_map:
            with st.spinner('데이터를 다시 불러오고 있습니다...'):
                ticker_map = get_ticker_map()

        if search_name in ticker_map:
            ticker = ticker_map.get(search_name)
            
            # 분석 중 로딩 표시
            with st.spinner(f'{search_name} 데이터를 분석 중입니다...'):
                today = datetime.datetime.now().strftime("%Y%m%d")
                df = stock.get_market_ohlcv(today, today, ticker)
                
                if df.empty or df['종가'].iloc[-1] == 0:
                    start_7d = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y%m%d")
                    df = stock.get_market_ohlcv(start_7d, today, ticker)
                
                if not df.empty:
                    current_price = df['종가'].iloc[-1]
                    hist_start = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y%m%d")
                    df_hist = stock.get_market_ohlcv(hist_start, today, ticker)
                    rsi = calculate_rsi(df_hist).iloc[-1]
                    
                    st.session_state.analysis_result = {
                        "name": search_name, 
                        "curr": current_price, 
                        "rsi": rsi, 
                        "buy_p": buy_price if buy_price > 0 else current_price
                    }
                    
                    st.divider()
                    col1, col2 = st.columns(2)
                    col1.metric("현재가", f"{int(current_price):,}원")
                    col2.metric("RSI (상태)", f"{rsi:.1f}", delta="과매수" if rsi > 70 else "과매도" if rsi < 30 else "보통")
                    
                    if st.button("➕ 내 포트폴리오에 추가"):
                        with conn.session as s:
                            s.execute(text('INSERT INTO portfolio (user, name, buy1, qty1) VALUES (:u, :n, :b, :q)'),
                                      {"u": user_id, "n": search_name, "b": st.session_state.analysis_result['buy_p'], "q": 1})
                            s.commit()
                        st.success(f"'{user_id}'님의 장부에 저장되었습니다!")
                else:
                    st.error("주가 데이터를 가져오지 못했습니다. 종목명을 다시 확인해주세요.")
        else:
            st.error(f"'{search_name}' 종목을 찾을 수 없습니다. 정확한 명칭인지 확인해주세요.")

# [탭 2, 3은 기존과 동일하되 디자인 소폭 개선]
with tab2:
    port_df = conn.query(f"SELECT *, rowid FROM portfolio WHERE user = '{user_id}'", ttl=0)
    if port_df is not None and not port_df.empty:
        for i, row in port_df.iterrows():
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                c1.write(f"**{row['name']}** | 매수가: {int(row['buy1']):,}원")
                if c2.button("매도", key=f"s_{row['rowid']}"):
                    with conn.session as s:
                        s.execute(text('DELETE FROM portfolio WHERE rowid = :rid'), {"rid": row['rowid']})
                        s.commit()
                    st.rerun()
    else:
        st.info("등록된 종목이 없습니다.")

with tab3:
    st.write("준비 중인 기능입니다.")