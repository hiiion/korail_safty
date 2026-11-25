"""Vercel 서버리스 진입점: 모든 요청을 Flask 앱으로 보낸다 (vercel.json의 rewrites)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

app = create_app()
