"""Docker SDK를 통한 컨테이너 메트릭 수집."""

import logging
from dataclasses import dataclass, field
from typing import Optional

import docker
import docker.errors

logger = logging.getLogger(__name__)


@dataclass
class ContainerMetrics:
    container: str
    cpu_pct: float
    mem_pct: float
    mem_mb: float
    block_io_mb: float  # 이번 주기의 블록 I/O 델타 (MB)


class DockerStatsCollector:
    def __init__(self) -> None:
        self._client = docker.from_env()
        # 블록 I/O delta 계산을 위한 이전 누적값 저장
        self._prev_blkio: dict[str, float] = (
            field(default_factory=dict) if False else {}
        )

    def collect(self, container_name: str) -> Optional[ContainerMetrics]:
        try:
            container = self._client.containers.get(container_name)
            raw = container.stats(stream=False)
            return self._parse(container_name, raw)
        except docker.errors.NotFound:
            logger.warning("Container not found: %s", container_name)
            return None
        except Exception as exc:
            logger.error("Stats collection failed for %s: %s", container_name, exc)
            return None

    def _parse(self, name: str, raw: dict) -> Optional[ContainerMetrics]:
        try:
            cpu_pct = _calc_cpu(raw)
            mem_usage, mem_limit = _calc_mem(raw)
            mem_pct = (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0.0
            mem_mb = mem_usage / (1024 * 1024)

            blkio_total = _calc_blkio(raw)
            prev = self._prev_blkio.get(name, blkio_total)
            delta_mb = max(0.0, (blkio_total - prev) / (1024 * 1024))
            self._prev_blkio[name] = blkio_total

            return ContainerMetrics(
                container=name,
                cpu_pct=round(cpu_pct, 2),
                mem_pct=round(mem_pct, 2),
                mem_mb=round(mem_mb, 2),
                block_io_mb=round(delta_mb, 4),
            )
        except (KeyError, ZeroDivisionError, TypeError) as exc:
            logger.error("Failed to parse stats for %s: %s", name, exc)
            return None

    def collect_all(self, targets: list[str]) -> list[ContainerMetrics]:
        results = []
        for name in targets:
            m = self.collect(name)
            if m is not None:
                results.append(m)
        return results


def _calc_cpu(raw: dict) -> float:
    cpu = raw["cpu_stats"]["cpu_usage"]["total_usage"]
    pre_cpu = raw["precpu_stats"]["cpu_usage"]["total_usage"]
    sys_cpu = raw["cpu_stats"].get("system_cpu_usage", 0)
    pre_sys = raw["precpu_stats"].get("system_cpu_usage", 0)

    cpu_delta = cpu - pre_cpu
    sys_delta = sys_cpu - pre_sys
    if sys_delta <= 0 or cpu_delta < 0:
        return 0.0

    num_cpus = raw["cpu_stats"].get("online_cpus") or len(
        raw["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])
    )
    return (cpu_delta / sys_delta) * num_cpus * 100.0


def _calc_mem(raw: dict) -> tuple[float, float]:
    mem_stats = raw["memory_stats"]
    usage = mem_stats.get("usage", 0)
    cache = mem_stats.get("stats", {}).get("cache", 0)
    limit = mem_stats.get("limit", 1)
    return max(0.0, float(usage - cache)), float(limit)


def _calc_blkio(raw: dict) -> float:
    """누적 블록 I/O 바이트 합계."""
    entries = raw.get("blkio_stats", {}).get("io_service_bytes_recursive") or []
    return float(sum(e.get("value", 0) for e in entries))
