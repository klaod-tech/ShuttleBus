"use client";

import { useEffect, useState } from "react";

import { ApiRequestError, formatClock, formatRemaining, getStopUpcoming, type StopUpcomingResponse, type UpcomingItem } from "@/lib/api";

type Props = { stopId: string; routeId: string; serviceDate: string; onClose: () => void };

const EVENT_LABEL: Record<string, string> = { arrived: "도착", departed: "출발", passed: "통과" };

const REASON_LABEL: Record<string, string> = {
  arrived_confirmed: "도착 확인",
  arrival_observation_stale: "도착 확인 (오래됨)",
  scheduled_time_passed: "통과 여부 확인 중",
  prediction_expired: "출발 확인 중",
  stale_observation: "위치 확인 중",
  position_unverified: "위치 확인 중",
  awaiting_departure: "출발 확인 중",
  scheduled_event_type_unspecified: "도착/출발 확인 필요",
  no_scheduled_time: "시각 미공시",
};

const EMPTY_LABEL: Record<string, string> = {
  schedule_unavailable: "이 날짜에는 운행 정보가 없습니다.",
  past_date: "지난 날짜입니다. 시간표에서 확인하세요.",
  stop_not_on_route: "이 노선은 이 정거장을 지나지 않습니다.",
  unconfirmed_remaining: "예정된 버스는 없지만 확인 중인 항목이 있습니다.",
  no_remaining_service: "오늘 남은 운행이 없습니다.",
};

function basisLabel(item: UpcomingItem): string {
  switch (item.display_basis) {
    case "observed_event":
      return "실측";
    case "interpolated_event":
      return "자동 추정";
    case "scheduled_departure":
    case "timetable":
      return "시간표 기준";
    default:
      return "";
  }
}

function heading(item: UpcomingItem): string {
  if (item.is_terminal) return `${item.terminal_stop_name} 종점`;
  return `${item.next_stop_name} 방면 · ${item.terminal_stop_name}행`;
}

function Row({ item, serverTime, elapsedMs }: { item: UpcomingItem; serverTime: string; elapsedMs: number }) {
  const event = item.display_event_type ? EVENT_LABEL[item.display_event_type] : "";
  const isPrediction = item.reason === null && item.display_at;
  const time = item.display_at
    ? isPrediction
      ? `${formatRemaining(item.display_at, serverTime, elapsedMs)} ${event}${item.display_basis === "timetable" || item.display_basis === "scheduled_departure" ? " 예정" : " 예상"}`
      : `${formatClock(item.display_at)} ${event}`
    : "";
  return (
    <li className="row">
      <div className="row-main">
        <span className="row-trip">순{item.trip_no}{item.scheduled_vehicle_count > 1 ? ` · ${item.vehicle_slot}호차` : ""}</span>
        <span className="row-time">{time}</span>
      </div>
      <div className="row-sub">
        <span>{heading(item)}</span>
        {item.reason && <span className="tag">{REASON_LABEL[item.reason] ?? item.reason}</span>}
        {basisLabel(item) && <span className="tag muted">{basisLabel(item)}</span>}
        {item.secondary_departure_at && <span className="tag muted">출발 예상 {formatClock(item.secondary_departure_at)}</span>}
        {item.notes.includes("boarding_not_allowed") && <span className="tag warn">하차 전용</span>}
        {item.notes.includes("boarding_policy_unknown") && <span className="tag warn">승차 가능 여부 확인 필요</span>}
      </div>
    </li>
  );
}

export default function StopCard({ stopId, routeId, serviceDate, onClose }: Props) {
  const [data, setData] = useState<StopUpcomingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [receivedAt, setReceivedAt] = useState<number>(0);
  const [tick, setTick] = useState(0);

  // 조회 + refresh_after_seconds 주기 재조회. 늦게 온 이전 응답이 새 선택을 덮지 않게 요청마다 AbortController
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      try {
        const body = await getStopUpcoming(stopId, routeId, serviceDate, controller.signal);
        if (cancelled) return;
        setData(body);
        setError(null);
        setReceivedAt(Date.now());
        timer = setTimeout(load, Math.max(5, body.refresh_after_seconds) * 1000);
      } catch (e) {
        if (cancelled || (e instanceof DOMException && e.name === "AbortError")) return;
        setError(e instanceof ApiRequestError ? e.error.message : "서버에 연결할 수 없습니다.");
        timer = setTimeout(load, 30_000);
      }
    };
    setData(null);
    load();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [stopId, routeId, serviceDate]);

  // 남은 시간 표시는 서버 시각 + 경과 시간으로 계산한다 (초 단위 숫자는 노출하지 않음)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 15_000);
    return () => clearInterval(id);
  }, []);
  void tick;

  const elapsedMs = receivedAt ? Date.now() - receivedAt : 0;

  return (
    <section className="card" aria-live="polite">
      <header className="card-head">
        <h2>{data?.stop_name ?? "정거장"}</h2>
        <button type="button" onClick={onClose} aria-label="닫기">✕</button>
      </header>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">불러오는 중…</p>}
      {data && (
        <>
          {data.upcoming.length > 0 && (
            <ul className="rows">
              {data.upcoming.map((item) => (
                <Row key={`${item.trip_vehicle_id}:${item.trip_stop_id}`} item={item} serverTime={data.server_time} elapsedMs={elapsedMs} />
              ))}
            </ul>
          )}
          {data.upcoming.length === 0 && data.empty_reason && <p className="muted">{EMPTY_LABEL[data.empty_reason] ?? data.empty_reason}</p>}
          {data.attention.length > 0 && (
            <>
              <h3>확인 중</h3>
              <ul className="rows">
                {data.attention.map((item) => (
                  <Row key={`${item.trip_vehicle_id}:${item.trip_stop_id}`} item={item} serverTime={data.server_time} elapsedMs={elapsedMs} />
                ))}
              </ul>
            </>
          )}
          {data.reference_timetable.length > 0 && (
            <details>
              <summary>참고 시간표 ({data.reference_timetable.length})</summary>
              <ul className="rows">
                {data.reference_timetable.map((item) => (
                  <Row key={`${item.trip_vehicle_id}:${item.trip_stop_id}`} item={item} serverTime={data.server_time} elapsedMs={elapsedMs} />
                ))}
              </ul>
            </details>
          )}
          <p className="muted small">기준 시각 {formatClock(data.server_time)} · {data.refresh_after_seconds}초마다 갱신</p>
        </>
      )}
    </section>
  );
}
