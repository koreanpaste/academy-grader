"""페이지 2: 데이터 업로드 → 자동 채점 → 엑셀 추출 / 채팅."""
import hashlib
import hmac
from datetime import datetime

import streamlit as st

from core.agent import LEAK_HOLDBACK, REFUSAL_TEXT, GradingAgent, contains_internal_leak, is_injection_attempt
from core.config import academy_name, get_setting
from core.excel_export import build_excel
from core.grading import grade
from core.parsers import detect_file_role, parse_answer_key, parse_omr, parse_question_paper

ss = st.session_state
ss.setdefault("result", None)
ss.setdefault("excel", None)
ss.setdefault("messages", [])
ss.setdefault("analyzed_fp", None)

# ---------------------------------------------------------------- (선택) 접속 비밀번호
# APP_PASSWORD를 설정했을 때만 동작. 설정하지 않으면 누구나 사용 가능(과제 평가용 기본값).
_app_pw = get_setting("APP_PASSWORD")
if _app_pw and not ss.get("authed"):
    st.markdown(f"## {academy_name()} 평가 도우미")
    pw = st.text_input("접속 비밀번호", type="password")
    if pw:
        if hmac.compare_digest(pw.encode(), _app_pw.encode()):
            ss.authed = True
            st.rerun()
        st.error("비밀번호가 맞지 않아요.")
    st.stop()


# 칸별 로더: 파일을 올리는 즉시 내용을 읽어서 검증
# st.cache_data(서버 전체가 공유하는 캐시)는 쓰지 않는다. 학생 성적이 다른 세션·만료 없는 캐시에 남지 않도록
# 읽은 결과는 '이 사용자 세션'의 session_state에만, 칸마다 현재 파일 하나만 보관한다.
def _load_paper(data: bytes, name: str):
    return parse_question_paper(data)


def _load_omr(data: bytes, name: str):
    return parse_omr(data, name)


def _load_answer(data: bytes, name: str):
    return parse_answer_key(data)


def _session_load(role: str, label: str, data: bytes, name: str, loader):
    """같은 칸에 같은 파일이면 다시 읽지 않음(채팅할 때마다 PDF를 다시 읽지 않도록). 실패도 기억."""
    digest = hashlib.sha256(data).hexdigest()
    cache = ss.setdefault("parse_cache", {})
    hit = cache.get(role)
    if hit is None or hit[0] != digest:
        with st.spinner(f"{label} 읽는 중..."):
            try:
                hit = (digest, loader(data, name), None)
            except Exception as e:
                hit = (digest, None, e)
        cache[role] = hit
    if hit[2] is not None:
        raise hit[2]
    return hit[1]


# (종류, 칸 이름, 허용 확장자, 로더, 읽기 성공 시 보여줄 요약)
SLOTS = [
    ("paper", "① 문제지 (PDF)", ["pdf"], _load_paper,
     lambda p: f"{len(p.questions)}문항 인식"),
    ("omr", "② OMR 인식 결과 (엑셀/CSV)", ["xlsx", "xls", "csv"], _load_omr,
     lambda o: f"학생 {len(o)}명 · {sum(isinstance(c, int) for c in o.columns)}문항"),
    ("answer", "③ 정답지 (PDF)", ["pdf"], _load_answer,
     lambda k: f"{len(k.table)}문항 · 만점 {k.total_points}점"),
]


def _wrong_slot_hint(role: str, data: bytes, name: str) -> str:
    """칸을 잘못 골라 올린 경우 안내."""
    guess = detect_file_role(data, name)
    if role == "paper" and guess == "answer":
        return "정답지 파일 같아요. ③ 정답지 칸에 올려주세요."
    if role == "answer" and guess == "paper":
        return "정답표 형식이 아니에요. 문제지라면 ① 문제지 칸에 올려주세요."
    return ""


def _fingerprint(files: dict[str, tuple[str, bytes]]) -> tuple:
    """업로드 파일 지문: 파일이 바뀌거나 빠지면 값이 달라진다."""
    return tuple(sorted((role, name, hashlib.sha256(data).hexdigest()) for role, (name, data) in files.items()))


def _reset_results():
    ss.result, ss.excel, ss.analyzed_fp = None, None, None
    ss.messages = []


def _welcome(result) -> str:
    s = result.stats
    top3 = ", ".join(f"{t['문항']}번" for t in s["가장 많이 틀린 문항 TOP3"])
    return (
        f"채점이 완료됐어요! **{s['응시 인원']}명** 응시 · 평균 **{s['평균']}점** · 중앙값 **{s['중앙값']}점** "
        f"· 가장 많이 틀린 문항 {top3}\n\n"
        "궁금한 걸 물어보세요. 예) \"가장 성적이 저조한 학생은 누구야?\", \"87번 학생 몇 점이야?\", "
        "\"많이 틀린 문제랑 비슷한 문제 만들어 줘\""
    )


def _prepend(first, rest):
    if first:
        yield first
    yield from rest


