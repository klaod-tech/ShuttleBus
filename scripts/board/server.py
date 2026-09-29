"""Local project board: document library + numbered work cards (Python stdlib only).

Runs on 127.0.0.1 only. Settings live in config.json, project stages in stages.json,
cards in workspace.json. Nothing here needs network access or third-party packages.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
IDENTITY = "project-board-v1"
STATUSES = ("blocked", "planned", "in_progress", "review", "completed")
LOCK = Lock()
SKIP = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build", "__pycache__",
        "outputs", "artifacts", "checkpoints", "target", "coverage"}
MAX_DOCS = 5000
MAX_DOC_BYTES = 2_000_000
DEFAULT_CONFIG = {
    "projectName": "내 프로젝트",
    "tagline": "",
    "taskPrefix": "T",
    "port": 8774,
    "root": "auto",
    "categories": ["기획", "개발", "문서", "운영"],
    "categoryRules": [],
    "createDocDir": "docs/work",
    "quickDocs": [],
    "excludeDirs": [],
    "aiNames": [],
    "rulesFile": "AGENTS.md",
    "requireSourceForActive": True,
    # 카드 상태를 저장소에 문서로 남길 경로 (예: "md/board-status.md"). 비우면 만들지 않는다.
    # 관리판은 로컬 전용이라, GitHub만 보는 사람에게 상태를 보이려면 커밋되는 문서가 필요하다
    "statusDoc": "",
}


# ---------------------------------------------------------------- settings

def load_config(path=None):
    """Read config.json, fill defaults and reject values that would break the board."""
    path = Path(path) if path else HERE / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError("config.json은 객체여야 합니다.")
    config = dict(DEFAULT_CONFIG)
    config.update({k: v for k, v in raw.items() if not k.startswith("_")})
    if not isinstance(config["projectName"], str) or not config["projectName"].strip():
        raise ValueError("config.json projectName이 비어 있습니다.")
    if not isinstance(config["taskPrefix"], str) or not re.fullmatch(r"[A-Z][A-Z0-9]{0,7}", config["taskPrefix"]):
        raise ValueError("config.json taskPrefix는 영문 대문자로 시작하는 1~8자입니다 (예: T, SB, APP).")
    if type(config["port"]) is not int or not 1024 <= config["port"] <= 65535:
        raise ValueError("config.json port는 1024~65535 정수입니다.")
    cats = config["categories"]
    if not isinstance(cats, list) or not cats or any(not isinstance(c, str) or not c.strip() or "," in c for c in cats) or len(set(cats)) != len(cats):
        raise ValueError("config.json categories는 쉼표 없는 서로 다른 이름의 목록입니다.")
    for rule in config["categoryRules"]:
        if not isinstance(rule, dict) or rule.get("category") not in cats:
            raise ValueError("config.json categoryRules의 category는 categories 중 하나여야 합니다.")
    for key in ("quickDocs", "excludeDirs", "aiNames", "categoryRules"):
        if not isinstance(config[key], list):
            raise ValueError(f"config.json {key}는 목록입니다.")
    if not isinstance(config["createDocDir"], str) or ".." in Path(config["createDocDir"]).parts:
        raise ValueError("config.json createDocDir는 저장소 안의 상대 경로입니다.")
    status_doc = config["statusDoc"]
    if not isinstance(status_doc, str) or (status_doc and (".." in Path(status_doc).parts or not status_doc.endswith(".md"))):
        raise ValueError("config.json statusDoc은 저장소 안의 .md 상대 경로이거나 빈 값입니다.")
    return config


def find_root(config, board_dir=HERE):
    """'auto' = nearest folder above the board that has .git; without git, the board's parent."""
    setting = config.get("root", "auto")
    if setting != "auto":
        root = (board_dir / setting).resolve()
        if not root.is_dir():
            raise ValueError("config.json root 폴더가 없습니다: " + str(root))
        return root
    for folder in board_dir.parents:
        if (folder / ".git").exists():
            return folder
    return board_dir.parent


def load_stages(path=None):
    path = Path(path) if path else HERE / "stages.json"
    stages = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else []
    if not isinstance(stages, list) or not stages:
        raise ValueError("stages.json에 단계가 하나 이상 있어야 합니다.")
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict) or not re.fullmatch(r"[a-z0-9_-]{1,40}", str(stage.get("id", ""))) or stage["id"] in seen:
            raise ValueError("stages.json의 id는 영문 소문자·숫자·-_ 이고 서로 달라야 합니다.")
        if not isinstance(stage.get("title"), str) or not stage["title"].strip():
            raise ValueError("stages.json의 각 단계에 title이 필요합니다.")
        seen.add(stage["id"])
        stage.setdefault("goal", "")
        stage.setdefault("exit", "")
        stage.setdefault("docs", [])
        stage["ongoing"] = bool(stage.get("ongoing", False))
    return stages


