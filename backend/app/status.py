import asyncio
import os
import time
import logging
from collections import deque
from .streaming import _cache_manager, get_forward_snapshot, _forward_streams, _dc_disk_size

logger = logging.getLogger("streamer")

_app_start = time.monotonic()
_prev_cpu = None
_prev_net = None
_history = deque(maxlen=60)
_last_oom_clear = 0.0
_OOM_CLEAR_COOLDOWN = 20  # seconds
_proc_rss_cache = (0.0, 0)  # (timestamp, value)
_PROC_RSS_TTL = 10  # seconds


def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _read_key(path: str, key: str) -> int | None:
    try:
        with open(path) as f:
            for line in f:
                k, _, v = line.partition(" ")
                if k == key:
                    return int(v.strip())
    except Exception:
        return None
    return None


def _cgroup_v1_cpu_usage() -> int | None:
    for p in [
        "/sys/fs/cgroup/cpuacct/cpuacct.usage",
        "/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage",
        "/sys/fs/cgroup/cpu/cpuacct.usage",
    ]:
        v = _read_int(p)
        if v is not None:
            return v
    return None


def _cgroup_v1_cpu_cores() -> float | None:
    for cf in [
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
        "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us",
    ]:
        q = _read_int(cf)
        if q is not None and q > 0:
            p = _read_int(cf.replace("cfs_quota_us", "cfs_period_us"))
            if p and p > 0:
                return q / p
    return None


def get_cpu() -> float:
    global _prev_cpu
    try:
        usage = _read_key("/sys/fs/cgroup/cpu.stat", "usage_usec")
        if usage is None:
            usage = _cgroup_v1_cpu_usage()
            if usage is not None:
                usage //= 1000  # v1 is in nanoseconds → microseconds
        if usage is None:
            return 0.0

        cores = None
        # cgroup v2: cpu.max is "<quota> <period>" where quota may be "max"
        # (unlimited). _read_int can't parse the two-token format, so split it.
        try:
            with open("/sys/fs/cgroup/cpu.max") as f:
                parts = f.read().split()
            if len(parts) == 2 and parts[0] != "max":
                q, p = int(parts[0]), int(parts[1])
                if q > 0 and p > 0:
                    cores = q / p
        except (OSError, ValueError):
            cores = None
        if cores is None:
            cores = _cgroup_v1_cpu_cores()
        if cores is None:
            cores = os.cpu_count() or 1

        now = time.monotonic()
        if _prev_cpu is not None:
            pu, pt = _prev_cpu
            dt = now - pt
            du = usage - pu
            _prev_cpu = (usage, now)
            if dt > 0:
                return round(du / 1_000_000 / dt * 100 / cores, 1)
            return 0.0
        _prev_cpu = (usage, now)
        return 0.0
    except Exception:
        return 0.0


def _parse_mem_env(val: str) -> int:
    val = val.strip().upper()
    for suffix in ["GIB", "GI", "GB", "G", "MIB", "MI", "MB", "M"]:
        if val.endswith(suffix):
            return int(float(val[: -len(suffix)]) * (1024**3 if suffix[0] == "G" else 1024**2))
    return int(val)


def _cgroup_memory_max() -> int | None:
    for p in [
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
        "/sys/fs/cgroup/memory.limit_in_bytes",
    ]:
        v = _read_int(p)
        if v is not None:
            return v
    return None


def _discover_cgroup_memory() -> tuple[int | None, int | None]:
    for cur in [
        "/sys/fs/cgroup/memory.current",
        "/sys/fs/cgroup/memory/memory.usage_in_bytes",
        "/sys/fs/cgroup/memory.usage_in_bytes",
    ]:
        c = _read_int(cur)
        if c is not None:
            return c, _cgroup_memory_max()
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                if line.startswith("0::"):
                    cg = line.strip()[3:]
                    if cg and cg != "/":
                        c = _read_int(f"/sys/fs/cgroup{cg}/memory.current")
                        if c is not None:
                            m = _read_int(f"/sys/fs/cgroup{cg}/memory.max")
                            return c, m
    except OSError:
        pass
    return None, None


