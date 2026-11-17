"""다운로드 전에 디스크와 메모리를 측정한다. 추정 사양을 만들지 않는다."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

# Hugging Face API models 응답의 usedStorage. 2026-10-22 조회.
# https://huggingface.co/api/models/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit
# https://huggingface.co/api/models/mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit
MODEL_06 = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
MODEL_17 = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
MODEL_06_STORAGE_BYTES = 2_967_061_479
MODEL_17_STORAGE_BYTES = 5_160_340_544
GIB = 1024 ** 3
# 가중치 파일보다 활성화·KV·OS가 더 필요하다. 이 여유보다 작으면 1.7B는 받지 않는다.
MODEL_17_MEMORY_MARGIN_BYTES = 4 * GIB
MODEL_17_DISK_MARGIN_BYTES = 8 * GIB
MODEL_06_DISK_MARGIN_BYTES = 2 * GIB


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemorySnapshot:
    page_size: int
    pages_free: int
    pages_inactive: int
    pages_speculative: int
    pages_purgeable: int
    pages_wired: int
    pages_compressor: int
    pressure_free_percent: int | None
    raw_vm_stat: str
    raw_memory_pressure: str

    @property
    def reclaimable_pages(self) -> int:
        return (
            self.pages_free
            + self.pages_inactive
            + self.pages_speculative
            + self.pages_purgeable
        )

    @property
    def reclaimable_bytes(self) -> int:
        return self.reclaimable_pages * self.page_size


@dataclass(frozen=True)
class Model17Decision:
    allowed: bool
    reason: str
    snapshot: MemorySnapshot
    disk_avail_bytes: int


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProbeError(
            f"명령이 실패했습니다: {' '.join(command)}\n{completed.stderr.strip()}"
        )
    return completed.stdout


def _first_int(pattern: str, text: str, label: str) -> int:
    match = re.search(pattern, text)
    if match is None:
        raise ProbeError(f"{label} 수치를 읽지 못했습니다.")
    return int(match.group(1))


def read_memory() -> MemorySnapshot:
    page_size = int(_run(["/usr/sbin/sysctl", "-n", "hw.pagesize"]).strip())
    vm_stat = _run(["/usr/bin/vm_stat"])
    pressure = _run(["/usr/bin/memory_pressure"])
    free_match = re.search(r"System-wide memory free percentage:\s*(\d+)%", pressure)
    return MemorySnapshot(
        page_size=page_size,
        pages_free=_first_int(r"Pages free:\s*(\d+)", vm_stat, "Pages free"),
        pages_inactive=_first_int(r"Pages inactive:\s*(\d+)", vm_stat, "Pages inactive"),
        pages_speculative=_first_int(
            r"Pages speculative:\s*(\d+)", vm_stat, "Pages speculative"
        ),
        pages_purgeable=_first_int(r"Pages purgeable:\s*(\d+)", vm_stat, "Pages purgeable"),
        pages_wired=_first_int(r"Pages wired down:\s*(\d+)", vm_stat, "Pages wired"),
        pages_compressor=_first_int(
            r"Pages occupied by compressor:\s*(\d+)", vm_stat, "compressor"
        ),
        pressure_free_percent=int(free_match.group(1)) if free_match else None,
        raw_vm_stat=vm_stat,
        raw_memory_pressure=pressure,
    )


def disk_avail_bytes(path: str = "/") -> int:
    raw = _run(["/bin/df", "-k", path])
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ProbeError(f"df 출력을 읽지 못했습니다.\n{raw}")
    parts = lines[-1].split()
    if len(parts) < 4:
        raise ProbeError(f"df 열을 읽지 못했습니다.\n{raw}")
    try:
        available_kib = int(parts[3])
    except ValueError as exc:
        raise ProbeError(f"df 여유 용량이 숫자가 아닙니다: {parts[3]}") from exc
    return available_kib * 1024


def decide_model_17() -> Model17Decision:
    snapshot = read_memory()
    avail = disk_avail_bytes("/")
    reclaim = snapshot.reclaimable_bytes
    pressure = (
        f"{snapshot.pressure_free_percent}%"
        if snapshot.pressure_free_percent is not None
        else "읽지 못함"
    )
    common = (
        f"모델 ID {MODEL_17} 는 Hugging Face에 있습니다. "
        f"usedStorage {MODEL_17_STORAGE_BYTES} bytes. "
        f"디스크 여유 {avail} bytes. "
        f"vm_stat 기준 회수 가능 페이지(free+inactive+speculative+purgeable) "
        f"{snapshot.reclaimable_pages} x {snapshot.page_size} = {reclaim} bytes. "
        f"memory_pressure 여유 비율 {pressure}. "
        f"wired {snapshot.pages_wired * snapshot.page_size} bytes, "
        f"compressor {snapshot.pages_compressor * snapshot.page_size} bytes."
    )
    if avail < MODEL_17_STORAGE_BYTES + MODEL_17_DISK_MARGIN_BYTES:
        return Model17Decision(
            allowed=False,
            reason=(
                "1.7B 비활성. 디스크 여유가 모델 파일과 8GiB 여유를 합친 값보다 작습니다. "
                + common
            ),
            snapshot=snapshot,
            disk_avail_bytes=avail,
        )
    if reclaim < MODEL_17_STORAGE_BYTES + MODEL_17_MEMORY_MARGIN_BYTES:
        return Model17Decision(
            allowed=False,
            reason=(
                "1.7B 비활성. 바로 회수 가능한 메모리가 모델 파일 크기와 4GiB 여유를 합친 값보다 작아 "
                "다운로드와 실행을 하지 않습니다. " + common
            ),
            snapshot=snapshot,
            disk_avail_bytes=avail,
        )
    return Model17Decision(
        allowed=True,
        reason="1.7B 실행 조건이 맞습니다. " + common,
        snapshot=snapshot,
        disk_avail_bytes=avail,
    )


def assert_disk_for_06() -> int:
    avail = disk_avail_bytes("/")
    needed = MODEL_06_STORAGE_BYTES + MODEL_06_DISK_MARGIN_BYTES
    if avail < needed:
        raise ProbeError(
            "0.6B 8-bit와 의존성을 받을 디스크가 부족합니다. "
            f"여유 {avail} bytes, 필요 기준 {needed} bytes "
            f"(모델 usedStorage {MODEL_06_STORAGE_BYTES} bytes + 2GiB)."
        )
    return avail
