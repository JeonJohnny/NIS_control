"""
Mesh + ND Generator UI  (통합 단일 프로그램)

NIS 좌표 XML(4개 모서리)을 감지/추출하여 메시 multipoints XML을 생성하고,
이어서 ND 실험 XML 파일(nd01.xml, nd01-F1.xml ...)까지 한 번에 생성하는 통합 GUI.

- 1단계: multipoints_from_NIS.xml(4개 모서리) -> generated_multipoints.xml (메시 그리드)
- 2단계: generated_multipoints.xml + 템플릿 -> nd_output/nd01.xml 등 (형광 채널/그룹 분할/체이닝)

이 파일은 외부 프로젝트 모듈에 의존하지 않는 자립형(self-contained) 프로그램이다.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import os
import re
import sys
import copy
import time
import json
import xml.etree.ElementTree as ET
from bisect import bisect_right
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional
from xml.etree.ElementTree import Element, ElementTree

import numpy as np


# ============================================================================
# 공통 유틸
# ============================================================================
def _get_app_dir() -> str:
    """실행 위치 기준 디렉터리 반환 (개발/PyInstaller 배포 모두 대응)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _get_app_dir()
CONFIG_FILE = os.path.join(APP_DIR, "mesh_nd_config.json")
NUM_FLUOR_CHANNELS = 8


# ============================================================================
# 1단계: 메시 생성 (좌표 -> 그리드 -> multipoints XML)
# ============================================================================
def generate_mesh(left_top, top_right, bottom_right, rows, cols):
    """입력 모서리 좌표를 기반으로 메시 그리드를 생성."""
    lt_x, lt_y, lt_z = left_top
    rt_x, rt_y, rt_z = top_right
    br_x, br_y, br_z = bottom_right
    lb_x, lb_y, lb_z = lt_x + (br_x - rt_x), lt_y + (br_y - rt_y), lt_z + (br_z - rt_z)

    x_linspace = np.linspace(0, 1, cols)
    y_linspace = np.linspace(0, 1, rows)
    position_matrix = []

    for i in range(rows):
        row = []
        for j in range(cols):
            if i == 0 and j == 0:
                x, y, z = lt_x, lt_y, lt_z
            else:
                alpha_x = x_linspace[j]
                alpha_y = y_linspace[i]
                x = (1 - alpha_x) * ((1 - alpha_y) * lt_x + alpha_y * lb_x) + alpha_x * ((1 - alpha_y) * rt_x + alpha_y * br_x)
                y = (1 - alpha_x) * ((1 - alpha_y) * lt_y + alpha_y * lb_y) + alpha_x * ((1 - alpha_y) * rt_y + alpha_y * br_y)
                z = (1 - alpha_x) * ((1 - alpha_y) * lt_z + alpha_y * lb_z) + alpha_x * ((1 - alpha_y) * rt_z + alpha_y * br_z)
            row.append((x, y, z))
        position_matrix.append(row)

    return position_matrix


def generate_offset_meshes(left_top_first, left_top_last, top_right, bottom_right, rows, cols, repetitions):
    """left_top_first ~ left_top_last 선을 따라 offset 메시들을 생성."""
    lt_dx = (left_top_last[0] - left_top_first[0]) / (repetitions - 1)
    lt_dy = (left_top_last[1] - left_top_first[1]) / (repetitions - 1)
    lt_dz = (left_top_last[2] - left_top_first[2]) / (repetitions - 1)

    all_meshes = []
    base_mesh = generate_mesh(left_top_first, top_right, bottom_right, rows, cols)

    for r in range(repetitions):
        offset_x = r * lt_dx
        offset_y = r * lt_dy
        offset_z = r * lt_dz
        offset_mesh = [
            [(point[0] + offset_x, point[1] + offset_y, point[2] + offset_z) for point in row]
            for row in base_mesh
        ]
        all_meshes.append(offset_mesh)

    return all_meshes