_MEM_STAT_PATHS = [
    "/sys/fs/cgroup/memory.stat",           # cgroup v2
    "/sys/fs/cgroup/memory/memory.stat",     # cgroup v1
]


def _read_memory_stat() -> dict[str, int] | None:
    """Parse memory.stat into a dict. Tries v2 then v1 paths."""
    for sp in _MEM_STAT_PATHS:
        try:
            result = {}
            with open(sp) as f:
                for line in f:
                    k, _, v = line.partition(" ")
                    result[k] = int(v.strip())
            return result
        except Exception:
            continue
    # Also try nested cgroup path from /proc/self/cgroup
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                if line.startswith("0::"):
                    cg = line.strip()[3:]
                    if cg and cg != "/":
                        with open(f"/sys/fs/cgroup{cg}/memory.stat") as sf:
                            result = {}
                            for entry in sf:
                                k, _, v = entry.partition(" ")
                                result[k] = int(v.strip())
                            return result
    except Exception:
        pass
    return None


_MEM_STAT_KEYS = ["anon", "file", "kernel_stack", "pagetables",
                   "slab_reclaimable", "slab_unreclaimable", "sock", "shmem"]


def _sum_memory_stat(stat: dict) -> int:
    """Sum the major components that make up memory.current.
    memory.current ≈ anon + file + kernel + slab + sock + ...
    """
    return sum(stat.get(k, 0) for k in _MEM_STAT_KEYS)


_SUSPICIOUSLY_LOW = 500 * 1024 * 1024  # 500 MB


def _own_cgroup_path() -> str | None:
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                if line.startswith("0::"):
                    return line.strip()[3:]
    except OSError:
        pass
    return None


def _sum_proc_rss() -> int:
    global _proc_rss_cache
    now = time.monotonic()
    if now - _proc_rss_cache[0] < _PROC_RSS_TTL:
        return _proc_rss_cache[1]
    own_cgroup = _own_cgroup_path()
    total = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        if own_cgroup is not None:
            try:
                with open(f"/proc/{entry}/cgroup") as cf:
                    pid_in_cgroup = False
                    for cline in cf:
                        if cline.startswith("0::"):
                            pid_cgroup = cline.strip()[3:]
                            pid_in_cgroup = (pid_cgroup == own_cgroup)
                            break
                    if not pid_in_cgroup:
                        continue
            except OSError:
                continue
        try:
            with open(f"/proc/{entry}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1])
        except OSError:
            pass
    result = total * 1024
    _proc_rss_cache = (now, result)
    return result


def maybe_oom_clear():
    """Check memory and clear caches if above 65%. Called periodically from background task.
    Only logs when something was actually freed — RAM persistently sitting just
    over the threshold as reclaimable page cache (which this cannot touch) used
    to spam a warning every cooldown."""
    global _last_oom_clear
    cur, mx = _discover_cgroup_memory()
    now = time.monotonic()
    if cur is not None and mx is not None and cur > 0.65 * mx and now - _last_oom_clear > _OOM_CLEAR_COOLDOWN:
        _last_oom_clear = now
        active = {(info["chat_id"], mid) for mid, info in list(_forward_streams.items())}
        freed = _cache_manager.clear_all(exclude_keys=active)
        kept = len(active)
        if freed > 0:
            logger.warning("OOM guard: cleared %.1f MB from cache (%d streams preserved)", freed / 1024 / 1024, kept)


def get_ram() -> dict:
    cur, mx = _discover_cgroup_memory()
    if cur is not None:
        stat = _read_memory_stat()
        if stat is not None:
            stat_total = _sum_memory_stat(stat)
            if cur < _SUSPICIOUSLY_LOW and stat_total > cur:
                cur = stat_total
        else:
            proc = _sum_proc_rss()
            if proc > cur:
                cur = proc
        if mx is None or mx <= 0 or mx > 10**18:
            mx = _parse_mem_env(os.environ.get("MEMORY", "16Gi"))
        return {
            "total_gb": round(mx / 1024**3, 1),
            "used_gb": round(cur / 1024**3, 1),
            "percent": round(100.0 * cur / mx, 1),
        }
    used = _sum_proc_rss()
    total = _parse_mem_env(os.environ.get("MEMORY", "16Gi"))
    return {
        "total_gb": round(total / 1024**3, 1),
        "used_gb": round(used / 1024**3, 1),
        "percent": round(100.0 * used / total, 1),
    }


def get_net() -> dict:
    global _prev_net
    try:
        with open("/proc/net/dev") as f:
            f.readline()
            f.readline()
            rx = tx = 0
            for line in f:
                parts = line.strip().split()
                iface = parts[0].rstrip(":")
                if iface == "eth0":
                    rx = int(parts[1])
                    tx = int(parts[9])
                    break
        now = time.time()
        rx_mbps = tx_mbps = 0.0
        if _prev_net is not None:
            pt, pr, pt_ = _prev_net
            dt = now - pt
            if dt > 0:
                rx_mbps = round((rx - pr) * 8 / dt / 1024 / 1024, 1)
                tx_mbps = round((tx - pt_) * 8 / dt / 1024 / 1024, 1)
        _prev_net = (now, rx, tx)
        return {"rx_mbps": rx_mbps, "tx_mbps": tx_mbps}
    except Exception:
        return {"rx_mbps": 0, "tx_mbps": 0}


def get_uptime() -> int:
    return int(time.monotonic() - _app_start)


class RingHandler(logging.Handler):
    def __init__(self, maxlen: int = 500):
        super().__init__()
        self.logs: deque[str] = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord):
        self.logs.append(self.format(record))

    def get_logs(self) -> list[str]:
        return list(self.logs)

    def clear(self):
        self.logs.clear()


