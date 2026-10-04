"""
ND Generator UI  (통합 단일 프로그램)

NIS ND 실험 XML(4개 모서리, nd_4point.xml)을 감지/추출하여
전체 메시가 채워진 nd_full.xml 을 생성하고,
이어서 그룹별/형광채널별로 분할된 nd_output 파일들까지 생성한다.

- 1단계: nd_4point.xml (4모서리, RLxExperiment) -> nd_full.xml (전체 메시, RLxExperiment)
- 2단계: nd_full.xml -> nd_output/nd01-F1.xml ... (그룹 분할 + 형광채널 분리 + ND_LoadExperiment 체이닝)

출력 XML은 원본(nd_ref) 포맷과 바이트 단위로 동일한 스타일(UTF-16, 단일라인,
요소 사이 공백, compact self-closing)로 저장되어 NIS 및 후속 프로그램에서 인식된다.

이 파일은 외부 프로젝트 모듈에 의존하지 않는 자립형(self-contained) 프로그램이다.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import os
import re
import sys
import copy
import time
import json
import shutil
import xml.etree.ElementTree as ET
from bisect import bisect_right
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, List

import numpy as np


# ============================================================================
# 공통 상수/유틸
# ============================================================================
def _get_app_dir() -> str:
    """실행 위치 기준 디렉터리 반환 (개발/PyInstaller 배포 모두 대응)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _get_app_dir()
CONFIG_FILE = os.path.join(APP_DIR, "nd_generator_config.json")

# 기본 파일 경로 (nd_ref 폴더 기준)
ND_REF_DIR = os.path.join(APP_DIR, "nd_ref")
DEFAULT_INPUT_FILE = os.path.join(ND_REF_DIR, "nd_4point.xml")
DEFAULT_OUTPUT_FILE = os.path.join(ND_REF_DIR, "nd_full.xml")
# "4point 초기화" 가 구조를 빌려오는 참조 파일. nd_4point.xml 과 같은 RLxExperiment 전체 구조여야
# 하며(XYPosLoop 필요), 초기화 시 이 구조에 DEFAULT_CORNERS 4개 위치만 채워 넣는다.
REFERENCE_4POINT_FILE = os.path.join(ND_REF_DIR, "4porint-reference.xml")

# 템플릿은 고정 위치(.\template\nd_template.xml)에서만 읽는다.
# 템플릿을 바꿔야 하면 이 파일을 새 XML로 덮어쓰면 된다. (UI에서 선택하지 않음)
TEMPLATE_DIR = os.path.join(APP_DIR, "template")
TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "nd_template.xml")
LEGACY_TEMPLATE_FILE = os.path.join(ND_REF_DIR, "nd_template.xml")  # 구버전 위치(자동 이전용)

# ND Output 생성 후 NIS 매크로를 이 파일에 다시 쓴다. (생성된 파일마다 Load + Run 한 쌍)
DEFAULT_MACRO_FILE = r"C:\Program Files\NIS-Elements\Macros\nd_output_autorun.mac"

# ND Output 을 만들 때마다 결과 한 벌을 여기에 스냅샷으로 남기고 최근 N개만 유지한다.
ARCHIVE_DIR = os.path.join(APP_DIR, "archive")
ARCHIVE_KEEP = 10
# 보관 폴더 이름은 'YYYYMMDD_HHMMSS' 로 시작한다. 정리할 때 이 형식만 지우므로
# 사용자가 직접 넣어둔 다른 폴더는 건드리지 않는다.
ARCHIVE_NAME_RE = re.compile(r"^\d{8}_\d{6}")

XY_LOOP = "RLxExperiment.RLxExpXYPosLoop"
SPECT_LOOP = "RLxExperiment.RLxExpSpectLoop"
Z_LOOP = "RLxExperiment.RLxExpZStackLoop"
# 템플릿 SpectLoop 의 채널 수와 같아야 한다. (2026-09-23: Cy5 추가로 8 -> 9)
# 순서: BF, FITC, Cy3, Cy5, DAPI, Triple_BF, Triple_475(G), Triple_550(R), Triple_385(B)
NUM_FLUOR_CHANNELS = 9
LINE_LABELS = "ABCDEFGHI"

# 형광 채널별 초점(Z) 오프셋의 기준 채널 인덱스. SpectLoop 의 iOffsetReference 와 같은 의미로,
# 이 채널(BF)의 오프셋은 항상 0 이고 나머지 채널은 이 채널 대비 µm 단위로 지정한다.
OFFSET_REFERENCE_CHANNEL = 0

# 실험 래퍼(no_name runtype="RLxExperiment")의 eType 값
ETYPE_XY = "2"
ETYPE_ZSTACK = "4"

# 메시 프리셋: key -> (라벨, rows, cols, reps)
MESH_PRESETS = {
    "general": ("일반", 2, 18, 8),
    "log": ("로그", 4, 9, 8),
}
CUSTOM_PRESET = "custom"

# 기본 창 크기(내용 영역 px). NIS 옆에 세로로 길게 두고 쓰는 배치 기준이며,
# 이후에는 닫을 때의 크기/위치를 설정 파일에 저장해 다음 실행에 되살린다.
DEFAULT_WINDOW_SIZE = (631, 1368)
MIN_WINDOW_SIZE = (580, 940)     # 이보다 작으면 실행 결과 패널이 창 밖으로 밀린다

# 실행 결과 패널 / 로그 색
STATUS_COLORS = {"red": "#c01c28", "green": "#1a7f37", "blue": "#1a5fb4",
                 "gray": "#666666", "black": "#000000"}
STATUS_ICONS = {"green": "✔ ", "red": "✖ "}
RESULT_ROW_COUNT = 8      # 실행 결과 패널에 보일 수 있는 최대 항목 수

# ---- Z-Stack 기본값 (test.xml 의 RLxExpZStackLoop 구성을 그대로 따름) ----
# UI에서 조절하는 값은 Range/Step/장치뿐이고, 나머지는 아래 값이 그대로 쓰인다.
DEFAULT_Z_RANGE = 25.0    # dZHigh - dZLow (µm)
DEFAULT_Z_STEP = 2.5      # dZStep (µm)
DEFAULT_Z_DEVICE = "Ti2 ZDrive"

# (태그, runtype) 순서 — NIS가 읽는 순서 그대로 유지해야 한다.
ZSTACK_FIELDS = [
    ("uiCount", "lx_uint32"),
    ("dZLow", "double"),
    ("dZLowPFSOffset", "double"),
    ("dZHigh", "double"),
    ("dZHighPFSOffset", "double"),
    ("dZHome", "double"),
    ("dZStep", "double"),
    ("bAbsolute", "bool"),
    ("bTriggeredPiezo", "bool"),
    ("iType", "lx_int32"),
    ("bZInverted", "bool"),
    ("dReferencePosition", "double"),
    ("dTIRFPosition", "double"),
    ("dTIRFPFSOffset", "double"),
    ("bTIRF", "bool"),
    ("sZDevice", "CLxStringW"),
    ("sCommandBeforeCapture", "CLxStringW"),
    ("sCommandAfterCapture", "CLxStringW"),
]

# Range/Step/장치로 결정되지 않는 고정 필드 (test.xml 값)
ZSTACK_FIXED = {
    "dZLowPFSOffset": "0.000000000000000",
    "dZHighPFSOffset": "0.000000000000000",
    "bAbsolute": "false",          # 상대 모드 (현재 Z 기준)
    "bTriggeredPiezo": "false",
    "iType": "2",                  # Range + Step 로 정의하는 모드
    "bZInverted": "false",
    "dReferencePosition": "0.000000000000000",
    "dTIRFPosition": "0.000333000000000",
    "dTIRFPFSOffset": "-1.000000000000000",
    "bTIRF": "false",
    "sCommandBeforeCapture": "",
    "sCommandAfterCapture": "",
}

# 초기 4point 파일 생성용 기본 4모서리 (name, x, y, z) — [LTfirst, TR, BR, LTlast]
DEFAULT_CORNERS = [
    ("A1",   "-4708.900000000000546",  "-19829.700000000000728", "6325.500000000000000"),
    ("A54",  "-16531.100000000002183", "-19720.900000000001455", "6326.079999999999927"),
    ("A108", "-16503.900000000001455", "-17059.900000000001455", "6321.300000000000182"),
    ("D1",   "-4370.900000000000546",  "7685.900000000000546",   "6295.039999999999964"),
]


def _fmt(value) -> str:
    """NIS 스타일 double 문자열 (소수점 15자리 고정)."""
    return f"{float(value):.15f}"


def list_archive_entries(archive_dir=ARCHIVE_DIR) -> List[str]:
    """보관 폴더의 스냅샷 목록을 최신순으로 반환. (이름이 타임스탬프라 사전 역순 = 최신순)"""
    if not os.path.isdir(archive_dir):
        return []
    names = [d for d in os.listdir(archive_dir)
             if ARCHIVE_NAME_RE.match(d) and os.path.isdir(os.path.join(archive_dir, d))]
    return sorted(names, reverse=True)


def prune_archive(archive_dir=ARCHIVE_DIR, keep=ARCHIVE_KEEP, log=None) -> List[str]:
    """최근 keep 개만 남기고 오래된 스냅샷을 지운다. 반환: 지운 폴더 이름 목록."""
    log = log or (lambda m: None)
    removed = []
    for name in list_archive_entries(archive_dir)[keep:]:
        try:
            shutil.rmtree(os.path.join(archive_dir, name))
            removed.append(name)
        except OSError as e:
            log(f"  보관 정리 실패: {name} ({e})")
    return removed


def archive_run(input_path, full_path, nd_files, label="", info_text="",
                archive_dir=ARCHIVE_DIR, keep=ARCHIVE_KEEP, log=None):
    """이번 생성 결과 한 벌을 보관 폴더에 복사하고 오래된 스냅샷을 정리한다.

    스냅샷 구성: 입력 4point, nd_full, nd_output/*.xml, run_info.txt(설정 요약)
    반환: (스냅샷 경로, 지운 폴더 이름 목록)
    """
    log = log or (lambda m: None)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(archive_dir, f"{stamp}_{label}" if label else stamp)
    os.makedirs(dest, exist_ok=True)

    for src in (input_path, full_path):
        if src and os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, os.path.basename(src)))

    if nd_files:
        nd_dir = os.path.join(dest, "nd_output")
        os.makedirs(nd_dir, exist_ok=True)
        for src in nd_files:
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(nd_dir, os.path.basename(src)))

    if info_text:
        with open(os.path.join(dest, "run_info.txt"), "w", encoding="utf-8") as fp:
            fp.write(info_text)

    return dest, prune_archive(archive_dir, keep, log)


# 매크로 앞뒤에 붙는 경과 시간 측정 블록. (NIS 매크로 문법, time_test.mac 으로 검증됨)
# - Get_Time(): NIS 시작 후 경과 ms. 시작/끝에서 읽어 빼면 매크로 실행 시간.
# - NIS 의 sprintf 는 값 인자를 하나만 받고, 값은 변수 이름을 따옴표로 감싸 넘긴다.
#   그래서 시/분/초/ms 를 한 번씩 포맷해 strcat 으로 이어 붙인다.
# - WaitText(0, ...) 은 Continue 버튼이 있는 창을 띄우고 누를 때까지 기다린다.
MACRO_TIMER_HEAD = [
    "// nd_output_autorun.mac : generated by ND Generator (rewritten on every ND Output run)",
    "int t0, t1, elapsed;",
    "int ms, sec, min, hour;",
    "char msg[256];",
    "char tmp[64];",
    "",
    "t0 = Get_Time();",
    "",
]
MACRO_TIMER_TAIL = [
    "",
    "t1 = Get_Time();",
    "elapsed = t1 - t0;",
    "Convert_ms_To_Time(&ms, &sec, &min, &hour, elapsed);",
    'sprintf(msg, "ND output DONE ({count} files).  Elapsed: %d h", "hour");',
    'sprintf(tmp, " %d min", "min");',
    "strcat(msg, tmp);",
    'sprintf(tmp, " %d s", "sec");',
    "strcat(msg, tmp);",
    'sprintf(tmp, "  (%d ms total)", "elapsed");',
    "strcat(msg, tmp);",
    "WaitText(0, msg);",
]


def build_autorun_macro(nd_files, with_timer=True) -> str:
    """생성된 nd_output 파일 목록(체이닝 순서)으로 NIS 매크로 본문을 만든다.

    파일마다 ND_LoadExperiment + ND_RunExperiment(0) 한 쌍. nd 파일 안에도 다음 파일을
    불러오는 명령이 있지만, 매크로에서 한 번 더 불러와도 무방하다.
    with_timer 면 시작 시각을 기록하고 마지막에 완료 창(경과 시간)을 띄운다.
    """
    lines = []
    if with_timer:
        lines += MACRO_TIMER_HEAD
    for i, path in enumerate(nd_files):
        if i:
            lines.append("")
        abs_path = os.path.abspath(path)
        lines.append(f'ND_LoadExperiment("{abs_path}");')
        lines.append("ND_RunExperiment(0);")
    if with_timer:
        lines += [s.replace("{count}", str(len(nd_files))) for s in MACRO_TIMER_TAIL]
    return "\r\n".join(lines) + "\r\n"


def write_autorun_macro(nd_files, macro_path=DEFAULT_MACRO_FILE) -> str:
    """매크로 파일을 ASCII/CRLF 로 덮어쓴다. 반환: 매크로 경로."""
    os.makedirs(os.path.dirname(macro_path) or ".", exist_ok=True)
    with open(macro_path, "w", encoding="ascii", newline="") as fp:
        fp.write(build_autorun_macro(nd_files))
    return macro_path


def to_portable_path(path: str) -> str:
    """저장용 경로 변환. 프로젝트 폴더 안이면 상대경로로 바꾼다.

    폴더를 통째로 다른 위치/PC로 옮겨도 설정이 그대로 유효하도록 하기 위함이다.
    폴더 밖(다른 드라이브 포함)이면 절대경로 그대로 둔다.
    """
    if not path:
        return path
    try:
        abs_path = os.path.abspath(path)
        common = os.path.commonpath([abs_path, APP_DIR])
    except (ValueError, OSError):
        return path
    if os.path.normcase(common) == os.path.normcase(APP_DIR):
        return os.path.relpath(abs_path, APP_DIR)
    return abs_path


