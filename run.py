"""
A股交易系统 — 一键启动
用法: python run.py
      Ctrl+C 停止所有服务
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path

# Windows GBK 环境下 print 含 emoji/中文会 UnicodeEncodeError，统一转 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

processes: list[subprocess.Popen] = []


def find_python() -> str:
    """优先使用 ts conda 环境的 Python"""
    # 尝试 conda run
    try:
        r = subprocess.run(
            ["conda", "run", "-n", "ts", "python", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return "conda:ts"
    except Exception:
        pass
    return sys.executable


def start_backend() -> subprocess.Popen:
    print("[backend] 启动 FastAPI 服务 (port 8000) …")
    # 输出重定向到日志文件，避免 PIPE 缓冲区填满后阻塞子进程
    log_file = open(BACKEND_DIR / "backend.log", "w", encoding="utf-8", errors="replace")
    if find_python() == "conda:ts":
        proc = subprocess.Popen(
            ["conda", "run", "-n", "ts", "python", "-m", "uvicorn",
             "main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(BACKEND_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    else:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn",
             "main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(BACKEND_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    return proc


def start_frontend() -> subprocess.Popen:
    print("[frontend] 启动 Vite 开发服务器 (port 5173) …")
    log_file = open(FRONTEND_DIR / "frontend.log", "w", encoding="utf-8", errors="replace")
    if find_python() == "conda:ts":
        proc = subprocess.Popen(
            ["conda", "run", "-n", "ts", "npx", "vite",
             "--host", "127.0.0.1", "--port", "5173"],
            cwd=str(FRONTEND_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    else:
        proc = subprocess.Popen(
            ["npx", "vite", "--host", "127.0.0.1", "--port", "5173"],
            cwd=str(FRONTEND_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    return proc


def stop_all():
    print("\n[shutdown] 正在停止所有服务…")
    for proc in processes:
        try:
            proc.terminate()
        except Exception:
            pass
    time.sleep(1)
    for proc in processes:
        try:
            proc.kill()
        except Exception:
            pass
    print("[shutdown] 已停止")


def signal_handler(signum, frame):
    stop_all()
    sys.exit(0)


def main():
    print("=" * 60)
    print("  A股交易系统 启动中…")
    print("=" * 60)
    print(f"  后端:  http://127.0.0.1:8000")
    print(f"  API文档: http://127.0.0.1:8000/docs")
    print(f"  前端:  http://127.0.0.1:5173")
    print("=" * 60)
    print()

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动后端
    try:
        backend = start_backend()
        processes.append(backend)
    except Exception as e:
        print(f"[backend] 启动失败: {e}")
        stop_all()
        sys.exit(1)

    # 等后端先就绪
    time.sleep(2)

    # 启动前端
    try:
        frontend = start_frontend()
        processes.append(frontend)
    except Exception as e:
        print(f"[frontend] 启动失败: {e}")
        stop_all()
        sys.exit(1)

    print()
    print("[ready] ✅ 全部启动完成，浏览器访问 http://127.0.0.1:5173")
    print("[ready] 按 Ctrl+C 停止所有服务")
    print()

    # 监控并打印输出
    try:
        while True:
            for proc in processes:
                if proc.poll() is not None:
                    print(f"[error] 进程 {proc.args[0] if proc.args else '?'} 意外退出 (code={proc.returncode})")
                    stop_all()
                    sys.exit(1)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()


if __name__ == "__main__":
    main()