def generate_XML_for_meshes(all_meshes, rows, cols, file_name, auto_focus=False,
                            start_idx=None, end_idx=None, delete_numbers=None):
    """
    여러 메시를 하나의 multipoints XML로 저장.
    auto_focus: False=수동 Z(포함), True=PFS 자동(제외)
    start_idx(0-based)/end_idx(1-based 포함): 구간만 생성 (미입력 시 전체)
    delete_numbers: 삭제할 포인트 번호 집합 (예: {5,6,7})
    반환: 생성된 XML 파일 경로
    """
    variant = Element("variant", {"version": "1.0"})
    no_name = Element("no_name", {"runtype": "CLxListVariant"})
    variant.append(no_name)

    if auto_focus:
        no_name.append(Element("bIncludeZ", {"runtype": "bool", "value": "false"}))
        no_name.append(Element("bPFSEnabled", {"runtype": "bool", "value": "true"}))
    else:
        no_name.append(Element("bIncludeZ", {"runtype": "bool", "value": "true"}))
        no_name.append(Element("bPFSEnabled", {"runtype": "bool", "value": "false"}))

    label_1 = "ABCDEFGHI"
    cnt = 0
    delete_numbers = delete_numbers or set()
    sorted_delete_numbers = sorted(delete_numbers)

    for line_idx, mesh in enumerate(all_meshes):
        for i in range(rows):
            for j in range(cols):
                point_number = i * cols + j + 1
                if point_number in delete_numbers:
                    continue
                shifted_point_number = point_number - bisect_right(sorted_delete_numbers, point_number)
                if start_idx is not None and end_idx is not None:
                    if not (start_idx < shifted_point_number <= end_idx):
                        continue

                cnt_str = f"{cnt:05d}"
                cnt += 1
                position_name = f"{label_1[line_idx]}{shifted_point_number:02d}"
                position_xy = mesh[i][j]

                point_name = Element(f"Point{cnt_str}", {"runtype": "NDSetupMultipointListItem"})
                no_name.append(point_name)
                point_name.append(Element("bChecked", {"runtype": "bool", "value": "true"}))
                point_name.append(Element("strName", {"runtype": "CLxStringW", "value": position_name}))
                point_name.append(Element("dXPosition", {"runtype": "double", "value": str(position_xy[0])}))
                point_name.append(Element("dYPosition", {"runtype": "double", "value": str(position_xy[1])}))
                point_name.append(Element("dZPosition", {"runtype": "double", "value": str(position_xy[2])}))
                point_name.append(Element("dPFSOffset", {"runtype": "double", "value": "-1.000000000000000"}))
                point_name.append(Element("baUserData", {"runtype": "CLxByteArray", "value": ""}))

    tree = ElementTree(variant)
    file_path = f"{file_name}.xml"
    with open(file_path, "wb") as file:
        tree.write(file, encoding="UTF-16", xml_declaration=True)
    return file_path


# ============================================================================
# 2단계: ND 실험 파일 생성 (multipoints + 템플릿 -> nd01.xml ...)
# ============================================================================
def normalize_name(name: str) -> str:
    """a1/A01/aa3 등을 표준형 A01/AA03 으로 변환."""
    m = re.fullmatch(r"\s*([A-Za-z]+)\s*0*([0-9]+)\s*", name or "")
    if not m:
        raise ValueError(f"Invalid point name format: {name!r}")
    return f"{m.group(1).upper()}{int(m.group(2)):02d}"


def nd_split_name(name: str):
    m = re.fullmatch(r"([A-Z]+)(\d+)", normalize_name(name))
    if not m:
        raise ValueError(f"Invalid normalized name: {name!r}")
    return m.group(1), int(m.group(2))


def children_map(node: ET.Element):
    return {child.tag: child for child in list(node)}


def clear_and_fill_list(list_node: ET.Element, values, runtype: str):
    list_node[:] = []
    for i, value in enumerate(values):
        ET.SubElement(list_node, f"item_{i:05d}", {"runtype": runtype, "value": str(value)})


def clear_and_fill_name_list(list_node: ET.Element, values):
    list_node[:] = []
    for i, value in enumerate(values):
        ET.SubElement(list_node, f"item_{i:05d}", {"runtype": "CLxStringW", "value": value})


def parse_tag_pattern(tag: str):
    m = re.match(r"^(.*?)(\d+)$", tag or "")
    if not m:
        return "_", 2
    return m.group(1), len(m.group(2))


def rebuild_variant_list(list_node: ET.Element, item_count: int):
    children = list(list_node)
    prefix, width = ("_", 2)
    if children:
        prefix, width = parse_tag_pattern(children[0].tag)
    runtype = children[0].attrib.get("runtype", "bool") if children else "bool"
    value = children[0].attrib.get("value", "true") if children else "true"

    list_node[:] = []
    for i in range(item_count):
        ET.SubElement(list_node, f"{prefix}{i:0{width}d}", {"runtype": runtype, "value": value})


def find_loop(root: ET.Element, loop_runtype: str) -> ET.Element:
    for node in root.iter("no_name"):
        if node.attrib.get("runtype") == loop_runtype:
            return node
    raise RuntimeError(f"Could not find {loop_runtype}")


def find_experiment_with_loop(root: ET.Element, loop_runtype: str):
    for exp in root.iter("no_name"):
        if exp.attrib.get("runtype") != "RLxExperiment":
            continue
        c = children_map(exp)
        u_loop_pars = c.get("uLoopPars")
        if u_loop_pars is None:
            continue
        loops = list(u_loop_pars)
        if not loops:
            continue
        if loops[0].attrib.get("runtype") == loop_runtype:
            return exp
    return None