CONFIG = load_config()
ROOT = find_root(CONFIG)
STAGES = load_stages()
STORE = HERE / "workspace.json"


def number_pattern(prefix=None):
    return re.compile(re.escape(prefix or CONFIG["taskPrefix"]) + r"-\d{4,}")


def board_dir_label():
    try:
        return HERE.relative_to(ROOT).as_posix()
    except ValueError:
        return str(HERE)


# ---------------------------------------------------------------- documents

def _excluded(rel_dir, name):
    if name in SKIP or name.startswith("."):
        return True
    rel = (rel_dir + "/" + name).lstrip("/")
    return any(rel == e.strip("/") or name == e.strip("/") for e in CONFIG["excludeDirs"])


def classify(path, title, declared):
    """Declared '- 분야:' wins; then config categoryRules; otherwise '미분류'."""
    if declared:
        return declared
    found = []
    for rule in CONFIG["categoryRules"]:
        paths = rule.get("paths", [])
        pattern = rule.get("titlePattern", "")
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in paths) or (pattern and re.search(pattern, title, re.I)):
            if rule["category"] not in found:
                found.append(rule["category"])
    return found or ["미분류"]


def parse_doc(path, body):
    title = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    title = title.group(1) if title else path.rsplit("/", 1)[-1]
    declared = re.search(r"^- 분야:\s*(.+?)\s*$", body, re.M)
    declared = [c.strip() for c in declared.group(1).split(",") if c.strip()] if declared else []
    task = re.search(r"^- 작업:\s*(" + number_pattern().pattern + r")\s*$", body, re.M)
    state = re.search(r"^- 상태:\s*(" + "|".join(STATUSES) + r")\s*$", body, re.M)
    return dict(path=path, title=title, groups=classify(path, title, declared), declared=declared,
                task=task.group(1) if task else "", status=state.group(1) if state else None)


def documents(root=None, with_body=False):
    """Every Markdown file under the project root, read fresh each time (no stale index)."""
    root = Path(root or ROOT)
    result = []
    for base, dirs, files in os.walk(root, followlinks=False):
        rel_dir = Path(base).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirs[:] = sorted(d for d in dirs if not _excluded(rel_dir, d) and not (Path(base) / d).is_symlink())
        for name in sorted(files):
            file = Path(base) / name
            if file.suffix.lower() != ".md" or file.is_symlink():
                continue
            if len(result) >= MAX_DOCS:
                return sorted(result, key=lambda d: d["path"])
            path = file.relative_to(root).as_posix()
            stat = file.stat()
            try:
                body = file.read_text(encoding="utf-8-sig") if stat.st_size <= MAX_DOC_BYTES else ""
            except (UnicodeDecodeError, OSError):
                body = ""
            doc = parse_doc(path, body)
            doc.update(modified=stat.st_mtime, size=stat.st_size)
            if with_body:
                doc["body"] = body
            result.append(doc)
    return sorted(result, key=lambda d: d["path"])


def read_document(path, root=None):
    root = Path(root or ROOT)
    if not isinstance(path, str) or not path.endswith(".md") or path not in {d["path"] for d in documents(root)}:
        raise LookupError("문서를 찾을 수 없습니다.")
    return next(d for d in documents(root, with_body=True) if d["path"] == path)


def search_documents(query, root=None, limit=200):
    q = query.casefold().strip()
    if not q:
        return []
    return [d["path"] for d in documents(root, with_body=True)
            if q in (d["title"] + "\n" + d["path"] + "\n" + d["body"]).casefold()][:limit]


# ---------------------------------------------------------------- cards

