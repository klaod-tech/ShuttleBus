// 카카오맵 JavaScript SDK 전역. 지금은 any — 필요해지면 @types/kakao.maps.d.ts 로 교체한다.
declare global {
  interface Window {
    kakao: any;
  }
}

export {};
