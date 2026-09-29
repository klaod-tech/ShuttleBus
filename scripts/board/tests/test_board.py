"""Board tests with synthetic projects only. Run: python -m unittest discover -s tests -v (inside the board folder)."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

BOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOARD))
import server  # noqa: E402
import work  # noqa: E402

STAGES = [{"id": "build", "title": "구현", "goal": "", "exit": "", "docs": [], "ongoing": False},
          {"id": "ops", "title": "운영", "goal": "", "exit": "", "docs": [], "ongoing": True}]


def card(**extra):
    base = dict(id="c1", title="합성 작업", body="사용자 원문", source="", status="planned", updated="2026-01-01T00:00:00Z",
                category="개발", stage="build", log=[])
    base.update(extra)
    return base


class Project(unittest.TestCase):
    """Each test gets its own fake project root, store and config."""
    config = {}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / "workspace.json"
        config = dict(server.DEFAULT_CONFIG, **self.config)
        stages = copy.deepcopy(STAGES)
        self.patches = [patch.object(server, "ROOT", self.root), patch.object(server, "STORE", self.store),
                        patch.object(server, "CONFIG", config), patch.object(server, "STAGES", stages),
                        patch.object(work, "ROOT", self.root), patch.object(work, "CONFIG", config),
                        patch.object(work, "STAGES", stages), patch.object(work, "BASELINE", self.root / "baseline.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        return file


class SettingsTests(unittest.TestCase):
    def test_config_defaults_and_rejections(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            self.assertEqual(server.load_config(path)["taskPrefix"], "T")  # missing file = defaults
            for bad in ({"taskPrefix": "sb"}, {"port": 80}, {"categories": []}, {"categories": ["a", "a"]},
                        {"categories": ["a,b"]}, {"categoryRules": [{"category": "없음"}]}, {"createDocDir": "../x"}):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    server.load_config(path)
            path.write_text(json.dumps({"_설명": "무시", "taskPrefix": "SB"}), encoding="utf-8")
            self.assertEqual(server.load_config(path)["taskPrefix"], "SB")

    def test_root_prefers_git_then_board_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            board_dir = base / "repo" / "tools" / "board"
            board_dir.mkdir(parents=True)
            self.assertEqual(server.find_root({"root": "auto"}, board_dir), board_dir.parent)
            (base / "repo" / ".git").mkdir()
            self.assertEqual(server.find_root({"root": "auto"}, board_dir), base / "repo")
            self.assertEqual(server.find_root({"root": ".."}, board_dir), board_dir.parent)

    def test_stage_file_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stages.json"
            for bad in ([], [{"id": "A", "title": "x"}], [{"id": "a", "title": ""}], [{"id": "a", "title": "x"}, {"id": "a", "title": "y"}]):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    server.load_stages(path)
            path.write_text(json.dumps([{"id": "a", "title": "x"}]), encoding="utf-8")
            self.assertEqual(server.load_stages(path)[0]["ongoing"], False)


class DocumentTests(Project):
    config = {"taskPrefix": "SB", "categories": ["개발", "문서"], "categoryRules": [{"category": "문서", "paths": ["md/"]}]}

    def test_empty_project_has_no_documents(self):
        self.assertEqual(server.documents(), [])
        self.assertEqual(server.read_store()[0], {"cards": [], "nextNumber": 1})

    def test_metadata_rules_and_exclusions(self):
        self.write("md/plan.md", "# 계획\n\n- 분야: 개발\n- 작업: SB-0003\n- 상태: in_progress\n")
        self.write("md/note.md", "# 메모\n\n작성일: x · 상태: 진행중\n")  # free text is not a plan status
        self.write("md/other.md", "# 다른 접두사\n\n- 작업: T-0001\n")
        for hidden in ("node_modules/x.md", ".git/x.md", ".tools/x.md"):
            self.write(hidden, "# 숨김\n")
        docs = {d["path"]: d for d in server.documents()}
        self.assertEqual(set(docs), {"md/plan.md", "md/note.md", "md/other.md"})
        self.assertEqual((docs["md/plan.md"]["groups"], docs["md/plan.md"]["task"], docs["md/plan.md"]["status"]), (["개발"], "SB-0003", "in_progress"))
        self.assertEqual((docs["md/note.md"]["groups"], docs["md/note.md"]["status"]), (["문서"], None))
        self.assertEqual(docs["md/other.md"]["task"], "")
        self.write("README.md", "제목 없음")
        self.assertEqual({d["path"]: d for d in server.documents()}["README.md"]["groups"], ["미분류"])

    def test_read_and_search_stay_inside_the_document_list(self):
        self.write("a.md", "# A\n\n셔틀 도착 예측\n")
        self.assertIn("셔틀", server.read_document("a.md")["body"])
        for bad in ("../a.md", "/etc/passwd", "b.md", "a.txt"):
            with self.subTest(bad=bad), self.assertRaises(LookupError):
                server.read_document(bad)
        self.assertEqual(server.search_documents("도착 예측"), ["a.md"])
        self.assertEqual(server.search_documents("  "), [])


class CardTests(Project):
    config = {"taskPrefix": "SB", "categories": ["개발", "문서"]}

    def test_numbers_use_prefix_and_are_never_recycled(self):
        before = {"cards": [], "nextNumber": 1}
        data = {"cards": [card()], "nextNumber": 1}
        server.prepare_cards(data, before)
        self.assertEqual((data["cards"][0]["number"], data["cards"][0]["order"]), ("SB-0001", 10))
        edited = copy.deepcopy(data)
        edited["cards"][0]["title"] = "바뀐 제목"
        server.prepare_cards(edited, data)
        self.assertEqual(edited["cards"][0]["number"], "SB-0001")
        deleted = dict(copy.deepcopy(edited), cards=[])
        server.prepare_cards(deleted, edited)
        again = dict(copy.deepcopy(deleted), cards=[card(id="c2")])
        server.prepare_cards(again, deleted)
        self.assertEqual(again["cards"][0]["number"], "SB-0002")
        stolen = copy.deepcopy(again)
        stolen["cards"][0]["number"] = "SB-0009"
        with self.assertRaises(ValueError):
            server.prepare_cards(stolen, again)

    def test_completion_requires_evidence(self):
        before = {"cards": [card(number="SB-0001")], "nextNumber": 2}
        data = copy.deepcopy(before)
        data["cards"][0]["status"] = "completed"
        with self.assertRaisesRegex(ValueError, "완료 근거"):
            server.prepare_cards(data, before)
        data["cards"][0]["evidence"] = "합성 시험 통과"
        server.prepare_cards(data, before, "ai", "Leo_CL", "완료")
        self.assertEqual(data["cards"][0]["log"][-1], dict(at=data["cards"][0]["updated"], by="Leo_CL", kind="ai", text="완료"))

    def test_message_is_logged_only_on_the_touched_card(self):
        before = {"cards": [card(number="SB-0001"), card(id="c2", number="SB-0002")], "nextNumber": 3}
        data = copy.deepcopy(before)
        data["cards"][1]["updated"] = "2026-02-02T00:00:00Z"
        server.prepare_cards(data, before, message="검수 의견")
        self.assertEqual(data["cards"][0]["log"], [])
        self.assertEqual(data["cards"][0]["updated"], before["cards"][0]["updated"])
        self.assertEqual([e["text"] for e in data["cards"][1]["log"]], ["검수 의견"])

    def test_dependencies_must_exist_and_not_cycle(self):
        a, b = card(id="a", number="SB-0001", dependsOn=["SB-0002"]), card(id="b", number="SB-0002", dependsOn=["SB-0001"])
        with self.assertRaisesRegex(ValueError, "순환"):
            server.validate({"cards": [a, b], "nextNumber": 3})
        b["dependsOn"] = []
        server.validate({"cards": [a, b], "nextNumber": 3})
        a["dependsOn"] = ["SB-0099"]
        with self.assertRaisesRegex(ValueError, "존재하지 않는"):
            server.validate({"cards": [a, b], "nextNumber": 3})

    def test_removed_stage_does_not_lock_old_cards(self):
        old = {"cards": [card(number="SB-0001", stage="removed-stage")], "nextNumber": 2}
        server.validate(old)  # readable
        same = copy.deepcopy(old)
        server.prepare_cards(same, old)  # untouched card still saves
        changed = copy.deepcopy(old)
        changed["cards"][0]["title"] = "수정"
        with self.assertRaisesRegex(ValueError, "단계"):
            server.prepare_cards(changed, old)

    def test_ai_names(self):
        server.validate_ai("아무_CL")
        for bad in ("", " ", "x" * 81):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                server.validate_ai(bad)
        with patch.dict(server.CONFIG, {"aiNames": ["Leo_CL"]}):
            server.validate_ai("Leo_CL")
            with self.assertRaises(ValueError):
                server.validate_ai("Leo_GPT")

    def test_inbox_and_ready(self):
        entry = lambda kind: {"kind": kind, "at": "t", "by": "x", "text": "y"}  # noqa: E731
        self.assertFalse(work.unseen({"log": [entry("user"), entry("ai")]}))
        self.assertTrue(work.unseen({"log": [entry("user"), entry("ai"), entry("user")]}))
        cards = [card(id="a", number="SB-0001", status="completed", order=10), card(id="b", number="SB-0002", dependsOn=["SB-0001"], order=20),
                 card(id="c", number="SB-0003", dependsOn=["SB-0002"], order=5), card(id="d", number="SB-0004", status="in_progress", order=30)]
        self.assertEqual([c["number"] for c in work.ready(cards)], ["SB-0004", "SB-0002"])


class AuditTests(Project):
    config = {"taskPrefix": "SB", "categories": ["개발", "문서"]}

    def test_baseline_new_documents_plans_and_cards(self):
        self.write("old.md", "# 예전 문서\n")
        self.write("new.md", "# 새 문서\n")
        self.write("linked.md", "# 연결\n\n- 분야: 개발\n- 작업: SB-0001\n")
        self.write("plan.md", "# 계획\n\n- 상태: planned\n")
        data = {"cards": [card(number="SB-0001", source="linked.md", status="in_progress"), card(id="c2", number="SB-0002", stage="gone", status="review")], "nextNumber": 3}
        problems = "\n".join(work.audit(data, server.documents(), {"old.md", "plan.md"}))
        self.assertNotIn("old.md", problems)
        self.assertIn("new.md", problems)
        self.assertNotIn("linked.md:", problems)
        self.assertIn("plan.md: 계획 문서가 카드로 등록되지 않았습니다", problems)
        self.assertIn("SB-0002: stages.json에 없는 단계", problems)
        self.assertIn("SB-0002: 진행·검수·완료 작업에는 근거 문서", problems)


class HttpBase(Project):
    config = {"taskPrefix": "SB", "categories": ["개발", "문서"]}

    def setUp(self):
        super().setUp()
        self.server = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, path, payload=None, headers=None):
        default = {"Origin": self.url, "Content-Type": "application/json"} if payload is not None else {}
        request = urllib.request.Request(self.url + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers or default)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)


class HttpTests(HttpBase):
    def test_save_then_stale_version_is_rejected(self):
        data, version = server.read_store()
        data["cards"].append(card())
        status, saved = self.request("/api/workspace", dict(data=data, version=version))
        self.assertEqual(status, 200)
        self.assertEqual(saved["data"]["cards"][0]["number"], "SB-0001")
        stale = copy.deepcopy(saved["data"])
        stale["cards"][0]["body"] = "덮어쓰기"
        self.assertEqual(self.request("/api/workspace", dict(data=stale, version=version))[0], 409)
        self.assertEqual(server.read_store()[0]["cards"][0]["body"], "사용자 원문")

    def test_untrusted_writers_and_bad_data_do_not_touch_the_store(self):
        data, version = server.read_store()
        payload = dict(data=dict(data, cards=[card()]), version=version)
        self.assertEqual(self.request("/api/workspace", payload, {"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("/api/workspace", payload, {"Origin": self.url, "Host": "example.com"})[0], 403)
        self.assertEqual(self.request("/api/shutdown", {}, {"Origin": "https://example.com"})[0], 403)
        bad = dict(data=dict(data, cards=[card(category="없는 분야")]), version=version)
        self.assertEqual(self.request("/api/workspace", bad)[0], 400)
        self.assertFalse(self.store.exists())

    def test_corrupt_store_is_kept(self):
        self.store.write_text("broken", encoding="utf-8")
        self.assertEqual(self.request("/api/workspace")[0], 500)
        self.assertEqual(self.request("/api/workspace", dict(data={"cards": [], "nextNumber": 1}, version="x"))[0], 400)
        self.assertEqual(self.store.read_text(encoding="utf-8"), "broken")

    def test_only_listed_files_are_served(self):
        self.write("a.md", "# A\n")
        for path in ("/workspace.json", "/server.py", "/config.json", "/../../a.md", "/.git/config"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/api/document?path=a.md")[1]["title"], "A")
        self.assertEqual(self.request("/api/document?path=../a.md")[0], 404)
        self.assertEqual(self.request("/api/config")[1]["taskPrefix"], "SB")
        self.assertEqual(self.request("/api/search?q=A")[1]["paths"], ["a.md"])


class CliTests(HttpBase):
    """The AI path: add → show → link → move → complete, plus create-doc and sync-plans."""

    def run_work(self, *argv):
        out = io.StringIO()
        with patch.object(work, "URL", self.url), contextlib.redirect_stdout(out):
            code = work.main(list(argv))
        text = out.getvalue()
        return code, (json.loads(text) if text.strip().startswith("{") else text)

    def test_ai_card_lifecycle(self):
        self.write("md/spec.md", "# 명세\n")
        code, added = self.run_work("add", "--title", "로그인 API", "--category", "개발", "--stage", "build", "--by", "Leo_CL", "--ref", "must_do S3")
        self.assertEqual((code, added["card"]["number"], added["card"]["ref"]), (0, "SB-0001", "must_do S3"))
        _, shown = self.run_work("show", "SB-0001")
        with self.assertRaisesRegex(ValueError, "link"):
            self.run_work("move", "SB-0001", "in_progress", "--by", "Leo_CL", "--note", "착수", "--version", shown["version"])
        _, linked = self.run_work("link", "SB-0001", "--source", "md/spec.md", "--by", "Leo_CL", "--note", "근거 연결", "--version", shown["version"])
        with self.assertRaisesRegex(ValueError, "그 사이"):
            self.run_work("move", "SB-0001", "in_progress", "--by", "Leo_CL", "--note", "착수", "--version", shown["version"])
        _, moved = self.run_work("move", "SB-0001", "in_progress", "--by", "Leo_CL", "--note", "착수", "--version", linked["version"])
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_work("move", "SB-0001", "completed", "--by", "Leo_CL", "--note", "끝", "--version", moved["version"])
        _, done = self.run_work("move", "SB-0001", "completed", "--by", "Leo_CL", "--note", "끝", "--evidence", "pytest 3개 통과", "--performed-by", "Leo", "--version", moved["version"])
        final = done["card"]
        self.assertEqual((final["status"], final["performedBy"], final["log"][-1]["kind"]), ("completed", "Leo", "ai"))
        self.assertEqual([e["text"] for e in final["log"]], ["작업 등록", "근거 연결", "착수", "끝"])

    def test_create_doc_and_sync_plans(self):
        _, created = self.run_work("create-doc", "--title", "경로 설계", "--category", "문서", "--stage", "build", "--slug", "route-design", "--by", "Leo_CL")
        text = (self.root / "docs/work/route-design.md").read_text(encoding="utf-8")
        self.assertIn("- 분야: 문서\n- 작업: SB-0001", text)
        self.assertEqual(created["card"]["source"], "docs/work/route-design.md")
        with self.assertRaisesRegex(ValueError, "이미 있는"):
            self.run_work("create-doc", "--title", "중복", "--category", "문서", "--stage", "build", "--slug", "route-design", "--by", "Leo_CL")
        self.write("md/plan-a.md", "# 계획 A\n\n- 상태: review\n")
        self.write("md/plan-b.md", "# 계획 B\n\n- 분야: 개발\n- 상태: completed\n")
        self.run_work("sync-plans", "--stage", "ops", "--category", "문서", "--by", "Leo_CL")
        cards = {c["source"]: c for c in server.read_store()[0]["cards"]}
        self.assertEqual((cards["md/plan-a.md"]["status"], cards["md/plan-a.md"]["category"]), ("review", "문서"))
        self.assertEqual((cards["md/plan-b.md"]["category"], cards["md/plan-b.md"]["evidence"]), ("개발", "기존 완료 계획 문서: md/plan-b.md"))
        code, text = self.run_work("sync-plans", "--stage", "ops", "--category", "문서", "--by", "Leo_CL")
        self.assertIn("없습니다", text)
        self.assertEqual(self.run_work("check")[0], 1)  # no baseline: every doc must declare 분야/작업
        self.run_work("init")
        self.assertEqual(self.run_work("check")[0], 0)


if __name__ == "__main__":
    unittest.main()
