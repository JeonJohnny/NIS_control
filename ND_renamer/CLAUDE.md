# CLAUDE.md — 01_ND2Tools

## 1. 목적

Nikon `.nd2` 파일의 **이름을 규칙에 맞게 바꾸고 하위 폴더로 분류**하는 tkinter GUI. nd2 파일을 열지 않고 이름만 다룬다.

- 새 이름: `[헤더_][약물_]t값[_번호].nd2`, 폴더: `[추가단어/][약물/][t값/]` (체크한 기준만)
- 마지막 t(폴더에서 가장 큰 t값)의 번호 파일은 번호 대신 `_L라인_채널` — 채널 수만큼의 파일이 한 라인 (`_L1_BF`, `_L1_FITC`, `_L1_PI`, `_L1_ANX`, `_L2_BF` …)
- 그 외 t(t1, t2 …)는 끝에 `_BF` (`CML_AS_t1_BF.nd2`)
- 채널은 체크박스 + 수정 가능한 이름 칸 4개(기본 BF, FITC, PI, ANX). 체크한 것만 왼쪽부터 촬영 순서로 쓴다. 첫 칸(BF)을 해제하면 그 외 t에는 아무것도 안 붙고, 전부 해제하면 마지막 t도 `_001`…
- 폴더는 쉼표로 여러 개 입력 가능 (`D:\exp\48, D:\exp\72`, "추가" 버튼). 폴더마다 같은 설정으로 실행. 각 폴더의 최상위 nd2만 본다
- 미리보기 → 왼쪽 목록(폴더 > 파일, 기본 전체 선택)에서 체크한 파일만 실행. 건너뜀/주의/요약은 오른쪽 로그
- 실행마다 폴더에 `_FileNamer_log_*.csv` 기록 → "마지막 실행 되돌리기" (폴더마다 가장 최근 기록)

## 2. 실행

- `run.bat` 더블클릭 → `ND2Tools.py`
- Python 3 + tkinter만 있으면 됨 (표준 라이브러리만 사용). run.bat은 `hjeon` env 우선, 없으면 PATH의 python
- 설정은 `ND2Tools_settings.json`에 자동 저장

## 3. 구조

```
ND2Tools.py              # GUI
nd2tools/filenamer.py    # 이름 해석(parse_name), 계획(build_plan), 이동(execute_plan), 되돌리기(undo_log)
```

## 4. 지운 기능 (2026-10-04)

OME-TIFF 변환(라인 분할)과 z-projection은 사용자 요청으로 뺐다. 그때의 전체 코드(`zproject.py`, `zstack.py`, 테스트, 스크립트, GUI)는 `..\00_Archive\ND2Tools_ometiff_zprojection\`에 있다.

- 남겨 둔 호환 처리: 예전 버전이 `origin\`으로 옮긴 실행 기록도 되돌리기에서 찾고, 기록에 "만든 파일" 행(OME-TIFF 등)이 있으면 되돌릴 때 지운다 (확인 창에 개수 표시)
- 참고 실측: D: 읽기 약 100~150MB/s라 z-projection은 디스크 읽기가 병목이었음 (포지션당 읽기 0.50초, 계산 0.11초)

## 5. 코딩 규칙

- 처리 로직은 `nd2tools/`, GUI는 `ND2Tools.py`
- 주석은 한국어 가능, 식별자는 영어
