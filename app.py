"""앱 진입점: 페이지 2개(랜딩 / 채점·분석)를 연결한다.

실행: streamlit run app.py
"""
import streamlit as st

from core.config import academy_name

st.set_page_config(page_title=f"{academy_name()} 평가 도우미", page_icon="📝", layout="wide")

home = st.Page("views/home.py", title="홈", icon=":material/home:", default=True)
analysis = st.Page("views/analysis.py", title="채점 · 분석", icon=":material/analytics:", url_path="analysis")

st.navigation([home, analysis]).run()
