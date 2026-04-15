import sys
import types
import datetime
import pandas as pd
from sqlalchemy import text
import streamlit as st
import time
from pykrx import stock
import plotly.graph_objects as go
from plotly.subplots import make_subplots # RSI 차트 분리를 위해 추가

# --- [1. 시스템 환경 설정 및 함수 정의] ---
try:
    import pkg_resources
except ImportError:
    m = types.ModuleType('pkg_resources')
    sys.modules['pkg_resources'] = m
    m.resource_filename = lambda x, y: ""

# RSI 계산을 위한 함수
def calculate_rsi(df, period=14):
    delta = df['종가'].diff()
    gain = delta.where(delta > 0, 0).ewm(com=period - 1, min_periods=period).mean()
    loss = -delta.where(delta < 0, 0).ewm(com=period - 1, min_periods=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- [2. 앱 기본 설정] ---
st.set_page_config(page_title="아빠의 주식장부", page_icon="📈", layout="wide")
conn = st.connection("local_db", type="sql", url="sqlite:///stock_app.db")

with conn.session as s:
    s.execute(text('CREATE TABLE IF NOT EXISTS portfolio (user TEXT, name TEXT, buy1 REAL, qty1 INTEGER)'))
    s.commit()

# 스타일 설정
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; font-weight: bold; color: #1f77b4; }
    .stMetric { background-color: #f8f9fa; padding: 10px; border-radius: 10px; border: 1px solid #ddd; }
    </style>
    """, unsafe_allow_html=True)

# --- [3. 종목 리스트 확보] ---
@st.cache_data(ttl=3600)
def get_full_master():
    for i in range(15):
        target_date = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime("%Y%m%d")
        try:
            tickers = stock.get_market_ticker_list(target_date, market="ALL")
            if tickers:
                return {stock.get_market_ticker_name(t).replace(" ", ""): t for t in tickers}
        except: continue
    return {}

master_list = get_full_master()

# --- [4. 메인 화면] ---
# 사이드바에서 이름을 입력받고 바로 아래에 알림 추가
user_id = st.sidebar.text_input("사용자", value="나").strip()

if user_id:
    # 사용자 이름이 입력되어 있으면 초록색 알림창을 띄워줍니다.
    st.sidebar.success(f"✅ '{user_id}' 님 장부 접속 중")
else:
    # 이름이 비어있으면 경고 메시지를 보여줍니다.
    st.sidebar.warning("사용자 이름을 입력해주세요.")

st.title("📈 아빠의 주식장부")

tab1, tab2 = st.tabs(["📊 종목 분석 & 뉴스", "💼 나의 장부"])

with tab1:
    c1, c2, c3 = st.columns([2, 1, 1])
    query = c1.text_input("종목명 또는 코드", placeholder="예: 삼성전자, 네오셈...").strip().replace(" ", "")
    b_price = c2.number_input("매수가(원)", value=0, step=1)
    b_qty = c3.number_input("수량(주)", value=1, min_value=1)

    target_code, target_name = None, None

    if query:
        if query.isdigit() and len(query) == 6:
            target_code = query
            try: target_name = stock.get_market_ticker_name(query)
            except: target_name = f"종목({query})"
        else:
            for name, code in master_list.items():
                if query in name:
                    target_code, target_name = code, name
                    break

    if target_code:
        with st.spinner(f'{target_name} 정보를 불러오는 중...'):
            end_d = datetime.datetime.now().strftime("%Y%m%d")
            start_d = (datetime.datetime.now() - datetime.timedelta(days=120)).strftime("%Y%m%d")
            df = stock.get_market_ohlcv(start_d, end_d, target_code)
            
            if not df.empty:
                curr = int(df['종가'].iloc[-1])
                rsi_series = calculate_rsi(df) # RSI 계산
                rsi_val = rsi_series.iloc[-1]
                base = b_price if b_price > 0 else curr
                
                st.divider()
                st.subheader(f"🔍 {target_name} ({target_code})")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("현재가", f"{curr:,}원")
                m2.metric("RSI (14일)", f"{rsi_val:.1f}", delta="과매수" if rsi_val > 70 else "과매도" if rsi_val < 30 else "보통")
                m3.metric("2차(-6%)", f"{int(base*0.94):,}원")
                m4.metric("손절(-10%)", f"{int(base*0.90):,}원")

                # --- [차트 보강: 캔들 + RSI + 지지선] ---
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                    vertical_spacing=0.1, subplot_titles=('주가 및 지지선', 'RSI 지표'),
                                    row_heights=[0.7, 0.3])

                # 1. 캔들차트 추가
                fig.add_trace(go.Candlestick(x=df.index, open=df['시가'], high=df['고가'], low=df['저가'], close=df['종가'], name='주가'), row=1, col=1)
                
                # 지지선(매매 기준선) 추가
                fig.add_hline(y=base, line_dash="dash", line_color="green", annotation_text="1차 매수", row=1, col=1)
                fig.add_hline(y=base*0.94, line_dash="dash", line_color="orange", annotation_text="2차 매수", row=1, col=1)
                fig.add_hline(y=base*0.90, line_dash="dash", line_color="red", annotation_text="손절선", row=1, col=1)

                # 2. RSI 차트 추가
                fig.add_trace(go.Scatter(x=rsi_series.index, y=rsi_series, name='RSI', line=dict(color='purple')), row=2, col=1)
                fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1) # 과매수 기준선
                fig.add_hline(y=30, line_dash="dot", line_color="blue", row=2, col=1) # 과매도 기준선

                fig.update_layout(height=600, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("### 📰 최신 뉴스")
                try:
                    news_df = stock.get_market_news(target_code).head(3)
                    if not news_df.empty:
                        for _, row in news_df.iterrows():
                            st.info(f"**[{row['날짜']}]** {row['제목']}")
                except: st.write("뉴스 정보를 불러올 수 없습니다.")

                if st.button(f"🚀 {target_name} 장부 등록"):
                    save_name = f"{target_name}({target_code})"
                    with conn.session as s:
                        s.execute(text('INSERT INTO portfolio (user, name, buy1, qty1) VALUES (:u, :n, :b, :q)'),
                                  {"u": user_id, "n": save_name, "b": base, "q": b_qty})
                        s.commit()
                    
                    st.success(f"✅ '{target_name}' 종목이 장부에 저장되었습니다!")
                    st.balloons()
                    time.sleep(1)
                    st.rerun()
    elif query:
        st.error("종목을 찾을 수 없습니다.")

with tab2:
    p_df = conn.query(f"SELECT *, rowid FROM portfolio WHERE user = '{user_id}'", ttl=0)
    if p_df is not None and not p_df.empty:
        total_profit = 0
        for _, row in p_df.iterrows():
            with st.container(border=True):
                col_i, col_d = st.columns([4, 1])
                full_name = row['name']
                code = full_name.split('(')[-1].replace(')', '')
                
                c_df = stock.get_market_ohlcv((datetime.datetime.now()-datetime.timedelta(days=7)).strftime("%Y%m%d"), 
                                              datetime.datetime.now().strftime("%Y%m%d"), code)
                now_p = int(c_df['종가'].iloc[-1]) if not c_df.empty else 0
                b1, q = int(row['buy1']), int(row['qty1'])
                profit = (now_p - b1) * q
                total_profit += profit

                col_i.write(f"### {full_name}")
                m1, m2, m3 = col_i.columns(3)
                m1.metric("현재가", f"{now_p:,}원")
                m2.metric("매수가", f"{b1:,}원")
                m3.metric("수익금", f"{profit:,}원", delta=f"{((now_p/b1)-1)*100:.2f}%" if b1>0 else "0%")
                
                col_i.write(f"**수량:** {q}주 | **2차 매수:** {int(b1*0.94):,}원 | **손절선:** {int(b1*0.90):,}원")
                
                if col_d.button("삭제", key=f"del_{row['rowid']}"):
                    with conn.session as s:
                        s.execute(text('DELETE FROM portfolio WHERE rowid = :rid'), {"rid": row['rowid']})
                        s.commit()
                    st.rerun()
        st.divider()
        st.subheader(f"💰 총 수익 합계: {int(total_profit):,}원")
    else:
        st.info("장부가 비어 있습니다.")