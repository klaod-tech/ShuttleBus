import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import HomePage from "@/app/page";
import { getRoutePath, getRouteStops, listRoutes } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({ ...await original<object>(), listRoutes: vi.fn(), getRoutePath: vi.fn(), getRouteStops: vi.fn() }));
vi.mock("@/components/KakaoMap", () => ({ default: ({ paths, stops }: { paths: unknown; stops: unknown }) => <div data-testid="map">{JSON.stringify({ paths, stops })}</div> }));
vi.mock("@/components/StopCard", () => ({ default: () => <div>정거장 카드</div> }));

const deferred = () => {
  let resolve!: (value: any) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<any>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const response = (name: string) => ({ schedule_status: "available", patterns: [{ stops: [{ stop_id: name, stop_name: name, latitude: 36.8, longitude: 127.1, verification_status: "verified" }] }] });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listRoutes).mockResolvedValue([{ route_id: "A", name: "천안아산역", short_name: "A", is_active: true }, { route_id: "B", name: "B", short_name: "B", is_active: true }]);
});
afterEach(cleanup);

test.each(["success", "error", "abort"])("old %s after latest response cannot overwrite route or stops", async (outcome) => {
  const oldPath = deferred(), oldStops = deferred();
  vi.mocked(getRoutePath).mockImplementation((id) => id === "A" ? oldPath.promise : Promise.resolve({ patterns: [{ pattern_code: "B-path" }] } as any));
  vi.mocked(getRouteStops).mockImplementation((id) => id === "A" ? oldStops.promise : Promise.resolve(response("B-stop") as any));
  render(<StrictMode><HomePage /></StrictMode>);
  await waitFor(() => expect(getRoutePath).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText("노선"), { target: { value: "B" } });
  await screen.findByRole("button", { name: /B-stop/ });
  await act(async () => {
    if (outcome === "success") { oldPath.resolve({ patterns: [{ pattern_code: "old" }] }); oldStops.resolve(response("old")); }
    else { const error = outcome === "abort" ? new DOMException("cancelled", "AbortError") : new Error("late failure"); oldPath.reject(error); oldStops.reject(error); }
  });
  expect(screen.getByTestId("map").textContent).toContain("B-path");
  expect(screen.queryByText(/정거장 목록을 불러오지 못했습니다/)).toBeNull();
  expect(screen.queryByRole("button", { name: /old/ })).toBeNull();
});

test("date change and current path failure preserve latest stop list", async () => {
  const oldPath = deferred();
  vi.mocked(getRoutePath).mockReturnValueOnce(oldPath.promise).mockRejectedValue(new Error("current failure"));
  vi.mocked(getRouteStops).mockImplementation((_id, date) => Promise.resolve(response(date) as any));
  render(<HomePage />);
  await waitFor(() => expect(getRoutePath).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("날짜"), { target: { value: "2026-10-01" } });
  await screen.findByRole("button", { name: /2026-10-01/ });
  await act(async () => oldPath.resolve({ patterns: [{ pattern_code: "old" }] }));
  expect(screen.getByTestId("map").textContent).toContain('"paths":[]');
});

test("unknown status and missing longitude remain labelled in the list", async () => {
  vi.mocked(getRoutePath).mockResolvedValue({ patterns: [] } as any);
  const stops = [
    { stop_id: "ok", stop_name: "확인됨", latitude: 36.8, longitude: 127.1, verification_status: "verified" },
    { stop_id: "unknown", stop_name: "미검증", latitude: 36.8, longitude: 127.1, verification_status: "unverified" },
    { stop_id: "missing", stop_name: "경도없음", latitude: 36.8, longitude: null, verification_status: "verified" },
  ];
  vi.mocked(getRouteStops).mockResolvedValue({ schedule_status: "available", patterns: [{ stops: [...stops, stops[0]] }] } as any);
  render(<HomePage />);
  await screen.findByRole("button", { name: /미검증.*좌표 확인 필요/ });
  expect(screen.getByRole("button", { name: /경도없음.*좌표 확인 필요/ })).toBeTruthy();
  expect(screen.getAllByRole("button", { name: /확인됨/ })).toHaveLength(1);
  expect(screen.getByTestId("map").textContent).not.toContain("경도없음");
});
