"""채점 결과를 엑셀 파일(bytes)로 만든다. (요구사항 3)

시트1 '채점 결과' : 위쪽에 전체 학생 성적 개요, 아래쪽에 학생별 점수 + 문항별 정답 여부(O/X)
시트2 '문항 분석' : 문항별 정답, 배점, 정답률, 선택지 분포
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .grading import GradingResult

BLUE = "0B5CAD"
HEADER_FILL = PatternFill("solid", fgColor=BLUE)
LABEL_FILL = PatternFill("solid", fgColor="E8F0FA")
O_FILL = PatternFill("solid", fgColor="E3F4E8")
X_FILL = PatternFill("solid", fgColor="FCE4E4")
THIN = Side(style="thin", color="C9D3DF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)


def _header(cell):
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = HEADER_FILL
    cell.alignment = CENTER
    cell.border = BORDER


def build_excel(result: GradingResult) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "채점 결과"
    stats = result.stats
    qnums = result.question_numbers

    # ---------------- 1. 전체 학생 성적 개요 ----------------
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    ws.cell(1, 1, "전체 학생 성적 개요").font = Font(bold=True, size=14, color=BLUE)
    ws.cell(2, 1, stats.get("시험명", "")).font = Font(color="666666")

    top3 = ", ".join(f"{t['문항']}번 (오답률 {t['오답률']}%)" for t in stats["가장 많이 틀린 문항 TOP3"])
    overview = [
        ("응시 인원", f"{stats['응시 인원']}명"),
        ("만점", f"{stats['만점']}점"),
        ("평균", stats["평균"]),
        ("중앙값", stats["중앙값"]),
        ("표준편차", stats["표준편차"]),
        ("최고점", stats["최고점"]),
        ("최저점", stats["최저점"]),
        ("가장 많이 틀린 문항 번호 (TOP3)", top3),
    ]
    if stats.get("TOP3 동률 안내"):
        overview.append(("참고", stats["TOP3 동률 안내"]))

    row = 4
    for label, value in overview:
        lc = ws.cell(row, 1, label)
        lc.font = Font(bold=True)
        lc.fill = LABEL_FILL
        lc.border = BORDER
        lc.alignment = LEFT
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
        vc = ws.cell(row, 2, value)
        vc.border = BORDER
        vc.alignment = LEFT
        row += 1

    # ---------------- 2. 학생별 점수 및 문항별 정답 여부 ----------------
    row += 1
    ws.cell(row, 1, "학생별 점수 및 문항별 정답 여부 (O: 정답, X: 오답)").font = Font(bold=True, size=12, color=BLUE)
    row += 1
    header_row = row
    headers = ["학생", "점수", "맞은 문항 수", "순위"] + [f"{q}번" for q in qnums]
    for c, h in enumerate(headers, start=1):
        _header(ws.cell(row, c, h))

    st = result.students
    for idx in st.index:
        row += 1
        values = [st.at[idx, "학생"], int(st.at[idx, "점수"]), int(st.at[idx, "맞은 문항 수"]), int(st.at[idx, "순위"])]
        for c, v in enumerate(values, start=1):
            cell = ws.cell(row, c, v)
            cell.border = BORDER
            cell.alignment = CENTER
        for j, q in enumerate(qnums):
            ok = bool(result.correct.at[idx, q])
            cell = ws.cell(row, 5 + j, "O" if ok else "X")
            cell.alignment = CENTER
            cell.border = BORDER
            cell.fill = O_FILL if ok else X_FILL
            cell.font = Font(color="1E7B34" if ok else "C0392B", bold=not ok)

    ws.column_dimensions["A"].width = 32
    for c in range(2, 5):
        ws.column_dimensions[get_column_letter(c)].width = 11
    for j in range(len(qnums)):
        ws.column_dimensions[get_column_letter(5 + j)].width = 5.5
    ws.freeze_panes = ws.cell(header_row + 1, 2)

    # ---------------- 시트2: 문항 분석 ----------------
    ws2 = wb.create_sheet("문항 분석")
    qs = result.question_stats
    cols = ["문항", "정답", "배점", "정답 인원", "오답 인원", "정답률", "오답률",
            "1번 선택", "2번 선택", "3번 선택", "4번 선택", "5번 선택", "무응답", "가장 많이 고른 오답"]
    for c, h in enumerate(cols, start=1):
        _header(ws2.cell(1, c, h))
        ws2.column_dimensions[get_column_letter(c)].width = 12
    ws2.column_dimensions[get_column_letter(len(cols))].width = 18
    for r, (_, rec) in enumerate(qs.iterrows(), start=2):
        for c, h in enumerate(cols, start=1):
            v = rec[h]
            cell = ws2.cell(r, c, float(v) if h in ("정답률", "오답률") else (int(v) if h not in ("정답", "가장 많이 고른 오답") else v))
            cell.border = BORDER
            cell.alignment = CENTER
            if h in ("정답률", "오답률"):
                cell.number_format = "0.0%"
    ws2.freeze_panes = "B2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