# ---------------------------------------------------------------- 사이드바
with st.sidebar:
    st.markdown("### 데이터 업로드")

    files: dict[str, tuple[str, bytes]] = {}  # 종류 → (파일명, 내용)  : 파일 지문 계산용
    parsed: dict[str, object] = {}            # 종류 → 읽어낸 결과       : 채점에 사용
    for role, label, types, loader, summary in SLOTS:
        up = st.file_uploader(label, type=types, key=f"up_{role}")
        if up is None:
            continue
        data = up.getvalue()
        files[role] = (up.name, data)
        try:
            parsed[role] = _session_load(role, label, data, up.name, loader)
            st.caption(f"✅ {summary(parsed[role])}")
        except Exception as e:
            hint = _wrong_slot_hint(role, data, up.name)
            st.error(f"{hint}\n\n({e})" if hint else f"파일을 읽지 못했어요: {e}")

    # 칸에서 파일을 지우면 읽어둔 내용도 세션에서 바로 삭제
    for role in list(ss.get("parse_cache", {})):
        if role not in files:
            del ss.parse_cache[role]

    # 1) 업로드 파일이 바뀌거나 빠지면 이전 채점 결과·엑셀·대화를 모두 지움
    current_fp = _fingerprint(files)
    if ss.result is not None and current_fp != ss.analyzed_fp:
        _reset_results()
        st.info("업로드 파일이 바뀌어서 이전 채점 결과를 지웠어요. **분석 시작**을 다시 눌러주세요.")

    # 2) 문제지 · OMR · 정답지 3개를 모두 정상적으로 읽었을 때만 분석 가능
    ready = all(role in parsed for role, *_ in SLOTS)
    start = st.button("분석 시작", type="primary", width="stretch", disabled=not ready)

    if start:
        with st.spinner("채점 중이에요..."):
            try:
                ss.result = grade(parsed["answer"], parsed["omr"], parsed["paper"])
                ss.excel = build_excel(ss.result)
                ss.analyzed_fp = current_fp
                ss.messages = [{"role": "assistant", "content": _welcome(ss.result)}]
            except Exception as e:
                _reset_results()
                st.error(f"채점을 진행할 수 없어요: {e}")

    st.download_button(
        "엑셀 추출",
        data=ss.excel or b"",
        file_name=f"채점결과_{datetime.now():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=ss.result is None,
        width="stretch",
        icon=":material/download:",
        on_click="ignore",
    )
    if not ready:
        missing = [label for role, label, *_ in SLOTS if role not in parsed]
        st.caption(f"남은 파일: {', '.join(missing)}")
    if not get_setting("OPENAI_API_KEY"):
        st.warning("OpenAI API 키를 찾지 못했어요. `.env` 또는 `.streamlit/secrets.toml`에 OPENAI_API_KEY를 넣어주세요.", icon="🔑")
    st.caption(
        "🔒 업로드한 파일·채점 결과·대화는 파일이나 DB로 저장하지 않고, 지금 접속한 세션의 메모리에만 있어요. "
        "파일을 지우면 바로, 창을 닫으면 잠시 후 사라져요. "
        "질문에 답하는 데 필요한 최소한의 채점 정보만 AI(OpenAI)로 전송됩니다."
    )


# ---------------------------------------------------------------- 메인 (채팅)
st.markdown(f"## {academy_name()} 평가 도우미")
result = ss.result

if result is None:
    st.info("왼쪽 사이드바의 **① 문제지 · ② OMR 결과 · ③ 정답지** 칸에 각각 파일을 올리고 **분석 시작**을 누르면 채팅이 활성화돼요.")
else:
    for w in result.warnings:
        st.warning(w)
    with st.expander("채점 결과 요약 보기", expanded=False):
        s = result.stats
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("응시 인원", f"{s['응시 인원']}명")
        m2.metric("평균", f"{s['평균']}점")
        m3.metric("중앙값", f"{s['중앙값']}점")
        m4.metric("표준편차", f"{s['표준편차']}")
        st.caption(
            "가장 많이 틀린 문항: "
            + ", ".join(f"{t['문항']}번({t['오답률']}%)" for t in s["가장 많이 틀린 문항 TOP3"])
            + (f" · {s['TOP3 동률 안내']}" if s["TOP3 동률 안내"] else "")
        )
        st.dataframe(
            result.students[["학생", "점수", "맞은 문항 수", "순위"]],
            hide_index=True,
            width="stretch",
            height=260,
        )

for msg in ss.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input(
    "채점 결과에 대해 물어보세요" if result else "분석을 시작하면 채팅을 사용할 수 있어요",
    disabled=result is None,
)

if prompt and result is not None:
    user_msg = {"role": "user", "content": prompt}
    ss.messages.append(user_msg)
    with st.chat_message("user"):
        st.markdown(prompt)

    blocked = False
    with st.chat_message("assistant"):
        box = st.empty()
        if is_injection_attempt(prompt):
            reply, blocked = REFUSAL_TEXT, True
            box.markdown(reply)
        else:
            api_key = get_setting("OPENAI_API_KEY")
            if not api_key:
                reply = "⚠️ OpenAI API 키가 설정되지 않았어요. 관리자에게 OPENAI_API_KEY 설정을 요청해 주세요."
                box.markdown(reply)
            else:
                agent = GradingAgent(result, api_key, get_setting("OPENAI_MODEL"), academy_name())
                stream = agent.stream_reply(ss.messages)
                with st.spinner("답변을 준비하고 있어요..."):
                    first = next(stream, "")  # tool 조회가 끝나고 첫 글자가 나올 때까지 대기

                # 끝부분 LEAK_HOLDBACK 글자는 붙잡아 두고, 검사를 통과한 앞부분만 화면에 보여줌
                # → 내부 이름은 끝까지 다 들어와야 화면에 나갈 수 있으므로, 화면에 나가기 전에 반드시 걸러짐
                text = ""
                for chunk in _prepend(first, stream):
                    text += chunk
                    if contains_internal_leak(text):
                        blocked = True
                        break
                    visible = text[:-LEAK_HOLDBACK]
                    if visible:
                        box.markdown(visible + "▌")
                reply = REFUSAL_TEXT if blocked else (text or "답변을 만들지 못했어요. 다시 질문해 주세요.")
                box.markdown(reply)

    # 보안 필터에 걸린 질문/답변은 표시만 하고, 다음 질문 때 모델에게는 보내지 않음
    if blocked:
        user_msg["blocked"] = True
    ss.messages.append({"role": "assistant", "content": reply, "blocked": blocked})