def extract_points_from_multipoints(multipoints_root: ET.Element):
    data = {}
    for node in multipoints_root.iter():
        if not node.tag.startswith("Point"):
            continue
        c = children_map(node)
        required = {"strName", "dXPosition", "dYPosition", "dZPosition", "dPFSOffset"}
        if not required <= set(c):
            continue
        name = normalize_name(c["strName"].attrib.get("value", ""))
        data[name] = {
            "x": c["dXPosition"].attrib["value"],
            "y": c["dYPosition"].attrib["value"],
            "z": c["dZPosition"].attrib["value"],
            "pfs": c["dPFSOffset"].attrib.get("value", "-1.0"),
        }
    return data


def apply_points_to_template(root: ET.Element, points: dict, targets: list):
    xy_loop = find_loop(root, "RLxExperiment.RLxExpXYPosLoop")
    c = children_map(xy_loop)
    required = {"uiCount", "dPosX", "dPosY", "dPosZ", "dPFSOffset", "pPosName"}
    if not required <= set(c):
        missing = ", ".join(sorted(required - set(c)))
        raise RuntimeError(f"XYPosLoop is missing required tags: {missing}")

    clear_and_fill_list(c["dPosX"], [points[name]["x"] for name in targets], "double")
    clear_and_fill_list(c["dPosY"], [points[name]["y"] for name in targets], "double")
    clear_and_fill_list(c["dPosZ"], [points[name]["z"] for name in targets], "double")
    clear_and_fill_list(c["dPFSOffset"], [points[name]["pfs"] for name in targets], "double")
    clear_and_fill_name_list(c["pPosName"], targets)
    c["uiCount"].attrib["value"] = str(len(targets))


def apply_fluor_flags(root: ET.Element, flags):
    spect_loop = find_loop(root, "RLxExperiment.RLxExpSpectLoop")
    loop_children = children_map(spect_loop)
    if "uiCount" not in loop_children:
        raise RuntimeError("Spect loop does not contain uiCount")

    total_channels = int(loop_children["uiCount"].attrib.get("value", "0"))
    if len(flags) != total_channels:
        raise ValueError(f"형광 채널 수는 {total_channels}개여야 합니다. (현재 {len(flags)}개)")

    spect_exp = find_experiment_with_loop(root, "RLxExperiment.RLxExpSpectLoop")
    if spect_exp is None:
        raise RuntimeError("Could not find RLxExperiment for SpectLoop")

    exp_children = children_map(spect_exp)
    p_item_valid = exp_children.get("pItemValid")
    if p_item_valid is None:
        raise RuntimeError("Spect experiment does not contain pItemValid")

    if len(list(p_item_valid)) != total_channels:
        rebuild_variant_list(p_item_valid, total_channels)

    for idx, item in enumerate(list(p_item_valid)):
        item.attrib["value"] = "true" if int(flags[idx]) != 0 else "false"


def sync_experiment_pitemvalid_with_loop_count(root: ET.Element):
    """pItemValid 리스트 길이를 대응 루프의 uiCount와 동기화."""
    for exp in root.iter("no_name"):
        if exp.attrib.get("runtype") != "RLxExperiment":
            continue
        c = children_map(exp)
        p_item_valid = c.get("pItemValid")
        u_loop_pars = c.get("uLoopPars")
        if p_item_valid is None or u_loop_pars is None:
            continue
        if len(list(p_item_valid)) == 0:
            continue
        loops = list(u_loop_pars)
        if not loops:
            continue
        loop_children = children_map(loops[0])
        ui_count = loop_children.get("uiCount")
        if ui_count is None:
            continue
        target_count = int(ui_count.attrib.get("value", "0"))
        if len(list(p_item_valid)) != target_count:
            rebuild_variant_list(p_item_valid, target_count)


def set_top_level_after_capture_command(root: ET.Element, command_text: str):
    """최상위(타임루프) 실험의 wsCommandAfterCapture 만 설정."""
    for exp in root.iter("no_name"):
        if exp.attrib.get("runtype") != "RLxExperiment":
            continue
        c = children_map(exp)
        e_type = c.get("eType")
        after_capture = c.get("wsCommandAfterCapture")
        if e_type is None or after_capture is None:
            continue
        if e_type.attrib.get("value") == "1":
            after_capture.attrib["value"] = command_text
            return


def write_xml_with_double_quote_declaration(root: ET.Element, out_path: Path):
    """NIS 친화적 스타일(UTF-16, 큰따옴표 선언, compact self-closing)로 XML 저장."""
    def strip_ws(node: ET.Element):
        if node.text and node.text.strip() == "":
            node.text = None
        if node.tail and node.tail.strip() == "":
            node.tail = None
        for child in list(node):
            strip_ws(child)

    strip_ws(root)
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    xml_body = xml_body.replace("&quot;", "&#x0022;").replace(" />", "/>")
    xml_text = f'<?xml version="1.0" encoding="UTF-16"?>{xml_body}'
    with open(out_path, "w", encoding="utf-16", newline="") as fp:
        fp.write(xml_text)