def _text(item, key, limit, required=True):
    value = item.get(key, None if required else "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("필드 오류: " + key)
    return value


def validate(data, strict_ids=None):
    """Structural check for the whole store. Stage/category membership is checked only for
    cards in strict_ids (new or changed), so editing stages.json never locks old data."""
    if not isinstance(data, dict) or "cards" not in data or set(data) - {"cards", "nextNumber"}:
        raise ValueError("workspace 형식 오류: cards와 nextNumber만 허용합니다.")
    if type(data.get("nextNumber", 1)) is not int or data.get("nextNumber", 1) < 1:
        raise ValueError("다음 작업 번호 오류")
    cards = data["cards"]
    if not isinstance(cards, list) or len(cards) > 5000:
        raise ValueError("카드 수 제한 초과")
    pattern, stage_ids = number_pattern(), {s["id"] for s in STAGES}
    ids, numbers = set(), set()
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("카드 형식 오류")
        for key, limit in (("id", 100), ("title", 160), ("body", 20000), ("source", 300), ("updated", 80)):
            _text(card, key, limit)
        for key, limit in (("result", 20000), ("agent", 160), ("priorityNote", 500), ("evidence", 4000),
                           ("performedBy", 160), ("ref", 100), ("category", 60), ("stage", 60)):
            _text(card, key, limit, required=False)
        if not card["id"] or card["id"] in ids or not card["title"].strip():
            raise ValueError("제목 또는 식별자 오류")
        ids.add(card["id"])
        number = card.get("number")
        if number is not None:
            if not isinstance(number, str) or not pattern.fullmatch(number) or number in numbers:
                raise ValueError("작업 번호 중복 또는 형식 오류: " + str(number))
            numbers.add(number)
        if card.get("status") not in STATUSES:
            raise ValueError("상태 오류")
        if type(card.get("priority", 0)) is not int or card.get("priority", 0) not in range(4):
            raise ValueError("별 중요도는 0~3입니다.")
        if type(card.get("size", 1)) is not int or card.get("size", 1) not in (1, 2, 3):
            raise ValueError("작업 규모는 1~3입니다.")
        if type(card.get("order", 0)) is not int or card.get("order", 0) < 0:
            raise ValueError("배치 순서는 0 이상 정수입니다.")
        if not isinstance(card.get("plan", False), bool):
            raise ValueError("plan 표시 형식 오류")
        deps = card.get("dependsOn", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) or not pattern.fullmatch(d) for d in deps) or len(deps) != len(set(deps)):
            raise ValueError("선행 작업 형식 오류")
        log = card.get("log", [])
        if not isinstance(log, list) or len(log) > 1000:
            raise ValueError("작업 기록 형식 오류")
        for entry in log:
            if not isinstance(entry, dict) or entry.get("kind") not in ("user", "ai"):
                raise ValueError("기록 작성자 구분 오류")
            for key, limit in (("at", 80), ("by", 160), ("text", 4000)):
                _text(entry, key, limit)
        if strict_ids is not None and card["id"] in strict_ids:
            if card.get("stage") not in stage_ids:
                raise ValueError("프로젝트 단계를 선택하세요 (stages.json).")
            if card.get("category") not in CONFIG["categories"]:
                raise ValueError("분야는 config.json categories 중 하나입니다.")
    graph = {c["number"]: c.get("dependsOn", []) for c in cards if c.get("number")}
    visiting, visited = set(), set()

    def visit(number):
        if number in visiting:
            raise ValueError("선행 작업에 순환 관계가 있습니다: " + number)
        if number in visited:
            return
        if number not in graph:
            raise ValueError("존재하지 않는 선행 작업: " + number)
        visiting.add(number)
        for dependency in graph[number]:
            visit(dependency)
        visiting.remove(number)
        visited.add(number)

    for number in graph:
        visit(number)


def read_store():
    raw = STORE.read_bytes() if STORE.exists() else b'{"cards":[],"nextNumber":1}'
    data = json.loads(raw)
    validate(data)
    return data, hashlib.sha256(raw).hexdigest()


TRACKED = ("title", "body", "status", "source", "category", "stage", "result", "priority", "size", "order",
           "dependsOn", "priorityNote", "evidence", "performedBy", "ref")


