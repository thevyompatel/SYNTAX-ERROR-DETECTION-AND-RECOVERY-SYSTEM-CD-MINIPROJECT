"""Tkinter GUI for SEDRS - Syntax Error Detection and Recovery System."""

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from sedrs import analyze
from sedrs.parser import MODES
from sedrs.tokens import category, TYPE_KEYWORDS, KEYWORDS
from sedrs.diagnostics import STRATEGIES
from sedrs.ll1 import Grammar, GrammarError, DEFAULT_GRAMMAR, parse_ll1, tokens_for, fmt

APP_TITLE = "SEDRS - Syntax Error Detection and Recovery System"
TEAM = [("Vyom Patel", "202307020084"),
        ("Priti Sisodiya", "20230702088"),
        ("Krushil Rafaliya", "202307020090")]
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(HERE, "samples")

MONO = ("Consolas", 11)
UI = ("Segoe UI", 10)
UI_B = ("Segoe UI", 10, "bold")

COL = {
    "bg": "#f4f6fa", "panel": "#ffffff", "header": "#1f2a44", "header_fg": "#ffffff",
    "accent": "#2f6fed", "muted": "#6b7280", "gutter": "#eef1f6",
    "error": "#d92d20", "warning": "#b54708", "note": "#0b6bcb",
    "error_bg": "#fde3e1", "warning_bg": "#fff2cc", "note_bg": "#dbeafe", "fix_bg": "#d1fadf",
    "kw": "#1d4ed8", "type": "#7c3aed", "str": "#b45309", "num": "#0f766e", "com": "#15803d",
}
STRATEGY_COLORS = {
    "Phrase Level": "#2f6fed", "Error Production": "#7c3aed", "Panic Mode": "#d92d20",
    "Global (Delimiter)": "#0b6bcb", "Lexical Recovery": "#b54708", "No Recovery": "#6b7280",
}

TOKEN_RE = re.compile(
    r'(?P<com>//[^\n]*|/\*.*?(?:\*/|$(?![\s\S])))|(?P<str>"[^"\n]*"?|\'[^\'\n]*\'?)'
    r'|(?P<num>\b\d+(?:\.\d+)?\b)|(?P<word>\b[A-Za-z_]\w*\b)', re.S)


class LineNumbers(tk.Canvas):
    def __init__(self, master, text, **kw):
        super().__init__(master, width=48, highlightthickness=0, bg=COL["gutter"], **kw)
        self.text = text
        self.marks = {}            # line -> severity

    def redraw(self):
        self.delete("all")
        i = self.text.index("@0,0")
        while True:
            info = self.text.dlineinfo(i)
            if info is None:
                break
            y = info[1]
            line = int(i.split(".")[0])
            sev = self.marks.get(line)
            if sev:
                self.create_oval(5, y + 5, 13, y + 13, fill=COL[sev], outline="")
            self.create_text(42, y, anchor="ne", text=str(line), font=MONO,
                             fill=COL[sev] if sev else COL["muted"])
            i = self.text.index(f"{i}+1line")
            if self.text.compare(i, "==", self.text.index("end")):
                break