def from_portable_path(path: Optional[str], default: str) -> str:
    """저장된 경로를 실제 경로로 복원. 상대경로면 프로젝트 폴더 기준으로 푼다."""
    if not path:
        return default
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(APP_DIR, path))


def ensure_template_file():
    """template 폴더를 준비하고 템플릿 경로를 반환. 반환: (경로, 안내 메시지 or None).

    폴더가 없으면 만들고, 템플릿이 없는데 구버전 위치(nd_ref)에 파일이 있으면 한 번 복사해 온다.
    이후 템플릿 교체는 이 파일을 덮어쓰는 방식으로만 한다.
    """
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    if os.path.exists(TEMPLATE_FILE):
        return TEMPLATE_FILE, None
    if os.path.exists(LEGACY_TEMPLATE_FILE):
        shutil.copy2(LEGACY_TEMPLATE_FILE, TEMPLATE_FILE)
        return TEMPLATE_FILE, f"템플릿을 template 폴더로 옮겼습니다: {LEGACY_TEMPLATE_FILE} → {TEMPLATE_FILE}"
    return TEMPLATE_FILE, f"템플릿이 없습니다. 이 위치에 템플릿 XML을 넣어주세요: {TEMPLATE_FILE}"


# ============================================================================
# XML 헬퍼 (RLxExperiment 포맷)
# ============================================================================
def cmap(node: ET.Element) -> dict:
    return {c.tag: c for c in list(node)}


def find_loop(root: ET.Element, loop_runtype: str) -> ET.Element:
    for node in root.iter("no_name"):
        if node.attrib.get("runtype") == loop_runtype:
            return node
    raise RuntimeError(f"루프를 찾을 수 없습니다: {loop_runtype}")


def find_experiment_with_loop(root: ET.Element, loop_runtype: str) -> Optional[ET.Element]:
    for exp in root.iter("no_name"):
        if exp.attrib.get("runtype") != "RLxExperiment":
            continue
        ulp = cmap(exp).get("uLoopPars")
        if ulp is None:
            continue
        loops = list(ulp)
        if loops and loops[0].attrib.get("runtype") == loop_runtype:
            return exp
    return None


def fill_item_list(list_node: ET.Element, values, runtype: str):
    """item_NNNNN 리스트를 재구성. 원본 포맷의 공백(tail=' ')을 보존."""
    list_node[:] = []
    list_node.text = " "
    for i, value in enumerate(values):
        el = ET.SubElement(list_node, f"item_{i:05d}", {"runtype": runtype, "value": str(value)})
        el.tail = " "


def rebuild_indexed_list(list_node: ET.Element, values, default_runtype: str):
    """_NN 형태(접두사+번호) 리스트를 문자열 값 목록으로 재구성 (태그 스타일/공백 보존)."""
    children = list(list_node)
    prefix, width, runtype = "_", 2, default_runtype
    if children:
        m = re.match(r"^(.*?)(\d+)$", children[0].tag)
        if m:
            prefix, width = m.group(1), len(m.group(2))
        runtype = children[0].attrib.get("runtype", default_runtype)

    list_node[:] = []
    list_node.text = " "
    for i, value in enumerate(values):
        el = ET.SubElement(list_node, f"{prefix}{i:0{width}d}",
                           {"runtype": runtype, "value": str(value)})
        el.tail = " "


def rebuild_flag_list(list_node: ET.Element, count: int, value_for_index):
    """_NN 형태 bool 리스트를 재구성 (공백 보존)."""
    rebuild_indexed_list(
        list_node, ["true" if value_for_index(i) else "false" for i in range(count)], "bool")


def serialize(root: ET.Element) -> str:
    """원본(nd_ref) 스타일로 직렬화. (UTF-16 선언, compact self-closing, 공백 보존)"""
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    body = body.replace(" />", "/>").replace("&quot;", "&#x0022;")
    return '<?xml version="1.0" encoding="UTF-16"?>' + body


def write_nd_xml(root: ET.Element, out_path):
    with open(out_path, "w", encoding="utf-16", newline="") as fp:
        fp.write(serialize(root))


def get_filter_names(root: ET.Element) -> List[str]:
    """SpectLoop pPlaneDesc 의 sDescription(형광 필터명) 목록을 반환."""
    sl = find_loop(root, SPECT_LOOP)
    pd = cmap(sl).get("pPlaneDesc")
    names = []
    if pd is not None:
        for plane in list(pd):
            desc = cmap(plane).get("sDescription")
            names.append(desc.attrib.get("value") if desc is not None else "")
    return names


def apply_fluor_filters(root: ET.Element, enabled_flags):
    """SpectLoop 실험의 pItemValid 를 갱신하여 활성 형광 채널을 설정."""
    sl = find_loop(root, SPECT_LOOP)
    total = int(cmap(sl)["uiCount"].attrib.get("value", "0"))
    if len(enabled_flags) != total:
        raise ValueError(f"형광 채널 수는 {total}개여야 합니다. (현재 {len(enabled_flags)}개)")
    exp = find_experiment_with_loop(root, SPECT_LOOP)
    if exp is None:
        raise RuntimeError("SpectLoop 실험을 찾을 수 없습니다.")
    piv = cmap(exp).get("pItemValid")
    if piv is None:
        raise RuntimeError("SpectLoop 실험에 pItemValid 가 없습니다.")
    rebuild_flag_list(piv, total, lambda i: bool(enabled_flags[i]))


# ---- 형광 채널별 초점 오프셋 ----
# SpectLoop 의 pdOffset 이 채널별 Z 오프셋(µm), iOffsetReference 가 기준 채널이다.
# NIS ND Acquisition 의 λ 탭에서 채널마다 넣는 "Z offset" 값과 같다. (예: Cy3 = +9)
def get_fluor_offsets(root: ET.Element) -> List[float]:
    """SpectLoop pdOffset 의 채널별 초점 오프셋 목록을 반환. 없으면 빈 목록."""
    pdo = cmap(find_loop(root, SPECT_LOOP)).get("pdOffset")
    if pdo is None:
        return []
    values = []
    for el in list(pdo):
        try:
            values.append(float(el.attrib.get("value", "0")))
        except (TypeError, ValueError):
            values.append(0.0)
    return values


def apply_fluor_offsets(root: ET.Element, offsets, reference_channel=OFFSET_REFERENCE_CHANNEL):
    """SpectLoop 의 pdOffset/iOffsetReference 를 갱신. 기준 채널은 항상 0 으로 쓴다."""
    c = cmap(find_loop(root, SPECT_LOOP))
    total = int(c["uiCount"].attrib.get("value", "0"))
    if len(offsets) != total:
        raise ValueError(f"초점 오프셋 수는 {total}개여야 합니다. (현재 {len(offsets)}개)")
    pdo = c.get("pdOffset")
    if pdo is None:
        raise RuntimeError("SpectLoop 에 pdOffset 이 없어 초점 오프셋을 넣을 수 없습니다.")
    values = [float(v) for v in offsets]
    if 0 <= reference_channel < total:
        values[reference_channel] = 0.0
    rebuild_indexed_list(pdo, [_fmt(v) for v in values], "double")
    ref = c.get("iOffsetReference")
    if ref is not None:
        ref.attrib["value"] = str(reference_channel)


def set_top_level_after_capture_command(root: ET.Element, command_text: str):
    """최상위(타임루프, eType=1) 실험의 wsCommandAfterCapture 만 설정."""
    for exp in root.iter("no_name"):
        if exp.attrib.get("runtype") != "RLxExperiment":
            continue
        c = cmap(exp)
        e_type = c.get("eType")
        after_capture = c.get("wsCommandAfterCapture")
        if e_type is None or after_capture is None:
            continue
        if e_type.attrib.get("value") == "1":
            after_capture.attrib["value"] = command_text
            return


# ---- Z-Stack ----
def zstack_slice_count(z_range: float, z_step: float) -> int:
    """Range/Step 으로 슬라이스 수 계산. (test.xml: 25 / 2.5 -> 11)"""
    if z_step <= 0 or z_range < 0:
        raise ValueError("Z Range 는 0 이상, Step 은 0 보다 커야 합니다.")
    return int(round(z_range / z_step)) + 1


def build_zstack_loop(z_range: float, z_step: float, device: str = DEFAULT_Z_DEVICE) -> ET.Element:
    """RLxExpZStackLoop 노드를 새로 만든다. (원본 포맷의 공백 규칙 유지)"""
    values = dict(ZSTACK_FIXED)
    values["uiCount"] = str(zstack_slice_count(z_range, z_step))
    values["dZLow"] = _fmt(0.0)
    values["dZHigh"] = _fmt(z_range)
    values["dZHome"] = _fmt(z_range / 2.0)
    values["dZStep"] = _fmt(z_step)
    values["sZDevice"] = device or DEFAULT_Z_DEVICE

    loop = ET.Element("no_name", {"runtype": Z_LOOP})
    loop.text = " "
    for tag, runtype in ZSTACK_FIELDS:
        el = ET.SubElement(loop, tag, {"runtype": runtype, "value": values[tag]})
        el.tail = " "
    return loop


def _set_container(node: ET.Element, children):
    """CLxListVariant 컨테이너의 자식을 교체하며 원본 공백 스타일을 유지."""
    node[:] = []
    node.text = " "
    for child in children:
        child.tail = " "
        node.append(child)


def find_zstack_experiment(root: ET.Element) -> Optional[ET.Element]:
    return find_experiment_with_loop(root, Z_LOOP)


def _find_parent_experiment(root: ET.Element, target: ET.Element) -> Optional[ET.Element]:
    """target 을 ppNextLevelEx 로 품고 있는 상위 실험을 찾는다."""
    for exp in root.iter("no_name"):
        if exp.attrib.get("runtype") != "RLxExperiment":
            continue
        nxt = cmap(exp).get("ppNextLevelEx")
        if nxt is not None and target in list(nxt):
            return exp
    return None


def apply_zstack(root: ET.Element, enabled: bool, z_range: float = DEFAULT_Z_RANGE,
                 z_step: float = DEFAULT_Z_STEP, device: str = DEFAULT_Z_DEVICE):
    """Z-Stack 루프를 켜거나 끈다.

    켤 때는 XY 실험(eType=2)과 Spect 실험(eType=6) 사이에 Z 실험(eType=4)을 끼워 넣는다.
    Z 실험 래퍼는 XY 실험과 eType 값만 다르므로(test.xml 확인) XY 래퍼를 복제해 만든다.
    끌 때는 Z 실험을 걷어내고 하위 실험을 상위로 끌어올린다.
    """
    z_exp = find_zstack_experiment(root)

    if not enabled:
        if z_exp is None:
            return False
        parent = _find_parent_experiment(root, z_exp)
        if parent is None:
            raise RuntimeError("Z-Stack 실험의 상위 실험을 찾을 수 없습니다.")
        inner = list(cmap(z_exp)["ppNextLevelEx"])
        _set_container(cmap(parent)["ppNextLevelEx"], inner)
        return True

    loop = build_zstack_loop(z_range, z_step, device)

    if z_exp is not None:
        # 이미 있으면 루프 파라미터만 교체
        _set_container(cmap(z_exp)["uLoopPars"], [loop])
        return True

    xy_exp = find_experiment_with_loop(root, XY_LOOP)
    if xy_exp is None:
        raise RuntimeError("XY 실험을 찾을 수 없어 Z-Stack 을 넣을 수 없습니다.")
    xy_next = cmap(xy_exp)["ppNextLevelEx"]
    inner = list(xy_next)  # Spect 실험 (하위 레벨)
    if not inner:
        raise RuntimeError("XY 실험 하위에 Spect 실험이 없어 Z-Stack 을 넣을 수 없습니다.")

    z_exp = copy.deepcopy(xy_exp)
    cz = cmap(z_exp)
    cz["eType"].attrib["value"] = ETYPE_ZSTACK
    _set_container(cz["uLoopPars"], [loop])
    _set_container(cz["pItemValid"], [])   # Z 실험은 항목별 유효 플래그를 쓰지 않는다
    _set_container(cz["ppNextLevelEx"], inner)
    _set_container(xy_next, [z_exp])
    return True


def get_zstack_params(root: ET.Element) -> Optional[dict]:
    """현재 XML의 Z-Stack 설정을 읽어 dict 로 반환. 없으면 None."""
    z_exp = find_zstack_experiment(root)
    if z_exp is None:
        return None
    c = cmap(find_loop(root, Z_LOOP))

    def num(tag, default=0.0):
        el = c.get(tag)
        try:
            return float(el.attrib.get("value")) if el is not None else default
        except (TypeError, ValueError):
            return default

    low, high = num("dZLow"), num("dZHigh")
    dev = c.get("sZDevice")
    return {
        "range": high - low,
        "step": num("dZStep", DEFAULT_Z_STEP),
        "count": int(num("uiCount", 0)),
        "device": dev.attrib.get("value", DEFAULT_Z_DEVICE) if dev is not None else DEFAULT_Z_DEVICE,
    }


# ---- Z-Stack 적용 채널 ----
# Z 루프는 형광(Spect) 루프를 통째로 감싸므로, 한 파일 안에서 채널마다 Z를 다르게 줄 수 없다.
# 대신 nd_output 은 이미 채널별로 파일을 나누므로, 파일마다 Z 루프를 넣거나 빼서
# "BF만 Z-Stack, 나머지는 초점면 1장" 같은 구성을 만든다.
def channel_uses_zstack(spec: Optional[dict], ch: int) -> bool:
    """채널 하나가 Z-Stack 대상인지 판단. spec 에 channels 가 없으면 전 채널 적용(구버전 호환)."""
    if not spec or not spec.get("enabled"):
        return False
    channels = spec.get("channels")
    if channels is None:
        return True
    return ch < len(channels) and bool(channels[ch])


def zstack_applies(spec: Optional[dict], ch_flags) -> bool:
    """이 채널 조합(파일 한 개)에 Z-Stack 을 적용할지 판단."""
    return any(channel_uses_zstack(spec, i) for i, v in enumerate(ch_flags) if int(v))


