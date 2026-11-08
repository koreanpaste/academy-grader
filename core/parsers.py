"""업로드된 파일(정답지 PDF, 문제지 PDF, OMR 엑셀/CSV)을 읽어서 다루기 쉬운 형태로 바꿔주는 모듈.

- 정답과 배점은 코드에 적지 않고, 매번 업로드된 정답 PDF에서 읽어온다. (요구사항 2)
- 문제지 PDF는 2단 편집이라 페이지를 좌/우로 잘라서 읽은 뒤 문항 번호로 나눈다.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd
import pdfplumber

CIRCLED = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
CIRCLED_BY_NUM = {v: k for k, v in CIRCLED.items()}


def to_choices(value) -> list[int]:
    """'③' / '3' / 3 / '②,④' 같은 값을 [3], [3], [3], [2, 4] 처럼 선택지 번호 목록으로 바꾼다."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if text.endswith(".0"):  # 엑셀에서 3 → 3.0 으로 읽힌 경우
        text = text[:-2]
    choices = [CIRCLED[ch] for ch in text if ch in CIRCLED]
    if not choices:
        choices = [int(d) for d in re.findall(r"[1-5]", text)]
    return sorted(set(choices))


def choice_label(choices: list[int]) -> str:
    """[3] → '③', [2, 4] → '②,④'"""
    return ",".join(CIRCLED_BY_NUM.get(c, str(c)) for c in choices)


# ---------------------------------------------------------------------------
# 1) 정답지 PDF
# ---------------------------------------------------------------------------
@dataclass
class AnswerKey:
    table: pd.DataFrame  # columns: 문항(int), 정답(list[int]), 배점(int)
    title: str = ""

    @property
    def total_points(self) -> int:
        return int(self.table["배점"].sum())


def _read_pdf_text(data: bytes, max_pages: int | None = None) -> list[str]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        return [p.extract_text() or "" for p in pages]


def parse_answer_key(data: bytes) -> AnswerKey:
    """정답 PDF에서 (문항 번호, 정답, 배점)을 추출한다."""
    rows: dict[int, tuple[list[int], int]] = {}
    texts: list[str] = []

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            # 1차: 표 인식 → 한 행에 (번호, 정답, 배점) 묶음이 여러 개 들어 있음
            for table in page.extract_tables():
                for row in table:
                    cells = [(c or "").strip() for c in row]
                    for i in range(0, len(cells) - 2, 3):
                        num, ans, pts = cells[i : i + 3]
                        if num.isdigit() and pts.isdigit():
                            choices = to_choices(ans)
                            if choices:
                                rows[int(num)] = (choices, int(pts))

    # 2차: 표 인식이 실패하면 텍스트에서 "번호 정답 배점" 패턴으로 찾기
    if len(rows) < 5:
        pattern = re.compile(r"(?<!\d)(\d{1,2})\s+([①②③④⑤](?:\s*,\s*[①②③④⑤])*)\s+(\d)(?!\d)")
        for text in texts:
            for m in pattern.finditer(text):
                rows[int(m.group(1))] = (to_choices(m.group(2)), int(m.group(3)))

    if not rows:
        raise ValueError("정답 PDF에서 문항 번호/정답/배점을 찾지 못했습니다.")

    numbers = sorted(rows)
    if numbers != list(range(1, numbers[-1] + 1)):
        missing = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
        raise ValueError(f"정답 PDF에서 일부 문항을 읽지 못했습니다. 누락 문항: {missing}")

    table = pd.DataFrame(
        [{"문항": n, "정답": rows[n][0], "배점": rows[n][1]} for n in numbers]
    )
    lines = [ln.strip() for ln in (texts[0] if texts else "").splitlines() if ln.strip()]
    title = " ".join(lines[:2]) if lines else "정답표"
    return AnswerKey(table=table, title=title)


