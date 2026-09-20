// 서버 계약 (../md/03·10·11)과 같은 이름을 쓴다. 화면이 시간표로 ETA를 직접 계산하지 않는다 (must_do F3).

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export type ApiError = { code: string; message: string; retryable: boolean };

export class ApiRequestError extends Error {
  constructor(public status: number, public error: ApiError) {
    super(error.message);
  }
}

async function getJson<T>(path: string, params?: Record<string, string>, signal?: AbortSignal): Promise<T> {
  const url = new URL(`${API_BASE}/api/v1${path}`);
  if (params) for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url.toString(), { signal, headers: { Accept: "application/json" } });
  if (!res.ok) {
    let error: ApiError = { code: "HTTP_" + res.status, message: res.statusText, retryable: res.status >= 500 };
    try {
      error = (await res.json()).error ?? error;
    } catch {
      /* 본문 없음 */
    }
    throw new ApiRequestError(res.status, error);
  }
  return (await res.json()) as T;
}

// ---------- 노선·정거장 (10) ----------

export type Route = { route_id: string; name: string; short_name: string; is_active: boolean };

export type RouteStop = {
  route_stop_id: string;
  stop_id: string;
  stop_name: string;
  stop_sequence: number;
  latitude: number | null;
  longitude: number | null;
  boarding_policy: "allowed" | "not_allowed" | "unknown";
  alighting_policy: "allowed" | "not_allowed" | "unknown";
  verification_status: "verified" | "needs_interpretation" | "unverified";
};

export type PatternStops = {
  route_pattern_id: string;
  pattern_code: string;
  direction: string;
  route_version_id: string;
  verification_status: string;
  stops: RouteStop[];
};

export type RouteStopsResponse = {
  route_id: string;
  service_date: string;
  schedule_status: "available" | "no_service" | "unknown" | "out_of_period";
  schedule_reason: string | null;
  patterns: PatternStops[];
};

export const listRoutes = (signal?: AbortSignal) => getJson<Route[]>("/routes", undefined, signal);

export const getRouteStops = (routeId: string, serviceDate: string, signal?: AbortSignal) =>
  getJson<RouteStopsResponse>(`/routes/${routeId}/stops`, { service_date: serviceDate }, signal);

// ---------- 경로 폴리라인 (04 1장, 10 5장) ----------

export type PathSegment = {
  from_route_stop_id: string;
  to_route_stop_id: string;
  path_from_seq: number;
  path_to_seq: number;
  distance_m: number | null;
  path_source: string;
  verification_status: "verified" | "needs_interpretation" | "unverified";
};

export type PatternPath = {
  route_pattern_id: string;
  pattern_code: string;
  route_version_id: string;
  path_source: "recorded_track" | "operator_provided" | "manual_trace" | null;
  point_count: number;
  points: [number, number][]; // [lat, lng]
  segments: PathSegment[];
  verification: "verified" | "partial" | "unverified" | "none";
};

export type RoutePathResponse = {
  route_id: string;
  service_date: string;
  schedule_status: string;
  schedule_reason: string | null;
  patterns: PatternPath[];
};

export const getRoutePath = (routeId: string, serviceDate: string, signal?: AbortSignal) =>
  getJson<RoutePathResponse>(`/routes/${routeId}/path`, { service_date: serviceDate }, signal);

// ---------- 정거장 단독 조회 (11 11장) ----------

export type VisitOut = {
  trip_stop_id: string;
  visit_status: string;
  estimated_event_at: string | null;
  target_event_type: string | null;
  prediction_basis: string | null;
  basis_observation: unknown;
  unavailable_reason: string | null;
  observed_arrival_at: string | null;
  observed_departure_at: string | null;
  observed_passed_at: string | null;
};

export type UpcomingItem = {
  trip_id: string;
  trip_no: number;
  trip_vehicle_id: string;
  vehicle_slot: number;
  route_id: string;
  route_pattern_id: string;
  pattern_code: string;
  trip_stop_id: string;
  stop_sequence: number;
  is_origin: boolean;
  is_terminal: boolean;
  next_stop_name: string | null;
  terminal_stop_name: string;
  display_at: string | null;
  display_event_type: "arrived" | "departed" | "passed" | null;
  display_basis: "observed_event" | "interpolated_event" | "scheduled_departure" | "timetable" | null;
  reason: string | null;
  secondary_departure_at: string | null;
  notes: string[];
  operation_status: string;
  information_status: "timetable_only" | "observed" | "stale" | "unavailable";
  scheduled_vehicle_count: number;
  tracked_vehicle_count: number;
  visit: VisitOut;
};

export type StopUpcomingResponse = {
  stop_id: string;
  stop_name: string;
  route_id: string;
  service_date: string;
  schedule_status: string;
  schedule_reason: string | null;
  server_time: string;
  refresh_after_seconds: number;
  upcoming: UpcomingItem[];
  attention: UpcomingItem[];
  reference_timetable: UpcomingItem[];
  empty_reason:
    | "schedule_unavailable"
    | "past_date"
    | "stop_not_on_route"
    | "unconfirmed_remaining"
    | "no_remaining_service"
    | null;
};

export const getStopUpcoming = (stopId: string, routeId: string, serviceDate: string, signal?: AbortSignal) =>
  getJson<StopUpcomingResponse>(`/stops/${stopId}/upcoming`, { route_id: routeId, service_date: serviceDate }, signal);

// ---------- 시각 표시 (md_frontend/02) ----------

/** 서울 날짜 YYYY-MM-DD. 브라우저 시간대와 무관하게 서울 기준으로 '오늘'을 정한다. */
export function todaySeoul(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(now); // sv-SE = ISO 날짜 형식
}

export function formatClock(iso: string): string {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
}

/**
 * 남은 시간 표시. 1시간 미만이면 'n분 뒤', 1시간 이상이면 HH:mm. 1분 미만이면 '1분 이내'.
 * 판단은 반올림한 분이 아니라 실제 남은 시간이다. 0 이하가 됐다고 '도착'을 만들지 않는다 — 호출한 쪽이 사유로 처리한다.
 * 분 단위 내림·올림은 미확정(must_do F2) — 여기서는 내림을 임시로 쓴다.
 */
export function formatRemaining(targetIso: string, serverTimeIso: string, elapsedMs: number): string {
  const remainingMs = new Date(targetIso).getTime() - (new Date(serverTimeIso).getTime() + elapsedMs);
  if (remainingMs <= 0) return formatClock(targetIso);
  if (remainingMs < 60_000) return "1분 이내";
  if (remainingMs < 3_600_000) return `${Math.floor(remainingMs / 60_000)}분 뒤`;
  return formatClock(targetIso);
}
