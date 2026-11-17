"""디스크·메모리 확인. 맥·윈도우·리눅스 공통(표준 라이브러리만)."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

GIB = 1024**3


def disk_free_bytes(path: Path) -> int:
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def memory_total_bytes() -> int | None:
    try:
        if platform.system() == "Windows":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.ullTotalPhys)
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def hf_cached(model_id: str, cache_dir: Path) -> bool:
    """Hugging Face 캐시에 그 저장소 폴더가 있는지(대략적인 판단)."""
    repo = model_id.split(" ")[0]
    return (Path(cache_dir) / ("models--" + repo.replace("/", "--"))).is_dir()


def assert_disk_for_download(model_id: str, approx_gb: float, cache_dir: Path, margin_gb: float = 2.0) -> None:
    if hf_cached(model_id, cache_dir):
        return
    free = disk_free_bytes(cache_dir)
    need = int((approx_gb + margin_gb) * GIB)
    if free < need:
        raise RuntimeError(
            f"디스크가 부족합니다. {model_id} 를 받으려면 약 {approx_gb:.1f}GB와 여유 {margin_gb:.0f}GB가 필요합니다. "
            f"지금 여유 {free / GIB:.1f}GB."
        )
