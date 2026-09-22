import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import KakaoMap from "@/components/KakaoMap";

vi.mock("next/script", () => ({ default: function Script({ onReady }: { onReady: () => void }) {
  // Simulate SDK readiness after the container has mounted.
  return <button onClick={onReady}>SDK ready</button>;
} }));
afterEach(cleanup);
test("verified and unverified markers use distinct images and labels; selection is shared", async () => {
  const markers: any[] = [], listeners: any[] = [];
  class Marker { constructor(public options: any) { markers.push(options); } setMap() {} getPosition() { return {}; } }
  class Map { setBounds() {} panTo() {} }
  class Value {}
  window.kakao = { maps: { Map, Marker, LatLng: Value, Size: Value, Point: Value, MarkerImage: class { constructor(public src: string) {} }, LatLngBounds: class { extend() {} }, load: (fn: () => void) => fn(), event: { addListener: (_marker: any, _event: string, fn: () => void) => listeners.push(fn) } } };
  const onSelect = vi.fn();
  render(<KakaoMap stops={[{ stopId: "a", name: "A", lat: 36.8, lng: 127.1, verified: true }, { stopId: "b", name: "B", lat: 36.8, lng: 127.1, verified: false }]} selectedStopId={null} onSelect={onSelect} />);
  // KEY is set by the test command to a non-secret placeholder.
  fireEvent.click(screen.getByText("SDK ready"));
  await waitFor(() => expect(markers).toHaveLength(2));
  expect(markers[0].image.src).not.toBe(markers[1].image.src);
  expect(markers[1].title).toContain("좌표 확인 필요");
  expect(screen.getByText("△ 좌표 확인 필요")).toBeTruthy();
  listeners[1]();
  expect(onSelect).toHaveBeenCalledWith("b");
});