# ---- XY 위치(포인트) 관련 ----
def extract_corners(root: ET.Element):
    """입력에서 앞 4개 위치를 [LTfirst, TR, BR, LTlast] 순으로 반환.
    RLxExperiment XYPos 형식과 단순 CLxListVariant/Point 형식을 모두 지원(자동 감지)."""
    # 1) XYPosLoop (RLxExperiment / 4porint-reference 형식)
    try:
        c = cmap(find_loop(root, XY_LOOP))
        xs = [float(e.attrib["value"]) for e in list(c["dPosX"])]
        ys = [float(e.attrib["value"]) for e in list(c["dPosY"])]
        zs = [float(e.attrib["value"]) for e in list(c["dPosZ"])]
        if len(xs) >= 4:
            return [(xs[k], ys[k], zs[k]) for k in range(4)]
    except RuntimeError:
        pass
    # 2) 단순 Point 형식 (CLxListVariant)
    coords = []
    for pt in [e for e in root.iter() if e.tag.startswith("Point")]:
        x = pt.find("dXPosition"); y = pt.find("dYPosition"); z = pt.find("dZPosition")
        if x is None or y is None or z is None:
            continue
        xv, yv, zv = x.get("value"), y.get("value"), z.get("value")
        if xv and yv and zv:
            coords.append((float(xv), float(yv), float(zv)))
    if len(coords) >= 4:
        return coords[:4]
    raise RuntimeError("입력 파일에서 4개의 모서리 위치를 찾을 수 없습니다. (XYPosLoop 또는 Point 형식 필요)")


def make_initial_4point(reference_path, output_path, corners=None):
    """4porint-reference.xml 구조를 기반으로 4모서리를 채운 초기 4point 파일 생성.
    corners: [(name, x, y, z), ...] (None이면 DEFAULT_CORNERS 사용)."""
    if not os.path.exists(reference_path):
        raise RuntimeError(f"참조 파일이 없습니다: {reference_path}")
    corners = corners or DEFAULT_CORNERS
    root = ET.parse(reference_path).getroot()
    records = [(name, x, y, z, "-1.000000000000000") for (name, x, y, z) in corners]
    set_xy_records(root, records)
    write_nd_xml(root, output_path)
    return output_path, len(records)


def extract_points_from_xyloop(root: ET.Element):
    """XYPosLoop 에서 (name, x_str, y_str, z_str, pfs_str) 레코드 목록을 반환 (문자열 보존)."""
    c = cmap(find_loop(root, XY_LOOP))
    names = [e.attrib.get("value", "") for e in list(c["pPosName"])]
    xs = [e.attrib.get("value", "0") for e in list(c["dPosX"])]
    ys = [e.attrib.get("value", "0") for e in list(c["dPosY"])]
    zs = [e.attrib.get("value", "0") for e in list(c["dPosZ"])]
    pfs = [e.attrib.get("value", "-1.000000000000000") for e in list(c["dPFSOffset"])]
    records = []
    for i in range(len(names)):
        records.append((
            names[i],
            xs[i] if i < len(xs) else "0",
            ys[i] if i < len(ys) else "0",
            zs[i] if i < len(zs) else "0",
            pfs[i] if i < len(pfs) else "-1.000000000000000",
        ))
    return records


def set_xy_records(root: ET.Element, records):
    """records: [(name, x_str, y_str, z_str, pfs_str), ...] 를 XYPosLoop 에 채우고 카운트 동기화."""
    c = cmap(find_loop(root, XY_LOOP))
    fill_item_list(c["dPosX"], [r[1] for r in records], "double")
    fill_item_list(c["dPosY"], [r[2] for r in records], "double")
    fill_item_list(c["dPosZ"], [r[3] for r in records], "double")
    fill_item_list(c["dPFSOffset"], [r[4] for r in records], "double")
    fill_item_list(c["pPosName"], [r[0] for r in records], "CLxStringW")
    c["uiCount"].attrib["value"] = str(len(records))

    # XYPos 실험의 pItemValid 를 위치 수에 맞게 동기화 (모두 true)
    exp = find_experiment_with_loop(root, XY_LOOP)
    if exp is not None:
        piv = cmap(exp).get("pItemValid")
        if piv is not None and len(list(piv)) > 0:
            rebuild_flag_list(piv, len(records), lambda i: True)


def _name_key(name: str):
    """정렬 키: 라인 라벨 + 번호. 예: A01 -> ('A', 1)"""
    m = re.match(r"^([A-Za-z]+)(\d+)$", (name or "").strip())
    if not m:
        return ("", 0)
    return (m.group(1).upper(), int(m.group(2)))


# ============================================================================
# 메시 생성
# ============================================================================
def generate_mesh(left_top, top_right, bottom_right, rows, cols):
    lt_x, lt_y, lt_z = left_top
    rt_x, rt_y, rt_z = top_right
    br_x, br_y, br_z = bottom_right
    lb_x, lb_y, lb_z = lt_x + (br_x - rt_x), lt_y + (br_y - rt_y), lt_z + (br_z - rt_z)

    x_linspace = np.linspace(0, 1, cols)
    y_linspace = np.linspace(0, 1, rows)
    matrix = []
    for i in range(rows):
        row = []
        for j in range(cols):
            if i == 0 and j == 0:
                x, y, z = lt_x, lt_y, lt_z
            else:
                ax, ay = x_linspace[j], y_linspace[i]
                x = (1 - ax) * ((1 - ay) * lt_x + ay * lb_x) + ax * ((1 - ay) * rt_x + ay * br_x)
                y = (1 - ax) * ((1 - ay) * lt_y + ay * lb_y) + ax * ((1 - ay) * rt_y + ay * br_y)
                z = (1 - ax) * ((1 - ay) * lt_z + ay * lb_z) + ax * ((1 - ay) * rt_z + ay * br_z)
            row.append((x, y, z))
        matrix.append(row)
    return matrix


def generate_offset_meshes(ltf, ltl, tr, br, rows, cols, repetitions):
    if repetitions < 1:
        raise ValueError("반복 횟수는 1 이상이어야 합니다.")
    if repetitions == 1:
        dx = dy = dz = 0.0
    else:
        dx = (ltl[0] - ltf[0]) / (repetitions - 1)
        dy = (ltl[1] - ltf[1]) / (repetitions - 1)
        dz = (ltl[2] - ltf[2]) / (repetitions - 1)

    base = generate_mesh(ltf, tr, br, rows, cols)
    out = []
    for r in range(repetitions):
        ox, oy, oz = r * dx, r * dy, r * dz
        out.append([[(p[0] + ox, p[1] + oy, p[2] + oz) for p in row] for row in base])
    return out


def iter_point_slots(rows, cols, repetitions, start_idx=None, end_idx=None, delete_numbers=None):
    """유지되는 포인트마다 (line_idx, i, j, name) 을 yield. 좌표 불필요 → 카운트/미리보기 공용."""
    delete_numbers = delete_numbers or set()
    sorted_del = sorted(delete_numbers)
    for line_idx in range(repetitions):
        if line_idx >= len(LINE_LABELS):
            break
        for i in range(rows):
            for j in range(cols):
                pn = i * cols + j + 1
                if pn in delete_numbers:
                    continue
                shifted = pn - bisect_right(sorted_del, pn)
                if start_idx is not None and end_idx is not None:
                    if not (start_idx < shifted <= end_idx):
                        continue
                yield line_idx, i, j, f"{LINE_LABELS[line_idx]}{shifted:02d}"


def build_point_records(all_meshes, rows, cols, start_idx=None, end_idx=None, delete_numbers=None):
    """메시 -> [(name, x_str, y_str, z_str, pfs_str)] (기존 명명/필터 규칙 유지)."""
    repetitions = len(all_meshes)
    records = []
    for line_idx, i, j, name in iter_point_slots(rows, cols, repetitions, start_idx, end_idx, delete_numbers):
        x, y, z = all_meshes[line_idx][i][j]
        records.append((name, _fmt(x), _fmt(y), _fmt(z), "-1.000000000000000"))
    return records


def estimate_output(point_count, positions_per_file, files_per_group):
    """(그룹 수, 파일 수) 추정. 유효하지 않으면 (0, 0).

    files_per_group 은 build_channel_sets 가 만드는 파일 벌 수(그룹 1개당 파일 수)다.
    """
    if point_count <= 0 or positions_per_file <= 0:
        return 0, 0
    groups = (point_count + positions_per_file - 1) // positions_per_file
    return groups, groups * max(files_per_group, 0)


# ============================================================================
# 1단계: nd_4point -> nd_full
# ============================================================================
def _apply_zstack_spec(root: ET.Element, spec: dict, log=None):
    """UI에서 넘어온 zstack dict 를 XML에 반영하고 결과를 로그로 남긴다."""
    log = log or (lambda m: None)
    enabled = bool(spec.get("enabled"))
    if enabled:
        z_range = float(spec.get("range", DEFAULT_Z_RANGE))
        z_step = float(spec.get("step", DEFAULT_Z_STEP))
        device = spec.get("device") or DEFAULT_Z_DEVICE
        apply_zstack(root, True, z_range, z_step, device)
        log(f"Z-Stack 적용: Range {z_range:g} µm, Step {z_step:g} µm, "
            f"{zstack_slice_count(z_range, z_step)} 슬라이스, 장치 '{device}'")
    else:
        if apply_zstack(root, False):
            log("Z-Stack 제거: 템플릿에 있던 Z 루프를 걷어냈습니다.")



def generate_full(input_path, template_path, output_path, rows, cols, repetitions,
                  start_idx=None, end_idx=None, delete_numbers=None,
                  fluor_flags=None, fluor_offsets=None, zstack=None, log_callback=None):
    """
    4모서리(입력)를 읽어 메시를 생성하고, full 템플릿(RLxExperiment 전체 구조)에 채워
    nd_full.xml 을 생성. 반환: (output_path, 포인트수).
    - input_path: 4point 파일 (XYPos 또는 단순 Point 형식, 자동 감지)
    - template_path: full 구조 템플릿 (TimeLoop›XYPos›Spect, 형광필터 포함)
    - fluor_offsets: 채널별 초점 오프셋(µm, 기준 채널 대비) 또는 None(템플릿 값 유지)
    - zstack: {"enabled": bool, "range": float, "step": float, "device": str} 또는 None(그대로 둠)
    """
    log = log_callback or (lambda m: None)

    in_root = ET.parse(input_path).getroot()
    corners = extract_corners(in_root)  # [LTfirst, TR, BR, LTlast]
    log(f"모서리 좌표: LTfirst={corners[0]}, TR={corners[1]}, BR={corners[2]}, LTlast={corners[3]}")

    meshes = generate_offset_meshes(corners[0], corners[3], corners[1], corners[2],
                                    rows, cols, repetitions)
    records = build_point_records(meshes, rows, cols, start_idx, end_idx, delete_numbers)
    if not records:
        raise RuntimeError("생성된 포인트가 없습니다. (범위/삭제 설정 확인)")

    tmpl_root = ET.parse(template_path).getroot()
    set_xy_records(tmpl_root, records)
    if fluor_flags is not None:
        apply_fluor_filters(tmpl_root, fluor_flags)
    if fluor_offsets is not None:
        apply_fluor_offsets(tmpl_root, fluor_offsets)
    if zstack is not None:
        # full 은 모든 채널을 한 파일에 담으므로 채널별 구분을 할 수 없다.
        # 적용 대상 채널이 하나라도 있으면 Z 루프를 넣고, 채널별 분리는 2단계에서 한다.
        spec = dict(zstack)
        if spec.get("enabled") and fluor_flags is not None:
            spec["enabled"] = zstack_applies(spec, fluor_flags)
            if not spec["enabled"]:
                log("Z-Stack 적용 채널이 선택된 형광 채널에 하나도 없어 full 에서 Z 루프를 뺍니다.")
        _apply_zstack_spec(tmpl_root, spec, log)

    write_nd_xml(tmpl_root, output_path)
    log(f"full 생성 완료: {output_path}  (포인트 {len(records)}개: {records[0][0]}..{records[-1][0]})")
    return output_path, len(records)


# ============================================================================
# 2단계: nd_full -> nd_output (그룹 분할 + 형광채널 분리 + 체이닝)
# ============================================================================
def build_channel_sets(fluor_flags, split_fluor, zstack=None):
    """출력 파일 한 개당 (파일 접미사, 채널 플래그, Z-Stack 적용 여부) 를 만든다.

    - 채널별 분리: 채널 하나당 파일 하나. Z 적용 여부는 그 채널의 설정을 그대로 따른다.
    - 분리 안 함: 원래는 한 파일에 모든 채널을 담지만, Z 적용 채널과 초점면 전용 채널이
      섞여 있으면 Z 루프가 형광 루프 전체를 감싸므로 한 파일로 표현할 수 없다.
      이 경우에만 zstack/plane 두 벌로 나눈다. (섞이지 않으면 기존대로 한 파일)
    """
    flags = [1 if int(v) != 0 else 0 for v in fluor_flags]
    enabled = [i for i, v in enumerate(flags) if v == 1]
    if not enabled:
        raise ValueError("최소 1개의 형광 채널을 선택하세요.")

    def mask(channels):
        one = [0] * len(flags)
        for ch in channels:
            one[ch] = 1
        return one

    if split_fluor:
        return [(f"F{order_idx}", mask([ch]), channel_uses_zstack(zstack, ch))
                for order_idx, ch in enumerate(enabled, start=1)]

    z_channels = [ch for ch in enabled if channel_uses_zstack(zstack, ch)]
    plane_channels = [ch for ch in enabled if not channel_uses_zstack(zstack, ch)]
    if not z_channels or not plane_channels:
        return [("all", flags, bool(z_channels))]
    return [("zstack", mask(z_channels), True),
            ("plane", mask(plane_channels), False)]