class Tooltip:
    def __init__(self, widget):
        self.widget = widget
        self.tip = None

    def show(self, x, y, text, color):
        self.hide()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x + 14}+{y + 18}")
        tk.Label(self.tip, text=text, justify="left", bg="#111827", fg="white", font=UI,
                 padx=8, pady=5, wraplength=520, highlightthickness=2,
                 highlightbackground=color).pack()

    def hide(self):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1400x860")
        self.minsize(1100, 650)
        self.configure(bg=COL["bg"])
        self.result = None
        self.current_file = None
        self.mode = tk.StringVar(value="full")
        self.live = tk.BooleanVar(value=True)
        self._after = None
        self._tip_diag = None
        self._style()
        self._header()
        self._toolbar()
        self._body()
        self._statusbar()
        self.bind("<F5>", lambda e: self.run_analysis())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-s>", lambda e: self.save_file())
        samples = self.sample_files()
        if samples:
            self.sample_box.set(samples[-1])
            self.load_sample()

    # ------------------------------------------------------------- layout
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=UI, background=COL["bg"])
        s.configure("TFrame", background=COL["bg"])
        s.configure("Panel.TFrame", background=COL["panel"])
        s.configure("TLabel", background=COL["bg"])
        s.configure("TRadiobutton", background=COL["bg"])
        s.configure("TCheckbutton", background=COL["bg"])
        s.configure("TNotebook", background=COL["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", padding=(12, 6), font=UI)
        s.map("TNotebook.Tab", background=[("selected", COL["panel"])],
              foreground=[("selected", COL["accent"])])
        s.configure("Treeview", rowheight=26, font=UI, background=COL["panel"],
                    fieldbackground=COL["panel"])
        s.configure("Treeview.Heading", font=UI_B, background="#e5e9f2")
        s.configure("Accent.TButton", font=UI_B, foreground="white", background=COL["accent"],
                    padding=(14, 6))
        s.map("Accent.TButton", background=[("active", "#1f57c9")])
        s.configure("TButton", padding=(10, 5))

    def _header(self):
        h = tk.Frame(self, bg=COL["header"], padx=16, pady=8)
        h.pack(fill="x")
        tk.Label(h, text="Syntax Error Detection & Recovery System", bg=COL["header"],
                 fg=COL["header_fg"], font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(h, text="Compiler Design Mini Project   |   Team: " +
                 ",   ".join(f"{n} ({r})" for n, r in TEAM),
                 bg=COL["header"], fg="#c7d2fe", font=UI).pack(anchor="w")

    def _toolbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        # right-hand buttons are packed first so they never get clipped
        ttk.Button(bar, text="About", command=self.about).pack(side="right")
        ttk.Button(bar, text="Apply Fixes", command=self.apply_fixes).pack(side="right", padx=4)
        ttk.Button(bar, text="Analyze (F5)", style="Accent.TButton",
                   command=self.run_analysis).pack(side="right", padx=4)
        ttk.Checkbutton(bar, text="Live", variable=self.live).pack(side="right", padx=8)
        ttk.Button(bar, text="Open", command=self.open_file).pack(side="left")
        ttk.Button(bar, text="Save", command=self.save_file).pack(side="left", padx=(4, 12))
        ttk.Label(bar, text="Sample:").pack(side="left")
        self.sample_box = ttk.Combobox(bar, values=self.sample_files(), width=26, state="readonly")
        self.sample_box.pack(side="left", padx=(4, 16))
        self.sample_box.bind("<<ComboboxSelected>>", lambda e: self.load_sample())
        ttk.Label(bar, text="Recovery:").pack(side="left")
        for key, label in (("full", "Full"), ("panic", "Panic only"), ("none", "None")):
            ttk.Radiobutton(bar, text=label, value=key, variable=self.mode,
                            command=self.run_analysis).pack(side="left", padx=4)

    def _body(self):
        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # ---- editor
        left = ttk.Frame(pw, style="Panel.TFrame")
        pw.add(left, weight=5)
        self.file_label = ttk.Label(left, text="Source program (MiniC)", font=UI_B,
                                    background=COL["panel"], padding=(8, 6))
        self.file_label.pack(fill="x")
        ed = ttk.Frame(left)
        ed.pack(fill="both", expand=True)
        self.editor = tk.Text(ed, wrap="none", font=MONO, undo=True, bd=0, padx=8, pady=4,
                              bg=COL["panel"], insertbackground="black",
                              selectbackground="#c7d7fe", tabs=("1c",))
        self.gutter = LineNumbers(ed, self.editor)
        ys = ttk.Scrollbar(ed, orient="vertical", command=self.editor.yview)
        xs = ttk.Scrollbar(left, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=lambda *a: (ys.set(*a), self.gutter.redraw()),
                              xscrollcommand=xs.set)
        self.gutter.pack(side="left", fill="y")
        ys.pack(side="right", fill="y")
        self.editor.pack(side="left", fill="both", expand=True)
        xs.pack(fill="x")
        for tag, color in (("kw", COL["kw"]), ("type", COL["type"]), ("str", COL["str"]),
                           ("num", COL["num"])):
            self.editor.tag_configure(tag, foreground=color)
        self.editor.tag_configure("kw", font=("Consolas", 11, "bold"))
        self.editor.tag_configure("com", foreground=COL["com"], font=("Consolas", 11, "italic"))
        for sev in ("error", "warning", "note"):
            self.editor.tag_configure(sev, background=COL[f"{sev}_bg"], underline=True)
            self.editor.tag_configure(f"{sev}_line", background=COL[f"{sev}_bg"])
        self.editor.tag_configure("focus", background="#fde68a")
        self.editor.tag_raise("sel")
        self.editor.bind("<<Modified>>", self._on_modified)
        self.editor.bind("<Motion>", self._on_hover)
        self.editor.bind("<Leave>", lambda e: self.tooltip.hide())
        self.editor.bind("<Configure>", lambda e: self.gutter.redraw())
        self.tooltip = Tooltip(self.editor)

        # ---- results
        right = ttk.Frame(pw)
        pw.add(right, weight=6)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)
        self._tab_diagnostics()
        self._tab_tokens()
        self._tab_tree()
        self._tab_corrected()
        self._tab_log()
        self._tab_stats()
        self._tab_ll1()

    def _tree(self, parent, cols, widths, height=10, show="headings"):
        frame = ttk.Frame(parent)
        tv = ttk.Treeview(frame, columns=cols, show=show, height=height)
        for c, w in zip(cols, widths):
            tv.heading(c, text=c, anchor="w")
            tv.column(c, width=w, anchor="w", stretch=(w > 150))
        ys = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        tv.pack(fill="both", expand=True)
        for sev in ("error", "warning", "note"):
            tv.tag_configure(sev, foreground=COL[sev])
        return frame, tv

    def _tab_diagnostics(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Diagnostics")
        self.summary = tk.Label(tab, text="", anchor="w", font=UI_B, bg=COL["bg"])
        self.summary.pack(fill="x", pady=(0, 6))
        frame, self.diag_tv = self._tree(
            tab, ("Severity", "Line:Col", "Phase", "Message", "Recovery strategy"),
            (80, 75, 85, 420, 150), height=14)
        frame.pack(fill="both", expand=True)
        self.diag_tv.bind("<<TreeviewSelect>>", self._on_diag_select)
        self.detail = tk.Text(tab, height=7, font=UI, wrap="word", bd=0, padx=10, pady=8,
                              bg=COL["panel"], state="disabled")
        self.detail.pack(fill="x", pady=(6, 0))
        self.detail.tag_configure("h", font=UI_B)

    def _tab_tokens(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Tokens")
        frame, self.tok_tv = self._tree(tab, ("#", "Line:Col", "Category", "Token", "Lexeme"),
                                        (50, 80, 130, 100, 300), height=20)
        frame.pack(fill="both", expand=True)

    def _tab_tree(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Parse Tree")
        frame, self.parse_tv = self._tree(tab, ("node",), (600,), height=20, show="tree")
        self.parse_tv.column("#0", width=650, stretch=True)
        self.parse_tv.tag_configure("err", foreground=COL["error"], font=UI_B)
        frame.pack(fill="both", expand=True)

    def _tab_corrected(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Corrected Code")
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Source after applying every recovery action (green = changed).",
                  foreground=COL["muted"]).pack(side="left")
        ttk.Button(top, text="Load into editor", command=self.apply_fixes).pack(side="right")
        self.fixed = tk.Text(tab, font=MONO, wrap="none", bd=0, padx=8, pady=6, bg=COL["panel"])
        self.fixed.pack(fill="both", expand=True)
        self.fixed.tag_configure("fix", background=COL["fix_bg"], foreground="#05603a")
        self.fixed.tag_configure("del", background=COL["error_bg"])

    def _tab_log(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Recovery Log")
        ttk.Label(tab, text="Step-by-step actions taken by the parser when it met an error.",
                  foreground=COL["muted"]).pack(anchor="w", pady=(0, 6))
        self.log = tk.Text(tab, font=("Consolas", 10), wrap="none", bd=0, padx=8, pady=6,
                           bg=COL["panel"])
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("detect", foreground=COL["error"])
        self.log.tag_configure("action", foreground=COL["accent"])
        self.log.tag_configure("halt", foreground=COL["error"], font=("Consolas", 10, "bold"))

    def _tab_stats(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Statistics")
        ttk.Label(tab, text="Errors handled by each recovery strategy", font=UI_B).pack(anchor="w")
        self.chart = tk.Canvas(tab, height=210, bg=COL["panel"], highlightthickness=0)
        self.chart.pack(fill="x", pady=(4, 12))
        ttk.Label(tab, text="Comparison of recovery modes on the current program",
                  font=UI_B).pack(anchor="w")
        frame, self.cmp_tv = self._tree(
            tab, ("Mode", "Errors reported", "Warnings", "Lines analysed", "Repairs", "Outcome"),
            (330, 120, 90, 120, 80, 260), height=4)
        frame.pack(fill="x", pady=(4, 8))
        self.explain = tk.Label(tab, justify="left", anchor="w", bg=COL["bg"], font=UI,
                                wraplength=760, fg=COL["muted"],
                                text="A compiler without recovery stops at the first error, so the "
                                     "programmer must fix-and-recompile once per error. Panic mode "
                                     "keeps going but discards whole statements and can produce "
                                     "spurious (cascading) errors. Phrase-level repair and error "
                                     "productions fix the error locally, giving precise messages "
                                     "and a corrected program.")
        self.explain.pack(fill="x")

    def _tab_ll1(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="LL(1) Parser")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        side = ttk.Frame(top, padding=(10, 18, 0, 0))
        side.pack(side="right", fill="y")
        gl = ttk.Frame(top)
        gl.pack(side="left", fill="both", expand=True)
        ttk.Label(gl, text="Grammar  (use ε for epsilon, | for alternatives)", font=UI_B).pack(anchor="w")
        self.gram = tk.Text(gl, height=7, font=MONO, bd=0, padx=6, pady=4, bg=COL["panel"])
        self.gram.insert("1.0", DEFAULT_GRAMMAR)
        self.gram.pack(fill="both", expand=True, pady=(2, 0))
        ttk.Button(side, text="Build LL(1) table", command=self.build_ll1).pack(fill="x")
        ttk.Label(side, text="Input string:").pack(anchor="w", pady=(12, 0))
        self.ll1_input = ttk.Entry(side, width=28, font=MONO)
        self.ll1_input.insert(0, "a + * b ) * 3")
        self.ll1_input.pack(fill="x")
        self.ll1_input.bind("<Return>", lambda e: self.run_ll1())
        ttk.Button(side, text="Parse with panic mode", style="Accent.TButton",
                   command=self.run_ll1).pack(fill="x", pady=(6, 0))
        self.ll1_status = tk.Label(tab, text="", anchor="w", font=UI_B, bg=COL["bg"])
        self.ll1_status.pack(fill="x", pady=6)
        self.ll1_nb = ttk.Notebook(tab)
        self.ll1_nb.pack(fill="both", expand=True)
        f1 = ttk.Frame(self.ll1_nb)
        self.ll1_nb.add(f1, text="FIRST & FOLLOW")
        frame, self.ff_tv = self._tree(f1, ("Non-terminal", "FIRST", "FOLLOW"), (110, 260, 260), 6)
        frame.pack(fill="both", expand=True)
        self.table_host = ttk.Frame(self.ll1_nb)
        self.ll1_nb.add(self.table_host, text="Parsing table M[A, a]")
        f3 = ttk.Frame(self.ll1_nb)
        self.ll1_nb.add(f3, text="Parsing trace")
        frame, self.trace_tv = self._tree(f3, ("Step", "Stack", "Input", "Action"),
                                          (50, 170, 170, 520), 10)
        frame.pack(fill="both", expand=True)
        self.grammar = None
        self.build_ll1()

    def _statusbar(self):
        self.status = tk.Label(self, text="Ready", anchor="w", bg="#e5e9f2", font=UI, padx=10)
        self.status.pack(fill="x", side="bottom")

    # ------------------------------------------------------------- files
    def sample_files(self):
        if not os.path.isdir(SAMPLES_DIR):
            return []
        return sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".mc"))

    def set_source(self, text):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.edit_reset()
        self.run_analysis()

    def load_sample(self):
        name = self.sample_box.get()
        path = os.path.join(SAMPLES_DIR, name)
        with open(path, encoding="utf-8") as f:
            self.set_source(f.read())
        self.current_file = path
        self.file_label.configure(text=f"Source program  -  {name}")

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("MiniC source", "*.mc"), ("All files", "*.*")],
                                          initialdir=SAMPLES_DIR)
        if path:
            with open(path, encoding="utf-8") as f:
                self.set_source(f.read())
            self.current_file = path
            self.file_label.configure(text=f"Source program  -  {os.path.basename(path)}")

    def save_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".mc",
                                            filetypes=[("MiniC source", "*.mc")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.source())
            self.status.configure(text=f"Saved {path}")

    def source(self):
        return self.editor.get("1.0", "end-1c")

    # ---------------------------------------------------------- analysis
    def _on_modified(self, _):
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        self.highlight_syntax()
        self.gutter.redraw()
        if self.result and self.result.source == self.source():
            return                                   # already analysed (e.g. just loaded)
        if self.live.get():
            if self._after:
                self.after_cancel(self._after)
            self._after = self.after(600, self.run_analysis)

    def highlight_syntax(self):
        ed = self.editor
        for t in ("kw", "type", "str", "num", "com"):
            ed.tag_remove(t, "1.0", "end")
        text = self.source()
        for m in TOKEN_RE.finditer(text):
            kind = m.lastgroup
            if kind == "word":
                w = m.group("word")
                if w in TYPE_KEYWORDS:
                    kind = "type"
                elif w in KEYWORDS:
                    kind = "kw"
                else:
                    continue
            ed.tag_add(kind, f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def run_analysis(self):
        self._after = None
        res = analyze(self.source(), self.mode.get())
        self.result = res
        self.show_diagnostics(res)
        self.show_tokens(res)
        self.show_tree(res)
        self.show_corrected(res)
        self.show_log(res)
        self.show_stats(res)
        self.highlight_syntax()
        s = res.stats
        self.status.configure(
            text=f"{MODES[res.mode]}   |   {s['lines']} lines, {s['tokens']} tokens   |   "
                 f"{s['errors']} errors, {s['warnings']} warnings, {s['notes']} notes   |   "
                 f"{s['repairs']} repairs   |   analysed in {res.elapsed_ms:.2f} ms")

    def show_diagnostics(self, res):
        ed, tv = self.editor, self.diag_tv
        for tag in ("error", "warning", "note", "error_line", "warning_line", "note_line", "focus"):
            ed.tag_remove(tag, "1.0", "end")
        tv.delete(*tv.get_children())
        self.gutter.marks = {}
        rank = {"error": 3, "warning": 2, "note": 1}
        for i, d in enumerate(res.diagnostics):
            tv.insert("", "end", iid=str(i), tags=(d.severity,),
                      values=(d.severity.upper(), f"{d.line}:{d.col}", d.phase, d.message, d.strategy))
            start = f"1.0+{d.pos}c"
            ed.tag_add(d.severity, start, f"{start}+{d.length}c")
            if rank[d.severity] > rank.get(self.gutter.marks.get(d.line), 0):
                self.gutter.marks[d.line] = d.severity
        for line, sev in self.gutter.marks.items():
            ed.tag_add(f"{sev}_line", f"{line}.0", f"{line}.0 lineend+1c")
        for sev in ("note", "warning", "error"):
            ed.tag_raise(f"{sev}_line")
        for sev in ("note", "warning", "error"):
            ed.tag_raise(sev)
        ed.tag_raise("sel")
        self.gutter.redraw()

        s = res.stats
        if res.halted:
            txt, color = (f"Compilation HALTED at the first error - the rest of the program was "
                          f"not checked ({s['errors']} error reported)"), COL["error"]
        elif s["errors"]:
            txt, color = (f"{s['errors']} error(s), {s['warnings']} warning(s) detected - parser "
                          f"recovered from all of them and analysed the whole program"), COL["error"]
        elif s["warnings"]:
            txt, color = f"No errors, {s['warnings']} warning(s)", COL["warning"]
        else:
            txt, color = "No syntax errors - program is syntactically correct", "#067647"
        self.summary.configure(text=txt, fg=color)
        self._set_detail(None)

    def _set_detail(self, d):
        t = self.detail
        t.configure(state="normal")
        t.delete("1.0", "end")
        if d is None:
            t.insert("end", "Select a diagnostic to see details, or hover over a highlighted "
                            "part of the source.")
        else:
            t.insert("end", f"{d.severity.upper()} at line {d.line}, column {d.col}  "
                            f"[{d.phase} phase]\n", "h")
            t.insert("end", f"{d.message}\n")
            t.insert("end", "Recovery strategy: ", "h")
            t.insert("end", f"{d.strategy}\n")
            t.insert("end", "Action taken: ", "h")
            t.insert("end", f"{d.action}\n")
            if d.suggestion:
                t.insert("end", "Suggestion: ", "h")
                t.insert("end", d.suggestion)
        t.configure(state="disabled")

    def _on_diag_select(self, _):
        sel = self.diag_tv.selection()
        if not sel or not self.result:
            return
        d = self.result.diagnostics[int(sel[0])]
        self._set_detail(d)
        start = f"1.0+{d.pos}c"
        self.editor.tag_remove("focus", "1.0", "end")
        self.editor.tag_add("focus", start, f"{start}+{d.length}c")
        self.editor.tag_raise("focus")
        self.editor.see(start)
        self.editor.mark_set("insert", start)

    def _on_hover(self, e):
        if not self.result:
            return
        idx = self.editor.index(f"@{e.x},{e.y}")
        off = self.editor.count("1.0", idx, "chars")
        off = off[0] if off else 0
        hit = [d for d in self.result.diagnostics if d.pos <= off < d.pos + d.length]
        if not hit:
            self._tip_diag = None
            self.tooltip.hide()
            return
        d = hit[0]
        if d is self._tip_diag:
            return
        self._tip_diag = d
        text = "\n".join(f"{x.severity.upper()}: {x.message}\n  -> {x.strategy}: {x.action}"
                         for x in hit)
        self.tooltip.show(e.x_root, e.y_root, text, COL[d.severity])

    def show_tokens(self, res):
        tv = self.tok_tv
        tv.delete(*tv.get_children())
        for i, t in enumerate(res.tokens, 1):
            tv.insert("", "end", values=(i, f"{t.line}:{t.col}", category(t), t.kind, t.lexeme))

    def show_tree(self, res):
        tv = self.parse_tv
        tv.delete(*tv.get_children())

        def add(parent, node):
            iid = tv.insert(parent, "end", text=node.label, open=True,
                            tags=("err",) if node.error else ())
            for c in node.children:
                add(iid, c)
        add("", res.tree)

    def show_corrected(self, res):
        t = self.fixed
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", res.corrected)
        for a, b in res.corrected_marks:
            if a == b:
                t.tag_add("del", f"1.0+{a}c")
            else:
                t.tag_add("fix", f"1.0+{a}c", f"1.0+{b}c")
        t.configure(state="disabled")

    def show_log(self, res):
        t = self.log
        t.delete("1.0", "end")
        if not res.log:
            t.insert("end", "No parser recovery events.\n")
        for line in res.log:
            tag = "detect" if "DETECT" in line else ("halt" if "HALT" in line else "action")
            t.insert("end", line + "\n", tag)
        lex = [d for d in res.diagnostics if d.phase == "Lexical"]
        if lex:
            t.insert("end", "\nLexical phase:\n")
            for d in lex:
                t.insert("end", f"L{d.line}:{d.col}  DETECT  {d.message}\n", "detect")
                t.insert("end", f"          {d.strategy.upper():<16} {d.action}\n", "action")
        if res.suppressed:
            t.insert("end", f"\n{res.suppressed} cascading error(s) suppressed.\n")

    def show_stats(self, res):
        c = self.chart
        c.delete("all")
        c.update_idletasks()
        width = max(c.winfo_width(), 500)
        counts = res.stats["by_strategy"]
        names = STRATEGIES + (["No Recovery"] if "No Recovery" in counts else [])
        top = max(counts.values(), default=0) or 1
        y = 14
        for n in names:
            v = counts.get(n, 0)
            c.create_text(12, y + 10, text=n, anchor="w", font=UI)
            bar_w = (width - 230) * v / top
            c.create_rectangle(170, y + 2, 170 + bar_w, y + 20, fill=STRATEGY_COLORS[n], outline="")
            c.create_text(178 + bar_w, y + 11, text=str(v), anchor="w", font=UI_B)
            y += 32

        tv = self.cmp_tv
        tv.delete(*tv.get_children())
        total = res.stats["lines"]
        for mode, label in MODES.items():
            r = res if mode == res.mode else analyze(res.source, mode)
            last = r.diagnostics[-1].line if r.halted and r.diagnostics else total
            outcome = ("stopped at first error" if r.halted else
                       "whole program checked" if mode != "full" else
                       "whole program checked + corrected")
            tv.insert("", "end", values=(label, r.stats["errors"], r.stats["warnings"],
                                         f"{last} / {total}", r.stats["repairs"], outcome))

    def apply_fixes(self):
        if not self.result:
            return
        if self.result.corrected == self.source():
            messagebox.showinfo(APP_TITLE, "There is nothing to fix.")
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.result.corrected)
        self.mode.set("full")
        self.run_analysis()
        self.nb.select(0)

    # ------------------------------------------------------------- LL(1)
    def build_ll1(self):
        try:
            g = Grammar(self.gram.get("1.0", "end-1c"))
        except GrammarError as e:
            self.ll1_status.configure(text=f"Grammar error: {e}", fg=COL["error"])
            return
        self.grammar = g
        tv = self.ff_tv
        tv.delete(*tv.get_children())
        for nt in g.nonterminals:
            tv.insert("", "end", values=(nt, "{ " + ", ".join(sorted(g.first[nt])) + " }",
                                         "{ " + ", ".join(sorted(g.follow[nt])) + " }"))
        for w in self.table_host.winfo_children():
            w.destroy()
        cols = ["NT"] + g.columns
        frame, ttv = self._tree(self.table_host, cols, [50] + [88] * len(g.columns), 6)
        ttv.tag_configure("synch", foreground=COL["muted"])
        frame.pack(fill="both", expand=True)
        for nt in g.nonterminals:
            row = [nt]
            for t in g.columns:
                e = g.table[nt].get(t)
                row.append("" if e is None else ("synch" if e == "synch" else fmt(nt, e)))
            ttv.insert("", "end", values=row)
        if g.is_ll1:
            self.ll1_status.configure(text="Grammar is LL(1) - table built. Empty cells = error "
                                           "(skip input); 'synch' = pop non-terminal.", fg="#067647")
        else:
            self.ll1_status.configure(text="NOT LL(1) - conflicts: " + "; ".join(g.conflicts),
                                      fg=COL["error"])
        self.trace_tv.delete(*self.trace_tv.get_children())

    def run_ll1(self):
        if not self.grammar:
            return
        rows, errors = parse_ll1(self.grammar, tokens_for(self.grammar, self.ll1_input.get()))
        tv = self.trace_tv
        tv.delete(*tv.get_children())
        for i, r in enumerate(rows, 1):
            tv.insert("", "end", values=(i, r["stack"], r["input"], r["action"]),
                      tags=("error",) if r["error"] else ())
        self.ll1_nb.select(2)
        if errors:
            self.ll1_status.configure(text=f"{len(errors)} error(s) detected and recovered by "
                                           f"panic mode: " + "; ".join(errors), fg=COL["error"])
        else:
            self.ll1_status.configure(text="Input accepted - no errors.", fg="#067647")

    def about(self):
        messagebox.showinfo(
            "About SEDRS",
            "Syntax Error Detection and Recovery System\nCompiler Design Mini Project\n\n"
            + "\n".join(f"{n}  -  {r}" for n, r in TEAM)
            + "\n\nStrategies: Panic mode, Phrase-level, Error productions,\n"
              "Global delimiter analysis, Lexical recovery, LL(1) synch sets.")


def run_gui():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App().mainloop()


if __name__ == "__main__":
    run_gui()
