"use client";

import Script from "next/script";
import { useEffect, useMemo, useRef, useState } from "react";

import type { PatternPath } from "@/lib/api";

export type MapStop = { stopId: string; name: string; lat: number; lng: number; verified: boolean };

type Props = {
  stops: MapStop[];
  /** 서버 route_path_points. 비어 있으면 아무 선도 긋지 않는다 — 직선 연결도 하지 않는다 (must_do F8) */
  paths?: PatternPath[];
  selectedStopId: string | null;
  onSelect: (stopId: string) => void;
};

/** 10 5장 표시 규칙: verified 실선, 그 외 점선. manual_trace는 '추정 경로' */
function pathStyle(p: PatternPath): { strokeStyle: string; strokeColor: string; label: string | null } {
  if (p.path_source === "manual_trace") return { strokeStyle: "shortdash", strokeColor: "#9ca3af", label: "추정 경로" };
  if (p.verification === "verified") return { strokeStyle: "solid", strokeColor: "#1d4ed8", label: null };
  return { strokeStyle: "dash", strokeColor: "#1d4ed8", label: "미검증 경로" };
}

const KEY = process.env.NEXT_PUBLIC_KAKAO_MAP_JS_KEY;
// autoload=false — Next.js 하이드레이션 뒤 컨테이너가 준비된 시점에 우리가 직접 초기화한다
const SDK_URL = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${KEY}&autoload=false`;
// 아산캠퍼스 부근 임시 중심. 실제 정거장 좌표는 서버 등록값을 따른다 (좌표 없으면 마커 없음)
const DEFAULT_CENTER = { lat: 36.7998, lng: 127.0745 };

/**
 * 정거장 마커와 서버가 제공한 경로만 표시한다. 정거장을 임의로 잇지 않는다.
 * 좌표가 없는 정거장은 마커를 만들지 않고 목록으로만 제공한다.
 */
export default function KakaoMap({ stops, paths = [], selectedStopId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const markersRef = useRef<Map<string, any>>(new Map());
  const polylinesRef = useRef<any[]>([]);
  const pathLabels = useMemo(() => [...new Set(paths.filter((p) => p.verification !== "none" && p.points.length >= 2).map((p) => pathStyle(p).label).filter((label): label is string => label !== null))], [paths]);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(KEY ? null : "카카오맵 키가 설정되지 않았습니다 (web/.env.local).");

  const init = () => {
    if (!window.kakao?.maps) {
      setFailed("카카오맵 SDK를 불러오지 못했습니다. 키와 도메인 등록을 확인하세요.");
      return;
    }
    window.kakao.maps.load(() => {
      if (!containerRef.current) return;
      mapRef.current = new window.kakao.maps.Map(containerRef.current, {
        center: new window.kakao.maps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lng),
        level: 6,
      });
      setReady(true);
    });
  };

  // 마커 동기화 — stops가 바뀌면 다시 찍고, 전부 들어오게 화면을 맞춘다
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const kakao = window.kakao;
    const markers = markersRef.current;
    for (const marker of markersRef.current.values()) marker.setMap(null);
    markersRef.current.clear();
    if (stops.length === 0) return;
    const bounds = new kakao.maps.LatLngBounds();
    for (const s of stops) {
      const position = new kakao.maps.LatLng(s.lat, s.lng);
      const marker = new kakao.maps.Marker({ map: mapRef.current, position, title: s.verified ? s.name : `${s.name} · 좌표 확인 필요`, clickable: true,
        image: new kakao.maps.MarkerImage(s.verified ? "/markers/verified.svg" : "/markers/unverified.svg", new kakao.maps.Size(32, 40), { offset: new kakao.maps.Point(16, 40) }) });
      kakao.maps.event.addListener(marker, "click", () => onSelect(s.stopId));
      markersRef.current.set(s.stopId, marker);
      bounds.extend(position);
    }
    mapRef.current.setBounds(bounds, 40, 40, 40, 40);
    return () => {
      for (const marker of markers.values()) marker.setMap(null);
      markers.clear();
    };
  }, [ready, stops, onSelect]);

  // 경로 폴리라인 — 서버에 행이 있는 패턴만. 정거장을 임의로 잇지 않는다
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const kakao = window.kakao;
    for (const line of polylinesRef.current) line.setMap(null);
    polylinesRef.current = [];
    for (const p of paths) {
      if (p.verification === "none" || p.points.length < 2) continue;
      const style = pathStyle(p);
      const line = new kakao.maps.Polyline({
        map: mapRef.current,
        path: p.points.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng)),
        strokeWeight: 4,
        strokeColor: style.strokeColor,
        strokeOpacity: 0.8,
        strokeStyle: style.strokeStyle,
      });
      polylinesRef.current.push(line);
    }
    return () => {
      for (const line of polylinesRef.current) line.setMap(null);
      polylinesRef.current = [];
    };
  }, [ready, paths]);

  // 선택 정거장으로 지도를 옮긴다 (줌은 유지)
  useEffect(() => {
    if (!ready || !mapRef.current || !selectedStopId) return;
    const marker = markersRef.current.get(selectedStopId);
    if (marker) mapRef.current.panTo(marker.getPosition());
  }, [ready, selectedStopId]);

  return (
    <div className="map-wrap">
      {KEY && <Script src={SDK_URL} strategy="afterInteractive" onReady={init} onError={() => setFailed("카카오맵 SDK 로드 실패")} />}
      <div ref={containerRef} className="map" aria-label="정거장 지도" />
      {(pathLabels.length > 0 || stops.length > 0) && (
        <div className="map-legend" role="note">
          {stops.some((s) => s.verified) && <span className="tag">● 확인된 좌표</span>}
          {stops.some((s) => !s.verified) && <span className="tag warn">△ 좌표 확인 필요</span>}
          {pathLabels.map((l) => (
            <span key={l} className="tag warn">{l}</span>
          ))}
        </div>
      )}
      {failed && (
        <div className="map-fallback" role="status">
          {failed} 아래 목록으로 계속 이용할 수 있습니다.
        </div>
      )}
    </div>
  );
}
