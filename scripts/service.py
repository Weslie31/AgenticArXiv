#!/usr/bin/env python3
"""跨平台启动/停止/查看服务。

    python scripts/service.py start [--backend-port 8000] [--frontend-port 5173]
    python scripts/service.py stop
    python scripts/service.py status
    python scripts/service.py logs [-n 100] [--follow]

Linux/macOS 用进程组管理，Windows 用 taskkill /T，行为一致。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "AgenticArxiv"
FRONTEND = ROOT / "AgenticArxivWeb"
RUN = ROOT / ".run"
LOG_BACKEND = RUN / "backend.log"
LOG_FRONTEND = RUN / "frontend.log"


def venv_dir() -> Path:
    """venv 位置：.venv_path 标记 > AGENTIC_VENV > <项目>/.venv。"""
    marker = ROOT / ".venv_path"
    if marker.exists():
        try:
            p = Path(marker.read_text(encoding="utf-8").strip())
            if p.exists():
                return p
        except Exception:
            pass
    env = os.environ.get("AGENTIC_VENV")
    return Path(env).expanduser() if env else ROOT / ".venv"


def venv_python() -> Path:
    d = venv_dir()
    if os.name == "nt":
        return d / "Scripts" / "python.exe"
    return d / "bin" / "python"


def say(msg: str, end: str = "\n") -> None:
    try:
        print(msg, end=end, flush=True)
    except UnicodeEncodeError:
        print(
            msg.encode("utf-8", "replace").decode("ascii", "replace"),
            end=end,
            flush=True,
        )


def pid_file(name: str) -> Path:
    return RUN / f"{name}.json"


def read_pid(name: str) -> dict | None:
    f = pid_file(name)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_pid(name: str, pid: int, port: int) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    pid_file(name).write_text(
        json.dumps({"pid": pid, "port": port, "started": time.time()}), encoding="utf-8"
    )


def clear_pid(name: str) -> None:
    try:
        pid_file(name).unlink()
    except FileNotFoundError:
        pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((probe_host, port)) == 0


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def popen_kwargs(log_path: Path) -> dict:
    RUN.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")
    kwargs: dict = {"stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


def start_backend(host: str, port: int, reload: bool) -> None:
    info = read_pid("backend")
    if info and pid_alive(int(info["pid"])):
        say(f"[skip] backend 已在运行 (pid={info['pid']})")
        return
    clear_pid("backend")
    py = venv_python()
    if not py.exists():
        raise SystemExit(
            f"未找到虚拟环境解释器：{py}\n"
            "请先运行：python scripts/bootstrap.py\n"
            "（U 盘/受限目录请用：python scripts/bootstrap.py --venv C:\\\\venvs\\\\agentic_arxiv）"
        )
    if port_in_use(host, port):
        raise SystemExit(f"端口 {port} 已被占用，无法启动后端")
    cmd = [
        str(py), "-m", "uvicorn", "api.app:app",
        "--host", host, "--port", str(port),
        "--timeout-graceful-shutdown", "5",
    ]
    if reload:
        cmd.append("--reload")
    # 未 activate venv 时 PATH 里没有 .venv/bin（Windows 是 Scripts），
    # 会导致 pdf2zh 等命令行工具找不到。这里显式补上。
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(py.parent), env.get("PATH", "")])
    proc = subprocess.Popen(
        cmd, cwd=str(BACKEND), env=env, **popen_kwargs(LOG_BACKEND)
    )
    write_pid("backend", proc.pid, port)
    say(f"[ok] backend 启动中 (pid={proc.pid}, http://{host}:{port})")


def start_frontend(host: str, port: int, backend_port: int) -> None:
    info = read_pid("frontend")
    if info and pid_alive(int(info["pid"])):
        say(f"[skip] frontend 已在运行 (pid={info['pid']})")
        return
    clear_pid("frontend")
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("未找到 npm，请先安装 Node.js 18+")
    if port_in_use(host, port):
        raise SystemExit(f"端口 {port} 已被占用，无法启动前端")
    env = os.environ.copy()
    if backend_port != 8000:
        env["VITE_API_BASE"] = f"http://127.0.0.1:{backend_port}/api"
    if os.name == "nt":
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", npm, "run", "dev", "--",
               "--host", host, "--port", str(port)]
    else:
        cmd = [npm, "run", "dev", "--", "--host", host, "--port", str(port)]
    proc = subprocess.Popen(
        cmd, cwd=str(FRONTEND), env=env, **popen_kwargs(LOG_FRONTEND)
    )
    write_pid("frontend", proc.pid, port)
    say(f"[ok] frontend 启动中 (pid={proc.pid}, http://{host}:{port})")


def stop_one(name: str, label: str) -> None:
    info = read_pid(name)
    if not info:
        # 兼容旧版 bin/start.sh 产生的 pgid 文件
        legacy = RUN / f"{name}.pgid"
        if legacy.exists():
            raw = legacy.read_text(encoding="utf-8").strip()
            if raw.isdigit() and os.name != "nt":
                pgid = int(raw)
                say(f"[..] 停止 {label}（旧版 pgid={pgid}）")
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                legacy.unlink(missing_ok=True)
                return
        say(f"[skip] {label}: 没有 pid 文件")
        return
    pid = int(info.get("pid", 0))
    if not pid_alive(pid):
        say(f"[skip] {label}: 进程已不存在 (pid={pid})")
        clear_pid(name)
        return
    say(f"[..] 停止 {label} (pid={pid})")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(20):
            if not pid_alive(pid):
                break
            time.sleep(0.3)
        if pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
    for _ in range(20):
        if not pid_alive(pid):
            break
        time.sleep(0.3)
    clear_pid(name)
    say(f"[ok] {label} 已停止")


def cmd_start(args: argparse.Namespace) -> int:
    backend_port = args.backend_port
    frontend_port = args.frontend_port
    if not args.frontend_only:
        start_backend(args.host, backend_port, reload=not args.no_reload)
    if not args.backend_only:
        start_frontend(args.host, frontend_port, backend_port)

    deadline = time.time() + 30
    ok = True
    while time.time() < deadline:
        b = args.frontend_only or http_ok(f"http://127.0.0.1:{backend_port}/api/health")
        f = args.backend_only or http_ok(f"http://127.0.0.1:{frontend_port}/")
        if b and f:
            break
        time.sleep(0.5)
    if not args.frontend_only and not http_ok(f"http://127.0.0.1:{backend_port}/api/health"):
        say(f"[warn] 后端 30s 内未就绪，请查看 {LOG_BACKEND}")
        ok = False
    if not args.backend_only and not http_ok(f"http://127.0.0.1:{frontend_port}/"):
        say(f"[warn] 前端 30s 内未就绪，请查看 {LOG_FRONTEND}")
        ok = False
    if ok:
        say("")
        say(f"后端: http://127.0.0.1:{backend_port}/docs")
        say(f"前端: http://127.0.0.1:{frontend_port}/")
    return 0 if ok else 1


def cmd_stop(_: argparse.Namespace) -> int:
    stop_one("backend", "backend")
    stop_one("frontend", "frontend")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    rows = [
        ("backend", f"http://127.0.0.1:{args.backend_port}/api/health"),
        ("frontend", f"http://127.0.0.1:{args.frontend_port}/"),
    ]
    healthy = True
    for name, url in rows:
        info = read_pid(name)
        if not info:
            say(f"{name:9s} 未启动（无 pid 文件）")
            healthy = False
            continue
        pid = int(info["pid"])
        alive = pid_alive(pid)
        ok = alive and http_ok(url)
        say(
            f"{name:9s} pid={pid} alive={alive} http={'ok' if ok else 'fail'} "
            f"port={info.get('port')}"
        )
        healthy = healthy and ok
    return 0 if healthy else 1


def _tail(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block = min(size, max(4096, n * 200))
        f.seek(size - block)
        data = f.read().decode("utf-8", "replace")
    return data.splitlines()[-n:]


def cmd_logs(args: argparse.Namespace) -> int:
    for label, path in (("backend", LOG_BACKEND), ("frontend", LOG_FRONTEND)):
        say(f"===== {label} ({path}) =====")
        for line in _tail(path, args.lines):
            say(line)
    if args.follow:
        say("(Ctrl+C 退出)")
        positions = {p: p.stat().st_size if p.exists() else 0 for p in (LOG_BACKEND, LOG_FRONTEND)}
        try:
            while True:
                time.sleep(1)
                for label, path in (("backend", LOG_BACKEND), ("frontend", LOG_FRONTEND)):
                    if not path.exists():
                        continue
                    size = path.stat().st_size
                    if size > positions[path]:
                        with open(path, "rb") as f:
                            f.seek(positions[path])
                            say(f.read().decode("utf-8", "replace"), end="")
                        positions[path] = size
        except KeyboardInterrupt:
            return 0
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="AgenticArXiv 跨平台服务管理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="启动后端与前端")
    p_start.add_argument("--host", default="0.0.0.0")
    p_start.add_argument("--backend-port", type=int, default=8000)
    p_start.add_argument("--frontend-port", type=int, default=5173)
    p_start.add_argument("--no-reload", action="store_true")
    p_start.add_argument("--backend-only", action="store_true")
    p_start.add_argument("--frontend-only", action="store_true")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="停止服务")
    p_stop.set_defaults(func=cmd_stop)

    p_status = sub.add_parser("status", help="查看状态")
    p_status.add_argument("--backend-port", type=int, default=8000)
    p_status.add_argument("--frontend-port", type=int, default=5173)
    p_status.set_defaults(func=cmd_status)

    p_logs = sub.add_parser("logs", help="查看日志")
    p_logs.add_argument("-n", "--lines", type=int, default=80)
    p_logs.add_argument("--follow", action="store_true")
    p_logs.set_defaults(func=cmd_logs)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
