"""
Local Production Server Launcher
區域產業 × 高教人才供需錯配預警系統 (System Spec v1.0)
Runs on http://127.0.0.1:8888
"""
import uvicorn
import socket
import os
import sys
from pathlib import Path


def load_local_env():
    """Load simple KEY=VALUE settings from a private local .env file."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def find_available_port(preferred_port=8888):
    for port in [preferred_port, 8088, 8008, 9000]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred_port

if __name__ == "__main__":
    load_local_env()
    port = find_available_port(8888)
    print("="*65)
    print("🚀 啟動本機端服務：區域產業 × 高教人才供需錯配預警系統 (v1.0)")
    print(f"👉 請開啟瀏覽器訪問: http://127.0.0.1:{port}")
    print(f"📖 API 交互文件: http://127.0.0.1:{port}/docs")
    print("="*65)
    uvicorn.run("api.main:app", host="127.0.0.1", port=port, log_level="info")
