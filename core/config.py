"""설정값 읽기.

찾는 순서: ① .streamlit/secrets.toml (배포 환경) → ② .env 파일 (로컬) → ③ 시스템 환경변수
빈 값은 '없음'으로 보고 다음 순서로 넘어간다.
(Streamlit은 secrets.toml 값을 환경변수로도 등록하기 때문에, .env는 환경변수를 거치지 않고 파일에서 직접 읽는다)
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    # 메모장이 BOM을 붙이거나 UTF-16으로 저장해도 읽히도록
    for enc in ("utf-8-sig", "utf-16", "cp949"):
        try:
            values = dotenv_values(ENV_FILE, encoding=enc)
            return {k.strip(): str(v).strip() for k, v in values.items() if k and v}
        except (UnicodeError, ValueError):
            continue
    return {}


def get_setting(name: str, default: str | None = None) -> str | None:
    try:
        if name in st.secrets and str(st.secrets[name]).strip():
            return str(st.secrets[name]).strip()
    except Exception:  # secrets.toml 파일이 없을 때
        pass
    value = _read_env_file().get(name)
    if value:
        return value
    value = os.getenv(name, "").strip()
    return value or default


def academy_name() -> str:
    return get_setting("ACADEMY_NAME", "한결 학원") or "한결 학원"


def logo_path() -> Path | None:
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.svg", "logo.webp"):
        p = ROOT / "assets" / name
        if p.exists():
            return p
    return None
