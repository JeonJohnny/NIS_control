"""
XML Coordinate Generator UI
XML 파일 변경을 감지하고 좌표를 추출하여 새로운 XML을 생성하는 GUI 애플리케이션
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import os
import sys
import xml.etree.ElementTree as ET
import time
from datetime import datetime
from typing import List, Tuple, Optional
import numpy as np
import json
from xml.etree.ElementTree import Element, ElementTree

# XML 메시 생성 함수 import
from func_xyposition_xml_gen import (
    generate_mesh, 
    generate_offset_meshes, 
    generate_XML_for_meshes
)

def _get_app_dir() -> str:
    """
    실행 위치 기준 디렉터리 반환.
    - 개발(파이썬 실행): 현재 파일 위치
    - 배포(exe, PyInstaller): exe 위치
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _get_app_dir()

# 설정 파일 경로 (exe 배포 시에도 같은 폴더에 저장/로드)
CONFIG_FILE = os.path.join(APP_DIR, "gui_config.json")


class XMLCoordinateGenerator:
    """XML 좌표 생성 및 모니터링 클래스"""
    
    def __init__(self, master):
        self.master = master
        self.master.title("XML Coordinate Generator")
        
        # 창 크기 설정
        window_width = 620
        window_height = 600
        
        # 화면 정보 가져오기
        screen_width = self.master.winfo_screenwidth()
        screen_height = self.master.winfo_screenheight()
        
        # 모니터 가장 오른쪽에 배치
        x = screen_width - window_width
        y = 0  # 상단에 붙임 (필요시 (screen_height - window_height) // 2 로 변경 가능)
        
        self.master.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 모니터링 상태
        self.monitoring = False
        self.monitor_thread = None
        self.last_modified = None
        self._check_interval_seconds = 0.5
        
        # 설정 불러오기
        self.config = self.load_config()
        
        # 기본 설정
        self.input_file = tk.StringVar(
            value=self.config.get("input_file") or os.path.join(APP_DIR, "multipoints_from_NIS.xml")
        )
        self.output_file = tk.StringVar(
            value=self.config.get("output_file") or os.path.join(APP_DIR, "generated_multipoints.xml")
        )
        self.check_interval = tk.DoubleVar(value=self.config.get("check_interval", 0.5))
        
        # 메시 설정
        self.mesh_rows = tk.IntVar(value=self.config.get("mesh_rows", 2))
        self.mesh_cols = tk.IntVar(value=self.config.get("mesh_cols", 54))
        self.num_repetitions = tk.IntVar(value=self.config.get("num_repetitions", 4))
        self.point_start_idx = tk.StringVar(value=str(self.config.get("point_start_idx", "")))
        self.point_end_idx = tk.StringVar(value=str(self.config.get("point_end_idx", "")))
        self.delete_numbers = tk.StringVar(value=str(self.config.get("delete_numbers", "")))
        
        # 포커스 모드 설정
        self.auto_focus = tk.BooleanVar(value=self.config.get("auto_focus", False))
        
        self.setup_ui()
        
        # 창 닫을 때 설정 저장
        self.master.bind('<Destroy>', lambda e: self.save_config())
        
    def setup_ui(self):
        """UI 구성 요소 생성"""
        # 메인 프레임
        main_frame = ttk.Frame(self.master, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 파일 설정 프레임
        file_frame = ttk.LabelFrame(main_frame, text="파일 설정", padding="10")
        file_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(file_frame, text="입력 XML 파일:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(file_frame, textvariable=self.input_file, width=40).grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(file_frame, text="출력 XML 파일:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(file_frame, textvariable=self.output_file, width=40).grid(row=1, column=1, padx=5, pady=5)
        
        # 메시 설정 프레임
        mesh_frame = ttk.LabelFrame(main_frame, text="메시 설정", padding="10")
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
        
        # 포커스 모드 선택
        ttk.Label(mesh_frame, text="포커스 모드:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        focus_frame = ttk.Frame(mesh_frame)
        focus_frame.grid(row=3, column=1, columnspan=6, sticky=tk.W, padx=5, pady=5)
        
        ttk.Radiobutton(focus_frame, text="수동 Z (Manual)", variable=self.auto_focus, value=False).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(focus_frame, text="PFS 자동 (Auto)", variable=self.auto_focus, value=True).pack(side=tk.LEFT, padx=10)
        
        # 컨트롤 버튼 프레임
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, columnspan=2, pady=10)
        
        self.start_button = ttk.Button(control_frame, text="모니터링 시작", command=self.start_monitoring)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(control_frame, text="모니터링 중지", command=self.stop_monitoring, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(control_frame, text="수동 실행", command=self.manual_run).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="로그 지우기", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        
        # 상태 표시
        self.status_label = ttk.Label(main_frame, text="대기 중...", font=("Arial", 10, "bold"))
        self.status_label.grid(row=3, column=0, columnspan=2, pady=5)
        
        # 로그 영역
        log_frame = ttk.LabelFrame(main_frame, text="로그", padding="10")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, width=78, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 그리드 가중치 설정
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        mesh_frame.columnconfigure(1, weight=1)
        mesh_frame.columnconfigure(2, weight=1)
        mesh_frame.columnconfigure(3, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
    def log_message(self, message):
        """로그 메시지 추가"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        
    def clear_log(self):
        """로그 지우기"""
        self.log_text.delete("1.0", tk.END)
        
    def extract_coordinates_from_xml(self, xml_file):
        """XML 파일에서 좌표 추출"""
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            # 모든 자식 요소 확인
            all_elements = list(root.iter())
            
            # Point로 시작하는 요소들 찾기
            points = [elem for elem in all_elements if elem.tag.startswith('Point')]
            
            coordinates = []
            for point in points:
                name_elem = point.find('strName')
                x_elem = point.find('dXPosition')
                y_elem = point.find('dYPosition')
                z_elem = point.find('dZPosition')
                
                if name_elem is not None and x_elem is not None and y_elem is not None and z_elem is not None:
                    name = name_elem.get('value')
                    x = float(x_elem.get('value'))
                    y = float(y_elem.get('value'))
                    z = float(z_elem.get('value'))
                    
                    coordinates.append({
                        'name': name,
                        'x': x,
                        'y': y,
                        'z': z
                    })
            
            return coordinates
        except Exception as e:
            self.log_message(f"XML 파싱 오류: {e}")
            return []
    
    def generate_XML_from_coordinates(self, coordinates, output_file):
        """추출된 좌표를 기반으로 새 XML 생성"""
        variant = Element("variant", {"version": "1.0"})
        no_name = Element("no_name", {"runtype": "CLxListVariant"})
        variant.append(no_name)

        # 포커스 설정에 따른 XML 요소 추가
        auto_focus = self.auto_focus.get()
        if auto_focus:
            # PFS 자동 포커스 모드: Z 좌표 제외
            bIncludeZ = Element("bIncludeZ", {"runtype": "bool", "value": "false"})
            no_name.append(bIncludeZ)
            bPFSEnabled = Element("bPFSEnabled", {"runtype": "bool", "value": "true"})
            no_name.append(bPFSEnabled)
        else:
            # 수동 Z 포커스 모드: Z 좌표 포함
            bIncludeZ = Element("bIncludeZ", {"runtype": "bool", "value": "true"})
            no_name.append(bIncludeZ)
            bPFSEnabled = Element("bPFSEnabled", {"runtype": "bool", "value": "false"})
            no_name.append(bPFSEnabled)

        for idx, coord in enumerate(coordinates):
            point_num_str = f"{idx:05d}"
            
            point_element = Element(f"Point{point_num_str}", {"runtype": "NDSetupMultipointListItem"})
            no_name.append(point_element)

            bChecked = Element("bChecked", {"runtype": "bool", "value": "true"})
            point_element.append(bChecked)

            strName = Element("strName", {"runtype": "CLxStringW", "value": coord['name']})
            point_element.append(strName)

            dXPosition = Element("dXPosition", {"runtype": "double", "value": str(coord['x'])})
            point_element.append(dXPosition)

            dYPosition = Element("dYPosition", {"runtype": "double", "value": str(coord['y'])})
            point_element.append(dYPosition)

            dZPosition = Element("dZPosition", {"runtype": "double", "value": str(coord['z'])})
            point_element.append(dZPosition)

            dPFSOffset = Element("dPFSOffset", {"runtype": "double", "value": "-1.000000000000000"})
            point_element.append(dPFSOffset)

            baUserData = Element("baUserData", {"runtype": "CLxByteArray", "value": ""})
            point_element.append(baUserData)

        tree = ElementTree(variant)
        with open(output_file, "wb") as file:
            tree.write(file, encoding="UTF-16", xml_declaration=True)
    
    def process_coordinates(self):
        """좌표 처리 및 XML mesh 생성"""
        input_file = self.input_file.get()
        output_file = self.output_file.get()
        
        if not os.path.exists(input_file):
            self.log_message(f"파일을 찾을 수 없습니다: {input_file}")
            return
            
        # 좌표 추출
        coordinates = self.extract_coordinates_from_xml(input_file)
        
        if not coordinates:
            self.log_message("추출된 좌표가 없습니다.")
            return
        
        self.log_message(f"총 {len(coordinates)}개의 좌표를 찾았습니다:")
        for i, coord in enumerate(coordinates):
            self.log_message(f"  {i+1}. {coord['name']}: ({coord['x']:.6f}, {coord['y']:.6f}, {coord['z']:.6f})")
        
        # 4개 모서리 좌표 추출
        if len(coordinates) < 4:
            self.log_message("최소 4개의 좌표가 필요합니다.")
            return
        
        # 좌표 정렬 (첫 4개를 사용)
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
        
        # 메시 설정값 가져오기
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
        
        # 메시 생성
        try:
            self.log_message("\n메시 생성 중...")
            offset_meshes = generate_offset_meshes(
                left_top_first, left_top_last, top_right, bottom_right,
                mesh_rows, mesh_cols, num_repetitions
            )
            
            # XML 파일 생성
            self.log_message("XML 파일 생성 중...")
            xml_path = generate_XML_for_meshes(
                offset_meshes, mesh_rows, mesh_cols, 
                output_file.replace('.xml', ''), auto_focus,
                start_idx=start_idx, end_idx=end_idx,
                delete_numbers=delete_numbers
            )
            
            self.log_message(f"\nXML 파일 생성 완료: {xml_path}")
            self.status_label.config(text=f"완료: {xml_path}", foreground="green")
            
        except Exception as e:
            self.log_message(f"메시 생성 오류: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.status_label.config(text="오류 발생", foreground="red")
    
    def start_monitoring(self):
        """모니터링 시작"""
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

        # 백그라운드 스레드에서 Tk 변수 접근을 최소화하기 위해 여기서 고정
        try:
            self._check_interval_seconds = float(self.check_interval.get())
        except Exception:
            self._check_interval_seconds = 0.5
        if self._check_interval_seconds <= 0:
            self._check_interval_seconds = 0.5
        
        # 모니터링 스레드 시작
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """모니터링 중지"""
        self.monitoring = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="중지됨", foreground="gray")
        self.log_message("모니터링을 중지했습니다.")
    
    def monitor_loop(self):
        """모니터링 루프"""
        input_file = self.input_file.get()
        check_interval = self._check_interval_seconds
        
        # 파일이 존재하는지 확인
        if not os.path.exists(input_file):
            self.log_message(f"파일이 존재하지 않습니다. 대기 중...")
            while self.monitoring and not os.path.exists(input_file):
                time.sleep(check_interval)
        
        if not self.monitoring:
            return
        
        # 초기 파일의 수정 시간 가져오기
        self.last_modified = os.path.getmtime(input_file)
        self.log_message(f"초기 파일 수정 시간: {datetime.fromtimestamp(self.last_modified).strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        while self.monitoring:
            if os.path.exists(input_file):
                current_modified = os.path.getmtime(input_file)
                
                if current_modified != self.last_modified:
                    self.log_message(f"\n{'='*60}")
                    self.log_message(f"파일 변경 감지: {datetime.fromtimestamp(current_modified).strftime('%Y-%m-%d %H:%M:%S')}")
                    self.log_message(f"{'='*60}\n")
                    
                    # 좌표 처리
                    self.master.after(0, self.process_coordinates)
                    
                    self.last_modified = current_modified
            
            time.sleep(check_interval)
    
    def manual_run(self):
        """수동 실행"""
        self.log_message("\n수동 실행 시작...")
        self.process_coordinates()

    def parse_point_range(self) -> Tuple[Optional[int], Optional[int]]:
        """GUI 범위 입력값 파싱 (비어있으면 전체)"""
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
        """삭제 번호 파싱: '5,6,7' (비어있으면 미적용)"""
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
    
    def load_config(self):
        """설정 파일에서 설정 불러오기"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"설정 로드 오류: {e}")
        return {}
    
    def save_config(self):
        """현재 설정을 파일에 저장"""
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
                "delete_numbers": self.delete_numbers.get()
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"설정 저장 완료: {CONFIG_FILE}")
        except Exception as e:
            print(f"설정 저장 오류: {e}")
    
    def on_closing(self):
        """창 닫기 처리"""
        if self.monitoring:
            self.stop_monitoring()
        self.save_config()
        self.master.destroy()


def main():
    """메인 함수"""
    root = tk.Tk()
    app = XMLCoordinateGenerator(root)
    root.mainloop()


if __name__ == "__main__":
    main()

