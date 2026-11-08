"""페이지 1: 웹 서비스를 소개하는 랜딩 페이지."""
import base64

import streamlit as st

from core.config import academy_name, logo_path

NAME = academy_name()

st.markdown(
    """
    <style>
    .hero { text-align: center; padding: 3.5rem 1rem 1.5rem; }
    .logo-box { width: 160px; height: 160px; margin: 0 auto 1.6rem; border: 2px solid #0B5CAD;
                border-radius: 20px; display: flex; align-items: center; justify-content: center;
                background: #fff; overflow: hidden; }
    .logo-box img { max-width: 85%; max-height: 85%; object-fit: contain; }
    .logo-box.has-img { width: 170px; height: 170px; border: none; border-radius: 0; background: transparent; }
    .logo-box.has-img img { max-width: 100%; max-height: 100%; mix-blend-mode: multiply; }
    .logo-fallback { color: #0B5CAD; font-weight: 800; font-size: 1.15rem; line-height: 1.4; }
    .hero h1 { font-size: 2.4rem; font-weight: 800; color: #12263F; margin: 0; word-break: keep-all; }
    .hero p.sub { color: #5A6B80; font-size: 1.05rem; margin-top: .6rem; word-break: keep-all; }
    @media (max-width: 640px) { .hero h1 { font-size: 1.9rem; } .hero { padding-top: 2rem; } }
    .card { border: 1px solid #DCE4EE; border-radius: 14px; padding: 1.3rem 1.2rem; height: 100%;
            background: #FFFFFF; }
    .card .ic { font-size: 1.6rem; }
    .card h3 { font-size: 1.05rem; margin: .5rem 0 .3rem; color: #12263F; }
    .card p { color: #5A6B80; font-size: .92rem; margin: 0; line-height: 1.55; }
    .steps { color: #3B4B60; font-size: .95rem; line-height: 1.9; }
    </style>
    """,
    unsafe_allow_html=True,
)

logo = logo_path()
if logo:
    mime = "image/svg+xml" if logo.suffix == ".svg" else f"image/{logo.suffix.lstrip('.').replace('jpg', 'jpeg')}"
    encoded = base64.b64encode(logo.read_bytes()).decode()
    logo_html = f'<img src="data:{mime};base64,{encoded}" alt="logo">'
else:
    logo_html = '<div class="logo-fallback">LOGO</div>'

st.markdown(
    f"""
    <div class="hero">
      <div class="logo-box{' has-img' if logo else ''}">{logo_html}</div>
      <h1>{NAME} 평가 도우미</h1>
      <p class="sub">문제지 · OMR 결과 · 정답지만 올리면 자동 채점부터 성적 분석, 유사 문제 생성까지</p>
    </div>
    """,
    unsafe_allow_html=True,
)

_, mid, _ = st.columns([2, 1, 2])
with mid:
    if st.button("채점 시작하기 →", type="primary", width="stretch"):
        st.switch_page("views/analysis.py")

st.write("")
c1, c2, c3 = st.columns(3)
cards = [
    ("✅", "자동 채점", "정답지 PDF에서 정답과 배점을 읽어 학생 전원의 OMR 답안을 바로 채점합니다."),
    ("📊", "엑셀 리포트", "평균·중앙값·표준편차, 많이 틀린 문항과 학생별 문항 O/X를 엑셀로 내려받습니다."),
    ("💬", "AI 분석 챗봇", "\"87번 학생 몇 점이야?\" 처럼 물어보면 답하고, 많이 틀린 문제의 유사 문제도 만들어 줍니다."),
]
for col, (ic, title, desc) in zip((c1, c2, c3), cards):
    with col:
        st.markdown(f'<div class="card"><div class="ic">{ic}</div><h3>{title}</h3><p>{desc}</p></div>', unsafe_allow_html=True)

st.write("")
st.markdown(
    """
    <div class="steps">
    <b>사용 방법</b><br>
    1. 왼쪽 메뉴에서 <b>채점 · 분석</b> 페이지로 이동<br>
    2. 사이드바의 <b>① 문제지 PDF · ② OMR 결과(엑셀/CSV) · ③ 정답지 PDF</b> 칸에 각각 파일 올리기<br>
    3. <b>분석 시작</b>을 누르면 자동 채점 → 엑셀 추출과 채팅이 활성화됩니다
    </div>
    """,
    unsafe_allow_html=True,
)
