import copy
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ===== User Config (edit here) =====
MULTIPOINTS_XML = "generated_multipoints.xml"
TEMPLATE_XML = "compare_origin.xml"
OUTPUT_DIR = "nd_output"
OUTPUT_PREFIX = "nd"

# Number of positions included in each output file.
POSITIONS_PER_FILE = 36

# Fluorescence channel enable flags.
# Example: [0, 0, 0, 0, 1, 1, 1, 0]
# 0 => false, non-zero => true
FLUOR_CHANNEL_FLAGS = [1, 1, 1, 0, 0, 0, 0, 0]

# If True, create one file per enabled fluorescence channel:
# nd01-F1.xml, nd01-F2.xml, ...
SPLIT_FLUOR_CHANNEL_FILES = True


def normalize_name(name: str) -> str:
    """Convert variants such as a1/A01/aa3 to canonical form A01/AA03."""
    m = re.fullmatch(r"\s*([A-Za-z]+)\s*0*([0-9]+)\s*", name or "")
    if not m:
        raise ValueError(f"Invalid point name format: {name!r}")
    row = m.group(1).upper()
    col = int(m.group(2))
    return f"{row}{col:02d}"


def split_name(name: str):
    m = re.fullmatch(r"([A-Z]+)(\d+)", normalize_name(name))
    if not m:
        raise ValueError(f"Invalid normalized name: {name!r}")
    return m.group(1), int(m.group(2))


def children_map(node: ET.Element):
    return {child.tag: child for child in list(node)}


def clear_and_fill_list(list_node: ET.Element, values, runtype: str):
    list_node[:] = []
    for i, value in enumerate(values):
        ET.SubElement(
            list_node,
            f"item_{i:05d}",
            {"runtype": runtype, "value": str(value)},
        )


def clear_and_fill_name_list(list_node: ET.Element, values):
    list_node[:] = []
    for i, value in enumerate(values):
        ET.SubElement(
            list_node,
            f"item_{i:05d}",
            {"runtype": "CLxStringW", "value": value},
        )


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
        ET.SubElement(
            list_node,
            f"{prefix}{i:0{width}d}",
            {"runtype": runtype, "value": value},
        )


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


def apply_points_to_template(root: ET.Element, points: dict, targets: list[str]):
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
        raise ValueError(
            f"FLUOR_CHANNEL_FLAGS length must be {total_channels}, got {len(flags)}"
        )

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


def build_channel_flag_sets(base_flags):
    flags = [1 if int(v) != 0 else 0 for v in list(base_flags)]
    enabled_indices = [idx for idx, v in enumerate(flags) if v == 1]
    if not enabled_indices:
        raise ValueError("At least one channel must be enabled in FLUOR_CHANNEL_FLAGS")

    if not SPLIT_FLUOR_CHANNEL_FILES:
        return [("all", flags)]

    result = []
    for order_idx, channel_idx in enumerate(enabled_indices, start=1):
        one_channel = [0] * len(flags)
        one_channel[channel_idx] = 1
        result.append((f"F{order_idx}", one_channel))
    return result


def sync_experiment_pitemvalid_with_loop_count(root: ET.Element):
    """Keep pItemValid list length equal to corresponding loop uiCount."""
    for exp in root.iter("no_name"):
        if exp.attrib.get("runtype") != "RLxExperiment":
            continue

        c = children_map(exp)
        p_item_valid = c.get("pItemValid")
        u_loop_pars = c.get("uLoopPars")
        if p_item_valid is None or u_loop_pars is None:
            continue

        # Top-level experiment can have empty pItemValid by design.
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
    """Set wsCommandAfterCapture only for the top-level (time-loop) experiment."""
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
    """
    Write XML with a fixed declaration line that uses double quotes:
    <?xml version="1.0" encoding="UTF-16"?>
    """
    def strip_ws(node: ET.Element):
        if node.text and node.text.strip() == "":
            node.text = None
        if node.tail and node.tail.strip() == "":
            node.tail = None
        for child in list(node):
            strip_ws(child)

    # Remove indentation/newline-only text nodes to produce compact output.
    strip_ws(root)
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    # Match NIS-friendly style: numeric quote entity and compact self-closing tags.
    xml_body = xml_body.replace("&quot;", "&#x0022;").replace(" />", "/>")
    xml_text = f'<?xml version="1.0" encoding="UTF-16"?>{xml_body}'
    with open(out_path, "w", encoding="utf-16", newline="") as fp:
        fp.write(xml_text)


def main():
    if POSITIONS_PER_FILE <= 0:
        raise ValueError("POSITIONS_PER_FILE must be > 0")

    multipoints_path = Path(MULTIPOINTS_XML)
    template_path = Path(TEMPLATE_XML)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    mp_root = ET.parse(multipoints_path).getroot()
    template_root = ET.parse(template_path).getroot()

    points = extract_points_from_multipoints(mp_root)
    all_names = sorted(points.keys(), key=split_name)
    if not all_names:
        raise RuntimeError("No valid points found in multipoints.xml")

    group_total = (len(all_names) + POSITIONS_PER_FILE - 1) // POSITIONS_PER_FILE
    index_width = max(2, len(str(group_total)))
    channel_sets = build_channel_flag_sets(FLUOR_CHANNEL_FLAGS)

    planned_jobs = []
    group_count = 0
    for start in range(0, len(all_names), POSITIONS_PER_FILE):
        group_count += 1
        targets = all_names[start : start + POSITIONS_PER_FILE]
        base_name = f"{OUTPUT_PREFIX}{group_count:0{index_width}d}"
        for suffix, channel_flags in channel_sets:
            out_name = f"{base_name}.xml" if suffix == "all" else f"{base_name}-{suffix}.xml"
            planned_jobs.append((targets, channel_flags, out_name))

    file_count = len(planned_jobs)
    for idx, (targets, channel_flags, out_name) in enumerate(planned_jobs):
        out_path = out_dir / out_name
        next_file = planned_jobs[idx + 1][2] if idx + 1 < file_count else None

        nd_root = copy.deepcopy(template_root)
        apply_fluor_flags(nd_root, channel_flags)
        apply_points_to_template(nd_root, points, targets)
        sync_experiment_pitemvalid_with_loop_count(nd_root)

        if next_file is not None:
            next_path = (out_dir / next_file).resolve()
            set_top_level_after_capture_command(
                nd_root, f'ND_LoadExperiment("{next_path}");'
            )
        else:
            set_top_level_after_capture_command(nd_root, "")

        write_xml_with_double_quote_declaration(nd_root, out_path)
        print(f"Created {out_path} ({len(targets)} points: {targets[0]}..{targets[-1]})")

    print(
        f"Done. Total points: {len(all_names)}, groups: {group_count}, files created: {file_count}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
