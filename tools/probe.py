# -*- coding: utf-8 -*-
"""按机器配置灵活调度：自适应 CPU / GPU 与内存占用率的推荐参数。
各脚本在未显式传 <并发数> 时，用本模块推荐值；显式传参优先级最高。
"""

import os


def cpus():
    return os.cpu_count() or 1


def mem():
    """内存占用率与可用内存（GB）。Windows 用 GlobalMemoryStatusEx，跨平台回退 sysconf。"""
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = _MS()
        m.dwLength = ctypes.sizeof(_MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {"load": m.dwMemoryLoad, "total_gb": m.ullTotalPhys / 1e9, "avail_gb": m.ullAvailPhys / 1e9}
    except Exception:
        try:
            names = getattr(os, "sysconf_names", ())
            if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in names and "SC_AVPHYS_PAGES" in names:
                t = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1e9
                a = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1e9
                return {"load": 0, "total_gb": t, "avail_gb": a}
        except Exception:
            pass
        return {"load": 0, "total_gb": 0, "avail_gb": 0}


def has_gpu():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def download_threads():
    """下载是网络 I/O 型，主要看核数；给 2..6。"""
    return max(2, min(cpus(), 6))


def frame_workers():
    """抽帧是 CPU-bound。按核数封顶，并按可用内存封顶防 OOM（每 worker 峰值约 1.2GB）。"""
    cores = cpus()
    m = mem()
    # avail<=1GB 时旧版回退 8 与"内存越少 worker 越少"语义相反；低内存宁可单进程慢跑
    mem_cap = max(1, int(m["avail_gb"] / 1.2)) if m["avail_gb"] > 1 else 1
    return max(1, min(cores, 4, mem_cap))


def transcribe_workers(gpu):
    """转写：GPU 共享显存 worker 宜少（2），避免争抢；CPU 用剩余核并按内存封顶。"""
    if gpu:
        return min(2, max(1, cpus() // 8))
    cores = max(1, cpus() // 2)
    m = mem()
    mem_cap = max(1, int(m["avail_gb"] / 4)) if m["avail_gb"] > 4 else 2
    return max(1, min(cores, mem_cap, 6))


def snapshot(gpu):
    m = mem()
    return (f"CPU={cpus()}核 内存{m['load']}%(可用{m['avail_gb']:.1f}GB/{m['total_gb']:.1f}GB) "
            f"GPU={'yes' if gpu else 'no'}")