# ---------------------------------------------------------------------------
# 2) 문제지 PDF (2단 편집)
# ---------------------------------------------------------------------------
@dataclass
class QuestionPaper:
    questions: dict[int, str]  # 문항 번호 → 본문(묶음 지문 포함)
    listening_range: tuple[int, int] | None = None
    title: str = ""
    groups: list[tuple[int, int, str]] = field(default_factory=list)

    def is_listening(self, number: int) -> bool:
        if not self.listening_range:
            return False
        lo, hi = self.listening_range
        return lo <= number <= hi


_NOISE_LINE = re.compile(
    r"^(\d{1,2}|홀수형|짝수형|제\s*\d+\s*교시|영어\s*영역|.*저작권.*|.*문제지\s*$)$"
)
_Q_START = re.compile(r"^(\d{1,2})\.(?:\s+|$)(.*)$")
_GROUP_START = re.compile(r"^\[(\d{1,2})\s*[～~\-–]\s*(\d{1,2})\]\s*(.*)$")
_LISTENING = re.compile(r"(\d{1,2})번부터\s*(\d{1,2})번까지는\s*듣고")


def parse_question_paper(data: bytes) -> QuestionPaper:
    """문제지 PDF를 좌/우 단으로 나눠 읽고, 문항 번호 순서대로 본문을 잘라낸다."""
    lines: list[str] = []
    raw_first_page = ""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for idx, page in enumerate(pdf.pages):
            w, h = page.width, page.height
            if idx == 0:
                raw_first_page = page.extract_text() or ""
            for box in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                text = page.crop(box).extract_text() or ""
                for line in text.splitlines():
                    s = line.strip()
                    if not s or _NOISE_LINE.match(s):
                        continue
                    lines.append(s)

    listening = None
    m = _LISTENING.search(raw_first_page.replace("\n", ""))
    if m:
        listening = (int(m.group(1)), int(m.group(2)))

    title_lines = [ln.strip() for ln in raw_first_page.splitlines() if "학년도" in ln]
    title = title_lines[0] if title_lines else ""

    expected = 1
    current: tuple[str, int] | None = None  # ("q", 번호) 또는 ("g", 묶음 index)
    bodies: dict[int, list[str]] = {}
    groups: list[list] = []  # [시작, 끝, [줄들]]

    for s in lines:
        if s.startswith("* 확인 사항"):
            break
        g = _GROUP_START.match(s)
        if g and int(g.group(1)) == expected:
            groups.append([int(g.group(1)), int(g.group(2)), [g.group(3)]])
            current = ("g", len(groups) - 1)
            continue
        q = _Q_START.match(s)
        # 번호가 '다음에 나와야 할 문항 번호'와 같을 때만 새 문항으로 인정 → 지문 속 숫자 오인식 방지
        if q and int(q.group(1)) == expected:
            bodies[expected] = [q.group(2)] if q.group(2) else []
            current = ("q", expected)
            expected += 1
            continue
        if "듣기 문제가 끝났습니다" in s:
            current = None  # 듣기 종료 안내문은 17번 본문에 붙지 않게 건너뜀
            continue
        if current is None:
            continue  # 첫 문항 이전 안내문
        if current[0] == "q":
            bodies[current[1]].append(s)
        else:
            groups[current[1]][2].append(s)

    questions: dict[int, str] = {}
    group_tuples = [(a, b, "\n".join(x for x in body if x)) for a, b, body in groups]
    for n, body in bodies.items():
        text = f"{n}. " + "\n".join(body)
        for a, b, gtext in group_tuples:
            if a <= n <= b:
                text = f"[{a}～{b}] {gtext}\n\n{text}"
                break
        questions[n] = text.strip()

    if not questions:
        raise ValueError("문제지 PDF에서 문항을 찾지 못했습니다.")
    return QuestionPaper(questions=questions, listening_range=listening, title=title, groups=group_tuples)


