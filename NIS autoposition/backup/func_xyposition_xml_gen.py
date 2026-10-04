"""
XML 메시 생성 함수 모듈
좌표를 기반으로 그리드 메시를 생성하고 XML 파일로 저장하는 함수들
"""

import numpy as np
from bisect import bisect_right
from xml.etree.ElementTree import Element, ElementTree
from typing import List, Tuple

def generate_mesh(left_top, top_right, bottom_right, rows, cols):
    """Generate a mesh grid based on the input corner coordinates."""
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
                # Explicitly set the first coordinate to be left_top
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
    """Generate offset meshes along the line connecting left_top_first and left_top_last."""
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

def plot_2d_meshes(all_meshes, input_points):
    """Plot all meshes in 2D with scatter and lines."""
    # 선택 기능(디버깅/시각화)이라, 런타임 의존성을 줄이기 위해 지연 import 처리
    import matplotlib.pyplot as plt
    plt.figure(figsize=(10, 8))

    for mesh in all_meshes:
        for row in mesh:
            x_coords = [point[0] for point in row]
            y_coords = [point[1] for point in row]
            plt.plot(x_coords, y_coords, 'b-', alpha=0.5)  # Horizontal lines
            plt.scatter(x_coords, y_coords, c='blue', s=10, alpha=0.5)

        for col in range(len(mesh[0])):
            x_coords = [mesh[row][col][0] for row in range(len(mesh))]
            y_coords = [mesh[row][col][1] for row in range(len(mesh))]
            plt.plot(x_coords, y_coords, 'b-', alpha=0.5)  # Vertical lines

    # Plot input points
    for point in input_points:
        plt.scatter(point[0], point[1], c='red', s=15, label='Input Point')

    plt.xlabel("X Coordinate")
    plt.ylabel("Y Coordinate")
    plt.title("2D Offset Meshes with Input Points")
    plt.axis("equal")
    plt.grid(True)

    # Reverse the axes
    plt.xlim(57000, -57000)
    plt.ylim(37000, -37000)

    plt.show()

def generate_XML_for_meshes(
    all_meshes,
    rows,
    cols,
    file_name,
    auto_focus=False,
    start_idx=None,
    end_idx=None,
    delete_numbers=None
):
    """
    Generate XML file for multiple meshes.
    
    Args:
        all_meshes: List of 2D mesh position matrices (list of list of tuples)
        rows: Number of rows in a single line mesh
        cols: Number of columns in a single line mesh
        file_name: Name of the output XML file
        auto_focus: False for manual Z-focus (포함), True for PFS auto-focus (제외)
        start_idx: 0-based 시작 인덱스(미입력 시 전체)
        end_idx: 1-based 끝 인덱스 포함값(미입력 시 전체)
        delete_numbers: 삭제할 번호 집합(예: {5, 6, 7})
    
    Returns:
        Created XML file path
    """
    variant = Element("variant", {"version": "1.0"})
    no_name = Element("no_name", {"runtype": "CLxListVariant"})
    variant.append(no_name)

    # Add common elements based on focus mode
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
        
    label_1 = "ABCDEFGHI"  # Labels for the 9 lines
    cnt = 0
    delete_numbers = delete_numbers or set()
    sorted_delete_numbers = sorted(delete_numbers)

    for line_idx, mesh in enumerate(all_meshes):
        for i in range(rows):
            for j in range(cols):
                # Generate position name based on line and grid location
                point_number = i * cols + j + 1
                if point_number in delete_numbers:
                    continue
                # 삭제된 번호 개수만큼 앞으로 당겨서 재할당
                shifted_point_number = point_number - bisect_right(sorted_delete_numbers, point_number)
                if start_idx is not None and end_idx is not None:
                    if not (start_idx < shifted_point_number <= end_idx):
                        continue

                cnt_str = f"{cnt:05d}"
                cnt += 1
                position_name = f"{label_1[line_idx]}{shifted_point_number:02d}"
                position_xy = mesh[i][j]

                # Create XML structure for each point
                point_name = Element(f"Point{cnt_str}", {"runtype": "NDSetupMultipointListItem"})
                no_name.append(point_name)

                bChecked = Element("bChecked", {"runtype": "bool", "value": "true"})
                point_name.append(bChecked)

                strName = Element("strName", {"runtype": "CLxStringW", "value": position_name})
                point_name.append(strName)

                dXPosition = Element("dXPosition", {"runtype": "double", "value": str(position_xy[0])})
                point_name.append(dXPosition)

                dYPosition = Element("dYPosition", {"runtype": "double", "value": str(position_xy[1])})
                point_name.append(dYPosition)

                dZPosition = Element("dZPosition", {"runtype": "double", "value": str(position_xy[2])})
                point_name.append(dZPosition)

                dPFSOffset = Element("dPFSOffset", {"runtype": "double", "value": "-1.000000000000000"})
                point_name.append(dPFSOffset)

                baUserData = Element("baUserData", {"runtype": "CLxByteArray", "value": ""})
                point_name.append(baUserData)

    # Write to XML file
    tree = ElementTree(variant)
    file_path = f"{file_name}.xml"
    with open(file_path, "wb") as file:
        tree.write(file, encoding="UTF-16", xml_declaration=True)
    
    return file_path
