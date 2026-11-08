"""채점과 통계 계산. 숫자는 전부 여기서 계산하고, 챗봇(LLM)은 이 결과를 그대로 전달만 한다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .parsers import AnswerKey, QuestionPaper, choice_label


@dataclass
class GradingResult:
    answer_key: AnswerKey
    responses: pd.DataFrame          # 행: 학생, 열: 문항 번호 → 학생이 고른 번호(1~5, 무응답은 NA)
    correct: pd.DataFrame            # 행: 학생, 열: 문항 번호 → 정답 여부(bool)
    students: pd.DataFrame           # 학생, 학생번호, 점수, 맞은 문항 수, 순위
    question_stats: pd.DataFrame     # 문항별 정답률/오답률/선택 분포
    stats: dict                      # 전체 통계
    paper: QuestionPaper | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def question_numbers(self) -> list[int]:
        return list(self.answer_key.table["문항"])


# 학생 번호로 볼 수 있는 형식 (위에서부터 우선). '1학년 87번 홍길동' → 87, '900학생' → 900, 'S087' → 87
_NUMBER_PATTERNS = [
    re.compile(r"(\d+)\s*번(?!째)"),                  # 87번
    re.compile(r"(\d+)\s*학생"),                      # 900학생
    re.compile(r"(?:번호|no\.?|#)\s*(\d+)", re.I),     # 번호 87, No.87, #87
    re.compile(r"^\s*[A-Za-z가-힣]*\s*(\d+)\s*$"),     # 87, S087, 학생087
]


def extract_student_numbers(text: str) -> list[int]:
    """이름/질문에서 학생 번호 후보를 모두 찾는다. '87번과 88번' → [87, 88]
    우선순위가 가장 높은 형식 하나로만 찾고, 서로 다른 번호는 전부 돌려준다."""
    s = str(text)
    for pat in _NUMBER_PATTERNS[:3]:  # 87번 / 900학생 / 번호 87
        found = list(dict.fromkeys(int(n) for n in pat.findall(s)))
        if found:
            return found
    if re.fullmatch(r"[\d\s,/·&와과및랑이하고]+", s):  # '87, 88', '87과 88' 처럼 숫자만 나열
        return list(dict.fromkeys(int(n) for n in re.findall(r"\d+", s)))
    m = _NUMBER_PATTERNS[3].search(s)  # S087, 학생087
    return [int(m.group(1))] if m else []


def extract_student_number(text: str):
    """번호가 정확히 하나일 때만 그 번호, 없거나 여러 개(애매함)면 NA."""
    nums = extract_student_numbers(text)
    return nums[0] if len(nums) == 1 else pd.NA


_student_number = extract_student_number


def grade(answer_key: AnswerKey, omr: pd.DataFrame, paper: QuestionPaper | None = None) -> GradingResult:
    key = answer_key.table.set_index("문항")
    qnums = list(key.index)
    warnings: list[str] = []

    if len(omr) == 0:
        raise ValueError("OMR 파일에 학생 데이터가 없습니다.")

    # 문항 '열' 자체가 빠진 건 파일이 잘못된 것 → 채점 중단 (응답 칸이 비어 있는 '무응답'과 구분)
    omr_q = [c for c in omr.columns if isinstance(c, int)]
    missing = [q for q in qnums if q not in omr_q]
    if missing:
        raise ValueError(
            f"OMR 파일에 {missing}번 문항 열이 없어요. 정답지는 {len(qnums)}문항입니다. "
            "정답지와 OMR이 같은 시험인지, OMR 파일이 잘리지 않았는지 확인해 주세요."
        )
    extra = [q for q in omr_q if q not in key.index]
    extra_filled = [q for q in extra if omr[q].notna().any()]
    if extra_filled:
        raise ValueError(
            f"정답지에는 없는 {extra_filled}번 문항에 OMR 응답이 있어요. 정답지와 OMR이 같은 시험인지 확인해 주세요."
        )
    if extra:
        warnings.append(f"OMR의 빈 문항 열 {extra}은 정답지에 없어서 무시했습니다.")

    responses = pd.DataFrame(index=omr.index)
    for q in qnums:
        responses[q] = omr[q]

    blanks = int(responses.isna().sum().sum())
    if blanks:
        warnings.append(f"무응답·복수 마킹 등 인식되지 않은 답안 {blanks}건은 오답으로 처리했습니다.")
    dup = omr["학생"][omr["학생"].duplicated()].unique().tolist()
    if dup:
        warnings.append(f"이름이 같은 학생이 있어요: {dup[:5]} — 채팅에서 조회할 때 후보로 보여드립니다.")

    correct = pd.DataFrame(index=omr.index)
    for q in qnums:
        answers = set(key.at[q, "정답"])
        correct[q] = responses[q].apply(lambda v, a=answers: (not pd.isna(v)) and int(v) in a)

    points = key["배점"]
    scores = sum(correct[q].astype(int) * int(points[q]) for q in qnums)

    students = pd.DataFrame(
        {
            "학생": omr["학생"],
            "학생번호": omr["학생"].map(_student_number).astype("Int64"),
            "점수": scores.astype(int),
            "맞은 문항 수": correct.sum(axis=1).astype(int),
        }
    )
    students["순위"] = students["점수"].rank(method="min", ascending=False).astype(int)

    # 문항별 통계
    n = len(students)
    qrows = []
    for q in qnums:
        col = responses[q]
        wrong = int((~correct[q]).sum())
        dist = {c: int((col == c).sum()) for c in range(1, 6)}
        blank = int(col.isna().sum())
        answers = key.at[q, "정답"]
        wrong_choices = {c: v for c, v in dist.items() if c not in answers and v > 0}
        top_wrong = max(wrong_choices, key=wrong_choices.get) if wrong_choices else None
        qrows.append(
            {
                "문항": q,
                "정답": choice_label(answers),
                "배점": int(key.at[q, "배점"]),
                "정답 인원": n - wrong,
                "오답 인원": wrong,
                "정답률": (n - wrong) / n,
                "오답률": wrong / n,
                **{f"{c}번 선택": dist[c] for c in range(1, 6)},
                "무응답": blank,
                "가장 많이 고른 오답": choice_label([top_wrong]) if top_wrong else "-",
            }
        )
    question_stats = pd.DataFrame(qrows)

    s = students["점수"]
    ranked_q = question_stats.sort_values(["오답률", "문항"], ascending=[False, True]).reset_index(drop=True)
    top3 = ranked_q.head(3)
    tie_note = ""
    if len(ranked_q) > 3 and ranked_q.loc[3, "오답률"] == ranked_q.loc[2, "오답률"]:
        tied = ranked_q[ranked_q["오답률"] == ranked_q.loc[2, "오답률"]]["문항"].tolist()
        tie_note = f"오답률 {ranked_q.loc[2, '오답률']:.1%} 동률 문항: {tied} (문항 번호가 빠른 순으로 선정)"

    stats = {
        "시험명": answer_key.title.replace("정답표", "").strip() or (paper.title if paper else ""),
        "응시 인원": n,
        "문항 수": len(qnums),
        "만점": answer_key.total_points,
        "평균": round(float(s.mean()), 2),
        "중앙값": round(float(s.median()), 2),
        "표준편차": round(float(s.std(ddof=0)), 2),  # 모집단 표준편차 (학원 전체 학생 기준)
        "최고점": int(s.max()),
        "최저점": int(s.min()),
        "최고점 학생": students.loc[s == s.max(), "학생"].tolist(),
        "최저점 학생": students.loc[s == s.min(), "학생"].tolist(),
        "가장 많이 틀린 문항 TOP3": [
            {"문항": int(r["문항"]), "오답률": round(float(r["오답률"]) * 100, 1)} for _, r in top3.iterrows()
        ],
        "TOP3 동률 안내": tie_note,
    }

    return GradingResult(
        answer_key=answer_key,
        responses=responses,
        correct=correct,
        students=students,
        question_stats=question_stats,
        stats=stats,
        paper=paper,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 조회 함수 (챗봇 tool이 사용)
# ---------------------------------------------------------------------------
def find_students(result: GradingResult, query: str) -> pd.DataFrame:
    """'87', '87번', '87번 학생', '900학생', '홍길동' 등으로 학생을 찾는다."""
    st = result.students
    q = str(query).strip()
    if not q:
        return st.iloc[0:0]

    exact = st[st["학생"] == q]
    # 질문에서 번호 외에 남는 글자(이름 등) — '87번 홍길동' → '홍길동'
    name_part = re.sub(r"\d+\s*(?:번째|번|학년|반|학생)?|학생|님|\s", "", q)
    nums = extract_student_numbers(q)

    if not nums:
        # 이름으로 찾기: '홍길동' → '홍길동', '1학년 87번 홍길동' 모두 후보 (동명이인이면 여러 명 반환)
        if name_part:
            partial = st[st["학생"].str.replace(" ", "").str.contains(re.escape(name_part), na=False)]
            if len(partial):
                return partial
        return exact

    # 번호로 찾기
    if len(exact):
        return exact
    if len(nums) > 1:
        # '87번과 88번'처럼 번호가 여러 개 → 하나를 임의로 고르지 않고 해당 학생 모두를 후보로 반환
        multi = st[st["학생번호"].isin(nums)]
        if not len(multi) and st["학생번호"].isna().all():
            multi = st.iloc[[n - 1 for n in nums if 1 <= n <= len(st)]]
        return multi
    num = nums[0]
    by_no = st[st["학생번호"] == num]
    if len(by_no) > 1 and name_part:  # 같은 번호가 여럿이면 이름으로 좁히기
        narrowed = by_no[by_no["학생"].str.replace(" ", "").str.contains(re.escape(name_part), na=False)]
        if len(narrowed):
            return narrowed
    if len(by_no):
        return by_no
    # 학생명에 번호가 전혀 없는 데이터라면 'N번' = 명단의 N번째 학생으로 해석
    if st["학생번호"].isna().all() and 1 <= num <= len(st):
        return st.iloc[[num - 1]]
    return st.iloc[0:0]


def students_by_rank(result: GradingResult, order: str = "lowest", count: int = 1) -> pd.DataFrame:
    """하위/상위 count명. count번째와 동점인 학생은 모두 포함."""
    count = max(1, int(count))
    asc = order != "highest"
    sorted_st = result.students.sort_values(["점수", "학생"], ascending=[asc, True])
    if count >= len(sorted_st):
        return sorted_st
    cutoff = sorted_st.iloc[count - 1]["점수"]
    if asc:
        return sorted_st[sorted_st["점수"] <= cutoff]
    return sorted_st[sorted_st["점수"] >= cutoff]


def most_wrong_questions(result: GradingResult, top_n: int = 3) -> pd.DataFrame:
    top_n = max(1, int(top_n))
    qs = result.question_stats.sort_values(["오답률", "문항"], ascending=[False, True])
    return qs.head(top_n)


def score_distribution(result: GradingResult, width: int = 10) -> dict[str, int]:
    s = result.students["점수"]
    full = result.stats["만점"]
    out = {}
    for lo in range(0, full + 1, width):
        hi = min(lo + width - 1, full)
        if lo > full:
            break
        label = f"{lo}점" if lo == hi else f"{lo}~{hi}점"
        out[label] = int(((s >= lo) & (s <= hi)).sum())
    return {k: v for k, v in out.items()}


def wrong_questions_of(result: GradingResult, row_index) -> list[dict]:
    key = result.answer_key.table.set_index("문항")
    out = []
    for q in result.question_numbers:
        if not result.correct.at[row_index, q]:
            v = result.responses.at[row_index, q]
            out.append(
                {
                    "문항": q,
                    "학생 답": "무응답" if pd.isna(v) else choice_label([int(v)]),
                    "정답": choice_label(key.at[q, "정답"]),
                }
            )
    return out
