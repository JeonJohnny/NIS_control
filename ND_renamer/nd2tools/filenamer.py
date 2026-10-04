# -*- coding: utf-8 -*-
"""이름 변경: nd2 파일명을 규칙에 맞게 정리하고 폴더별로 분류한다. (GUI: ND2Tools.py)

새 이름: [헤더_][약물_]t값[_번호].nd2   (예: AS_t1_001.nd2, AS_t2.nd2, t1_001.nd2)
폴더   : [추가단어/][약물/]   (약물명이 없으면 약물 폴더 없이 정리)
번호   : 같은 (단어, 약물, t값) 그룹에 파일이 여러 개일 때만 001부터 매김.
         기존 번호 순서대로, 번호 없는 파일은 그 뒤에 파일명 순서대로.
         마지막 t(폴더에서 가장 큰 t값)는 번호 대신 L라인_채널 (채널 수만큼이 한 라인):
         AS_t3_L1_BF.nd2, AS_t3_L1_FITC.nd2, AS_t3_L1_PI.nd2, AS_t3_L1_ANX.nd2, AS_t3_L2_BF.nd2 …
         그 밖의 파일은 끝에 _BF: AS_t1_BF.nd2
기록   : 실행할 때마다 폴더에 _FileNamer_log_*.csv를 남기고, 이 기록으로 되돌릴 수 있다.

표준 라이브러리만 쓴다 (nd2 파일을 열지 않고 이름만 다룬다).
"""
import csv
import glob
import os
import re
import shutil
from datetime import datetime

DRUGS = ["AS", "BO", "DA", "IM", "NI", "PO"]
EXT = ".nd2"
ORIGIN_DIR = "origin"  # 예전 버전(OME-TIFF 변환)이 실행 기록을 옮겨 두던 폴더. 되돌리기 때 여기서도 찾는다
LOG_PREFIX = "_FileNamer_log_"  # 기존 로그로도 되돌리기가 되도록 이름을 유지한다

