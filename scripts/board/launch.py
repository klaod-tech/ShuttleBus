"""Start (or stop) the board in the background and open the browser.

python launch.py              start if needed, open the browser
python launch.py --no-browser start if needed (for AI sessions)
python launch.py --stop       stop the running board of this project
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from server import CONFIG, IDENTITY, ROOT  # noqa: E402

URL = f"http://127.0.0.1:{CONFIG['port']}"
LOG = Path(tempfile.gettempdir()) / f"project-board-{CONFIG['port']}.log"


def health():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def ours(state):
    return bool(state) and state.get("app") == IDENTITY and Path(state.get("root", "")).resolve() == ROOT


def ensure_server():
    """Return True when this project's board answers on the configured port."""
    state = health()
    if not state:
        with LOG.open("a", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(HERE / "server.py")], cwd=HERE,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                       start_new_session=os.name != "nt")
        for _ in range(60):
            state = health()
            if state or process.poll() is not None:
                break
            time.sleep(0.15)
    return ours(state)


def stop():
    state = health()
    if not state:
        print("실행 중인 관리판이 없습니다.")
        return 0
    if not ours(state):
        print(f"포트 {CONFIG['port']}번은 다른 프로젝트의 관리판이 쓰고 있습니다. 그 프로젝트에서 --stop 하세요.")
        return 1
    request = urllib.request.Request(URL + "/api/shutdown", method="POST", data=b"{}",
                                     headers={"Content-Type": "application/json", "Origin": URL})
    try:
        urllib.request.urlopen(request, timeout=5).read()
    except urllib.error.URLError:
        pass
    print("관리판을 종료했습니다.")
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if args.stop:
        return stop()
    if not ensure_server():
        print(f"포트 {CONFIG['port']}번을 쓸 수 없거나 다른 프로젝트의 관리판이 쓰고 있습니다. "
              f"config.json의 port를 바꾸거나 로그를 확인하세요: {LOG}")
        return 1
    print(f"{CONFIG['projectName']} 관리판: {URL}")
    if not args.no_browser:
        webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