def prepare_cards(data, previous, actor="user", by="사용자", message=""):
    """Runs under the write lock: issue numbers (never recycled), keep history append-only,
    require evidence when a card becomes completed."""
    prefix = CONFIG["taskPrefix"]
    old = {c["id"]: c for c in previous["cards"]}
    reserved = {c["number"] for c in previous["cards"] if c.get("number")}
    start = len(prefix) + 1
    next_number = max(previous.get("nextNumber", 1), data.get("nextNumber", 1),
                      max((int(n[start:]) + 1 for n in reserved), default=1))
    stamp = datetime.now(timezone.utc).isoformat()
    changed_ids = set()
    for card in data["cards"]:
        before = old.get(card["id"])
        if before and before.get("number"):
            if card.get("number", before["number"]) != before["number"]:
                raise ValueError("기존 작업 번호는 바꿀 수 없습니다.")
            card["number"] = before["number"]
        else:
            requested = card.get("number")
            if requested and (requested in reserved or int(requested[start:]) < previous.get("nextNumber", 1)):
                raise ValueError("요청한 작업 번호가 이미 쓰였거나 예전에 쓴 번호입니다. 번호를 비워 두면 새로 발급합니다.")
            if not requested:
                while f"{prefix}-{next_number:04d}" in reserved:
                    next_number += 1
                card["number"] = f"{prefix}-{next_number:04d}"
            reserved.add(card["number"])
            next_number = max(next_number, int(card["number"][start:]) + 1)
        defaults = dict(priority=0, size=1, order=int(card["number"][start:]) * 10, dependsOn=[], priorityNote="",
                        evidence="", performedBy="", ref="", result="", agent="")
        for key, default in defaults.items():
            card.setdefault(key, default)
        if card["status"] == "completed" and (not before or before["status"] != "completed") and not card["evidence"].strip():
            raise ValueError("완료하려면 무엇을 했고 어떻게 확인했는지 '완료 근거'를 남기세요.")
        card["log"] = list(before.get("log", [])) if before else []
        # Compare with the same defaults on both sides so filling a default never counts as an edit.
        changed = not before or any(card.get(k) != before.get(k, defaults.get(k)) for k in TRACKED)
        # A message belongs only to the card the writer touched (its 'updated' moved).
        touched = not before or card.get("updated") != before.get("updated")
        if changed:
            changed_ids.add(card["id"])
        if changed or (message and touched):
            card["log"].append(dict(at=stamp, by=by, kind=actor,
                                    text=message or ("작업 등록" if not before else "작업 내용·상태 수정")))
            card["updated"] = stamp
        elif before:
            card["updated"] = before["updated"]
    data["nextNumber"] = next_number
    validate(data, strict_ids=changed_ids)
    return data


def validate_ai(by):
    if not isinstance(by, str) or not by.strip() or len(by) > 80:
        raise ValueError("AI 이름(--by)을 1~80자로 적으세요. 예: 이름_CL, 이름_GPT")
    names = CONFIG["aiNames"]
    if names and by not in names:
        raise ValueError("config.json aiNames에 등록된 이름만 쓸 수 있습니다: " + ", ".join(names))


def save_store(data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp = STORE.with_suffix(".tmp")
    temp.write_bytes(raw)
    os.replace(temp, STORE)
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- status document

STATUS_LABELS = {"completed": "완료", "review": "검수", "in_progress": "진행 중", "planned": "할 일", "blocked": "결정·확인 필요"}


def _cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def render_status(data):
    """카드 상태를 사람이 GitHub에서 읽을 문서로 만든다. 시각을 넣지 않아 같은 카드면 같은 글이 된다."""
    cards = [c for c in data["cards"] if c.get("number")]
    lines = [
        "# 작업 상태 — 관리판 자동 생성",
        "",
        "- 분야: 문서·연구",
        "",
        "> **이 파일은 자동으로 만들어진다. 직접 고치지 않는다.** 상태의 주인은 작업 관리판 카드다",
        "> (`scripts/board/workspace.json`). 카드가 바뀌면 관리판 저장 때 다시 쓰이고, 손으로 다시 만들려면",
        "> `python scripts/board/work.py export`. `work.py check`가 이 파일이 최신인지 검사한다.",
        ">",
        "> md 표의 `카드` 열(`SB-0000`)이 가리키는 상태를 여기서 찾는다.",
        "",
    ]
    counts = {key: sum(1 for c in cards if c["status"] == key) for key in STATUS_LABELS}
    lines += ["| 상태 | 카드 |", "|---|---|"]
    lines += [f"| {label} | {counts[key]} |" for key, label in STATUS_LABELS.items()]
    lines += [f"| 합계 | {len(cards)} |", ""]
    order = {key: i for i, key in enumerate(STATUS_LABELS)}
    for stage in STAGES:
        rows = [c for c in cards if c.get("stage") == stage["id"]]
        if not rows:
            continue
        done = sum(1 for c in rows if c["status"] == "completed")
        lines += [f"## {stage.get('title', stage['id'])} — 완료 {done}/{len(rows)}", ""]
        lines += ["| 카드 | 상태 | 제목 | 분야 | 원래 항목 |", "|---|---|---|---|---|"]
        for c in sorted(rows, key=lambda c: (order.get(c["status"], 9), c["number"])):
            lines.append(f"| {c['number']} | {STATUS_LABELS.get(c['status'], c['status'])} | {_cell(c['title'])} | "
                         f"{_cell(c.get('category'))} | {_cell(c.get('ref'))} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def status_path():
    return (ROOT / CONFIG["statusDoc"]) if CONFIG.get("statusDoc") else None


def write_status(data):
    """statusDoc이 설정돼 있으면 카드 상태 문서를 다시 쓴다. 내용이 같으면 파일을 건드리지 않는다."""
    path = status_path()
    if path is None:
        return False
    text = render_status(data)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)
    return True


def git_commit(ref):
    """Look up one commit by hash prefix. Returns None when the project has no git."""
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", ref or ""):
        raise ValueError("커밋 해시는 7자 이상 16진수입니다.")
    try:
        out = subprocess.run(["git", "--no-optional-locks", "log", "-1", "--format=%H%x1f%an%x1f%s", ref + "^{commit}", "--"],
                             cwd=ROOT, capture_output=True, timeout=10, check=True).stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return None
    fields = out.split("\x1f")
    return dict(hash=fields[0], author=fields[1], subject=fields[2]) if len(fields) == 3 else None


# ---------------------------------------------------------------- HTTP

ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
    "/fonts/PretendardVariable.woff2": ("fonts/PretendardVariable.woff2", "font/woff2"),
    "/fonts/LICENSE.txt": ("fonts/LICENSE.txt", "text/plain"),
}