def generate_nd_files(multipoints_path, template_path, out_dir,
                      output_prefix="nd", positions_per_file=36,
                      fluor_flags=(1, 1, 1, 0, 0, 0, 0, 0),
                      split_fluor=True, log_callback=None):
    """
    multipoints XML + 템플릿을 읽어 ND 실험 XML 파일들을 생성.
    반환: 생성된 파일 경로 문자열 리스트.
    """
    log = log_callback or (lambda m: None)

    if positions_per_file <= 0:
        raise ValueError("그룹당 포인트 수는 1 이상이어야 합니다.")

    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)

    mp_root = ET.parse(multipoints_path).getroot()
    template_root = ET.parse(template_path).getroot()

    points = extract_points_from_multipoints(mp_root)
    all_names = sorted(points.keys(), key=nd_split_name)
    if not all_names:
        raise RuntimeError("multipoints에서 유효한 포인트를 찾지 못했습니다.")

    group_total = (len(all_names) + positions_per_file - 1) // positions_per_file
    index_width = max(2, len(str(group_total)))

    # 형광 채널 세트 구성
    flags = [1 if int(v) != 0 else 0 for v in fluor_flags]
    enabled_indices = [i for i, v in enumerate(flags) if v == 1]
    if not enabled_indices:
        raise ValueError("최소 1개의 형광 채널을 선택하세요.")

    if not split_fluor:
        channel_sets = [("all", flags)]
    else:
        channel_sets = []
        for order_idx, channel_idx in enumerate(enabled_indices, start=1):
            one_channel = [0] * len(flags)
            one_channel[channel_idx] = 1
            channel_sets.append((f"F{order_idx}", one_channel))

    planned_jobs = []
    group_count = 0
    for start in range(0, len(all_names), positions_per_file):
        group_count += 1
        targets = all_names[start:start + positions_per_file]
        base_name = f"{output_prefix}{group_count:0{index_width}d}"
        for suffix, channel_flags in channel_sets:
            out_name = f"{base_name}.xml" if suffix == "all" else f"{base_name}-{suffix}.xml"
            planned_jobs.append((targets, channel_flags, out_name))

    created = []
    file_count = len(planned_jobs)
    for idx, (targets, channel_flags, out_name) in enumerate(planned_jobs):
        out_path = out_dir_p / out_name
        next_file = planned_jobs[idx + 1][2] if idx + 1 < file_count else None

        nd_root = copy.deepcopy(template_root)
        apply_fluor_flags(nd_root, channel_flags)
        apply_points_to_template(nd_root, points, targets)
        sync_experiment_pitemvalid_with_loop_count(nd_root)

        if next_file is not None:
            next_path = (out_dir_p / next_file).resolve()
            set_top_level_after_capture_command(nd_root, f'ND_LoadExperiment("{next_path}");')
        else:
            set_top_level_after_capture_command(nd_root, "")

        write_xml_with_double_quote_declaration(nd_root, out_path)
        created.append(str(out_path))
        log(f"생성: {out_path} ({len(targets)} points: {targets[0]}..{targets[-1]})")

    log(f"완료. 총 포인트: {len(all_names)}, 그룹: {group_count}, 파일: {file_count}")
    return created


