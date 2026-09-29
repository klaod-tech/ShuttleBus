프로젝트 관리판 (로컬 전용, Python 3.9+, 설치 패키지 없음)

실행   저장소 루트의 관리판.cmd 또는 이 폴더의 start-board.cmd 더블클릭
종료   stop-board.cmd  또는 화면 왼쪽 아래 "관리판 종료"
설정   config.json (프로젝트 이름, 번호 접두사, 분야, 포트)  /  stages.json (단계)
기준선 python work.py init   (지금 있는 문서를 검사에서 제외)
AI     python work.py next | inbox | show <번호> | add | create-doc | move | log | link | check
시험   python -m unittest discover -s tests -v

도입 계획과 결정: md/PLAN-project-board.md (저장소 루트 기준)
