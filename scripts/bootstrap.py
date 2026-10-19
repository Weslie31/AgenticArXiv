#!/usr/bin/env python3
"""跨平台环境引导：创建 venv、安装 Python 与前端依赖。

用法：
    python scripts/bootstrap.py              # 用 requirements.txt
    python scripts/bootstrap.py --locked     # 用 requirements.lock.txt（可复现）
    python scripts/bootstrap.py --dry-run    # 只检查环境，不安装

Windows 会使用 .venv\\Scripts\\python.exe，Linux/macOS 使用 .venv/bin/python，
不需要手动区分。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "AgenticArxiv"
FRONTEND = ROOT / "AgenticArxivWeb"
DEFAULT_VENV = ROOT / ".venv"
VENV_MARKER = ROOT / ".venv_path"


def _say(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", "replace").decode("ascii", "replace"), flush=True)


def venv_python(venv_dir: Path = DEFAULT_VENV) -> Path:
    """返回虚拟环境里的解释器路径（自动适配 Windows / POSIX）。"""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run(cmd: list[str], cwd: Path | None = None, dry: bool = False) -> None:
    printable = " ".join(str(c) for c in cmd)
    _say(f"  $ {printable}")
    if dry:
        return
    subprocess.check_call([str(c) for c in cmd], cwd=str(cwd) if cwd else None)


def check_python() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit(
            f"需要 Python 3.10+，当前是 {sys.version.split()[0]}。"
            "请安装更新的 Python 后重新运行。"
        )
    _say(f"[ok] Python {sys.version.split()[0]} ({sys.executable})")


def check_node() -> str:
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not node or not npm:
        raise SystemExit("未找到 Node.js/npm，请安装 Node.js 22+ 后重试。")
    try:
        node_ver = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    except Exception:
        node_ver = "0.0.0"
    _say(f"[ok] Node {node_ver} / npm {npm}")
    try:
        parts = tuple(int(x) for x in node_ver.split(".")[:3])
    except ValueError:
        parts = (0, 0, 0)
    if parts < (22, 13, 0):
        _say(
            f"[warn] Node {node_ver} 低于 pdfjs-dist 要求的 22.13+。"
            "安装仍会继续，但 PDF 预览可能有兼容问题；"
            "建议升级到 Node 22 LTS 后重新运行 npm install。"
        )
    return npm


def ensure_venv(venv_dir: Path, dry: bool) -> Path:
    py = venv_python(venv_dir)
    if py.exists():
        _say(f"[ok] venv 已存在：{py}")
        return py
    _say(f"[..] 创建 venv：{venv_dir}")
    if not dry:
        try:
            venv.EnvBuilder(with_pip=True).create(venv_dir)
        except (OSError, subprocess.SubprocessError) as e:
            raise SystemExit(
                f"创建 venv 失败：{e}\n"
                "如果项目位于 U 盘/受限制的目录，Windows 会拒绝在其中创建并执行 python.exe。\n"
                "请把虚拟环境放到本机磁盘，例如：\n"
                r"  python scripts/bootstrap.py --venv C:\venvs\agentic_arxiv"
            )
        if not py.exists():
            raise SystemExit(f"venv 创建后找不到解释器：{py}")
    return py


def install_python(py: Path, locked: bool, dry: bool) -> None:
    req = BACKEND / ("requirements.lock.txt" if locked else "requirements.txt")
    if not req.exists():
        raise SystemExit(f"找不到依赖文件：{req}")
    _say(f"[..] 安装 Python 依赖：{req.name}")
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"], dry=dry)
    target = _filtered_lock(req) if locked else req
    run([str(py), "-m", "pip", "install", "-r", str(target)], dry=dry)
    patch_pdf2zh(py, dry=dry)


# 锁文件是在 Python 3.13 上导出的：其中少数包只适用于特定 Python 版本，
# 在其它版本上会让 pip 直接解析失败。
PY313_ONLY = {"audioop-lts", "standard-aifc", "standard-sunau"}
PY311_PLUS_SKIP = {"tomli", "exceptiongroup"}


def _filtered_lock(path: Path) -> Path:
    ver = sys.version_info[:2]
    kept: list[str] = []
    dropped: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split("==", 1)[0].strip().lower()
        if ver < (3, 13) and name in PY313_ONLY:
            dropped.append(name)
            continue
        if ver >= (3, 11) and name in PY311_PLUS_SKIP:
            dropped.append(name)
            continue
        kept.append(line)
    if dropped:
        _say(f"[warn] 当前 Python {ver[0]}.{ver[1]}，跳过仅适用于其它版本的包：{', '.join(sorted(set(dropped)))}")
    out = Path(tempfile.gettempdir()) / f"agentic_requirements_{ver[0]}{ver[1]}.txt"
    out.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return out


def patch_pdf2zh(py: Path, dry: bool = False) -> None:
    """pdf2zh 1.7.9 使用 np.fromstring，NumPy 2 已移除；改成 frombuffer。"""
    if dry:
        return
    try:
        pkg = subprocess.check_output(
            [str(py), "-c", "import pathlib,pdf2zh;print(pathlib.Path(pdf2zh.__file__).parent)"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return
    root = Path(pkg)
    if not root.exists():
        return
    patched = []
    for f in root.rglob("*.py"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if "np.fromstring(" in text:
            f.write_text(text.replace("np.fromstring(", "np.frombuffer("), encoding="utf-8")
            patched.append(f.name)
    if patched:
        _say(f"[ok] 已修补 pdf2zh 的 NumPy 2 兼容性：{', '.join(sorted(set(patched)))}")


def install_frontend(npm: str, dry: bool) -> None:
    _say("[..] 安装前端依赖 (npm install)")
    run([npm, "install"], cwd=FRONTEND, dry=dry)


def main() -> int:
    ap = argparse.ArgumentParser(description="创建/更新项目运行环境")
    ap.add_argument("--locked", action="store_true", help="使用 requirements.lock.txt 精确版本")
    ap.add_argument("--skip-python", action="store_true", help="跳过 Python 依赖")
    ap.add_argument("--skip-frontend", action="store_true", help="跳过 npm install")
    ap.add_argument("--dry-run", action="store_true", help="只检查并打印计划，不实际安装")
    ap.add_argument(
        "--venv",
        default=os.environ.get("AGENTIC_VENV") or "",
        help="虚拟环境目录（默认 <项目>/.venv；U 盘/受限目录建议放本机磁盘）",
    )
    args = ap.parse_args()

    _say("== AgenticArXiv bootstrap ==")
    _say(f"项目目录：{ROOT}")
    check_python()

    venv_dir = Path(args.venv).expanduser().resolve() if args.venv else DEFAULT_VENV
    if venv_dir != DEFAULT_VENV:
        _say(f"虚拟环境目录：{venv_dir}")
        if not args.dry_run:
            VENV_MARKER.write_text(str(venv_dir) + "\n", encoding="utf-8")

    npm = None
    if not args.skip_frontend:
        npm = check_node()

    if not args.skip_python:
        py = ensure_venv(venv_dir, args.dry_run)
        install_python(py, args.locked, args.dry_run)

    if npm and not args.skip_frontend:
        install_frontend(npm, args.dry_run)

    _say("")
    _say("完成。下一步：")
    _say("  python scripts/service.py start     # 同时启动后端与前端")
    _say("  python scripts/service.py status    # 查看运行状态")
    _say("  python scripts/service.py stop      # 停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
