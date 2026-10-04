"""
draw mesh map.py
생성된 multipoints XML 좌표를 2D로 그리되, Z값을 색으로 표시한다.
"""

import argparse
import csv
import os
import re
import xml.etree.ElementTree as ET

def parse_points_from_xml(xml_path):
    """XML에서 (name, x, y, z) 목록을 읽어온다."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    points = []
    for elem in root.iter():
        if not elem.tag.startswith("Point"):
            continue

        name_elem = elem.find("strName")
        x_elem = elem.find("dXPosition")
        y_elem = elem.find("dYPosition")
        z_elem = elem.find("dZPosition")

        if name_elem is None or x_elem is None or y_elem is None or z_elem is None:
            continue

        name = name_elem.get("value")
        x = float(x_elem.get("value"))
        y = float(y_elem.get("value"))
        z = float(z_elem.get("value"))
        points.append((name, x, y, z))

    return points


def split_name(name):
    """
    이름을 (라인 라벨, 번호)로 분리한다.
    예: A01 -> ('A', 1), B12 -> ('B', 12)
    """
    match = re.match(r"^([A-Za-z]+)(\d+)$", name or "")
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))


def draw_mesh_map(points, title, reverse_axes=True):
    """2D 산점도 + Z 컬러맵 시각화."""
    import matplotlib.pyplot as plt

    if not points:
        raise ValueError("표시할 좌표가 없습니다.")

    # 라인/번호 기준으로 정렬하면 mesh가 보기에 더 안정적이다.
    points = sorted(points, key=lambda p: split_name(p[0]))

    x_values = [p[1] for p in points]
    y_values = [p[2] for p in points]
    z_values = [p[3] for p in points]

    fig, ax = plt.subplots(figsize=(11, 8))

    sc = ax.scatter(
        x_values,
        y_values,
        c=z_values,
        cmap="viridis",
        s=28,
        alpha=0.95,
        edgecolors="none",
    )

    colorbar = plt.colorbar(sc, ax=ax)
    colorbar.set_label("Z value")

    ax.set_title(title)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.grid(True, alpha=0.3)
    ax.set_aspect("equal", adjustable="box")

    # 기존 프로젝트 시각화 방향과 맞추기 위해 기본값은 축 반전
    if reverse_axes:
        ax.invert_xaxis()
        ax.invert_yaxis()

    plt.tight_layout()
    plt.show()


def save_points_to_csv(points, csv_path):
    """좌표를 x,y,z 순서로 CSV 저장."""
    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["x", "y", "z"])
        for _, x, y, z in points:
            writer.writerow([x, y, z])


def main():
    default_xml = os.path.join(os.path.dirname(__file__), "generated_multipoints.xml")
    parser = argparse.ArgumentParser(description="Draw 2D mesh map colored by Z from XML.")
    parser.add_argument(
        "--xml",
        default=default_xml,
        help=f"입력 XML 경로 (기본값: {default_xml})",
    )
    parser.add_argument(
        "--keep-axis",
        action="store_true",
        help="축 반전을 끄고 원래 축 방향으로 표시",
    )
    parser.add_argument(
        "--csv",
        default="",
        help="출력 CSV 경로 (기본값: 입력 XML과 같은 위치/이름의 .csv)",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="그래프를 띄우지 않고 CSV만 저장",
    )
    args = parser.parse_args()

    if not os.path.exists(args.xml):
        raise FileNotFoundError(f"XML 파일을 찾을 수 없습니다: {args.xml}")

    points = parse_points_from_xml(args.xml)
    csv_path = args.csv.strip() or os.path.splitext(args.xml)[0] + ".csv"
    save_points_to_csv(points, csv_path)
    print(f"CSV 저장 완료: {csv_path}")

    if not args.no_plot:
        draw_mesh_map(
            points=points,
            title=f"Mesh Map (N={len(points)})",
            reverse_axes=not args.keep_axis,
        )


if __name__ == "__main__":
    main()
