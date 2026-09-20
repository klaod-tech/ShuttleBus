"""정거장 좌표 등록 (04 11장, 10 2·3장). 지도 마커는 이 좌표로 찍는다.

원문 시간표에는 좌표가 없어 현장 확인으로 채운다. 확인하지 않은 좌표를 확정처럼 쓰지 않도록
verification_status를 함께 기록한다 — verified / needs_interpretation / unverified.

실행
  python -m app.stops list
  python -m app.stops set --name 아산캠퍼스 --lat 36.7998 --lng 127.0745 --status verified
  python -m app.stops import --file coords.json     {"아산캠퍼스": {"lat": .., "lng": .., "status": ".."}}
  python -m app.stops import --file samples/stops-provisional.json   현장 확인 전 임시 좌표 (needs_interpretation)

import는 이미 verified인 정거장을 덮지 않는다 (--overwrite-verified 로 강제). 현장 확인값이 임시값에 밀리지 않게.
"""

import argparse
import json

from sqlalchemy import select

from app.db import SessionLocal
from app.models.base import VERIFICATION_STATUS
from app.models.reference import Stop

# 대한민국 남한 영역. 위경도를 뒤집어 넣는 실수를 막는다
LAT_RANGE = (33.0, 38.7)
LNG_RANGE = (124.5, 131.0)


def check_coordinates(latitude: float, longitude: float) -> str | None:
    if not LAT_RANGE[0] <= latitude <= LAT_RANGE[1]:
        return f"위도가 범위({LAT_RANGE[0]}~{LAT_RANGE[1]}) 밖이다: {latitude}"
    if not LNG_RANGE[0] <= longitude <= LNG_RANGE[1]:
        return f"경도가 범위({LNG_RANGE[0]}~{LNG_RANGE[1]}) 밖이다: {longitude}"
    return None


def set_location(
    session, stop: Stop, latitude: float, longitude: float, verification_status: str, geofence_radius_m: int | None = None
) -> Stop:
    problem = check_coordinates(latitude, longitude)
    if problem:
        raise ValueError(problem)
    if verification_status not in VERIFICATION_STATUS:
        raise ValueError(f"확인 상태는 {VERIFICATION_STATUS} 중 하나다")
    stop.latitude, stop.longitude, stop.verification_status = latitude, longitude, verification_status
    if geofence_radius_m is not None:
        stop.geofence_radius_m = geofence_radius_m
    session.flush()
    return stop


def _stop_by_name(session, name: str) -> Stop:
    stop = session.scalar(select(Stop).where(Stop.name == name))
    if stop is None:
        raise SystemExit(f"정거장을 찾을 수 없다: {name}")
    return stop


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.stops")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="정거장·좌표·확인 상태 목록")
    one = sub.add_parser("set", help="한 정거장의 좌표 등록")
    one.add_argument("--name", required=True)
    one.add_argument("--lat", type=float, required=True)
    one.add_argument("--lng", type=float, required=True)
    one.add_argument("--status", choices=list(VERIFICATION_STATUS), default="verified")
    one.add_argument("--radius", type=int, default=None, help="지오펜스 반경(m). 생략하면 그대로 둔다")
    bulk = sub.add_parser("import", help="JSON 파일에서 여러 정거장 좌표 등록")
    bulk.add_argument("--file", required=True)
    bulk.add_argument("--overwrite-verified", action="store_true", help="verified 정거장도 덮어쓴다 (기본은 건너뜀)")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.command == "list":
            for s in session.scalars(select(Stop).order_by(Stop.name)):
                coords = "좌표 없음" if s.latitude is None else f"{s.latitude:.6f}, {s.longitude:.6f}"
                print(f"{s.name}\t{coords}\t{s.verification_status}")
            return
        if args.command == "set":
            stop = _stop_by_name(session, args.name)
            set_location(session, stop, args.lat, args.lng, args.status, args.radius)
            session.commit()
            print(f"등록: {stop.name} {stop.latitude}, {stop.longitude} ({stop.verification_status})")
            return
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
        done, skipped = 0, 0
        for name, value in data.items():
            if name.startswith("_"):
                continue  # 설명 칸
            stop = _stop_by_name(session, name)
            if stop.verification_status == "verified" and stop.latitude is not None and not args.overwrite_verified:
                skipped += 1
                print(f"건너뜀 (verified 유지): {name}")
                continue
            set_location(session, stop, float(value["lat"]), float(value["lng"]), value.get("status", "verified"), value.get("radius"))
            done += 1
        session.commit()
        print(f"{done}개 정거장 좌표 등록, {skipped}개 건너뜀")


if __name__ == "__main__":
    main()