def generate_nd_output(full_path, out_dir, output_prefix="nd", positions_per_file=36,
                       fluor_flags=(0, 0, 1, 0, 0, 0, 0, 0, 0), split_fluor=True,
                       fluor_offsets=None, zstack=None, clear_existing=False,
                       log_callback=None):
    """full 파일을 그룹/채널별로 분할하여 nd_output 파일들을 생성. 반환: 생성 경로 리스트.

    fluor_offsets 를 주면 full 을 다시 만들지 않아도 현재 UI 의 초점 오프셋이 파일마다 반영된다.
    clear_existing 이면 쓰기 전에 out_dir 바로 아래의 *.xml 을 모두 지운다.
    """
    log = log_callback or (lambda m: None)
    if positions_per_file <= 0:
        raise ValueError("그룹당 포인트 수는 1 이상이어야 합니다.")

    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)

    full_root = ET.parse(full_path).getroot()
    records = extract_points_from_xyloop(full_root)
    if not records:
        raise RuntimeError("full 파일에서 포인트를 찾지 못했습니다.")
    records.sort(key=lambda r: _name_key(r[0]))

    group_total = (len(records) + positions_per_file - 1) // positions_per_file
    index_width = max(2, len(str(group_total)))
    channel_sets = build_channel_sets(fluor_flags, split_fluor, zstack)
    if zstack is not None and zstack.get("enabled"):
        z_sets = [s for s, _, use_z in channel_sets if use_z]
        log(f"  Z-Stack 적용 파일: {', '.join(z_sets) if z_sets else '없음'}"
            f" / 초점면 1장: {', '.join(s for s, _, use_z in channel_sets if not use_z) or '없음'}")

    planned = []
    group_count = 0
    for start in range(0, len(records), positions_per_file):
        group_count += 1
        group = records[start:start + positions_per_file]
        base_name = f"{output_prefix}{group_count:0{index_width}d}"
        for suffix, ch_flags, use_z in channel_sets:
            out_name = f"{base_name}.xml" if suffix == "all" else f"{base_name}-{suffix}.xml"
            planned.append((group, ch_flags, use_z, out_name))

    if clear_existing:
        # 지난 생성분(다른 채널 조합 등)이 섞여 헷갈리지 않도록 폴더의 XML 을 먼저 비운다.
        # 하위 폴더나 XML 이 아닌 파일은 건드리지 않는다. (지난 결과는 archive 에 보관됨)
        removed = 0
        for old in out_dir_p.glob("*.xml"):
            try:
                old.unlink()
                removed += 1
            except OSError as e:
                log(f"  기존 파일 삭제 실패: {old.name} ({e})")
        if removed:
            log(f"  출력 폴더 비움: 기존 XML {removed}개 삭제")

    created = []
    for idx, (group, ch_flags, use_z, out_name) in enumerate(planned):
        out_path = out_dir_p / out_name
        next_file = planned[idx + 1][3] if idx + 1 < len(planned) else None

        nd_root = copy.deepcopy(full_root)
        set_xy_records(nd_root, group)
        apply_fluor_filters(nd_root, ch_flags)
        if fluor_offsets is not None:
            apply_fluor_offsets(nd_root, fluor_offsets)
        if zstack is not None:
            # full 을 다시 만들지 않고 2단계만 실행해도 현재 UI 설정이 반영된다.
            # 파일마다 Z 루프를 넣거나 빼서 채널별 Z-Stack 을 구현한다.
            _apply_zstack_spec(nd_root, dict(zstack, enabled=use_z))

        if next_file is not None:
            next_path = (out_dir_p / next_file).resolve()
            set_top_level_after_capture_command(nd_root, f'ND_LoadExperiment("{next_path}");')
        else:
            set_top_level_after_capture_command(nd_root, "")

        write_nd_xml(nd_root, out_path)
        created.append(str(out_path))
        z_note = ""
        if zstack is not None and zstack.get("enabled"):
            z_note = " · Z-Stack" if use_z else " · 초점면 1장"
        log(f"생성: {out_path} ({len(group)} points: {group[0][0]}..{group[-1][0]}){z_note}")

    log(f"완료. 총 포인트: {len(records)}, 그룹: {group_count}, 파일: {len(created)}")
    return created


