"""
[임시] 폴더 변화 모니터 — NIS 촬영 시작/종료를 트리거로 쓸 수 있는지 관찰용.

지정 폴더를 0.5초마다 스캔해서 (파일 추가/삭제, 크기, 수정시각, 잠금 여부, 폴더 자체 mtime)
바뀐 항목만 타임스탬프와 함께 로그로 남긴다.

    python tmp_folder_monitor.py [폴더] [간격초]

종료: Ctrl+C 또는 스크립트 옆에 tmp_folder_monitor.stop 파일을 만들면 멈춘다.
로그: 스크립트 옆 tmp_folder_monitor.log (콘솔에도 같이 출력)
"""
import os
import sys
import time
from datetime import datetime

DEFAULT_DIR = r"D:\HSJ 2025\260923_형광염색 테스트"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "tmp_folder_monitor.log")
STOP_PATH = os.path.join(HERE, "tmp_folder_monitor.stop")


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fp:
        fp.write(line + "\n")


def is_locked(path):
    """다른 프로세스가 쓰기 잠금을 잡고 있으면 True. (append 로 열어보기만 하고 아무것도 쓰지 않음)"""
    try:
        with open(path, "ab"):
            return False
    except (PermissionError, OSError):
        return True


def snapshot(folder):
    snap = {}
    for root, dirs, files in os.walk(folder):
        for name in files:
            p = os.path.join(root, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            rel = os.path.relpath(p, folder)
            snap[rel] = {"size": st.st_size, "mtime": st.st_mtime, "locked": is_locked(p)}
        for name in dirs:
            rel = os.path.relpath(os.path.join(root, name), folder)
            snap[rel + os.sep] = {"size": -1, "mtime": os.stat(os.path.join(root, name)).st_mtime,
                                  "locked": False}
    try:
        dir_mtime = os.stat(folder).st_mtime
    except OSError:
        dir_mtime = None
    return snap, dir_mtime


def fmt_t(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]


def describe(info):
    return f"size={info['size']:,} mtime={fmt_t(info['mtime'])} locked={info['locked']}"


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    if os.path.exists(STOP_PATH):
        os.remove(STOP_PATH)

    log("=" * 70)
    log(f"모니터링 시작: {folder}  (간격 {interval}s, PID {os.getpid()})")
    prev, prev_dir_mtime = snapshot(folder)
    log(f"초기 상태: 항목 {len(prev)}개, 폴더 mtime={fmt_t(prev_dir_mtime) if prev_dir_mtime else '?'}")
    for rel in sorted(prev):
        log(f"  {rel}: {describe(prev[rel])}")
    log("-" * 70)

    try:
        while not os.path.exists(STOP_PATH):
            time.sleep(interval)
            cur, dir_mtime = snapshot(folder)
            if dir_mtime != prev_dir_mtime:
                log(f"[폴더 mtime] {fmt_t(prev_dir_mtime)} -> {fmt_t(dir_mtime)}")
            for rel in sorted(set(cur) - set(prev)):
                log(f"[추가] {rel}: {describe(cur[rel])}")
            for rel in sorted(set(prev) - set(cur)):
                log(f"[삭제] {rel}  (마지막: {describe(prev[rel])})")
            for rel in sorted(set(cur) & set(prev)):
                a, b = prev[rel], cur[rel]
                changes = []
                if a["size"] != b["size"]:
                    changes.append(f"size {a['size']:,} -> {b['size']:,} ({b['size'] - a['size']:+,})")
                if a["mtime"] != b["mtime"]:
                    changes.append(f"mtime {fmt_t(a['mtime'])} -> {fmt_t(b['mtime'])}")
                if a["locked"] != b["locked"]:
                    changes.append(f"locked {a['locked']} -> {b['locked']}")
                if changes:
                    log(f"[변경] {rel}: " + ", ".join(changes))
            prev, prev_dir_mtime = cur, dir_mtime
    except KeyboardInterrupt:
        pass
    log("모니터링 종료")


if __name__ == "__main__":
    main()
