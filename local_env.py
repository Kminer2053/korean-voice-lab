"""로컬 전용 환경 변수. mlx, huggingface, gradio import 전에 불러온다."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REFERENCES = ROOT / "references"
OUTPUTS = ROOT / "outputs"
HF_HOME = ROOT / ".cache" / "huggingface"
HF_HUB_CACHE = HF_HOME / "hub"

REFERENCES.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)
HF_HUB_CACHE.mkdir(parents=True, exist_ok=True)

os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["GRADIO_SHARE"] = "False"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("PYTHONUNBUFFERED", "1")
