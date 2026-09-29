"""Small, bounded document map for AI sessions. Reads the real files every time.

python docs.py --query 로그인 --limit 10       title/path/body search
python docs.py --category 개발                   by '- 분야:' or config categoryRules
python docs.py --task T-0012                      documents linked to a card
python docs.py --outline docs/work/login.md       headings with line numbers only
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import CONFIG, documents  # noqa: E402


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", choices=CONFIG["categories"] + ["미분류"])
    parser.add_argument("--query", default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--outline", help="저장소 루트 기준 MD 경로")
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("limit은 1~100입니다.")
    rows = documents(with_body=True)
    if args.outline:
        doc = next((d for d in rows if d["path"] == args.outline), None)
        if not doc:
            parser.error("문서를 찾을 수 없습니다: " + args.outline)
        headings = [dict(line=i, text=line) for i, line in enumerate(doc["body"].splitlines(), 1) if re.match(r"^#{1,6} ", line)]
        print(json.dumps(dict(path=doc["path"], categories=doc["groups"], task=doc["task"], headings=headings), ensure_ascii=False, indent=2))
        return 0
    q = args.query.casefold()
    matches = [d for d in rows if (not args.category or args.category in d["groups"])
               and (not args.task or d["task"] == args.task.upper())
               and (not q or q in (d["title"] + d["path"] + d["body"]).casefold())]
    print(json.dumps(dict(total=len(matches), shown=min(len(matches), args.limit), documents=[
        {k: d[k] for k in ("path", "title", "groups", "task", "status")} for d in matches[:args.limit]]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