# ============================================================================
# GUI
# ============================================================================
class NDGeneratorApp:
    def __init__(self, master):
        self.master = master
        self.master.title("ND Generator (4point -> full -> nd_output)")

        self.config = self.load_config()

        self._window_geometry = self._initial_geometry()
        self.master.geometry(self._window_geometry)
        self.master.minsize(*MIN_WINDOW_SIZE)
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.monitoring = False
        self.monitor_thread = None
        self.last_modified = None
        self._check_interval_seconds = 0.5

        # ---- 파일 ----
        self.input_file = tk.StringVar(
            value=from_portable_path(self.config.get("input_file"), DEFAULT_INPUT_FILE))
        self.output_file = tk.StringVar(
            value=from_portable_path(self.config.get("output_file"), DEFAULT_OUTPUT_FILE))
        # 템플릿은 UI에서 고르지 않고 template 폴더의 고정 파일을 쓴다.
        template_path, self._template_notice = ensure_template_file()
        self.template_file = tk.StringVar(value=template_path)
        self.check_interval = tk.DoubleVar(value=self.config.get("check_interval", 0.5))

        # ---- 메시 ----
        self.mesh_rows = tk.IntVar(value=self.config.get("mesh_rows", 2))
        self.mesh_cols = tk.IntVar(value=self.config.get("mesh_cols", 54))
        self.num_repetitions = tk.IntVar(value=self.config.get("num_repetitions", 4))
        self.point_start_idx = tk.StringVar(value=str(self.config.get("point_start_idx", "")))
        self.point_end_idx = tk.StringVar(value=str(self.config.get("point_end_idx", "")))
        self.delete_numbers = tk.StringVar(value=str(self.config.get("delete_numbers", "")))
        self.mesh_preset = tk.StringVar(value=self._resolve_saved_preset())
        self.mesh_spinboxes = []

        # ---- 형광 필터 ----
        default_flags = [False, False, True, False, False, False, False, False, False]
        saved_flags = self.config.get("fluor_flags", default_flags)
        self.fluor_flags = []
        for i in range(NUM_FLUOR_CHANNELS):
            val = bool(saved_flags[i]) if i < len(saved_flags) else False
            self.fluor_flags.append(tk.BooleanVar(value=val))
        self.filter_names = self.config.get("filter_names") or [f"Ch{i+1}" for i in range(NUM_FLUOR_CHANNELS)]
        self.filter_checkbuttons = []

        # ---- 형광 채널별 초점 오프셋 (µm, 기준 채널 BF=0 대비) ----
        # 설정 파일에 없으면(첫 실행) 템플릿의 pdOffset 값을 초기값으로 쓴다. (예: Cy3 = +9)
        saved_offsets = self.config.get("fluor_offsets")
        if saved_offsets is None:
            saved_offsets = self._template_offsets()
        self.fluor_offsets = []
        for i in range(NUM_FLUOR_CHANNELS):
            val = saved_offsets[i] if i < len(saved_offsets) else 0
            self.fluor_offsets.append(tk.StringVar(value=self._offset_text(val)))
        self.offset_entries = []

        # ---- ND output ----
        self.nd_output_dir = tk.StringVar(
            value=from_portable_path(self.config.get("nd_output_dir"),
                                     os.path.join(ND_REF_DIR, "nd_output")))
        self.nd_output_prefix = tk.StringVar(value=self.config.get("nd_output_prefix", "nd"))
        self.nd_positions_per_file = tk.IntVar(value=self.config.get("nd_positions_per_file", 36))
        self.nd_split_fluor = tk.BooleanVar(value=self.config.get("nd_split_fluor", True))
        self.archive_enabled = tk.BooleanVar(value=self.config.get("archive_enabled", True))
        # 생성 전에 출력 폴더의 기존 XML 을 지운다. (지난 결과는 archive 에 남으므로 기본 켬)
        self.nd_clear_output = tk.BooleanVar(value=self.config.get("nd_clear_output", True))
        # 생성 후 NIS 매크로(nd_output_autorun.mac)를 생성 파일 목록으로 다시 쓴다.
        self.macro_enabled = tk.BooleanVar(value=self.config.get("macro_enabled", True))
        self.macro_file = tk.StringVar(value=self.config.get("macro_file") or DEFAULT_MACRO_FILE)

        # ---- Z-Stack ----
        self.zstack_enabled = tk.BooleanVar(value=self.config.get("zstack_enabled", False))
        self.zstack_range = tk.StringVar(value=str(self.config.get("zstack_range", DEFAULT_Z_RANGE)))
        self.zstack_step = tk.StringVar(value=str(self.config.get("zstack_step", DEFAULT_Z_STEP)))
        self.zstack_device = tk.StringVar(value=self.config.get("zstack_device") or DEFAULT_Z_DEVICE)
        self.zstack_summary = tk.StringVar(value="")
        self.zstack_widgets = []
        # Z-Stack 을 적용할 채널 (체크 안 된 채널은 현재 초점면 1장만 촬영)
        saved_z_channels = self.config.get("zstack_channel_flags")
        self.zstack_channel_flags = []
        for i in range(NUM_FLUOR_CHANNELS):
            val = True if saved_z_channels is None else (
                bool(saved_z_channels[i]) if i < len(saved_z_channels) else False)
            self.zstack_channel_flags.append(tk.BooleanVar(value=val))
        self.zstack_channel_checkbuttons = []

        # 실시간 예상 결과 표시용
        self.estimate_var = tk.StringVar(value="")

        self.setup_ui()
        # 자식 위젯이 사라질 때도 이 이벤트가 오므로 창 자체가 닫힐 때만 저장한다.
        self.master.bind('<Destroy>',
                         lambda e: self.save_config() if e.widget is self.master else None)
        self.master.after(200, self._show_path_ends)

        # 설정 변경 시 예상 결과 실시간 갱신
        watched = [self.mesh_rows, self.mesh_cols, self.num_repetitions,
                   self.point_start_idx, self.point_end_idx, self.delete_numbers,
                   self.nd_positions_per_file, self.nd_split_fluor,
                   self.zstack_enabled, self.zstack_range, self.zstack_step
                   ] + self.fluor_flags + self.zstack_channel_flags + self.fluor_offsets
        for var in watched:
            var.trace_add('write', lambda *a: self.update_estimate())

        if self._template_notice:
            self.log_message(self._template_notice)

        # 시작 시 템플릿에서 형광 필터명 로드 시도
        self.refresh_filter_names(silent=True)
        self.update_estimate()

    # ---------------- 창 크기/위치 ----------------
    def _initial_geometry(self) -> str:
        """지난번 창 크기/위치를 되살린다. 없거나 화면 밖이면 기본 배치(화면 왼쪽, 세로로 길게)."""
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()
        m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", str(self.config.get("window_geometry", "")))
        if m:
            w, h, x, y = (int(v) for v in m.groups())
            if (w >= MIN_WINDOW_SIZE[0] and h >= MIN_WINDOW_SIZE[1]
                    and x + w > 100 and x < screen_w - 100 and -20 <= y < screen_h - 100):
                return m.group(0)
        width, height = DEFAULT_WINDOW_SIZE
        # 72 = 작업 표시줄 + 제목 표시줄 여유
        return f"{min(width, screen_w)}x{min(height, screen_h - 72)}+0+0"

    def _current_geometry(self) -> str:
        """저장할 창 크기/위치. 최대화/최소화 상태이거나 창이 이미 닫혔으면 마지막 값을 쓴다."""
        try:
            if self.master.state() == "normal":
                self._window_geometry = self.master.geometry()
        except tk.TclError:
            pass
        return self._window_geometry

    # ---------------- 메시 프리셋 ----------------
    def _resolve_saved_preset(self) -> str:
        """저장된 프리셋 키를 검증한다.

        저장값이 프리셋이지만 rows/cols/reps가 그 프리셋과 다르면
        (예: 설정 파일을 직접 수정한 경우) 커스텀으로 되돌린다.
        """
        current = (self.mesh_rows.get(), self.mesh_cols.get(), self.num_repetitions.get())
        saved = self.config.get("mesh_preset")
        if saved is None:
            # 이전 버전 설정 파일 — 값이 프리셋과 같으면 그 프리셋으로 시작
            for key, (_, rows, cols, reps) in MESH_PRESETS.items():
                if current == (rows, cols, reps):
                    return key
            return CUSTOM_PRESET
        if saved not in MESH_PRESETS:
            return CUSTOM_PRESET
        _, rows, cols, reps = MESH_PRESETS[saved]
        return saved if current == (rows, cols, reps) else CUSTOM_PRESET

    def on_preset_change(self):
        """프리셋 선택에 맞춰 rows/cols/reps 값과 입력 가능 여부를 갱신."""
        key = self.mesh_preset.get()
        preset = MESH_PRESETS.get(key)
        if preset:
            _, rows, cols, reps = preset
            self.mesh_rows.set(rows)
            self.mesh_cols.set(cols)
            self.num_repetitions.set(reps)
        state = tk.NORMAL if preset is None else tk.DISABLED
        for sb in self.mesh_spinboxes:
            sb.configure(state=state)

    # ---------------- UI ----------------
    def _path_entry(self, parent, variable, **kwargs):
        """경로용 Entry. 폭이 좁아도 파일명이 보이도록 끝부분을 보여준다."""
        entry = ttk.Entry(parent, textvariable=variable, **kwargs)
        self._path_entries.append(entry)
        variable.trace_add('write', lambda *a: self.master.after_idle(self._show_path_ends))
        return entry

    def _show_path_ends(self):
        try:
            focused = self.master.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        for entry in self._path_entries:
            if entry is not focused:        # 입력 중인 칸은 건드리지 않는다
                entry.xview_moveto(1)

    def _on_main_resize(self, event):
        """창 폭이 바뀌면 줄바꿈 폭을 다시 잡는다. (좁은 창에서도 글자가 잘리지 않게)"""
        if event.widget is not self.main_frame or event.width == self._layout_width:
            return
        self._layout_width = event.width
        for label, margin in self._wrap_labels:
            label.configure(wraplength=max(event.width - margin, 200))
        self._show_path_ends()

    def setup_ui(self):
        # 기준 창 크기: 화면 왼쪽에 세로로 길게 둔 배치 (약 630 × 1370).
        # 가로는 좁게 쓰고, 남는 세로 공간은 실행 결과와 로그에 준다.
        main = ttk.Frame(self.master, padding="10")
        main.grid(row=0, column=0, sticky="nsew")
        self.main_frame = main
        self._layout_width = 0
        self._wrap_labels = []      # (라벨, 창 폭에서 뺄 여백)
        self._path_entries = []

        style = ttk.Style()
        # 기본 탭은 글자에 비해 좁아서 좌우 여백만 넓힌다.
        # 세로(두 번째 값)를 올리면 탭이 두꺼워져 비율이 어색해지므로 0으로 둔다.
        style.configure("Main.TNotebook.Tab", padding=(12, 0))
        style.configure("Primary.TButton", font=("Arial", 10, "bold"), padding=(10, 6))

        # 파일 설정
        ff = ttk.LabelFrame(main, text="파일 설정", padding="10")
        ff.grid(row=0, column=0, sticky="we", pady=5)
        ttk.Label(ff, text="입력 4point XML:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=3)
        self._path_entry(ff, self.input_file, width=20).grid(row=0, column=1, sticky="we", pady=3)
        ttk.Button(ff, text="찾아보기", command=self.browse_input, width=9).grid(row=0, column=2, padx=(4, 2), pady=3)
        ttk.Button(ff, text="4point 초기화", command=self.init_4point).grid(row=0, column=3, sticky="we", pady=3)
        ttk.Label(ff, text="템플릿 XML:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=3)
        self._path_entry(ff, self.template_file, width=20,
                         state="readonly").grid(row=1, column=1, sticky="we", pady=3)
        ttk.Button(ff, text="폴더 열기", command=self.open_template_dir,
                   width=9).grid(row=1, column=2, padx=(4, 2), pady=3)
        ttk.Button(ff, text="템플릿 새로고침", command=self.reload_template).grid(
            row=1, column=3, sticky="we", pady=3)
        ttk.Label(ff, text="출력 full XML:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5), pady=3)
        self._path_entry(ff, self.output_file, width=20).grid(row=2, column=1, sticky="we", pady=3)
        ttk.Button(ff, text="찾아보기", command=self.browse_output, width=9).grid(row=2, column=2, padx=(4, 2), pady=3)
        ff.columnconfigure(1, weight=1)

        # 메시 설정
        mf = ttk.LabelFrame(main, text="메시 설정 (1단계: 4point → full)", padding="10")
        mf.grid(row=1, column=0, sticky="we", pady=5)
        ttk.Label(mf, text="프리셋:").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        pf = ttk.Frame(mf)
        pf.grid(row=0, column=1, sticky=tk.W, pady=3)
        for key, (label, rows, cols, reps) in MESH_PRESETS.items():
            ttk.Radiobutton(pf, text=f"{label} ({rows}, {cols}, {reps})",
                            variable=self.mesh_preset, value=key,
                            command=self.on_preset_change).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Radiobutton(pf, text="커스텀 (직접 입력)",
                        variable=self.mesh_preset, value=CUSTOM_PRESET,
                        command=self.on_preset_change).pack(side=tk.LEFT)

        ttk.Label(mf, text="메시:").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        sf = ttk.Frame(mf)
        sf.grid(row=1, column=1, sticky=tk.W, pady=3)
        ttk.Label(sf, text="Rows (X)").pack(side=tk.LEFT)
        sb_rows = ttk.Spinbox(sf, from_=1, to=10, textvariable=self.mesh_rows, width=6)
        sb_rows.pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(sf, text="Cols (Y)").pack(side=tk.LEFT)
        sb_cols = ttk.Spinbox(sf, from_=1, to=200, textvariable=self.mesh_cols, width=6)
        sb_cols.pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(sf, text="반복 횟수").pack(side=tk.LEFT)
        sb_reps = ttk.Spinbox(sf, from_=1, to=10, textvariable=self.num_repetitions, width=6)
        sb_reps.pack(side=tk.LEFT, padx=(4, 0))
        self.mesh_spinboxes = [sb_rows, sb_cols, sb_reps]
        self.on_preset_change()

        ttk.Label(mf, text="구간:").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        rf = ttk.Frame(mf)
        rf.grid(row=2, column=1, sticky=tk.W, pady=3)
        ttk.Label(rf, text="시작").pack(side=tk.LEFT)
        ttk.Entry(rf, textvariable=self.point_start_idx, width=6).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(rf, text="끝").pack(side=tk.LEFT)
        ttk.Entry(rf, textvariable=self.point_end_idx, width=6).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(rf, text="비우면 전체 (예: 0, 15)", foreground="#666666").pack(side=tk.LEFT)

        ttk.Label(mf, text="삭제 번호:").grid(row=3, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        df = ttk.Frame(mf)
        df.grid(row=3, column=1, sticky=tk.W, pady=3)
        ttk.Entry(df, textvariable=self.delete_numbers, width=24).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(df, text="쉼표로 구분 (예: 5,6,7)", foreground="#666666").pack(side=tk.LEFT)

        # ND Output 설정 (2단계) — 형광 필터 / ND Output / Z-Stack 탭
        nb = ttk.Notebook(main, style="Main.TNotebook")
        nb.grid(row=2, column=0, sticky="we", pady=5)
        # 가려져 있던 탭의 경로 칸은 탭이 보일 때 끝부분으로 맞춘다.
        nb.bind("<<NotebookTabChanged>>", lambda e: self.master.after_idle(self._show_path_ends))

        # --- 탭 1: 형광 필터 ---
        cf = ttk.Frame(nb, padding="10")
        nb.add(cf, text="형광 필터")
        ttk.Label(cf, text="활성 채널 선택  ·  초점 오프셋 (µm, 기준 채널 대비 / +면 위로)").grid(
            row=0, column=0, sticky=tk.W, padx=4, pady=(0, 4))
        grid_frame = ttk.Frame(cf)
        grid_frame.grid(row=1, column=0, sticky=tk.W)
        # 채널 5개씩 두 묶음 (좁은 창 기준). 한 채널 = [체크박스][오프셋 입력][µm]
        per_col = 5
        for i in range(NUM_FLUOR_CHANNELS):
            r, base = i % per_col, (i // per_col) * 3
            cb = ttk.Checkbutton(grid_frame, text=self.filter_names[i], variable=self.fluor_flags[i],
                                 width=14)
            cb.grid(row=r, column=base, sticky=tk.W, padx=(8, 2), pady=2)
            self.filter_checkbuttons.append(cb)
            entry = ttk.Entry(grid_frame, textvariable=self.fluor_offsets[i], width=7, justify=tk.RIGHT)
            entry.grid(row=r, column=base + 1, sticky=tk.W, pady=2)
            if i == OFFSET_REFERENCE_CHANNEL:
                entry.configure(state="readonly")   # 기준 채널은 항상 0
            self.offset_entries.append(entry)
            ttk.Label(grid_frame, text="µm").grid(row=r, column=base + 2, sticky=tk.W,
                                                  padx=(2, 24), pady=2)
        self.offset_summary = tk.StringVar(value="")
        offset_label = ttk.Label(cf, textvariable=self.offset_summary, foreground="#1a5fb4",
                                 justify=tk.LEFT)
        offset_label.grid(row=2, column=0, sticky=tk.W, padx=4, pady=(6, 0))
        self._wrap_labels.append((offset_label, 60))
        fbtns = ttk.Frame(cf)
        fbtns.grid(row=3, column=0, sticky=tk.W, padx=4, pady=(8, 0))
        ttk.Button(fbtns, text="필터명 새로 가져오기",
                   command=self.refresh_filter_names).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(fbtns, text="템플릿 오프셋 불러오기",
                   command=self.load_template_offsets).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(fbtns, text="오프셋 모두 0",
                   command=self.reset_offsets).pack(side=tk.LEFT)

        # --- 탭 2: ND Output ---
        nf = ttk.Frame(nb, padding="10")
        nb.add(nf, text="ND Output")
        ttk.Label(nf, text="출력 폴더:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=3)
        self._path_entry(nf, self.nd_output_dir, width=20).grid(row=0, column=1, sticky="we", pady=3)
        ttk.Button(nf, text="찾아보기", command=self.browse_output_dir, width=9).grid(row=0, column=2, padx=(4, 2), pady=3)
        ttk.Button(nf, text="열기", command=self.open_output_dir, width=6).grid(row=0, column=3, pady=3)
        ttk.Label(nf, text="출력 접두사:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=3)
        gf = ttk.Frame(nf)
        gf.grid(row=1, column=1, columnspan=3, sticky=tk.W, pady=3)
        ttk.Entry(gf, textvariable=self.nd_output_prefix, width=10).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(gf, text="그룹당 포인트 수:").pack(side=tk.LEFT)
        ttk.Entry(gf, textvariable=self.nd_positions_per_file, width=7,
                  state="readonly").pack(side=tk.LEFT, padx=(4, 6))
        ttk.Label(gf, text="= Rows × Cols (자동)", foreground="#666666").pack(side=tk.LEFT)
        ttk.Checkbutton(nf, text="채널별 파일 분리 (nd01-F1.xml ...)", variable=self.nd_split_fluor).grid(
            row=2, column=0, columnspan=4, sticky=tk.W, pady=3)
        af = ttk.Frame(nf)
        af.grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=3)
        ttk.Checkbutton(af, text=f"생성 결과 자동 보관 (최근 {ARCHIVE_KEEP}개 유지)",
                        variable=self.archive_enabled).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(af, text="보관 폴더 열기", command=self.open_archive_dir).pack(side=tk.LEFT)
        ttk.Checkbutton(nf, text="생성 전 출력 폴더의 기존 XML 비우기 (지난 결과는 보관 폴더에 있음)",
                        variable=self.nd_clear_output).grid(
            row=4, column=0, columnspan=4, sticky=tk.W, pady=3)
        ttk.Checkbutton(nf, text="생성 후 NIS 매크로 갱신", variable=self.macro_enabled).grid(
            row=5, column=0, columnspan=4, sticky=tk.W, pady=(3, 0))
        ttk.Label(nf, text="매크로 파일:").grid(row=6, column=0, sticky=tk.W, padx=(20, 5), pady=3)
        self._path_entry(nf, self.macro_file, width=20).grid(
            row=6, column=1, sticky="we", pady=3)
        ttk.Button(nf, text="찾아보기", command=self.browse_macro_file, width=9).grid(
            row=6, column=2, padx=(4, 2), pady=3)
        nf.columnconfigure(1, weight=1)

        # --- 탭 3: Z-Stack ---
        zf = ttk.Frame(nb, padding="10")
        nb.add(zf, text="Z-Stack")
        # 1행: 사용 여부 · Range · Step,  2행: Z 장치
        zrow = ttk.Frame(zf)
        zrow.grid(row=0, column=0, sticky=tk.W, padx=4, pady=(0, 4))
        ttk.Checkbutton(zrow, text="Z-Stack 사용", variable=self.zstack_enabled,
                        command=self.on_zstack_toggle).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(zrow, text="Range (µm):").pack(side=tk.LEFT)
        e_range = ttk.Entry(zrow, textvariable=self.zstack_range, width=8)
        e_range.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(zrow, text="Step (µm):").pack(side=tk.LEFT)
        e_step = ttk.Entry(zrow, textvariable=self.zstack_step, width=8)
        e_step.pack(side=tk.LEFT, padx=(4, 0))
        zdev = ttk.Frame(zf)
        zdev.grid(row=1, column=0, sticky=tk.W, padx=4, pady=(0, 6))
        ttk.Label(zdev, text="Z 장치:").pack(side=tk.LEFT)
        e_dev = ttk.Entry(zdev, textvariable=self.zstack_device, width=18)
        e_dev.pack(side=tk.LEFT, padx=(4, 0))

        # 적용 채널: 왼쪽 열에 라벨/버튼, 오른쪽에 채널 체크박스를 3개씩.
        # (체크 해제한 채널은 현재 초점면 1장만 촬영)
        per_row = 3
        zc = ttk.Frame(zf)
        zc.grid(row=2, column=0, sticky=tk.W, padx=4, pady=2)
        ttk.Label(zc, text="적용 채널:").grid(row=0, column=0, sticky=tk.W, padx=(0, 12), pady=2)
        zbtns = ttk.Frame(zc)
        zbtns.grid(row=1, column=0, sticky=tk.W, padx=(0, 12), pady=2)
        b_all = ttk.Button(zbtns, text="전체", width=5,
                           command=lambda: self.set_zstack_channels(True))
        b_all.pack(side=tk.LEFT, padx=(0, 2))
        b_none = ttk.Button(zbtns, text="해제", width=5,
                            command=lambda: self.set_zstack_channels(False))
        b_none.pack(side=tk.LEFT)
        for i in range(NUM_FLUOR_CHANNELS):
            cb = ttk.Checkbutton(zc, text=self.filter_names[i],
                                 variable=self.zstack_channel_flags[i], width=14)
            cb.grid(row=i // per_row, column=1 + i % per_row, sticky=tk.W, padx=(0, 6), pady=2)
            self.zstack_channel_checkbuttons.append(cb)

        # 요약 + 안내
        self.zstack_summary_label = ttk.Label(zf, textvariable=self.zstack_summary,
                                              foreground="#1a5fb4", justify=tk.LEFT)
        self.zstack_summary_label.grid(row=3, column=0, sticky=tk.W, padx=4, pady=(6, 0))
        self._wrap_labels.append((self.zstack_summary_label, 60))

        self.zstack_widgets = [e_range, e_step, e_dev, b_all, b_none] + self.zstack_channel_checkbuttons
        self.on_zstack_toggle()

        # 예상 결과 (실시간)
        self.estimate_label = ttk.Label(main, textvariable=self.estimate_var,
                                        font=("Arial", 10, "bold"), foreground="#1a5fb4",
                                        justify=tk.CENTER)
        self.estimate_label.grid(row=3, column=0, pady=(2, 0))
        self._wrap_labels.append((self.estimate_label, 20))

        # 실행: 윗줄은 생성, 아랫줄은 모니터링/폴더
        ctrl = ttk.Frame(main)
        ctrl.grid(row=4, column=0, pady=(8, 2))
        ttk.Button(ctrl, text="▶ 생성 (800 Full + ND Output)", style="Primary.TButton",
                   command=self.manual_run).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="ND Output만 다시 생성",
                   command=self.run_nd_output).pack(side=tk.LEFT, padx=4, fill=tk.Y)
        ttk.Button(ctrl, text="미리보기", command=self.preview).pack(side=tk.LEFT, padx=4, fill=tk.Y)

        ctrl2 = ttk.Frame(main)
        ctrl2.grid(row=5, column=0, pady=(2, 6))
        self.start_button = ttk.Button(ctrl2, text="모니터링 시작", command=self.start_monitoring)
        self.start_button.pack(side=tk.LEFT, padx=4)
        self.stop_button = ttk.Button(ctrl2, text="모니터링 중지", command=self.stop_monitoring, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl2, text="출력 폴더 열기", command=self.open_output_dir).pack(side=tk.LEFT, padx=4)

        # 실행 결과: 윗줄에 성공/실패 한마디, 아래에 항목별 내용. (팝업 대신 여기에 표시)
        sf2 = ttk.LabelFrame(main, text="실행 결과", padding=(10, 6))
        sf2.grid(row=6, column=0, sticky="we", pady=5)
        self.status_label = ttk.Label(sf2, text="대기 중...", font=("Arial", 11, "bold"),
                                      justify=tk.LEFT)
        self.status_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 2))
        self._wrap_labels.append((self.status_label, 50))
        self._result_details = []
        self.result_rows = []
        for i in range(RESULT_ROW_COUNT):
            key_label = ttk.Label(sf2, foreground="#666666")
            value_label = ttk.Label(sf2, justify=tk.LEFT)
            key_label.grid(row=i + 1, column=0, sticky="nw", padx=(2, 12), pady=1)
            value_label.grid(row=i + 1, column=1, sticky="nw", pady=1)
            key_label.grid_remove()
            value_label.grid_remove()
            self._wrap_labels.append((value_label, 150))
            self.result_rows.append((key_label, value_label))
        sf2.columnconfigure(1, weight=1)

        lf = ttk.LabelFrame(main, text="로그", padding=(10, 4, 10, 10))
        lf.grid(row=7, column=0, sticky="nsew", pady=5)
        lbar = ttk.Frame(lf)
        lbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(lbar, text="로그 지우기", command=self.clear_log).pack(side=tk.RIGHT)
        ttk.Button(lbar, text="로그 저장", command=self.save_log).pack(side=tk.RIGHT, padx=4)
        self.log_text = scrolledtext.ScrolledText(lf, height=10, width=60, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.tag_configure("error", foreground=STATUS_COLORS["red"])
        self.log_text.tag_configure("warn", foreground="#b35900")
        self.log_text.tag_configure("ok", foreground=STATUS_COLORS["green"])
        self.log_text.tag_configure("dim", foreground="#888888")

        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(7, weight=1)
        main.bind("<Configure>", self._on_main_resize)

    # ---------------- 실행 결과 ----------------
    def set_status(self, text, color="black", details=None, append=False):
        """실행 결과 패널 갱신.

        text: 윗줄 한마디. color 가 green/red 면 ✔/✖ 를 앞에 붙인다.
        details: [(항목, 내용)] 또는 [(항목, 내용, 색)]. append=True 면 기존 항목 뒤에 덧붙인다.
        """
        self.status_label.config(text=STATUS_ICONS.get(color, "") + text,
                                 foreground=STATUS_COLORS.get(color, color))
        if not append:
            self._result_details = []
        self._result_details.extend(details or [])
        for i, (key_label, value_label) in enumerate(self.result_rows):
            if i < len(self._result_details):
                key, value, *rest = self._result_details[i]
                key_label.config(text=key)
                value_label.config(text=value,
                                   foreground=STATUS_COLORS[rest[0]] if rest else STATUS_COLORS["black"])
                key_label.grid()
                value_label.grid()
            else:
                key_label.grid_remove()
                value_label.grid_remove()

    # ---------------- 로그 ----------------
    @staticmethod
    def _log_tag(message) -> str:
        """로그 한 줄의 색 태그. 오류/경고/완료/구분선을 눈에 띄게 구분한다."""
        if any(k in message for k in ("오류", "실패", "Traceback")):
            return "error"
        if any(k in message for k in ("[경고]", "[주의]")):
            return "warn"
        if "완료" in message:
            return "ok"
        if message.strip() and set(message.strip()) <= {"=", "-"}:
            return "dim"
        return "plain"

    def log_message(self, message):
        # 모니터링 스레드에서도 호출되므로 위젯 접근은 메인 스레드로 넘긴다.
        if threading.current_thread() is not threading.main_thread():
            self.master.after(0, self.log_message, message)
            return
        message = str(message)
        body = message.lstrip("\n")
        if len(body) != len(message):
            self.log_text.insert(tk.END, "\n")      # 앞의 빈 줄은 시각 없이 그대로 띄운다
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] ", "dim")
        self.log_text.insert(tk.END, f"{body}\n", self._log_tag(body))
        self.log_text.see(tk.END)

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    # ---------------- 파일/폴더 선택 ----------------
    def browse_input(self):
        cur = self.input_file.get()
        init_dir = os.path.dirname(cur) if cur else APP_DIR
        path = filedialog.askopenfilename(
            title="입력 4point XML 선택", initialdir=init_dir or APP_DIR,
            filetypes=[("XML 파일", "*.xml"), ("모든 파일", "*.*")])
        if path:
            self.input_file.set(os.path.normpath(path))
            self.refresh_filter_names()

    def browse_output(self):
        cur = self.output_file.get()
        init_dir = os.path.dirname(cur) if cur else APP_DIR
        path = filedialog.asksaveasfilename(
            title="출력 full XML 선택", initialdir=init_dir or APP_DIR,
            initialfile=os.path.basename(cur) or "nd_full.xml",
            defaultextension=".xml",
            filetypes=[("XML 파일", "*.xml"), ("모든 파일", "*.*")])
        if path:
            self.output_file.set(os.path.normpath(path))

    def open_template_dir(self):
        """template 폴더 열기. 템플릿 교체는 이 폴더의 파일을 덮어쓰는 방식."""
        self._open_folder(TEMPLATE_DIR)

    def reload_template(self):
        """template 폴더의 파일을 교체한 뒤 필터명 등을 다시 읽어온다."""
        path, notice = ensure_template_file()
        self.template_file.set(path)
        if notice:
            self.log_message(notice)
        if not os.path.exists(path):
            self.set_status("템플릿 없음", "red")
            return
        self.log_message(f"템플릿 새로고침: {path}")
        self.refresh_filter_names()
        self._log_template_zstack()

    def _log_template_zstack(self):
        """템플릿에 이미 Z-Stack 이 들어있으면 알려준다."""
        path = self.template_file.get()
        if not os.path.exists(path):
            return
        try:
            params = get_zstack_params(ET.parse(path).getroot())
        except Exception:
            return
        if params:
            self.log_message(
                f"  템플릿에 Z-Stack 있음: Range {params['range']:g} µm, "
                f"Step {params['step']:g} µm, {params['count']} 슬라이스")

    def browse_output_dir(self):
        path = filedialog.askdirectory(
            title="ND Output 폴더 선택", initialdir=self.nd_output_dir.get() or APP_DIR)
        if path:
            self.nd_output_dir.set(os.path.normpath(path))

    def browse_macro_file(self):
        cur = self.macro_file.get()
        path = filedialog.asksaveasfilename(
            title="NIS 매크로 파일 선택", initialdir=os.path.dirname(cur) or APP_DIR,
            initialfile=os.path.basename(cur) or "nd_output_autorun.mac",
            defaultextension=".mac",
            filetypes=[("NIS 매크로", "*.mac"), ("모든 파일", "*.*")])
        if path:
            self.macro_file.set(os.path.normpath(path))

    def _write_macro(self, created) -> Tuple[bool, str]:
        """생성된 파일 목록으로 NIS 매크로를 다시 쓴다. 실패해도 생성 자체는 성공으로 둔다.

        반환: (성공 여부, 실행 결과 패널에 보일 한 줄 요약).
        """
        path = self.macro_file.get().strip() or DEFAULT_MACRO_FILE
        try:
            write_autorun_macro(created, path)
            self.log_message(f"NIS 매크로 갱신: {path} ({len(created)}개 Load/Run + 완료 시간 창)")
            return True, f"{os.path.basename(path)} 갱신 ({len(created)}개 Load/Run)"
        except PermissionError:
            self.log_message(f"NIS 매크로 쓰기 실패(권한 없음): {path}")
            self.log_message("  관리자 권한으로 실행하거나 매크로 경로를 쓰기 가능한 폴더로 바꾸세요.")
            return False, "갱신 실패 (권한 없음 — 관리자 권한으로 실행하거나 경로 변경)"
        except Exception as e:
            self.log_message(f"NIS 매크로 쓰기 실패: {e}")
            return False, "갱신 실패 (로그 확인)"

    def init_4point(self):
        """4porint-reference 형식으로 4개 기본 위치가 담긴 초기 4point 파일 생성."""
        input_file = self.input_file.get()
        if os.path.exists(input_file):
            if not messagebox.askyesno("4point 초기화",
                                       f"기존 파일을 기본 4위치로 덮어쓸까요?\n{input_file}"):
                return
        try:
            _, n = make_initial_4point(REFERENCE_4POINT_FILE, input_file)
            self.log_message(f"초기 4point 파일 생성: {input_file} ({n}개 기본 위치)")
            self.set_status("4point 초기화 완료", "green")
        except Exception as e:
            self.log_message(f"4point 초기화 오류: {e}")
            self.set_status("4point 초기화 실패", "red")

    def ensure_4point_exists(self):
        """입력 4point 파일이 없으면 기본값으로 자동 생성. 반환: 존재 여부."""
        input_file = self.input_file.get()
        if os.path.exists(input_file):
            return True
        try:
            _, n = make_initial_4point(REFERENCE_4POINT_FILE, input_file)
            self.log_message(f"[자동] 입력 파일이 없어 기본 4point 생성: {input_file} ({n}개)")
            return True
        except Exception as e:
            self.log_message(f"[자동] 4point 생성 실패: {e}")
            return False

    def open_output_dir(self):
        d = self.nd_output_dir.get()
        if not d:
            self.log_message("출력 폴더가 지정되지 않았습니다.")
            return
        self._open_folder(d)

    def open_archive_dir(self):
        entries = list_archive_entries()
        self.log_message(f"보관 중인 스냅샷: {len(entries)}개" +
                         (f" (최신: {entries[0]})" if entries else " (아직 없음)"))
        self._open_folder(ARCHIVE_DIR)

    def _open_folder(self, folder):
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)  # Windows 탐색기로 열기
        except Exception as e:
            self.log_message(f"폴더 열기 오류: {e}")

    # ---------------- Z-Stack ----------------
    def on_zstack_toggle(self):
        """Z-Stack 체크 상태에 따라 입력 위젯 활성/비활성."""
        state = tk.NORMAL if self.zstack_enabled.get() else tk.DISABLED
        for w in self.zstack_widgets:
            w.configure(state=state)
        self.update_zstack_summary()

    def _zstack_values(self):
        """(range, step) 반환. 입력이 유효하지 않으면 None."""
        try:
            z_range = float(self.zstack_range.get())
            z_step = float(self.zstack_step.get())
        except (ValueError, TypeError, tk.TclError):
            return None
        if z_range < 0 or z_step <= 0:
            return None
        return z_range, z_step

    def set_zstack_channels(self, value: bool):
        """Z-Stack 적용 채널을 전체 선택/해제."""
        for v in self.zstack_channel_flags:
            v.set(value)

    def zstack_spec(self):
        """생성 함수에 넘길 Z-Stack 설정 dict. 입력 오류면 None."""
        if not self.zstack_enabled.get():
            return {"enabled": False}
        values = self._zstack_values()
        if values is None:
            return None
        z_range, z_step = values
        return {
            "enabled": True,
            "range": z_range,
            "step": z_step,
            "device": self.zstack_device.get().strip() or DEFAULT_Z_DEVICE,
            "channels": [bool(v.get()) for v in self.zstack_channel_flags],
        }

    def _zstack_channel_split(self, spec):
        """선택된 형광 채널을 (Z-Stack 적용, 초점면 전용) 이름 목록으로 나눈다."""
        applied, plane = [], []
        for i in range(NUM_FLUOR_CHANNELS):
            if not self.fluor_flags[i].get():
                continue
            (applied if channel_uses_zstack(spec, i) else plane).append(self.filter_names[i])
        return applied, plane

    def _zstack_log_text(self, spec):
        if not spec or not spec.get("enabled"):
            return "사용 안 함"
        text = (f"Range {spec['range']:g} µm, Step {spec['step']:g} µm, "
                f"{zstack_slice_count(spec['range'], spec['step'])} 슬라이스, 장치 '{spec['device']}'")
        applied, plane = self._zstack_channel_split(spec)
        if not applied:
            return text + " · 적용 채널 없음 (선택한 채널 모두 초점면 1장)"
        text += f" · 적용: {', '.join(applied)}"
        if plane:
            text += f" · 초점면 1장: {', '.join(plane)}"
        return text

    def update_zstack_summary(self):
        if not self.zstack_enabled.get():
            self.zstack_summary.set("Z-Stack 꺼짐 (단일 Z 평면으로 촬영)")
            return
        values = self._zstack_values()
        if values is None:
            self.zstack_summary.set("Range/Step 입력값 확인 필요 (Range ≥ 0, Step > 0)")
            return
        z_range, z_step = values
        count = zstack_slice_count(z_range, z_step)
        # 한 줄 요약 (상대 모드: 현재 Z 기준으로 Range 의 중앙에서 위아래로 스캔)
        head = f"슬라이스 {count}장 · 현재 Z 기준 ±{z_range / 2:g} µm"
        applied, plane = self._zstack_channel_split(self.zstack_spec())
        if not applied and not plane:
            self.zstack_summary.set(head + " · 형광 필터 탭에서 채널을 먼저 선택하세요.")
        elif not applied:
            self.zstack_summary.set(
                head + " · [주의] 선택한 채널 중 적용 채널이 없어 모두 초점면 1장으로 촬영됩니다.")
        elif plane:
            self.zstack_summary.set(
                head + f" · Z-Stack: {', '.join(applied)}  /  초점면 1장: {', '.join(plane)}")
        else:
            self.zstack_summary.set(head + f" · Z-Stack: {', '.join(applied)} (선택한 채널 전체)")

    # ---------------- 형광 채널별 초점 오프셋 ----------------
    @staticmethod
    def _offset_text(value) -> str:
        """오프셋 표시용 문자열. 9.0 -> '9', 2.5 -> '2.5', 잘못된 값 -> '0'."""
        try:
            return f"{float(value):g}"
        except (TypeError, ValueError):
            return "0"

    def _template_offsets(self) -> List[float]:
        """템플릿의 pdOffset 값을 읽는다. 실패하면 모두 0."""
        try:
            values = get_fluor_offsets(ET.parse(self.template_file.get()).getroot())
        except Exception:
            values = []
        return [values[i] if i < len(values) else 0.0 for i in range(NUM_FLUOR_CHANNELS)]

    def _set_offsets(self, values):
        for i, var in enumerate(self.fluor_offsets):
            var.set(self._offset_text(values[i] if i < len(values) else 0))
        self.fluor_offsets[OFFSET_REFERENCE_CHANNEL].set("0")

    def load_template_offsets(self):
        self._set_offsets(self._template_offsets())
        self.log_message(f"템플릿 초점 오프셋 불러옴: {self._offset_log_text()}")

    def reset_offsets(self):
        self._set_offsets([0.0] * NUM_FLUOR_CHANNELS)

    def offset_values(self):
        """채널별 초점 오프셋(float) 목록. 입력이 숫자가 아니면 None."""
        values = []
        for i, var in enumerate(self.fluor_offsets):
            text = var.get().strip()
            if i == OFFSET_REFERENCE_CHANNEL:
                values.append(0.0)
                continue
            try:
                values.append(float(text) if text else 0.0)
            except (ValueError, TypeError, tk.TclError):
                return None
        return values

    def _offset_log_text(self, fluor_flags=None) -> str:
        """로그/보관용 오프셋 요약. fluor_flags 를 주면 선택된 채널만 보여준다."""
        values = self.offset_values()
        if values is None:
            return "입력 오류 (숫자만 입력)"
        parts = []
        for i, v in enumerate(values):
            if fluor_flags is not None and not fluor_flags[i]:
                continue
            tag = " (기준)" if i == OFFSET_REFERENCE_CHANNEL else ""
            parts.append(f"{self.filter_names[i]} {v:+g}{tag}")
        return ", ".join(parts) if parts else "-"

    def update_offset_summary(self):
        values = self.offset_values()
        if values is None:
            self.offset_summary.set("초점 오프셋 입력값 확인 필요 (숫자만 입력)")
            return
        ref_name = self.filter_names[OFFSET_REFERENCE_CHANNEL]
        moved = [f"{self.filter_names[i]} {v:+g}" for i, v in enumerate(values)
                 if self.fluor_flags[i].get() and i != OFFSET_REFERENCE_CHANNEL and v != 0]
        text = f"기준 채널: {ref_name} (0 µm)"
        if moved:
            text += "  ·  선택 채널 오프셋: " + ", ".join(moved)
        else:
            text += "  ·  선택 채널 모두 기준과 같은 초점면"
        self.offset_summary.set(text)

    # ---------------- 예상 결과(실시간) / 미리보기 ----------------
    def _parse_range_silent(self):
        """(start, end) 반환. 비었으면 (None,None). 유효하지 않으면 'invalid'."""
        s = self.point_start_idx.get().strip()
        e = self.point_end_idx.get().strip()
        if not s and not e:
            return None, None
        try:
            si, ei = int(s), int(e)
        except (ValueError, TypeError):
            return "invalid", "invalid"
        if si < 0 or ei <= 0 or si >= ei:
            return "invalid", "invalid"
        return si, ei

    def _parse_delete_silent(self):
        """삭제 번호 집합 반환. 유효하지 않으면 None."""
        value = self.delete_numbers.get().strip()
        if not value:
            return set()
        numbers = set()
        for part in [p.strip() for p in value.split(',') if p.strip()]:
            try:
                n = int(part)
            except (ValueError, TypeError):
                return None
            if n <= 0:
                return None
            numbers.add(n)
        return numbers

    def _compute_estimate(self):
        """(point_count, groups, files) 또는 None(입력 오류)."""
        try:
            rows = int(self.mesh_rows.get())
            cols = int(self.mesh_cols.get())
            reps = int(self.num_repetitions.get())
            ppf = int(self.nd_positions_per_file.get())
        except (ValueError, TypeError, tk.TclError):
            return None
        if rows < 1 or cols < 1 or reps < 1 or ppf < 1:
            return None
        start_idx, end_idx = self._parse_range_silent()
        if start_idx == "invalid":
            return None
        delete_numbers = self._parse_delete_silent()
        if delete_numbers is None:
            return None
        count = sum(1 for _ in iter_point_slots(rows, cols, reps, start_idx, end_idx, delete_numbers))
        fluor_flags = [1 if v.get() else 0 for v in self.fluor_flags]
        try:
            # 파일 벌 수는 채널 분리 설정과 Z 적용 채널 조합에 따라 달라진다.
            per_group = len(build_channel_sets(fluor_flags, self.nd_split_fluor.get(),
                                               self.zstack_spec()))
        except ValueError:
            per_group = 0        # 선택된 형광 채널 없음
        groups, files = estimate_output(count, ppf, per_group)
        return count, groups, files

    def _zstack_estimate_suffix(self):
        """예상 문구에 붙일 Z-Stack 요약. 꺼져 있으면 빈 문자열."""
        if not self.zstack_enabled.get():
            return ""
        values = self._zstack_values()
        if values is None:
            return " · Z 설정 확인 필요"
        applied, plane = self._zstack_channel_split(self.zstack_spec())
        if not applied:
            return f" · Z {zstack_slice_count(*values)} 슬라이스 (적용 채널 없음)"
        detail = f"{', '.join(applied)}만" if plane else "전 채널"
        return f" · Z {zstack_slice_count(*values)} 슬라이스 ({detail})"

    def _sync_positions_per_file(self):
        """그룹당 포인트 수 = Rows × Cols (한 그룹 = 메시 한 판)."""
        try:
            value = int(self.mesh_rows.get()) * int(self.mesh_cols.get())
        except (ValueError, TypeError, tk.TclError):
            return
        if value < 1:
            return
        try:
            if int(self.nd_positions_per_file.get()) == value:
                return          # 값이 같으면 쓰지 않는다 (trace 재진입 방지)
        except (ValueError, TypeError, tk.TclError):
            pass
        self.nd_positions_per_file.set(value)

    def update_estimate(self):
        self._sync_positions_per_file()
        self.update_zstack_summary()
        self.update_offset_summary()
        est = self._compute_estimate()
        if est is None:
            self.estimate_var.set("예상: 입력값 확인 필요")
            return
        count, groups, files = est
        enabled = sum(1 for v in self.fluor_flags if v.get())
        z = self._zstack_estimate_suffix()
        if count == 0:
            self.estimate_var.set("예상: 생성 포인트 없음 (범위/삭제 확인)")
        elif enabled == 0:
            self.estimate_var.set(f"예상: {count} 포인트 · {groups} 그룹 · (형광 채널 미선택){z}")
        else:
            self.estimate_var.set(f"예상: {count} 포인트 · {groups} 그룹 · {files} 파일{z}")

    def preview(self):
        """생성 없이 입력 유효성 + 예상 결과를 로그로 확인."""
        self.log_message("\n" + "-" * 60)
        self.log_message("미리보기 (검증)")
        input_file = self.input_file.get()
        if not os.path.exists(input_file):
            self.log_message(f"  [경고] 입력 파일이 없습니다: {input_file}")
            self.set_status("미리보기: 입력 파일 없음", "red")
            return
        try:
            root = ET.parse(input_file).getroot()
            corners = extract_corners(root)
            self.log_message(f"  입력 파일 OK, 4모서리 확인: LTfirst={corners[0]}, TR={corners[1]}")
            self.log_message(f"                              BR={corners[2]}, LTlast={corners[3]}")
        except Exception as e:
            self.log_message(f"  [경고] 입력 파일 검증 실패: {e}")
            self.set_status("미리보기: 입력 오류", "red")
            return

        # 형광 필터(SpectLoop)는 4point 입력이 아니라 템플릿에 들어 있다.
        template_file = self.template_file.get()
        if not os.path.exists(template_file):
            self.log_message(f"  [경고] 템플릿이 없습니다: {template_file}")
            self.set_status("미리보기: 템플릿 없음", "red")
            return
        try:
            filters = get_filter_names(ET.parse(template_file).getroot())
            active = [filters[i] for i, v in enumerate(self.fluor_flags) if v.get() and i < len(filters)]
            self.log_message(f"  형광 필터: {active if active else '(미선택)'}")
            self.log_message(f"  초점 오프셋: {self._offset_log_text([v.get() for v in self.fluor_flags])}")
        except Exception as e:
            self.log_message(f"  [경고] 템플릿 검증 실패: {e}")
            self.set_status("미리보기: 템플릿 오류", "red")
            return

        # 예상 포인트/그룹/파일 + 첫·끝 이름
        try:
            rows = int(self.mesh_rows.get()); cols = int(self.mesh_cols.get())
            reps = int(self.num_repetitions.get())
            start_idx, end_idx = self._parse_range_silent()
            if start_idx == "invalid":
                self.log_message("  [경고] 구간 입력 오류")
                return
            delete_numbers = self._parse_delete_silent()
            if delete_numbers is None:
                self.log_message("  [경고] 삭제 번호 입력 오류")
                return
            names = [name for _, _, _, name in iter_point_slots(rows, cols, reps, start_idx, end_idx, delete_numbers)]
        except (ValueError, TypeError, tk.TclError):
            self.log_message("  [경고] 메시 설정값 오류")
            return

        if not names:
            self.log_message("  예상: 생성 포인트 없음 (범위/삭제 확인)")
            self.set_status("미리보기: 포인트 없음", "red")
            return
        est = self._compute_estimate()
        if est is None:
            self.log_message("  [경고] 예상 계산 실패 (입력값 확인)")
            return
        count, groups, files = est
        self.log_message(f"  예상 포인트: {count}개 ({names[0]} .. {names[-1]})")
        self.log_message(f"  예상 nd_output: {groups} 그룹 · {files} 파일")
        self.log_message(f"  Z-Stack: {self._zstack_log_text(self.zstack_spec())}")
        self.log_message("-" * 60)
        self.set_status("미리보기 (아직 생성하지 않음)", "blue", details=[
            ("예상 포인트", f"{count}개 ({names[0]} .. {names[-1]})"),
            ("예상 ND", f"{groups} 그룹 · {files} 파일"),
            ("Z-Stack", self._zstack_log_text(self.zstack_spec())),
        ])

    def save_log(self):
        """현재 로그를 텍스트 파일로 저장."""
        default_name = f"nd_generator_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path = filedialog.asksaveasfilename(
            title="로그 저장", initialdir=APP_DIR, initialfile=default_name,
            defaultextension=".txt", filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                # 로그 줄에는 시각만 찍히므로 날짜는 파일 머리에 남긴다.
                f.write(f"저장 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(self.log_text.get("1.0", tk.END))
            self.log_message(f"로그 저장 완료: {path}")
        except Exception as e:
            self.log_message(f"로그 저장 오류: {e}")

    # ---------------- 형광 필터명 ----------------
    def refresh_filter_names(self, silent=False):
        # 형광 필터(SpectLoop)는 템플릿에 있으므로 템플릿에서 읽는다.
        path = self.template_file.get()
        if not os.path.exists(path):
            if not silent:
                self.log_message(f"필터명 새로고침 실패: 템플릿 파일이 없습니다: {path}")
            return
        try:
            root = ET.parse(path).getroot()
            names = get_filter_names(root)
            if not names:
                if not silent:
                    self.log_message("필터명 새로고침 실패: 템플릿에서 SpectLoop 필터 정보를 찾지 못했습니다.")
                return
            for i in range(NUM_FLUOR_CHANNELS):
                label = names[i] if i < len(names) else f"Ch{i+1}"
                self.filter_names[i] = label
                self.filter_checkbuttons[i].config(text=label)
                if i < len(self.zstack_channel_checkbuttons):
                    self.zstack_channel_checkbuttons[i].config(text=label)
            self.update_zstack_summary()
            self.update_offset_summary()
            if not silent:
                self.log_message(f"형광 필터명 로드: {', '.join(self.filter_names)}")
        except Exception as e:
            if not silent:
                self.log_message(f"필터명 새로고침 오류: {e}")

    # ---------------- 1단계 실행 ----------------
    def _collect_mesh_params(self):
        """(rows, cols, reps, start, end, delete) 반환. 오류 시 None."""
        delete_numbers = self.parse_delete_numbers()
        if delete_numbers is None:
            self.set_status("삭제 번호 입력 오류", "red")
            return None
        start_idx, end_idx = self.parse_point_range()
        if (start_idx == 0 and end_idx is None):  # 파싱 오류 신호
            self.set_status("범위 입력 오류", "red")
            return None
        return (self.mesh_rows.get(), self.mesh_cols.get(), self.num_repetitions.get(),
                start_idx, end_idx, delete_numbers)

    def process_full(self):
        """1단계(Full) 생성. 반환: 성공 여부."""
        output_file = self.output_file.get()
        template_file = self.template_file.get()

        # 입력 4point 없으면 기본값으로 자동 생성
        if not self.ensure_4point_exists():
            self.set_status("입력 파일 없음", "red")
            return
        input_file = self.input_file.get()

        if not os.path.exists(template_file):
            self.log_message(f"템플릿 파일을 찾을 수 없습니다: {template_file}")
            self.set_status("템플릿 없음", "red")
            return

        params = self._collect_mesh_params()
        if params is None:
            return
        rows, cols, reps, start_idx, end_idx, delete_numbers = params
        fluor_flags = [1 if v.get() else 0 for v in self.fluor_flags]

        fluor_offsets = self.offset_values()
        if fluor_offsets is None:
            self.log_message("초점 오프셋 입력 오류: 숫자만 입력하세요. (예: 9, -2.5)")
            self.set_status("초점 오프셋 입력 오류", "red")
            return

        zstack = self.zstack_spec()
        if zstack is None:
            self.log_message("Z-Stack 설정 오류: Range 는 0 이상, Step 은 0 보다 커야 합니다.")
            self.set_status("Z-Stack 입력 오류", "red")
            return

        self.log_message("\n" + "=" * 60)
        self.log_message("Full 생성 (1단계)")
        self.log_message(f"  입력: {input_file}")
        self.log_message(f"  템플릿: {template_file}")
        self.log_message(f"  출력: {output_file}")
        self.log_message(f"  Rows={rows}, Cols={cols}, Reps={reps}")
        if delete_numbers:
            self.log_message(f"  삭제 번호: {', '.join(str(n) for n in sorted(delete_numbers))}")
        if start_idx is not None and end_idx is not None:
            self.log_message(f"  범위: {start_idx}-{end_idx}")
        active = [self.filter_names[i] for i, f in enumerate(fluor_flags) if f]
        self.log_message(f"  형광 필터: {active if active else '(설정 유지)'}")
        self.log_message(f"  초점 오프셋: {self._offset_log_text()}")
        self.log_message(f"  Z-Stack: {self._zstack_log_text(zstack)}")
        self.log_message("=" * 60)

        try:
            _, n = generate_full(
                input_file, template_file, output_file, rows, cols, reps,
                start_idx=start_idx, end_idx=end_idx, delete_numbers=delete_numbers,
                fluor_flags=fluor_flags if sum(fluor_flags) > 0 else None,
                fluor_offsets=fluor_offsets,
                zstack=zstack,
                log_callback=self.log_message,
            )
            self.set_status(
                f"Full 완료 {datetime.now().strftime('%H:%M:%S')}", "green",
                details=[("1단계 Full", f"포인트 {n}개 (Rows {rows} × Cols {cols} × 반복 {reps})"
                                        f" → {os.path.basename(output_file)}")])
        except Exception as e:
            self.log_message(f"Full 생성 오류: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.set_status("Full 생성 오류 (로그 확인)", "red")
            return False
        return True

    def run_all(self):
        """1단계(Full, 800) 생성에 성공하면 곧바로 2단계(ND Output)까지 이어서 만든다."""
        if self.process_full():
            self.log_message("\n[자동] ND Output 생성 시작...")
            self.run_nd_output(after_full=True)

    # ---------------- 결과 보관 ----------------
    def _archive_result(self, created, fluor_flags, zstack,
                        positions_per_file, split_fluor, prefix):
        """이번 생성 결과 한 벌을 archive 폴더에 남기고 오래된 스냅샷을 정리.

        반환: 스냅샷 폴더 이름(상태 라벨용). 실패하면 None.
        """
        try:
            active = [self.filter_names[i] for i, f in enumerate(fluor_flags) if f]
            info = "\n".join([
                f"생성 시각      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"메시           : Rows {self.mesh_rows.get()} × Cols {self.mesh_cols.get()}"
                f" × 반복 {self.num_repetitions.get()}  (프리셋: {self.mesh_preset.get()})",
                f"구간           : {self.point_start_idx.get() or '-'} ~ {self.point_end_idx.get() or '-'}",
                f"삭제 번호      : {self.delete_numbers.get() or '-'}",
                f"형광 필터      : {', '.join(active) if active else '-'}",
                f"초점 오프셋    : {self._offset_log_text(fluor_flags)}",
                f"Z-Stack        : {self._zstack_log_text(zstack)}",
                f"그룹당 포인트  : {positions_per_file}  (= Rows × Cols)",
                f"채널별 분리    : {split_fluor}",
                f"출력 접두사    : {prefix}",
                f"생성 파일 수   : {len(created)}",
                f"NIS 매크로     : {self.macro_file.get() if self.macro_enabled.get() else '갱신 안 함'}",
                f"템플릿         : {self.template_file.get()}",
                "",
            ])
            label = f"{prefix}_{len(created)}f"
            dest, removed = archive_run(
                self.input_file.get(), self.output_file.get(), created,
                label=label, info_text=info, log=self.log_message)
            self.log_message(f"결과 보관: {dest}")
            snapshot_name = os.path.basename(dest)
            if removed:
                self.log_message(f"  오래된 스냅샷 {len(removed)}개 삭제: {', '.join(removed)}")
            self.log_message(f"  보관 중: {len(list_archive_entries())} / {ARCHIVE_KEEP}개")
            return snapshot_name
        except Exception as e:
            # 보관 실패가 생성 자체를 실패로 만들지는 않는다.
            self.log_message(f"결과 보관 실패(생성은 정상 완료): {e}")
            return None

    # ---------------- 2단계 실행 ----------------
    def run_nd_output(self, after_full=False):
        """2단계(ND Output) 생성. after_full=True 면 방금 끝난 Full 결과 아래에 이어서 표시한다."""
        full_path = self.output_file.get()
        out_dir = self.nd_output_dir.get()
        prefix = self.nd_output_prefix.get().strip() or "nd"

        if not os.path.exists(full_path):
            self.log_message(f"ND Output 실패: full 파일이 없습니다: {full_path}")
            self.log_message("  먼저 'Full 생성'을 실행하세요.")
            self.set_status("ND: full 없음", "red", append=after_full)
            return

        try:
            positions_per_file = int(self.nd_positions_per_file.get())
        except Exception:
            self.log_message("ND Output 실패: 그룹당 포인트 수는 정수여야 합니다.")
            self.set_status("ND: 그룹당 포인트 수 오류", "red", append=after_full)
            return

        fluor_flags = [1 if v.get() else 0 for v in self.fluor_flags]
        if sum(fluor_flags) == 0:
            self.log_message("ND Output 실패: 최소 1개의 형광 채널을 선택하세요.")
            self.set_status("ND: 채널 없음", "red", append=after_full)
            return

        fluor_offsets = self.offset_values()
        if fluor_offsets is None:
            self.log_message("ND Output 실패: 초점 오프셋은 숫자만 입력하세요. (예: 9, -2.5)")
            self.set_status("초점 오프셋 입력 오류", "red", append=after_full)
            return

        zstack = self.zstack_spec()
        if zstack is None:
            self.log_message("ND Output 실패: Z-Stack Range 는 0 이상, Step 은 0 보다 커야 합니다.")
            self.set_status("Z-Stack 입력 오류", "red", append=after_full)
            return

        split_fluor = self.nd_split_fluor.get()
        self.log_message("\n" + "=" * 60)
        self.log_message("ND Output 생성 (2단계)")
        self.log_message(f"  full: {full_path}")
        self.log_message(f"  출력 폴더: {out_dir}")
        self.log_message(f"  접두사: {prefix}, 그룹당: {positions_per_file}, 채널별 분리: {split_fluor}")
        active = [self.filter_names[i] for i, f in enumerate(fluor_flags) if f]
        self.log_message(f"  형광 필터: {active}")
        self.log_message(f"  초점 오프셋: {self._offset_log_text(fluor_flags)}")
        self.log_message(f"  Z-Stack: {self._zstack_log_text(zstack)}")
        clear_existing = self.nd_clear_output.get()
        if clear_existing and not self.archive_enabled.get():
            self.log_message("  [주의] 자동 보관이 꺼져 있어 출력 폴더의 기존 XML 은 백업 없이 삭제됩니다.")
        if zstack.get("enabled"):
            applied, plane = self._zstack_channel_split(zstack)
            if not applied:
                self.log_message("  [주의] Z-Stack 을 켰지만 적용 채널이 없어 모든 파일이 초점면 1장으로 만들어집니다.")
            elif plane and not split_fluor:
                self.log_message("  [안내] 채널별 분리가 꺼져 있고 Z 적용 채널이 섞여 있어, "
                                 "그룹마다 '-zstack' / '-plane' 두 파일로 나눕니다.")
        self.log_message("=" * 60)

        try:
            created = generate_nd_output(
                full_path, out_dir, output_prefix=prefix,
                positions_per_file=positions_per_file,
                fluor_flags=fluor_flags, split_fluor=split_fluor,
                fluor_offsets=fluor_offsets, zstack=zstack,
                clear_existing=clear_existing,
                log_callback=self.log_message,
            )
            details: List[tuple] = [
                ("2단계 ND", f"파일 {len(created)}개"
                             f" ({os.path.basename(created[0])} .. {os.path.basename(created[-1])})"),
                ("채널", ", ".join(active)),
                ("Z-Stack", self._zstack_log_text(zstack)),
                ("출력 폴더", out_dir),
            ]
            if self.macro_enabled.get():
                ok, macro_text = self._write_macro(created)
                details.append(("매크로", macro_text) if ok else ("매크로", macro_text, "red"))
            else:
                details.append(("매크로", "갱신 안 함", "gray"))
            if self.archive_enabled.get():
                snapshot = self._archive_result(created, fluor_flags, zstack,
                                                positions_per_file, split_fluor, prefix)
                details.append(("보관", snapshot) if snapshot
                               else ("보관", "실패 (로그 확인)", "red"))
            else:
                details.append(("보관", "사용 안 함", "gray"))
            done = datetime.now().strftime('%H:%M:%S')
            self.set_status(f"생성 완료 {done} (Full + ND Output)" if after_full
                            else f"ND Output 완료 {done}",
                            "green", details=details, append=after_full)
        except Exception as e:
            self.log_message(f"ND Output 오류: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.set_status("ND Output 오류 (로그 확인)", "red", append=after_full)

    def manual_run(self):
        self.log_message("\n수동 생성 시작 (Full → ND Output)...")
        self.run_all()

    # ---------------- 모니터링 ----------------
    def start_monitoring(self):
        if self.monitoring:
            return
        # 입력 4point 없으면 기본값으로 자동 생성 후 감시
        self.ensure_4point_exists()
        self.monitoring = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.set_status("모니터링 중...", "blue")
        self.log_message("=" * 60)
        self.log_message("모니터링 시작 (입력 파일 변경 시 Full + ND Output 자동 생성)")
        self.log_message(f"입력: {self.input_file.get()}")
        self.log_message("=" * 60)
        try:
            self._check_interval_seconds = float(self.check_interval.get())
        except Exception:
            self._check_interval_seconds = 0.5
        if self._check_interval_seconds <= 0:
            self._check_interval_seconds = 0.5
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop_monitoring(self):
        self.monitoring = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.set_status("중지됨", "gray")
        self.log_message("모니터링을 중지했습니다.")

    def monitor_loop(self):
        input_file = self.input_file.get()
        check_interval = self._check_interval_seconds
        if not os.path.exists(input_file):
            self.log_message("입력 파일이 존재하지 않습니다. 대기 중...")
            while self.monitoring and not os.path.exists(input_file):
                time.sleep(check_interval)
        if not self.monitoring:
            return
        self.last_modified = os.path.getmtime(input_file)
        self.log_message(f"초기 수정 시간: {datetime.fromtimestamp(self.last_modified).strftime('%Y-%m-%d %H:%M:%S')}\n")
        while self.monitoring:
            if os.path.exists(input_file):
                cur = os.path.getmtime(input_file)
                if cur != self.last_modified:
                    self.log_message(f"\n파일 변경 감지: {datetime.fromtimestamp(cur).strftime('%Y-%m-%d %H:%M:%S')}")
                    self.master.after(0, self.run_all)
                    self.last_modified = cur
            time.sleep(check_interval)

    # ---------------- 입력 파싱 ----------------
    def parse_point_range(self) -> Tuple[Optional[int], Optional[int]]:
        s = self.point_start_idx.get().strip()
        e = self.point_end_idx.get().strip()
        if not s and not e:
            return None, None
        if (not s and e) or (s and not e):
            self.log_message("범위 입력 오류: 시작/끝을 모두 입력하거나 모두 비워주세요.")
            return 0, None
        try:
            si, ei = int(s), int(e)
        except ValueError:
            self.log_message("범위 입력 오류: 정수만 입력 가능합니다.")
            return 0, None
        if si < 0 or ei <= 0 or si >= ei:
            self.log_message("범위 입력 오류: 0 <= 시작 < 끝 이어야 합니다. (예: 0-15)")
            return 0, None
        return si, ei

    def parse_delete_numbers(self):
        value = self.delete_numbers.get().strip()
        if not value:
            return set()
        parts = [p.strip() for p in value.split(',') if p.strip()]
        numbers = set()
        for part in parts:
            try:
                n = int(part)
            except ValueError:
                self.log_message("삭제 번호 오류: 정수만 입력하세요. (예: 5,6,7)")
                return None
            if n <= 0:
                self.log_message("삭제 번호 오류: 1 이상의 번호만 입력하세요.")
                return None
            numbers.add(n)
        return numbers

    # ---------------- 설정 ----------------
    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"설정 로드 오류: {e}")
        return {}

    def save_config(self):
        try:
            config = {
                "input_file": to_portable_path(self.input_file.get()),
                "output_file": to_portable_path(self.output_file.get()),
                "check_interval": self.check_interval.get(),
                "mesh_rows": self.mesh_rows.get(),
                "mesh_cols": self.mesh_cols.get(),
                "num_repetitions": self.num_repetitions.get(),
                "mesh_preset": self.mesh_preset.get(),
                "point_start_idx": self.point_start_idx.get(),
                "point_end_idx": self.point_end_idx.get(),
                "delete_numbers": self.delete_numbers.get(),
                "fluor_flags": [v.get() for v in self.fluor_flags],
                "fluor_offsets": [v.get() for v in self.fluor_offsets],
                "filter_names": self.filter_names,
                "nd_output_dir": to_portable_path(self.nd_output_dir.get()),
                "nd_output_prefix": self.nd_output_prefix.get(),
                "nd_positions_per_file": self.nd_positions_per_file.get(),
                "nd_split_fluor": self.nd_split_fluor.get(),
                "archive_enabled": self.archive_enabled.get(),
                "nd_clear_output": self.nd_clear_output.get(),
                "macro_enabled": self.macro_enabled.get(),
                "macro_file": self.macro_file.get(),
                "zstack_enabled": self.zstack_enabled.get(),
                "zstack_range": self.zstack_range.get(),
                "zstack_step": self.zstack_step.get(),
                "zstack_device": self.zstack_device.get(),
                "zstack_channel_flags": [v.get() for v in self.zstack_channel_flags],
                "window_geometry": self._current_geometry(),
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"설정 저장 오류: {e}")

    def on_closing(self):
        if self.monitoring:
            self.stop_monitoring()
        self.save_config()
        self.master.destroy()


def main():
    root = tk.Tk()
    NDGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
