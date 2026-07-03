# Collision Avoidance Firmware V2.0.0

이 폴더는 HC-SR04 충돌 방지 기능이 포함된 OTA 업데이트용 RA6E1 펌웨어 소스다.

## 파일

- `hal_entry.c`: OTA, SPI 명령, 버전 V2.0.0, HC-SR04 비차단 측정 및 전진 차단
- `motorhat.c`: 긴급 정지 지연을 줄인 I2C 모터 제어
- `motorhat.h`: 모터 제어 선언

기능이 없는 V1.0.0 원본은 상위 `OTA` 폴더의 `hal_entry.c`, `motorhat.c`,
`motorhat.h`다. 두 버전을 동시에 e2 studio의 `src`에 넣으면 함수가 중복되므로,
빌드할 버전의 세 파일만 `src`에 복사한다.

전체 배선과 빌드·시험 절차는
[`../HC_SR04_Collision_Avoidance.md`](../HC_SR04_Collision_Avoidance.md)를 참고한다.