_ring_handler: RingHandler | None = None


def attach_ring_handler():
    global _ring_handler
    if _ring_handler is not None:
        return
    _ring_handler = RingHandler()
    streamer = logging.getLogger("streamer")
    streamer.addHandler(_ring_handler)
    logger.info("Aruvi monitor ready")


def clear_logs():
    if _ring_handler:
        _ring_handler.clear()


async def get_status() -> dict:
    cpu = get_cpu()
    ram = get_ram()
    net = get_net()
    _history.append({"cpu": cpu, "ram": ram["percent"], "rx": net["rx_mbps"], "tx": net["tx_mbps"]})
    logs = _ring_handler.get_logs() if _ring_handler else []
    cache = _cache_manager.info
    per_video = _cache_manager.per_video
    forward = get_forward_snapshot()

    # Merge forward data into per_video
    forward_by_mid = {s["message_id"]: s for s in forward}
    for v in per_video:
        mid = v["message_id"]
        fwd = forward_by_mid.pop(mid, None)
        v["forward_mb"] = fwd["prebuffer_mb"] if fwd else 0
        v["forward_max_mb"] = fwd["max_mb"] if fwd else 0
    # Active streams not yet in backward cache
    for mid, fwd in forward_by_mid.items():
        per_video.append({
            "message_id": mid,
            "chat_id": fwd["chat_id"],
            "chunks": 0, "size_mb": 0, "max_mb": 200,
            "hits": 0, "misses": 0, "evictions": 0,
            "forward_mb": fwd["prebuffer_mb"],
            "forward_max_mb": fwd["max_mb"],
        })

    cache["per_video"] = per_video
    cache["forward"] = {
        "total_prebuffer_mb": sum(s["prebuffer_mb"] for s in forward),
        "total_max_mb": sum(s["max_mb"] for s in forward),
        "stream_count": len(forward),
    } if forward else None
    # Full-cache directory scan — run off the event loop so status polls
    # never stall active streams when the 15s internal cache expires.
    disk_bytes = await asyncio.to_thread(_dc_disk_size)
    return {
        "name": "Aruvi",
        "cpu": cpu,
        "ram": ram,
        "net": net,
        "cache": cache,
        "disk": {"used_mb": round(disk_bytes / 1024 / 1024, 1), "available_gb": 15},
        "uptime_seconds": get_uptime(),
        "history": list(_history),
        "logs": logs,
    }
