"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import KakaoMap, { type MapStop } from "@/components/KakaoMap";
import StopCard from "@/components/StopCard";
import { ApiRequestError, getRoutePath, getRouteStops, listRoutes, todaySeoul, type PatternPath, type Route, type RouteStop, type RouteStopsResponse } from "@/lib/api";

const DEFAULT_ROUTE_NAME = "천안아산역"; // 최초 선택 노선 (md_frontend/01, 2026-09-15 확정)

const SCHEDULE_LABEL: Record<string, string> = {
  no_service: "이 날짜에는 운행하지 않습니다.",
  unknown: "이 날짜의 운행 자료를 아직 확인하지 못했습니다.",
  out_of_period: "시간표 적용 기간 밖의 날짜입니다.",
};

/** 같은 물리 정거장은 마커 하나 — 여러 패턴·방문에 나와도 stop_id로 합친다 (md_frontend/01). */
function uniqueStops(body: RouteStopsResponse | null): RouteStop[] {
  if (!body) return [];
  const seen = new Map<string, RouteStop>();
  for (const p of body.patterns) for (const s of p.stops) if (!seen.has(s.stop_id)) seen.set(s.stop_id, s);
  return [...seen.values()];
}

export default function HomePage() {
  const [routes, setRoutes] = useState<Route[]>([]);
  const [routeId, setRouteId] = useState<string>("");
  const [serviceDate, setServiceDate] = useState<string>(todaySeoul());
  const [stopsBody, setStopsBody] = useState<RouteStopsResponse | null>(null);
  const [paths, setPaths] = useState<PatternPath[]>([]);
  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listRoutes(controller.signal)
      .then((rs) => {
        if (controller.signal.aborted) return;
        setRoutes(rs);
        const first = rs.find((r) => r.name.includes(DEFAULT_ROUTE_NAME)) ?? rs[0];
        if (first) setRouteId(first.route_id);
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        if (!(e instanceof DOMException && e.name === "AbortError")) setError("서버에 연결할 수 없습니다. API 주소와 CORS 설정을 확인하세요.");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!routeId) return;
    const controller = new AbortController();
    setStopsBody(null);
    setPaths([]);
    setSelectedStopId(null);
    // 경로는 있으면 그리고 없으면 조용히 넘어간다 — 경로 조회 실패가 정거장 목록을 막지 않는다
    getRoutePath(routeId, serviceDate, controller.signal)
      .then((body) => {
        if (!controller.signal.aborted) setPaths(body.patterns);
      })
      .catch(() => {
        if (!controller.signal.aborted) setPaths([]);
      });
    getRouteStops(routeId, serviceDate, controller.signal)
      .then((body) => {
        if (controller.signal.aborted) return;
        setStopsBody(body);
        setError(null);
      })
      .catch((e) => {
        if (controller.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
        setError(e instanceof ApiRequestError ? e.error.message : "정거장 목록을 불러오지 못했습니다.");
      });
    return () => controller.abort();
  }, [routeId, serviceDate]);

  const stops = useMemo(() => uniqueStops(stopsBody), [stopsBody]);
  // 좌표가 있는 정거장만 마커. 없는 정거장은 목록에서 '확인 필요' (must_do F8)
  const mapStops = useMemo<MapStop[]>(
    () =>
      stops
        .filter((s) => s.latitude !== null && s.longitude !== null)
        .map((s) => ({ stopId: s.stop_id, name: s.stop_name, lat: s.latitude as number, lng: s.longitude as number, verified: s.verification_status === "verified" })),
    [stops],
  );
  const onSelect = useCallback((stopId: string) => setSelectedStopId(stopId), []);

  const scheduleNote = stopsBody && stopsBody.schedule_status !== "available" ? SCHEDULE_LABEL[stopsBody.schedule_status] ?? stopsBody.schedule_status : null;

  return (
    <div className="app">
      <header className="topbar">
        <h1>ShuttleBus</h1>
        <span className="spacer" />
        <label>
          노선{" "}
          <select value={routeId} onChange={(e) => setRouteId(e.target.value)} disabled={routes.length === 0}>
            {routes.map((r) => (
              <option key={r.route_id} value={r.route_id}>{r.name}</option>
            ))}
          </select>
        </label>
        <label>
          날짜 <input type="date" value={serviceDate} onChange={(e) => e.target.value && setServiceDate(e.target.value)} />
        </label>
      </header>

      <div className="main">
        <KakaoMap stops={mapStops} paths={paths} selectedStopId={selectedStopId} onSelect={onSelect} />

        <aside className="panel">
          {error && <p className="error">{error}</p>}
          {scheduleNote && <p className="muted">{scheduleNote}</p>}
          {selectedStopId && routeId ? (
            <StopCard stopId={selectedStopId} routeId={routeId} serviceDate={serviceDate} onClose={() => setSelectedStopId(null)} />
          ) : (
            <>
              <p className="hint">정류장을 누르거나 출발지와 도착지를 선택하세요.</p>
              {stops.length > 0 && (
                <ul className="stop-list">
                  {stops.map((s, i) => (
                    <li key={s.stop_id}>
                      <button type="button" onClick={() => onSelect(s.stop_id)} aria-pressed={selectedStopId === s.stop_id}>
                        <span className="seq">{i + 1}</span>
                        {s.stop_name}
                        {(s.latitude === null || s.longitude === null || s.verification_status !== "verified") && <span className="tag warn" style={{ marginLeft: 6 }}>좌표 확인 필요</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {stopsBody && stops.length === 0 && !scheduleNote && <p className="muted">이 노선의 정거장 자료가 없습니다.</p>}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