def public_config():
    return dict(projectName=CONFIG["projectName"], tagline=CONFIG["tagline"], taskPrefix=CONFIG["taskPrefix"],
                categories=CONFIG["categories"], quickDocs=CONFIG["quickDocs"], rulesFile=CONFIG["rulesFile"],
                boardDir=board_dir_label(), statuses=list(STATUSES))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the background log small
        pass

    def send(self, status, value, mime="application/json; charset=utf-8"):
        raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def allowed(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def same_origin(self):
        return self.allowed() and self.headers.get("Origin") == "http://" + self.headers.get("Host", "")

    def do_GET(self):
        if not self.allowed():
            return self.send(403, {"error": "로컬 주소(127.0.0.1)로 접속하세요."})
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        try:
            if url.path == "/api/health":
                return self.send(200, {"app": IDENTITY, "root": str(ROOT), "projectName": CONFIG["projectName"]})
            if url.path == "/api/config":
                return self.send(200, public_config())
            if url.path == "/api/stages":
                return self.send(200, {"stages": STAGES})
            if url.path == "/api/documents":
                return self.send(200, {"documents": documents()})
            if url.path == "/api/document":
                try:
                    return self.send(200, read_document(query.get("path", [""])[0]))
                except LookupError as error:
                    return self.send(404, {"error": str(error)})
            if url.path == "/api/search":
                return self.send(200, {"paths": search_documents(query.get("q", [""])[0][:200])})
            if url.path == "/api/workspace":
                with LOCK:
                    data, version = read_store()
                return self.send(200, {"data": data, "version": version})
            if url.path in ASSETS:
                file, mime = ASSETS[url.path]
                return self.send(200, (HERE / file).read_bytes(), mime + ("" if mime.startswith("font/") else "; charset=utf-8"))
            self.send(404, {"error": "페이지를 찾을 수 없습니다."})
        except (ValueError, OSError) as error:
            self.send(500, {"error": "파일을 읽지 못했습니다. 원본을 보존하고 확인하세요: " + str(error)})

    def do_POST(self):
        if not self.same_origin():
            return self.send(403, {"error": "같은 로컬 관리판에서만 변경할 수 있습니다."})
        if self.path == "/api/shutdown":
            self.send(200, {"stopped": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        if self.path != "/api/workspace":
            return self.send(404, {"error": "없는 API"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4_000_000:
                return self.send(413, {"error": "저장 크기 제한 초과"})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("저장 요청 형식 오류")
            validate(payload.get("data"))
            actor, by, message = payload.get("actor", "user"), payload.get("by", "사용자"), payload.get("message", "")
            if actor not in ("user", "ai") or not isinstance(by, str) or len(by) > 160 or not isinstance(message, str) or len(message) > 4000:
                raise ValueError("기록 입력 오류")
            if actor == "ai":
                validate_ai(by)
            with LOCK:
                previous, version = read_store()
                if payload.get("version") != version:
                    return self.send(409, {"error": "다른 창이나 AI가 먼저 수정했습니다. 입력은 창에 남아 있습니다. 내용을 복사해 두고 새로고침한 뒤 다시 적용하세요."})
                data = prepare_cards(payload["data"], previous, actor, by, message)
                new_version = save_store(data)
                write_status(data)
            self.send(200, {"data": data, "version": new_version})
        except (ValueError, OSError) as error:
            self.send(400, {"error": "저장하지 못했습니다: " + str(error)})


def serve(port=None):
    server = ThreadingHTTPServer(("127.0.0.1", port or CONFIG["port"]), Handler)
    print(f"{CONFIG['projectName']} board: http://127.0.0.1:{server.server_port}  (root: {ROOT})", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