# ---------------------------------------------------------------------------
# 3) OMR 인식 결과 (엑셀/CSV)
# ---------------------------------------------------------------------------
_Q_COL = re.compile(r"^\s*(?:Q|q|문항|문제|문)?\s*0*(\d{1,2})\s*(?:번)?\s*$")
_NAME_COL = re.compile(r"(이름|성명|학생명|^학생$|name)", re.IGNORECASE)
_ID_COL = re.compile(r"(번호|수험|학번|^id$|^no\.?$)", re.IGNORECASE)


def _read_table(data: bytes, filename: str, header) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                return pd.read_csv(io.BytesIO(data), header=header, encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError("CSV 파일 인코딩을 읽을 수 없습니다.")
    return pd.read_excel(io.BytesIO(data), header=header)


def _question_columns(columns) -> dict:
    found = {}
    for col in columns:
        m = _Q_COL.match(str(col))
        if m:
            found[col] = int(m.group(1))
    return found


def parse_omr(data: bytes, filename: str) -> pd.DataFrame:
    """OMR 결과를 [학생, 1, 2, ..., N] 형태로 정리한다. 응답은 1~5 정수, 무응답/복수 마킹은 NaN."""
    raw = _read_table(data, filename, header=None)

    # 헤더 행 찾기: 문항 번호처럼 생긴 칸이 가장 많은 행 (위쪽 5줄 안에서)
    header_row, best = 0, -1
    for i in range(min(5, len(raw))):
        cnt = len(_question_columns(raw.iloc[i].tolist()))
        if cnt > best:
            header_row, best = i, cnt
    if best < 1:
        raise ValueError("OMR 파일에서 문항 열(Q01, 1번 등)을 찾지 못했습니다.")

    df = raw.iloc[header_row + 1 :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[header_row].tolist()]
    df = df.dropna(how="all")

    qcols = _question_columns(df.columns)
    others = [c for c in df.columns if c not in qcols]
    name_col = next((c for c in others if _NAME_COL.search(c)), None)
    id_col = next((c for c in others if c != name_col and _ID_COL.search(c)), None)
    if name_col is None and id_col is None and others:
        name_col = others[0]

    def _clean(v) -> str:
        s = "" if pd.isna(v) else str(v).strip()
        return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s

    def _id_label(v) -> str:
        s = _clean(v)
        return f"{s}번" if s.isdigit() else s

    out = pd.DataFrame()
    if name_col is not None and id_col is not None:  # 번호 열 + 이름 열 → '87번 홍길동'
        out["학생"] = [f"{_id_label(i)} {_clean(n)}".strip() for i, n in zip(df[id_col], df[name_col])]
    elif name_col is not None:
        out["학생"] = [_clean(v) for v in df[name_col]]
    elif id_col is not None:
        out["학생"] = [_id_label(v) for v in df[id_col]]
    else:
        out["학생"] = [f"{i + 1}번 학생" for i in range(len(df))]
    out["학생"] = [s if s else f"{i + 1}번째 행 학생" for i, s in enumerate(out["학생"])]

    for col, num in sorted(qcols.items(), key=lambda kv: kv[1]):
        out[num] = [
            (c[0] if len(c) == 1 else pd.NA) for c in (to_choices(v) for v in df[col].tolist())
        ]
        out[num] = out[num].astype("Int64")

    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4) 업로드 파일 자동 분류
# ---------------------------------------------------------------------------
def detect_file_role(data: bytes, filename: str) -> str:
    """'answer'(정답지) / 'paper'(문제지) / 'omr'(OMR 결과) / 'unknown' 중 하나를 돌려준다."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xls", ".csv")):
        return "omr"
    if name.endswith(".pdf"):
        try:
            first = (_read_pdf_text(data, max_pages=1) or [""])[0]
        except Exception:
            return "unknown"
        compact = first.replace(" ", "")
        if "정답" in compact and ("배점" in compact or compact.count("①") + compact.count("③") >= 10):
            return "answer"
        return "paper"
    return "unknown"
