"""Numbered work cards for humans and AI. Every write goes through the board's conflict check.

Read:   list, show, inbox, next, check
Write:  add, create-doc, sync-plans, move, log, link      (need --by <AI name>)
Setup:  init                                              (baseline of existing documents)
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from server import CONFIG, ROOT, STAGES, STATUSES, documents, read_store, validate_ai, git_commit  # noqa: E402

URL = f"http://127.0.0.1:{CONFIG['port']}"
BASELINE = HERE / "baseline-docs.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def save(data, version, by, message):
    """POST through the running board (starts it in the background if needed)."""
    validate_ai(by)
    body = json.dumps(dict(data=data, version=version, actor="ai", by=by, message=message), ensure_ascii=False).encode("utf-8")
    for attempt in (1, 2):
        request = urllib.request.Request(URL + "/api/workspace", method="POST", data=body,
                                         headers={"Content-Type": "application/json", "Origin": URL})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise ValueError(json.loads(error.read().decode("utf-8")).get("error", "저장 실패")) from error
        except urllib.error.URLError:
            if attempt == 2:
                raise ValueError("관리판 서버에 연결하지 못했습니다. python launch.py --no-browser 후 다시 실행하세요.")
            import launch
            if not launch.ensure_server():
                raise ValueError(f"포트 {CONFIG['port']}번을 다른 프로그램이 쓰고 있습니다. config.json의 port를 확인하세요.")


def new_card(title, category, stage, source, body, by, status="planned"):
    return dict(id=str(uuid.uuid4()), title=title, category=category, stage=stage, source=source, body=body,
                status=status, agent=by, result="", updated=now(), log=[])


def find(data, number):
    matches = [c for c in data["cards"] if c.get("number", "").upper() == number.upper() or c["id"] == number]
    if len(matches) != 1:
        raise ValueError("작업 번호가 없거나 중복입니다. work.py list로 확인하세요.")
    return matches[0]


def unseen(card):
    """A user entry after the last AI entry means the AI has not answered it yet."""
    log = card.get("log", [])
    last_ai = max((i for i, entry in enumerate(log) if entry["kind"] == "ai"), default=-1)
    return any(entry["kind"] == "user" for entry in log[last_ai + 1:])


def waiting(card, cards):
    done = {c["number"] for c in cards if c["status"] == "completed"}
    return [n for n in card.get("dependsOn", []) if n not in done]


def ready(cards):
    rows = [c for c in cards if c["status"] in ("planned", "in_progress", "review") and not waiting(c, cards)]
    return sorted(rows, key=lambda c: (c["status"] == "planned", c.get("order", 0), -c.get("priority", 0)))


def safe_doc_path(path):
    target = (ROOT / path).resolve()
    target.relative_to(ROOT.resolve())
    if target.suffix != ".md" or any(p.startswith(".") for p in Path(path).parts):
        raise ValueError("새 문서는 저장소 안의 .md 경로여야 합니다.")
    return target


def load_baseline():
    return set(json.loads(BASELINE.read_text(encoding="utf-8"))) if BASELINE.exists() else set()


def audit(data, docs, baseline):
    problems = []
    stage_ids = {s["id"] for s in STAGES}
    by_number = {c.get("number"): c for c in data["cards"]}
    paths = {d["path"] for d in docs}
    for card in data["cards"]:
        label = card.get("number", card["id"])
        if card.get("stage") not in stage_ids:
            problems.append(label + ": stages.json에 없는 단계 " + str(card.get("stage")))
        if card.get("category") not in CONFIG["categories"]:
            problems.append(label + ": config.json에 없는 분야 " + str(card.get("category")))
        if card["source"] and card["source"] not in paths:
            problems.append(label + ": 근거 문서가 없습니다 " + card["source"])
        if CONFIG["requireSourceForActive"] and card["status"] in ("in_progress", "review", "completed") and not card["source"]:
            problems.append(label + ": 진행·검수·완료 작업에는 근거 문서(source)가 필요합니다 (work.py link)")
    for doc in docs:
        if doc["path"] in baseline and not doc["task"]:
            continue
        if not doc["declared"] or any(c not in CONFIG["categories"] for c in doc["declared"]):
            problems.append(doc["path"] + ": '- 분야:' 줄이 없거나 config.json에 없는 분야입니다")
        card = by_number.get(doc["task"])
        if not card:
            problems.append(doc["path"] + f": 등록된 작업 번호가 필요합니다 ('- 작업: {CONFIG['taskPrefix']}-0001')")
        elif doc["declared"] and card.get("category") not in doc["declared"]:
            problems.append(doc["path"] + ": 작업 카드의 분야와 문서의 분야가 다릅니다")
    for doc in docs:
        if doc["status"] and not any(c["source"] == doc["path"] or c.get("number") == doc["task"] for c in data["cards"]):
            problems.append(doc["path"] + ": 계획 문서가 카드로 등록되지 않았습니다 (work.py sync-plans)")
    return problems


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="현재 문서들을 기존 문서(검사 제외)로 기록")
    init.add_argument("--force", action="store_true")
    listing = sub.add_parser("list")
    listing.add_argument("--category", choices=CONFIG["categories"])
    listing.add_argument("--status", choices=STATUSES)
    listing.add_argument("--stage", choices=[s["id"] for s in STAGES])
    sub.add_parser("inbox", help="AI가 아직 답하지 않은 사용자 기록이 있는 카드")
    nxt = sub.add_parser("next", help="선행 작업이 끝나 바로 할 수 있는 카드")
    nxt.add_argument("--limit", type=int, default=5)
    sub.add_parser("check")
    sub.add_parser("show").add_argument("number")
    sync = sub.add_parser("sync-plans", help="'- 상태:' 줄이 있는 계획 문서를 카드로 한 번 등록")
    sync.add_argument("--by", required=True)
    sync.add_argument("--stage", required=True, choices=[s["id"] for s in STAGES])
    sync.add_argument("--category", required=True, choices=CONFIG["categories"])
    add = sub.add_parser("add")
    add.add_argument("--source", default="")
    add.add_argument("--ref", default="", help="원래 문서의 항목 번호 (예: must_do C1)")
    create = sub.add_parser("create-doc", help="분야·작업 번호가 박힌 새 MD와 카드를 함께 생성")
    create.add_argument("--slug", required=True)
    for command in (add, create):
        command.add_argument("--title", required=True)
        command.add_argument("--category", choices=CONFIG["categories"], required=True)
        command.add_argument("--stage", required=True, choices=[s["id"] for s in STAGES])
        command.add_argument("--body", default="해야 할 일과 완료 기준을 구체화한다.")
        command.add_argument("--priority", type=int, choices=range(4), default=0)
        command.add_argument("--size", type=int, choices=(1, 2, 3), default=1)
        command.add_argument("--depends", default="", help="선행 번호, 쉼표 구분")
        command.add_argument("--by", required=True)
    for name in ("move", "log", "link"):
        cmd = sub.add_parser(name)
        cmd.add_argument("number")
        if name == "move":
            cmd.add_argument("status", choices=STATUSES)
            cmd.add_argument("--evidence", default="")
            cmd.add_argument("--performed-by", default="")
            cmd.add_argument("--commit", default="")
        if name == "link":
            cmd.add_argument("--source", required=True)
        cmd.add_argument("--by", required=True)
        cmd.add_argument("--note", required=True)
        cmd.add_argument("--version", required=True, help="show/list가 출력한 version. 그 사이 변경이 있으면 거절")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    data, version = read_store()
    docs = documents(with_body=False)
    doc_paths = {d["path"] for d in docs}

    if args.command == "init":
        if BASELINE.exists() and not args.force:
            raise ValueError("이미 초기화했습니다. 다시 기록하려면 --force (새 문서도 검사 제외가 됩니다).")
        BASELINE.write_text(json.dumps(sorted(doc_paths), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit(dict(root=str(ROOT), project=CONFIG["projectName"], baselineDocs=len(doc_paths), stages=[s["id"] for s in STAGES]))
        return 0
    if args.command == "check":
        problems = audit(data, docs, load_baseline())
        print("\n".join(problems) if problems else "PASS: 카드 단계·분야·근거 문서와 새 문서의 분야·작업 번호 연결")
        return int(bool(problems))
    if args.command in ("list", "inbox"):
        rows = data["cards"]
        if args.command == "inbox":
            rows = [c for c in rows if unseen(c)]
        else:
            rows = [c for c in rows if (not args.category or c.get("category") == args.category)
                    and (not args.status or c["status"] == args.status) and (not args.stage or c.get("stage") == args.stage)]
        emit(dict(version=version, cards=rows))
        return 0
    if args.command == "next":
        rows = ready(data["cards"])[:max(1, min(args.limit, 50))]
        emit(dict(version=version, cards=[{k: c.get(k) for k in ("number", "title", "status", "stage", "category", "priority", "source")} for c in rows]))
        return 0
    if args.command == "show":
        card = find(data, args.number)
        related = [d["path"] for d in docs if d["task"] == card.get("number")]
        emit(dict(version=version, card=card, waitingFor=waiting(card, data["cards"]), documents=related))
        return 0

    target = None
    message = "작업 등록"
    if args.command == "sync-plans":
        sources = {c["source"] for c in data["cards"]}
        tasks = {d["task"] for d in docs if d["task"]} & {c.get("number") for c in data["cards"]}
        count = len(data["cards"])
        for doc in sorted(docs, key=lambda d: d["path"]):
            if not doc["status"] or doc["path"] in sources or doc["task"] in tasks:
                continue
            card = new_card(doc["title"][:160], doc["declared"][0] if doc["declared"] and doc["declared"][0] in CONFIG["categories"] else args.category,
                            args.stage, doc["path"], "계획 문서에서 등록. 범위·검증 이력은 근거 문서 참조.", args.by, doc["status"])
            card["plan"] = True
            if card["status"] == "completed":
                card["evidence"] = "기존 완료 계획 문서: " + doc["path"]
            data["cards"].append(card)
        if len(data["cards"]) == count:
            print("등록할 새 계획 문서가 없습니다.")
            return 0
        message = "계획 문서에서 등록"
    elif args.command in ("add", "create-doc"):
        source = args.source if args.command == "add" else ""
        if source and source not in doc_paths:
            raise ValueError("존재하는 근거 MD 경로를 지정하세요 (저장소 루트 기준).")
        if args.command == "create-doc":
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug):
                raise ValueError("slug는 영문 소문자·숫자·하이픈입니다.")
            source = (Path(CONFIG["createDocDir"]) / (args.slug + ".md")).as_posix()
            target = safe_doc_path(source)
            if target.exists():
                raise ValueError("이미 있는 문서입니다. 기존 카드를 찾아 이어가세요.")
        card = new_card(args.title, args.category, args.stage, source, args.body, args.by)
        card.update(priority=args.priority, size=args.size,
                    dependsOn=[d.strip().upper() for d in args.depends.split(",") if d.strip()])
        if args.command == "add":
            card["ref"] = args.ref
        data["cards"].append(card)
    else:
        if args.version != version:
            raise ValueError("그 사이 다른 변경이 있습니다. show로 최신 내용과 version을 다시 확인하세요.")
        card = find(data, args.number)
        if args.command == "move":
            if args.status == "completed" and not (args.evidence.strip() or card.get("evidence", "").strip()):
                raise ValueError("--evidence에 실제로 한 일과 검증 결과를 남기세요.")
            if args.evidence:
                card["evidence"] = args.evidence
            if args.performed_by:
                card["performedBy"] = args.performed_by
            if args.commit:
                commit = git_commit(args.commit)
                if not commit:
                    raise ValueError("git 저장소가 아니거나 커밋을 찾지 못했습니다.")
                if not args.performed_by and not card.get("performedBy"):
                    card["performedBy"] = commit["author"]
                card["evidence"] = (card.get("evidence", "") + "\n커밋: " + commit["hash"][:12] + " " + commit["subject"]).strip()
            if CONFIG["requireSourceForActive"] and args.status in ("in_progress", "review", "completed") and card["source"] not in doc_paths:
                raise ValueError("먼저 link 명령으로 근거 MD를 연결하세요.")
            card["status"] = args.status
        if args.command == "link":
            if args.source not in doc_paths:
                raise ValueError("근거 MD가 없습니다: " + args.source)
            card["source"] = args.source
        card["agent"] = args.by
        card["updated"] = now()
        card["result"] = args.note
        message = args.note
    saved = save(data, version, args.by, message)
    if args.command == "sync-plans":
        emit(dict(version=saved["version"], cards=len(saved["data"]["cards"])))
        return 0
    card = next(c for c in saved["data"]["cards"] if c["id"] == card["id"])
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (f"# {args.title}\n\n- 분야: {args.category}\n- 작업: {card['number']}\n\n## 요청과 완료 기준\n\n{args.body}\n\n"
                "## 진행 기록\n\n- 결정·수정·검증 결과를 기록한다. 상태는 작업 카드가 소유한다.\n\n## 검증과 남은 사항\n\n- 아직 검증하지 않았다.\n")
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
        except OSError as error:
            raise ValueError(f"{card['number']} 등록됨. 문서 생성 실패: {error}. 이 번호로 문서를 만들고 check를 실행하세요.") from error
    emit(dict(version=saved["version"], card=card))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
