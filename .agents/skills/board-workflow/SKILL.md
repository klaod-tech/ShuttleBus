---
name: board-workflow
description: ShuttleBus 작업 카드(SB 번호)로 착수·진행·완료와 검증 근거를 기록한다. 작업을 시작하거나 이어서 하거나 끝낼 때 사용한다.
---

# 작업 카드 흐름 — ShuttleBus

저장소 루트에서 실행한다. 규칙의 정본은 [CLAUDE.md](../../../CLAUDE.md) 8장이며 이 스킬은 순서만 적는다. 사용자 요청의 범위를 넓히지 않고, 커밋·푸시는 요청할 때만 한다.

1. **확인** — `python scripts/board/work.py inbox`(사용자가 카드에 남긴 새 기록), `work.py next`(바로 할 수 있는 카드), 관련 카드는 `work.py show SB-0000`. 출력의 `waitingFor`가 비어 있지 않으면 선행 카드부터 본다.
2. **등록** — 관련 카드가 없을 때만. `work.py list --stage p2`처럼 먼저 찾는다.
   `work.py add --title "…" --category <서버|화면|자료·현장|인프라|문서·연구> --stage <p0~p8|operations> --by klaod-tech_CL [--source md/…] [--ref "must_do C1"] [--depends SB-0000]`.
   새 설계 문서가 필요하면 `work.py create-doc --slug <영문-소문자> …` (문서는 `md/`에 생긴다).
3. **착수** — 근거 md가 없으면 `work.py link SB-0000 --source md/… --by … --note … --version …`부터.
   `work.py move SB-0000 in_progress --by klaod-tech_CL --note "착수 범위" --version <show의 version>`.
   CLAUDE.md 2장의 승인 대상이면 `blocked`로 옮기고 계획을 md에 쓴 뒤 멈춘다.
4. **진행 기록** — 설명과 결정은 해당 md에, 카드에는 요약을 `work.py log SB-0000 --note "…" --version …`.
5. **완료** — 완료 조건을 실제로 확인했을 때만.
   `work.py move SB-0000 completed --note "완료 범위" --evidence "실행한 검증 명령과 결과(pytest 개수 등), 바꾼 파일·커밋" [--commit <해시>] --version …`.
   못 돌린 검증은 evidence에 "못 돌렸다"고 적거나 `review`로 둔다. 남은 범위는 새 카드.
6. **검사** — 끝내기 전 `work.py check`. 보고에 카드 번호와 검사 결과를 적는다. 큰 변화면 CHANGELOG도 3장 규칙대로.

규칙

- `--version`이 맞지 않아 거절되면 덮어쓰지 않는다. `show`로 최신 내용을 다시 읽고 반영한다.
- 번호는 바꾸거나 다시 쓰지 않는다. 사용자가 남긴 원문과 과거 기록을 고치지 않는다.
- md 표의 `카드` 열을 유지한다. 끝난 항목도 md 행과 ID(S1·F3·한계 2 등)는 지우지 않는다 — 코드 주석이 가리킨다.
- AI 이름은 Claude `klaod-tech_CL`, Codex 등 `klaod-tech_GPT`.