# ============================================================================
# GUI
# ============================================================================
class MeshNDGenerator:
    """메시 multipoints 생성 + ND 실험 파일 생성 통합 GUI"""

    def __init__(self, master):
        self.master = master
        self.master.title("Mesh + ND Generator")

        window_width = 640
        window_height = 860
        screen_width = self.master.winfo_screenwidth()
        x = screen_width - window_width
        y = 0
        self.master.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 모니터링 상태
        self.monitoring = False
        self.monitor_thread = None
        self.last_modified = None
        self._check_interval_seconds = 0.5

        # 설정 불러오기
        self.config = self.load_config()

        # ---- 1단계(메시) 설정 ----
        self.input_file = tk.StringVar(
            value=self.config.get("input_file") or os.path.join(APP_DIR, "multipoints_from_NIS.xml")
        )
        self.output_file = tk.StringVar(
            value=self.config.get("output_file") or os.path.join(APP_DIR, "generated_multipoints.xml")
        )
        self.check_interval = tk.DoubleVar(value=self.config.get("check_interval", 0.5))
        self.mesh_rows = tk.IntVar(value=self.config.get("mesh_rows", 2))
        self.mesh_cols = tk.IntVar(value=self.config.get("mesh_cols", 54))
        self.num_repetitions = tk.IntVar(value=self.config.get("num_repetitions", 4))
        self.point_start_idx = tk.StringVar(value=str(self.config.get("point_start_idx", "")))
        self.point_end_idx = tk.StringVar(value=str(self.config.get("point_end_idx", "")))
        self.delete_numbers = tk.StringVar(value=str(self.config.get("delete_numbers", "")))
        self.auto_focus = tk.BooleanVar(value=self.config.get("auto_focus", False))

        # ---- 2단계(ND) 설정 ----
        self.nd_template_file = tk.StringVar(
            value=self.config.get("nd_template_file")
            or os.path.join(APP_DIR, "nd_t3 gen", "compare_origin.xml")
        )
        self.nd_output_dir = tk.StringVar(
            value=self.config.get("nd_output_dir")
            or os.path.join(APP_DIR, "nd_t3 gen", "nd_output")
        )
        self.nd_output_prefix = tk.StringVar(value=self.config.get("nd_output_prefix", "nd"))
        self.nd_positions_per_file = tk.IntVar(value=self.config.get("nd_positions_per_file", 36))
        self.nd_split_fluor = tk.BooleanVar(value=self.config.get("nd_split_fluor", True))
        self.nd_auto_run = tk.BooleanVar(value=self.config.get("nd_auto_run", False))

        default_flags = [True, True, True, False, False, False, False, False]
        saved_flags = self.config.get("nd_fluor_flags", default_flags)
        self.nd_fluor_flags = []
        for i in range(NUM_FLUOR_CHANNELS):
            val = bool(saved_flags[i]) if i < len(saved_flags) else False
            self.nd_fluor_flags.append(tk.BooleanVar(value=val))

        self.setup_ui()
        self.master.bind('<Destroy>', lambda e: self.save_config())

    def setup_ui(self):
        main_frame = ttk.Frame(self.master, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # ===== 파일 설정 =====
        file_frame = ttk.LabelFrame(main_frame, text="파일 설정", padding="10")
        file_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(file_frame, text="입력 XML 파일:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(file_frame, textvariable=self.input_file, width=45).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(file_frame, text="출력 XML 파일:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(file_frame, textvariable=self.output_file, width=45).grid(row=1, column=1, padx=5, pady=5)

        # ===== 메시 설정 =====
        mesh_frame = ttk.LabelFrame(main_frame, text="메시 설정 (1단계)", padding="10")
        mesh_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(mesh_frame, text="Rows (X 방향):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Spinbox(mesh_frame, from_=1, to=10, textvariable=self.mesh_rows, width=10).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(mesh_frame, text="Cols (Y 방향):").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        ttk.Spinbox(mesh_frame, from_=1, to=100, textvariable=self.mesh_cols, width=10).grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(mesh_frame, text="반복 횟수:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Spinbox(mesh_frame, from_=1, to=10, textvariable=self.num_repetitions, width=10).grid(row=1, column=1, padx=5, pady=5)

        range_frame = ttk.Frame(mesh_frame)
        range_frame.grid(row=1, column=2, columnspan=5, sticky=tk.W, padx=5, pady=5)
        ttk.Label(range_frame, text="구간보기 시작 (").pack(side=tk.LEFT)
        ttk.Entry(range_frame, textvariable=self.point_start_idx, width=6).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(range_frame, text="), 끝 (").pack(side=tk.LEFT)
        ttk.Entry(range_frame, textvariable=self.point_end_idx, width=6).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(range_frame, text=")  (비우면 전체)").pack(side=tk.LEFT)

        ttk.Label(mesh_frame, text="삭제 번호 (쉼표구분):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(mesh_frame, textvariable=self.delete_numbers, width=34).grid(row=2, column=1, columnspan=3, sticky=(tk.W, tk.E), padx=5, pady=5)
        ttk.Label(mesh_frame, text="예: 5,6,7").grid(row=2, column=4, columnspan=3, sticky=tk.W, padx=5, pady=5)

        ttk.Label(mesh_frame, text="포커스 모드:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        focus_frame = ttk.Frame(mesh_frame)
        focus_frame.grid(row=3, column=1, columnspan=6, sticky=tk.W, padx=5, pady=5)
        ttk.Radiobutton(focus_frame, text="수동 Z (Manual)", variable=self.auto_focus, value=False).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(focus_frame, text="PFS 자동 (Auto)", variable=self.auto_focus, value=True).pack(side=tk.LEFT, padx=10)

        mesh_frame.columnconfigure(1, weight=1)
        mesh_frame.columnconfigure(2, weight=1)
        mesh_frame.columnconfigure(3, weight=1)

        # ===== ND 파일 생성 설정 =====
        nd_frame = ttk.LabelFrame(main_frame, text="ND 파일 생성 설정 (2단계)", padding="10")
        nd_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(nd_frame, text="템플릿 XML:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(nd_frame, textvariable=self.nd_template_file, width=45).grid(row=0, column=1, columnspan=5, sticky=(tk.W, tk.E), padx=5, pady=4)

        ttk.Label(nd_frame, text="출력 폴더:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(nd_frame, textvariable=self.nd_output_dir, width=45).grid(row=1, column=1, columnspan=5, sticky=(tk.W, tk.E), padx=5, pady=4)

        ttk.Label(nd_frame, text="출력 접두사:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(nd_frame, textvariable=self.nd_output_prefix, width=12).grid(row=2, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(nd_frame, text="그룹당 포인트 수:").grid(row=2, column=2, sticky=tk.W, padx=5, pady=4)
        ttk.Spinbox(nd_frame, from_=1, to=999, textvariable=self.nd_positions_per_file, width=8).grid(row=2, column=3, sticky=tk.W, padx=5, pady=4)

        ttk.Label(nd_frame, text="형광 채널:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=4)
        channel_frame = ttk.Frame(nd_frame)
        channel_frame.grid(row=3, column=1, columnspan=5, sticky=tk.W, padx=5, pady=4)
        for i in range(NUM_FLUOR_CHANNELS):
            ttk.Checkbutton(channel_frame, text=f"Ch{i+1}", variable=self.nd_fluor_flags[i]).pack(side=tk.LEFT, padx=2)

        ttk.Checkbutton(nd_frame, text="채널별 파일 분리 (nd01-F1.xml ...)", variable=self.nd_split_fluor).grid(
            row=4, column=0, columnspan=3, sticky=tk.W, padx=5, pady=4)
        ttk.Checkbutton(nd_frame, text="멀티포인트 생성 후 ND 자동 생성", variable=self.nd_auto_run).grid(
            row=4, column=3, columnspan=3, sticky=tk.W, padx=5, pady=4)

        nd_frame.columnconfigure(1, weight=1)

        # ===== 컨트롤 버튼 =====
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=3, column=0, columnspan=2, pady=10)

        self.start_button = ttk.Button(control_frame, text="모니터링 시작", command=self.start_monitoring)
        self.start_button.pack(side=tk.LEFT, padx=4)
        self.stop_button = ttk.Button(control_frame, text="모니터링 중지", command=self.stop_monitoring, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=4)
        ttk.Button(control_frame, text="메시 수동 실행", command=self.manual_run).pack(side=tk.LEFT, padx=4)
        ttk.Button(control_frame, text="ND 파일 생성", command=self.run_nd_generation).pack(side=tk.LEFT, padx=4)
        ttk.Button(control_frame, text="로그 지우기", command=self.clear_log).pack(side=tk.LEFT, padx=4)

        # ===== 상태 표시 =====
        self.status_label = ttk.Label(main_frame, text="대기 중...", font=("Arial", 10, "bold"))
        self.status_label.grid(row=4, column=0, columnspan=2, pady=5)

        # ===== 로그 =====
        log_frame = ttk.LabelFrame(main_frame, text="로그", padding="10")
        log_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=80, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 그리드 가중치
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(5, weight=1)

    # ---------------- 로그 ----------------
    def log_message(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    # ---------------- 1단계: 좌표 추출/메시 생성 ----------------
    def extract_coordinates_from_xml(self, xml_file):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            points = [elem for elem in root.iter() if elem.tag.startswith('Point')]

            coordinates = []
            for point in points:
                name_elem = point.find('strName')
                x_elem = point.find('dXPosition')
                y_elem = point.find('dYPosition')
                z_elem = point.find('dZPosition')
                if name_elem is not None and x_elem is not None and y_elem is not None and z_elem is not None:
                    coordinates.append({
                        'name': name_elem.get('value'),
                        'x': float(x_elem.get('value')),
                        'y': float(y_elem.get('value')),
                        'z': float(z_elem.get('value')),
                    })
            return coordinates
        except Exception as e:
            self.log_message(f"XML 파싱 오류: {e}")
            return []

    def process_coordinates(self):
        """좌표 처리 및 메시 XML 생성. 성공 시(옵션) ND 자동 생성."""
        input_file = self.input_file.get()
        output_file = self.output_file.get()

        if not os.path.exists(input_file):
            self.log_message(f"파일을 찾을 수 없습니다: {input_file}")
            return

        coordinates = self.extract_coordinates_from_xml(input_file)
        if not coordinates:
            self.log_message("추출된 좌표가 없습니다.")
            return

        self.log_message(f"총 {len(coordinates)}개의 좌표를 찾았습니다:")
        for i, coord in enumerate(coordinates):
            self.log_message(f"  {i+1}. {coord['name']}: ({coord['x']:.6f}, {coord['y']:.6f}, {coord['z']:.6f})")

        if len(coordinates) < 4:
            self.log_message("최소 4개의 좌표가 필요합니다.")
            return

        corners = coordinates[:4]
        left_top_first = (corners[0]['x'], corners[0]['y'], corners[0]['z'])
        top_right = (corners[1]['x'], corners[1]['y'], corners[1]['z'])
        bottom_right = (corners[2]['x'], corners[2]['y'], corners[2]['z'])
        left_top_last = (corners[3]['x'], corners[3]['y'], corners[3]['z'])

        self.log_message(f"\n모서리 좌표:")
        self.log_message(f"  좌상단 첫번째: {left_top_first}")
        self.log_message(f"  우상단: {top_right}")
        self.log_message(f"  우하단: {bottom_right}")
        self.log_message(f"  좌상단 마지막: {left_top_last}")

        mesh_rows = self.mesh_rows.get()
        mesh_cols = self.mesh_cols.get()
        num_repetitions = self.num_repetitions.get()
        auto_focus = self.auto_focus.get()

        delete_numbers = self.parse_delete_numbers()
        if delete_numbers is None:
            self.status_label.config(text="삭제 번호 입력 오류", foreground="red")
            return
        if not delete_numbers:
            self.log_message("  삭제 규칙: 미적용(전체 유지)")
        else:
            self.log_message(f"  삭제 번호: {', '.join(str(n) for n in sorted(delete_numbers))}")

        start_idx, end_idx = self.parse_point_range()
        if start_idx is None and end_idx is None:
            self.log_message("  Point 범위: 전체")
        elif start_idx is not None and end_idx is not None:
            self.log_message(f"  Point 범위: {start_idx}-{end_idx} (생성: 01~{end_idx:02d})")
        else:
            self.status_label.config(text="범위 입력 오류", foreground="red")
            return

        self.log_message(f"\n메시 설정:")
        self.log_message(f"  Rows: {mesh_rows}, Cols: {mesh_cols}, Repetitions: {num_repetitions}")
        self.log_message(f"  Focus: {'PFS 자동' if auto_focus else '수동 Z'}")

        try:
            self.log_message("\n메시 생성 중...")
            offset_meshes = generate_offset_meshes(
                left_top_first, left_top_last, top_right, bottom_right,
                mesh_rows, mesh_cols, num_repetitions
            )
            self.log_message("XML 파일 생성 중...")
            xml_path = generate_XML_for_meshes(
                offset_meshes, mesh_rows, mesh_cols,
                output_file.replace('.xml', ''), auto_focus,
                start_idx=start_idx, end_idx=end_idx,
                delete_numbers=delete_numbers
            )
            self.log_message(f"\n메시 XML 생성 완료: {xml_path}")
            self.status_label.config(text=f"메시 완료: {xml_path}", foreground="green")
        except Exception as e:
            self.log_message(f"메시 생성 오류: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.status_label.config(text="오류 발생", foreground="red")
            return

        if self.nd_auto_run.get():
            self.log_message("\n[자동] ND 파일 생성 시작...")
            self.run_nd_generation()

    # ---------------- 2단계: ND 파일 생성 ----------------
    def run_nd_generation(self):
        """ND 실험 XML 파일 생성 (수동 버튼/자동 공통 진입점)."""
        multipoints_path = self.output_file.get()
        template_path = self.nd_template_file.get()
        out_dir = self.nd_output_dir.get()
        prefix = self.nd_output_prefix.get().strip() or "nd"

        if not os.path.exists(multipoints_path):
            self.log_message(f"ND 생성 실패: multipoints 파일이 없습니다: {multipoints_path}")
            self.log_message("  먼저 '메시 수동 실행'으로 multipoints XML을 생성하세요.")
            self.status_label.config(text="ND 오류: multipoints 없음", foreground="red")
            return
        if not os.path.exists(template_path):
            self.log_message(f"ND 생성 실패: 템플릿 파일이 없습니다: {template_path}")
            self.status_label.config(text="ND 오류: 템플릿 없음", foreground="red")
            return

        try:
            positions_per_file = int(self.nd_positions_per_file.get())
        except Exception:
            self.log_message("ND 생성 실패: 그룹당 포인트 수는 정수여야 합니다.")
            self.status_label.config(text="ND 오류: 그룹 수", foreground="red")
            return

        fluor_flags = [1 if var.get() else 0 for var in self.nd_fluor_flags]
        if sum(fluor_flags) == 0:
            self.log_message("ND 생성 실패: 최소 1개의 형광 채널을 선택하세요.")
            self.status_label.config(text="ND 오류: 채널 없음", foreground="red")
            return

        split_fluor = self.nd_split_fluor.get()

        self.log_message("\n" + "=" * 60)
        self.log_message("ND 파일 생성")
        self.log_message(f"  multipoints: {multipoints_path}")
        self.log_message(f"  템플릿: {template_path}")
        self.log_message(f"  출력 폴더: {out_dir}")
        self.log_message(f"  접두사: {prefix}, 그룹당: {positions_per_file}")
        self.log_message(f"  형광 채널: {fluor_flags}, 채널별 분리: {split_fluor}")
        self.log_message("=" * 60)

        try:
            created = generate_nd_files(
                multipoints_path=multipoints_path,
                template_path=template_path,
                out_dir=out_dir,
                output_prefix=prefix,
                positions_per_file=positions_per_file,
                fluor_flags=fluor_flags,
                split_fluor=split_fluor,
                log_callback=self.log_message,
            )
            self.log_message(f"\nND 파일 생성 완료: {len(created)}개")
            self.status_label.config(text=f"ND 완료: {len(created)}개 파일", foreground="green")
        except Exception as e:
            self.log_message(f"ND 생성 오류: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.status_label.config(text="ND 오류 발생", foreground="red")

    # ---------------- 모니터링 ----------------
    def start_monitoring(self):
        if self.monitoring:
            return
        self.monitoring = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_label.config(text="모니터링 중...", foreground="blue")

        self.log_message("=" * 60)
        self.log_message("모니터링 시작")
        self.log_message(f"입력 파일: {self.input_file.get()}")
        self.log_message(f"출력 파일: {self.output_file.get()}")
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
        self.status_label.config(text="중지됨", foreground="gray")
        self.log_message("모니터링을 중지했습니다.")

    def monitor_loop(self):
        input_file = self.input_file.get()
        check_interval = self._check_interval_seconds

        if not os.path.exists(input_file):
            self.log_message(f"파일이 존재하지 않습니다. 대기 중...")
            while self.monitoring and not os.path.exists(input_file):
                time.sleep(check_interval)

        if not self.monitoring:
            return

        self.last_modified = os.path.getmtime(input_file)
        self.log_message(f"초기 파일 수정 시간: {datetime.fromtimestamp(self.last_modified).strftime('%Y-%m-%d %H:%M:%S')}\n")

        while self.monitoring:
            if os.path.exists(input_file):
                current_modified = os.path.getmtime(input_file)
                if current_modified != self.last_modified:
                    self.log_message(f"\n{'='*60}")
                    self.log_message(f"파일 변경 감지: {datetime.fromtimestamp(current_modified).strftime('%Y-%m-%d %H:%M:%S')}")
                    self.log_message(f"{'='*60}\n")
                    self.master.after(0, self.process_coordinates)
                    self.last_modified = current_modified
            time.sleep(check_interval)

    def manual_run(self):
        self.log_message("\n메시 수동 실행 시작...")
        self.process_coordinates()

    # ---------------- 입력 파싱 ----------------
    def parse_point_range(self) -> Tuple[Optional[int], Optional[int]]:
        start_text = self.point_start_idx.get().strip()
        end_text = self.point_end_idx.get().strip()

        if not start_text and not end_text:
            return None, None
        if (not start_text and end_text) or (start_text and not end_text):
            self.log_message("범위 입력 오류: 시작값/끝값을 모두 입력하거나 모두 비워주세요.")
            return 0, None

        try:
            start_idx = int(start_text)
            end_idx = int(end_text)
        except ValueError:
            self.log_message("범위 입력 오류: 시작값/끝값은 정수만 입력 가능합니다.")
            return 0, None

        if start_idx < 0:
            self.log_message("범위 입력 오류: 시작값은 0 이상이어야 합니다.")
            return 0, None
        if end_idx <= 0:
            self.log_message("범위 입력 오류: 끝값은 1 이상이어야 합니다.")
            return 0, None
        if start_idx >= end_idx:
            self.log_message("범위 입력 오류: 시작값은 끝값보다 작아야 합니다. (예: 0-15)")
            return 0, None

        return start_idx, end_idx

    def parse_delete_numbers(self):
        value = self.delete_numbers.get().strip()
        if not value:
            return set()

        parts = [part.strip() for part in value.split(',') if part.strip()]
        if not parts:
            return set()

        numbers = set()
        for part in parts:
            try:
                number = int(part)
            except ValueError:
                self.log_message("삭제 번호 입력 오류: 정수만 입력하세요. (예: 5,6,7)")
                return None
            if number <= 0:
                self.log_message("삭제 번호 입력 오류: 1 이상의 번호만 입력하세요.")
                return None
            numbers.add(number)

        return numbers

    # ---------------- 설정 저장/로드 ----------------
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
                "input_file": self.input_file.get(),
                "output_file": self.output_file.get(),
                "check_interval": self.check_interval.get(),
                "mesh_rows": self.mesh_rows.get(),
                "mesh_cols": self.mesh_cols.get(),
                "num_repetitions": self.num_repetitions.get(),
                "auto_focus": self.auto_focus.get(),
                "point_start_idx": self.point_start_idx.get(),
                "point_end_idx": self.point_end_idx.get(),
                "delete_numbers": self.delete_numbers.get(),
                "nd_template_file": self.nd_template_file.get(),
                "nd_output_dir": self.nd_output_dir.get(),
                "nd_output_prefix": self.nd_output_prefix.get(),
                "nd_positions_per_file": self.nd_positions_per_file.get(),
                "nd_split_fluor": self.nd_split_fluor.get(),
                "nd_auto_run": self.nd_auto_run.get(),
                "nd_fluor_flags": [var.get() for var in self.nd_fluor_flags],
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"설정 저장 완료: {CONFIG_FILE}")
        except Exception as e:
            print(f"설정 저장 오류: {e}")

    def on_closing(self):
        if self.monitoring:
            self.stop_monitoring()
        self.save_config()
        self.master.destroy()


def main():
    root = tk.Tk()
    app = MeshNDGenerator(root)
    root.mainloop()


if __name__ == "__main__":
    main()
