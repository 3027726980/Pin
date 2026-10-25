"""作者：LHF；时间：2026-10-25；作用：受控 Python 子进程、进程树回收及输出限制。"""

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def _windows_job(process):
    """将脚本放入关闭即终止的 Windows Job，避免遗留派生进程。"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        """Windows JOBOBJECT_BASIC_LIMIT_INFORMATION 结构。"""

        _fields_ = [("ProcessTime", ctypes.c_longlong), ("JobTime", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                    ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD),
                    ("Scheduling", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        """Windows IO_COUNTERS 结构。"""

        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

    class ExtendedLimits(ctypes.Structure):
        """Windows JOBOBJECT_EXTENDED_LIMIT_INFORMATION 结构。"""

        _fields_ = [("Basic", BasicLimits), ("IO", IoCounters),
                    ("ProcessMemory", ctypes.c_size_t), ("JobMemory", ctypes.c_size_t),
                    ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        if job:
            kernel.CloseHandle(job)
        raise OSError("无法创建脚本进程 Job")
    if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        kernel.CloseHandle(job)
        raise OSError("无法将脚本加入进程 Job")
    return kernel, job


def _terminate_tree(process, job=None):
    """回收整个脚本进程组，支持已退出父进程留下的子进程。"""
    if os.name == "nt":
        if job is not None:
            kernel, handle = job
            kernel.CloseHandle(handle)
        elif process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _execute(path: Path, args: list[str], stdin: str | None, timeout: float,
             max_output: int, stop: threading.Event, cwd: Path | None = None) -> dict:
    """在线程中运行 Popen，持续排空两路管道并限制合并输出。"""
    started = time.perf_counter()
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG"}}
    environment.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen([sys.executable, "-u", str(path), *args], cwd=cwd or path.parent,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=environment, shell=False, start_new_session=os.name != "nt",
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    job = None
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    guard = threading.Lock()
    overflow = threading.Event()

    def consume(stream, name):
        """持续读取一条管道；只保留合并上限内的数据。"""
        try:
            while data := stream.read(4096):
                with guard:
                    available = max_output - sum(map(len, chunks.values()))
                    chunks[name].extend(data[:max(0, available)])
                    if len(data) > available:
                        overflow.set()
        finally:
            stream.close()

    def feed():
        """独立写入 stdin，避免脚本不读输入时阻塞超时监督。"""
        try:
            if stdin is not None:
                process.stdin.write(stdin.encode("utf-8"))
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

    readers = [threading.Thread(target=consume, args=(getattr(process, name), name), daemon=True)
               for name in chunks]
    status = "completed"
    try:
        job = _windows_job(process)
        for reader in readers:
            reader.start()
        threading.Thread(target=feed, daemon=True).start()
        while process.poll() is None:
            if stop.is_set():
                status = "cancelled"
                break
            if overflow.is_set():
                status = "output_limit"
                break
            if time.perf_counter() - started >= timeout:
                status = "timed_out"
                break
            time.sleep(0.02)
    finally:
        # 正常退出同样清理脚本派生的后台子进程。
        _terminate_tree(process, job)
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=2)
    if overflow.is_set() and status == "completed":
        status = "output_limit"
    if process.returncode and status == "completed":
        status = "failed"
    return {"status": status, "exit_code": process.returncode,
            "stdout": chunks["stdout"].decode("utf-8", errors="replace"),
            "stderr": chunks["stderr"].decode("utf-8", errors="replace"),
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "timed_out": status == "timed_out", "cancelled": status == "cancelled"}


async def run_python(path: Path, args: list[str], stdin: str | None, *, timeout=60, max_output=256 * 1024, cwd=None) -> dict:
    """异步等待受控线程；请求取消后等待进程树确实回收。"""
    stop = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(_execute, path, args, stdin, timeout, max_output, stop, cwd))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        stop.set()
        await asyncio.shield(task)
        raise
