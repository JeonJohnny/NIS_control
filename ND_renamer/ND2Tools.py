# -*- coding: utf-8 -*-
"""ND2Tools: nd2 파일명을 규칙에 맞게 바꾸고 하위 폴더로 분류한다 (nd2tools/filenamer.py).

미리보기로 왼쪽 목록을 만들고, 체크한 파일만 이름을 바꾼다. 실행 기록으로 되돌릴 수 있다.
실행: run.bat
"""
import csv
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from nd2tools.filenamer import _clean, build_plan, execute_plan, latest_log, normalize_words, undo_log

APP_NAME = "ND2Tools"
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ND2Tools_settings.json")
DEFAULT_CHANNELS = ["BF", "FITC", "PI", "ANX"]  # 마지막 t의 촬영 순서 (001, 002, 003, 004)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("%s - nd2 파일명 정리" % APP_NAME)
        self.geometry("1150x720")
        self.minsize(800, 520)

        self.folder = tk.StringVar()
        self.header = tk.StringVar()
        self.words = tk.StringVar()
        self.by_word = tk.BooleanVar(value=True)
        self.by_drug = tk.BooleanVar(value=True)
        self.by_t = tk.BooleanVar(value=False)
        # 마지막 t에서 찍은 채널 (촬영 순서): [(사용 여부, 파일 이름 끝에 붙일 글자)]
        self.channels = [(tk.BooleanVar(value=True), tk.StringVar(value=name)) for name in DEFAULT_CHANNELS]
        self.channel_hint = tk.StringVar()
        self.check_count = tk.StringVar(value="")

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="x")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="폴더").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.folder).grid(row=0, column=1, sticky="ew", padx=6)
        side = ttk.Frame(frm)
        side.grid(row=0, column=2, sticky="w")
        ttk.Button(side, text="찾아보기", command=self.browse).pack(side="left")
        ttk.Button(side, text="추가", command=lambda: self.browse(append=True)).pack(side="left", padx=(4, 0))
        ttk.Label(frm, text="여러 폴더는 쉼표로 구분 (예: D:\\exp\\48, D:\\exp\\72). 폴더마다 같은 설정으로 실행합니다.",
                  foreground="gray").grid(row=1, column=1, columnspan=2, sticky="w", padx=6)

        ttk.Label(frm, text="헤더").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.header).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Label(frm, text="비워두면 헤더 없음").grid(row=2, column=2, sticky="w")

        ttk.Label(frm, text="추가 단어").grid(row=3, column=0, sticky="w", pady=3)
        self.words_entry = ttk.Entry(frm, textvariable=self.words)
        self.words_entry.grid(row=3, column=1, sticky="ew", padx=6)
        ttk.Label(frm, text="쉼표로 구분, 앞쪽이 우선").grid(row=3, column=2, sticky="w")

        ttk.Label(frm, text="하위 폴더 기준").grid(row=4, column=0, sticky="w", pady=3)
        opts = ttk.Frame(frm)
        opts.grid(row=4, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Checkbutton(opts, text="추가 단어", variable=self.by_word,
                        command=self._toggle_word).pack(side="left")
        ttk.Checkbutton(opts, text="약물", variable=self.by_drug).pack(side="left", padx=10)
        ttk.Checkbutton(opts, text="t값", variable=self.by_t).pack(side="left")
        ttk.Label(opts, text="(단어 > 약물 > t값 순서로 중첩, 모두 끄면 이름만 바꿈)").pack(side="left", padx=10)

        # 마지막 t의 번호 파일(001, 002 …)에 붙일 채널: 체크한 것만 왼쪽부터 촬영 순서로 쓴다.
        # 그 외 t(t1, t2 …)는 첫 칸(BF)을 체크했으면 그 이름을 끝에 붙인다.
        ttk.Label(frm, text="채널").grid(row=5, column=0, sticky="w", pady=3)
        chs = ttk.Frame(frm)
        chs.grid(row=5, column=1, columnspan=2, sticky="w", padx=6)
        for on, name in self.channels:
            ttk.Checkbutton(chs, variable=on, command=self._update_channel_hint).pack(side="left")
            ttk.Entry(chs, textvariable=name, width=7).pack(side="left", padx=(0, 10))
            name.trace_add("write", lambda *_: self._update_channel_hint())
        ttk.Label(chs, textvariable=self.channel_hint, foreground="gray").pack(side="left", padx=4)

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="미리보기", command=self.preview).pack(side="left")
        ttk.Button(btns, text="이름 변경 실행", command=self.run).pack(side="left", padx=6)
        ttk.Button(btns, text="마지막 실행 되돌리기", command=self.undo).pack(side="right")

        # 왼쪽: 미리보기 목록 (체크한 파일만 실행), 오른쪽: 로그
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(pane)
        tools = ttk.Frame(left)
        tools.pack(fill="x", pady=(0, 4))
        ttk.Button(tools, text="전체 선택", command=lambda: self._check_all(True)).pack(side="left")
        ttk.Button(tools, text="전체 해제", command=lambda: self._check_all(False)).pack(side="left", padx=4)
        ttk.Label(tools, textvariable=self.check_count, foreground="gray").pack(side="left", padx=6)
        body = ttk.Frame(left)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("new",), show="tree headings", selectmode="none")
        self.tree.heading("#0", text="원래 이름 (클릭해서 선택/해제)", anchor="w")
        self.tree.heading("new", text="새 이름", anchor="w")
        self.tree.column("#0", width=300)
        self.tree.column("new", width=300)
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self._items = {}   # 항목 iid -> (key, 라벨). 폴더 줄의 key는 None
        self._checks = {}  # key(원본 경로) -> 체크 여부. 미리보기를 새로 하면 비우고(모두 선택), 실행할 때는 유지한다.
        pane.add(left, weight=3)

        self.log = scrolledtext.ScrolledText(pane, font=("Consolas", 10), width=40)
        pane.add(self.log, weight=2)
        self.log.tag_config("err", foreground="#c0392b")
        self.log.tag_config("warn", foreground="#b9770e")
        self.log.tag_config("head", foreground="#1f5fbf")
        self._write("폴더를 고르고 미리보기를 누르세요.")

        self._load_settings()
        self._update_channel_hint()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ 설정
    def _settings_vars(self):
        result = {"folder": self.folder, "header": self.header, "words": self.words,
                  "by_word": self.by_word, "by_drug": self.by_drug, "by_t": self.by_t}
        for i, (on, name) in enumerate(self.channels, 1):
            result["channel%d_on" % i], result["channel%d_name" % i] = on, name
        return result

    def _load_settings(self):
        """지난번 설정을 불러온다. 파일이 없거나 깨져 있으면 기본값을 쓴다."""
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key, var in self._settings_vars().items():
            value = data.get(key)
            if isinstance(var, tk.BooleanVar) and isinstance(value, bool):
                var.set(value)
            elif isinstance(var, tk.StringVar) and isinstance(value, str):
                var.set(value)
        self._toggle_word()

    def _save_settings(self):
        data = {key: var.get() for key, var in self._settings_vars().items()}
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()

    def _toggle_word(self):
        self.words_entry.configure(state="normal" if self.by_word.get() else "disabled")

    # ------------------------------------------------------------ 채널
    def _channels(self):
        """마지막 t에 쓸 채널 이름들: 체크했고 이름이 비어 있지 않은 것만, 왼쪽부터."""
        names = [_clean(name.get()) for on, name in self.channels if on.get()]
        return [n for n in names if n]

    def _single_channel(self):
        """t1, t2처럼 한 채널만 찍은 파일에 붙일 이름: 첫 칸(BF)을 체크했을 때 그 이름."""
        on, name = self.channels[0]
        return _clean(name.get()) if on.get() else ""

    def _update_channel_hint(self):
        chs, single = self._channels(), self._single_channel()
        last = (", ".join("_L1_" + c for c in chs) + ", _L2_%s …" % chs[0]) if chs else "_001, _002 … (번호만)"
        self.channel_hint.set("→ 마지막 t: %s  /  그 외 t: %s" % (last, "_" + single if single else "안 붙임"))

    # ------------------------------------------------------------ 폴더
    def _folder_list(self):
        """폴더 칸의 쉼표 구분 입력을 목록으로. 따옴표·공백은 지우고 빈 항목은 버린다."""
        return [p.strip().strip('"').strip() for p in self.folder.get().split(",") if p.strip().strip('"').strip()]

    def browse(self, append=False):
        """찾아보기: 폴더 칸을 바꾼다. 추가(append): 쉼표로 이어 붙인다."""
        current = self._folder_list()
        path = filedialog.askdirectory(title="nd2 파일이 있는 폴더 선택",
                                       initialdir=current[-1] if current else None)
        if not path:
            return
        path = os.path.normpath(path)
        if append and current:
            if os.path.normcase(path) not in {os.path.normcase(os.path.normpath(p)) for p in current}:
                self.folder.set(", ".join(current + [path]))
        else:
            self.folder.set(path)

    def _folders(self):
        """폴더 칸의 폴더들을 확인한다. 절대 경로 목록(입력 순서, 중복 제거) 또는 None(오류)을 돌려준다."""
        folders, seen = [], set()
        for p in self._folder_list():
            path = os.path.abspath(p)
            if os.path.normcase(path) not in seen:
                seen.add(os.path.normcase(path))
                folders.append(path)
        if not folders:
            messagebox.showerror("오류", "폴더를 선택하세요.")
            return None
        bad = [p for p in folders if not os.path.isdir(p)]
        if bad:
            messagebox.showerror("오류", "폴더가 없습니다:\n" + "\n".join(bad))
            return None
        return folders

    # ------------------------------------------------------------ 로그 / 목록
    def _write(self, text="", tag=None):
        if tag is None:
            s = text.lstrip()
            tag = ("err" if s.startswith("[실패]") else
                   "warn" if s.startswith(("[주의]", "[건너뜀]")) else
                   "head" if s.startswith("===") else None)
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")

    def _refresh_marks(self):
        """체크 표시(☑/☐, 폴더는 일부 선택 ▣)와 선택 개수를 다시 그린다."""
        total = selected = 0
        for node in self.tree.get_children():
            children = self.tree.get_children(node)
            states = [self._checks[self._items[c][0]] for c in children]
            for c, on in zip(children, states):
                self.tree.item(c, text="%s %s" % ("☑" if on else "☐", self._items[c][1]))
            mark = "☑" if states and all(states) else "▣" if any(states) else "☐"
            self.tree.item(node, text="%s %s" % (mark, self._items[node][1]))
            total += len(states)
            selected += sum(states)
        self.check_count.set("선택 %d / %d" % (selected, total) if total else "")

    def _on_tree_click(self, event):
        """파일을 누르면 선택/해제. 폴더 줄을 누르면 그 폴더의 파일 전체를 바꾼다."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return None
        if self.tree.get_children(iid) and "indicator" in self.tree.identify_element(event.x, event.y):
            return None  # 폴더 줄의 펼치기 단추는 그대로 둔다
        keys = [self._items[c][0] for c in (self.tree.get_children(iid) or (iid,)) if self._items[c][0]]
        if keys:
            on = not all(self._checks[k] for k in keys)
            for k in keys:
                self._checks[k] = on
            self._refresh_marks()
        return "break"

    def _check_all(self, on):
        for key in self._checks:
            self._checks[key] = on
        self._refresh_marks()

    # ------------------------------------------------------------ 계획 / 실행
    def _make_plan(self):
        """폴더마다 이름 변경을 계획해 왼쪽 목록과 로그에 보여준다. [(폴더, 선택한 moves, 주의 수)] 또는 None(오류).

        목록에서 해제한 파일은 계획에서 빠진다 (그 파일은 이름과 위치가 그대로 남는다).
        """
        folders = self._folders()
        if folders is None:
            return None
        self.log.delete("1.0", "end")
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        plans = []
        for folder in folders:
            moves, skipped, warnings, _ = build_plan(folder, self.header.get(), normalize_words(self.words.get()),
                                                     self.by_word.get(), self.by_drug.get(), self.by_t.get(),
                                                     self._channels(), self._single_channel())
            node = self.tree.insert("", "end", text="", values=(folder,), open=True)
            self._items[node] = (None, os.path.basename(folder) or folder)
            for src, dest in moves:
                key = os.path.normcase(src)
                iid = self.tree.insert(node, "end", text="", values=(os.path.relpath(dest, folder),))
                self._items[iid] = (key, os.path.relpath(src, folder))
                self._checks.setdefault(key, True)
            moves = [(s, d) for s, d in moves if self._checks[os.path.normcase(s)]]

            self._write("=== %s" % folder)
            for name, reason in skipped:
                self._write("[건너뜀] %s  (%s)" % (name, reason))
            for w in warnings:
                self._write("[주의] " + w)
            self._write("→ (선택 기준) 이동 %d개, 건너뜀 %d개, 주의 %d개" % (len(moves), len(skipped), len(warnings)))
            self._write()
            plans.append((folder, moves, len(warnings)))
        self._refresh_marks()
        return plans

    def preview(self):
        self._checks.clear()  # 새 미리보기는 전체 선택으로 시작
        self._make_plan()

    def run(self):
        plans = self._make_plan()  # 목록의 선택 상태를 그대로 쓴다
        if plans is None:
            return
        n_moves = sum(len(moves) for _, moves, _ in plans)
        n_warn = sum(n for _, _, n in plans)
        if not n_moves:
            messagebox.showinfo("알림", "이름을 바꿀 파일이 없습니다. 왼쪽 목록에서 선택하세요.")
            return
        msg = "폴더 %d개에서 실행합니다.\n" % len(plans) if len(plans) > 1 else ""
        msg += "%d개 파일을 이동합니다.\n" % n_moves
        if n_warn:
            msg += "주의 항목이 %d개 있습니다. 로그를 확인하세요.\n" % n_warn
        if not messagebox.askyesno("확인", msg + "진행할까요?"):
            return
        self._save_settings()
        for folder, moves, _ in plans:
            if not moves:
                continue
            log_path, errors = execute_plan(folder, moves)
            self._write("이동 완료 (%s): %d개 이동, 실패 %d개" % (folder, len(moves) - len(errors), len(errors)))
            for src, err in errors:
                self._write("[실패] %s  (%s)" % (src, err))
            self._write("기록 파일: " + os.path.basename(log_path))

    def undo(self):
        """폴더마다 마지막 실행 기록을 되돌린다."""
        folders = self._folders()
        if folders is None:
            return
        logs = [(folder, latest_log(folder)) for folder in folders]
        logs = [(folder, log) for folder, log in logs if log]
        if not logs:
            messagebox.showinfo("알림", "선택한 폴더에 되돌릴 실행 기록이 없습니다.")
            return
        names = "\n".join(log for _, log in logs)
        # 예전 버전(OME-TIFF 변환, z-projection)의 기록이면 그때 만든 파일도 지워지므로 미리 알린다
        created = 0
        for _, log in logs:
            with open(log, newline="", encoding="utf-8-sig") as f:
                created += sum(1 for row in list(csv.reader(f))[1:] if row and not row[0])
        note = "\n이 기록으로 만들어진 파일 %d개(OME-TIFF 등)도 지워집니다." % created if created else ""
        if not messagebox.askyesno("확인", "다음 기록을 되돌릴까요?\n%s%s" % (names, note)):
            return
        self._write()
        for folder, log_path in logs:
            restored, removed, errors = undo_log(folder, log_path)
            extra = ", 만든 파일 %d개 삭제" % removed if removed else ""
            self._write("되돌리기 (%s): %d개 복원%s, 실패 %d개" % (folder, restored, extra, len(errors)))
            for name, err in errors:
                self._write("[실패] %s  (%s)" % (name, err))


def _enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


if __name__ == "__main__":
    _enable_dpi_awareness()
    App().mainloop()