# 약물명: 앞에 영숫자가 없고 뒤에 영문자가 없을 때만 인정 (AS_t1, AS001 OK / BASE, ASx 무시)
_DRUG_RE = re.compile(r"(?<![A-Za-z0-9])(%s)(?![A-Za-z])" % "|".join(DRUGS), re.I)
# t값: t1~t4. 바로 뒤에 3자리 이상 숫자가 붙으면 그 숫자는 번호로 본다 (t1001 = t1 + 001)
_T_RE = re.compile(r"(?<![A-Za-z0-9])t([1-4])(?=\d{3,}(?![A-Za-z])|(?![A-Za-z0-9]))", re.I)
_DIGITS_RE = re.compile(r"\d+")
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def _natural_key(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def _clean(text):
    """파일/폴더 이름에 쓸 수 없는 문자를 지운다. Windows가 무시하는 끝의 점과 공백도 지운다."""
    text = _BAD_CHARS.sub("", text).strip().rstrip(". ")
    if not text.strip(".") or text.upper() in _RESERVED:
        return ""
    return text


def parse_name(stem, words):
    """파일명(확장자 제외)에서 (word, drug, t, number)를 추출한다.

    실패하면 (None, 사유)를 돌려준다.
    """
    drugs = {m.group(1).upper() for m in _DRUG_RE.finditer(stem)} or {""}
    if len(drugs) > 1:
        return None, "약물명 여러 개: " + ", ".join(sorted(drugs))

    t_matches = list(_T_RE.finditer(stem))
    ts = {m.group(1) for m in t_matches}
    if not ts:
        return None, "t값 없음"
    if len(ts) > 1:
        return None, "t값 여러 개: " + ", ".join("t" + x for x in sorted(ts))

    # t값 숫자를 구분자로 바꾼 뒤 마지막 숫자 덩어리를 기존 번호로 본다.
    chars = list(stem)
    for m in t_matches:
        chars[m.start(1)] = "_"
    numbers = _DIGITS_RE.findall("".join(chars))
    number = int(numbers[-1]) if numbers else None

    low = stem.lower()
    word = next((w for w in words if w.lower() in low), "")
    return (word, drugs.pop(), "t" + ts.pop(), number), None


def normalize_words(raw):
    """쉼표로 구분된 입력을 정리한다. 대소문자만 다른 중복은 앞의 것만 남긴다."""
    words, seen = [], set()
    for w in raw.split(","):
        w = _clean(w)
        if w and w.lower() not in seen:
            seen.add(w.lower())
            words.append(w)
    return words


def _strip_channel(stem, channels):
    """이름 끝의 _채널이름을 뗀다 (이미 바꾼 파일을 다시 돌릴 때 채널 이름 속 숫자를 번호로 읽지 않게)."""
    low = stem.lower()
    for ch in channels:
        if low.endswith("_" + ch.lower()):
            return stem[: -len(ch) - 1]
    return stem


def build_plan(folder, header, words, by_word=True, by_drug=True, by_t=False, channels=(), single=""):
    """(moves, skipped, warnings, finals)를 돌려준다.

    by_word, by_drug, by_t: 하위 폴더를 만들 기준. 켜진 것만 단어 > 약물 > t값 순서로 중첩한다.
    모두 꺼지면 선택한 폴더 안에서 이름만 바꾼다.
    추가 단어는 폴더로만 쓰이므로 by_word가 꺼지면 쓰지 않는다.
    channels: 마지막 t(폴더에서 가장 큰 t값)의 번호 파일에 번호 대신 붙일 채널 이름들 (촬영 순서).
              채널 수만큼의 파일이 한 라인이다.
              예: ("BF", "FITC", "PI", "ANX") → _L1_BF, _L1_FITC, _L1_PI, _L1_ANX, _L2_BF, _L2_FITC …
              비어 있으면 마지막 t도 _001, _002 … 로 번호를 매긴다.
    single  : 그 밖의 파일(t1, t2 등 한 채널만 찍은 파일) 이름 끝에 붙일 채널 이름. 예: "BF" → AS_t1_BF.nd2
              번호가 붙는 경우는 AS_t1_001_BF.nd2. 비어 있으면 붙이지 않는다.

    moves   : [(원본 경로, 새 경로)]
    skipped : [(파일명, 사유)]
    warnings: [문장]
    finals  : [(원본 경로, 최종 경로, t값)]  이름이 그대로인 파일도 포함
    """
    header = _clean(header)
    if not by_word:
        words = []
    groups, skipped, warnings = {}, [], []

    names = [n for n in os.listdir(folder)
             if n.lower().endswith(EXT) and os.path.isfile(os.path.join(folder, n))]
    known = list(channels) + ([single] if single else [])
    tail = "_" + single if single else ""
    # 이미 _L라인_채널로 바꾼 이름은 촬영 순번으로 되돌려 읽는다 (다시 돌려도 같은 이름이 되게)
    lower = [c.lower() for c in channels]
    line_ch = re.compile(r"_L(\d+)_(%s)$" % "|".join(map(re.escape, channels)), re.I) if channels else None
    for name in sorted(names, key=_natural_key):
        stem = name[: -len(EXT)]
        m = line_ch.search(stem) if line_ch else None
        if m:
            stem = stem[: m.start()]
        parsed, reason = parse_name(_strip_channel(stem, known), words)
        if parsed is None:
            skipped.append((name, reason))
            continue
        word, drug, t, number = parsed
        if m:
            number = (int(m.group(1)) - 1) * len(channels) + lower.index(m.group(2).lower()) + 1
        groups.setdefault((word, drug, t), []).append((number, name))
    last_t = max((t for _, _, t in groups), default=None)

    # 이번에 함께 옮겨질 원본 파일은 자리를 비울 것이므로 "이미 있음"으로 보지 않는다.
    sources = {os.path.normcase(os.path.join(folder, n)) for items in groups.values() for _, n in items}
    planned = set()

    def taken(path):
        key = os.path.normcase(path)
        return key in planned or (os.path.exists(path) and key not in sources)

    moves, finals = [], []
    for (word, drug, t), items in sorted(groups.items()):
        # 기존 번호 순서대로, 번호 없는 파일은 그 뒤에 파일명 순서대로
        items.sort(key=lambda x: (x[0] is None, x[0] or 0, _natural_key(x[1])))
        label = "/".join(x for x in (word, drug or "(약물 없음)", t) if x)

        nums = [n for n, _ in items if n is not None]
        dups = sorted({n for n in nums if nums.count(n) > 1})
        if dups:
            warnings.append("%s: 기존 번호 중복 %s" % (label, ", ".join("%03d" % n for n in dups)))

        # 켜진 기준만 폴더로 만든다. 값이 없는 기준(예: 약물명 없음)은 건너뛴다.
        levels = [word if by_word else "", drug if by_drug else "", t if by_t else ""]
        dest_dir = os.path.join(folder, *[x for x in levels if x])
        base = "_".join(x for x in (header, drug, t) if x)

        dests = []
        # 그룹에 파일이 하나뿐이면 번호 없이 이름을 붙인다.
        if len(items) == 1:
            dest = os.path.join(dest_dir, base + tail + EXT)
            if not taken(dest):
                dests = [dest]
            else:
                warnings.append("%s: 대상 폴더에 %s 가 이미 있어 번호를 붙임" % (label, base + tail + EXT))

        if not dests:
            # 마지막 t의 번호 파일은 번호 대신 L라인_채널. 채널 수만큼이 한 라인 (촬영 순서 = 채널 순서)
            by_channel = bool(channels) and t == last_t and len(items) > 1
            if by_channel and len(items) % len(channels):
                warnings.append("%s: 파일 %d개가 채널 %d개(%s)의 배수가 아님" % (
                    label, len(items), len(channels), ", ".join(channels)))
            counter = 0
            for _ in items:
                while True:
                    counter += 1
                    line, ch = divmod(counter - 1, len(channels) or 1)
                    tag = ("L%d_%s" % (line + 1, channels[ch]) if by_channel
                           else "%03d%s" % (counter, tail))
                    dest = os.path.join(dest_dir, "%s_%s%s" % (base, tag, EXT))
                    if not taken(dest):
                        break
                planned.add(os.path.normcase(dest))
                dests.append(dest)
            if counter > len(items):
                warnings.append("%s: 대상 폴더에 같은 이름이 있어 번호를 건너뛰고 %03d번까지 붙임" % (label, counter))

        for (_, name), dest in zip(items, dests):
            planned.add(os.path.normcase(dest))
            src = os.path.join(folder, name)
            finals.append((src, dest, t))
            if src != dest:  # 이미 규칙에 맞는 이름이면 그대로 둔다
                moves.append((src, dest))
    return moves, skipped, warnings, finals


def _two_phase_move(pairs):
    """(src, dest) 목록을 임시 이름을 거쳐 옮긴다.

    같은 폴더 안에서 이름이 서로 맞물려도 (A->B, B->C) 덮어쓰지 않는다.
    (성공한 pair 목록, 실패 목록)을 돌려준다.
    """
    staged, errors = [], []
    for src, dest in pairs:
        tmp = src + ".FileNamer_tmp"
        try:
            if not os.path.exists(src):
                raise OSError("원본 파일이 없음")
            os.rename(src, tmp)
            staged.append((src, tmp, dest))
        except OSError as exc:
            errors.append((src, str(exc)))

    done = []
    for src, tmp, dest in staged:
        try:
            if os.path.exists(dest):
                raise OSError("대상 위치에 같은 이름이 있음")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(tmp, dest)
            done.append((src, dest))
        except OSError as exc:
            try:
                os.rename(tmp, src)
            except OSError:
                exc = OSError("%s / 임시 파일로 남음: %s" % (exc, os.path.basename(tmp)))
            errors.append((src, str(exc)))
    return done, errors


def execute_plan(folder, moves):
    """폴더를 만들고 파일을 이동한다. 성공한 이동은 CSV 로그로 남긴다.

    (로그 경로, 실패 목록)을 돌려준다.
    """
    log_path = os.path.join(folder, LOG_PREFIX + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
    done, errors = _two_phase_move(moves)
    with open(log_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["original", "new"])
        for src, dest in done:
            writer.writerow([os.path.relpath(src, folder), os.path.relpath(dest, folder)])
    return log_path, errors


def latest_log(folder):
    """되돌리지 않은 가장 최근 기록. 폴더와 그 origin 폴더(예전 버전이 옮겨 둔 기록)에서 찾는다."""
    logs = [p for d in (folder, os.path.join(folder, ORIGIN_DIR))
            for p in glob.glob(os.path.join(d, LOG_PREFIX + "*.csv")) if not p.endswith("_undone.csv")]
    return max(logs, key=os.path.basename) if logs else None  # 이름 속 시각 순


def undo_log(folder, log_path):
    """로그를 거꾸로 따라 파일을 원래 이름으로 되돌리고, 비게 된 폴더를 지운다.

    original이 빈 행은 예전 버전(OME-TIFF 변환, z-projection)이 만든 파일이라 지운다.
    (되돌린 개수, 지운 파일 개수, 실패 목록)을 돌려준다.
    """
    with open(log_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))[1:]
    pairs = [(os.path.join(folder, new), os.path.join(folder, original)) for original, new in rows if original]
    done, errors = _two_phase_move(pairs)
    restored = len(done)
    dirs = {os.path.dirname(src) for src, _ in done}
    errors = [(os.path.relpath(src, folder), err) for src, err in errors]

    removed = 0
    for original, new in rows:
        if original:
            continue
        path = os.path.join(folder, new)
        try:
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append((new, str(exc)))
        dirs.add(os.path.dirname(path))

    # 하위 폴더부터 비어 있으면 지운다 (선택한 폴더 자체는 건드리지 않음)
    root = os.path.normcase(os.path.abspath(folder))
    for d in sorted(dirs, key=len, reverse=True):
        while os.path.normcase(os.path.abspath(d)) != root:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)

    if not errors:
        os.replace(log_path, log_path[:-4] + "_undone.csv")
    return restored, removed, errors

