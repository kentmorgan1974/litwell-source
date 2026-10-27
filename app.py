#!/usr/bin/env python3
# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Litwell — tkinter desktop GUI.

Cross-platform (Windows / macOS). Run with:  python app.py
"""

from __future__ import annotations

import datetime as _dt
import os
import queue
import re as _re
import sys
import threading
from pathlib import Path
from tkinter import (
    BooleanVar,
    StringVar,
    Tk,
    filedialog,
    messagebox,
)
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from litsearch import CREDIT, LICENSE_LINE, __version__, profiles
from litsearch.config import CONFIG_PATH, load_config, save_config, selected_sources
from litsearch.models import MATCH_MODES, SearchParams
from litsearch.output import FORMATS, count_entries
from litsearch.search import SOURCES, key_problem, run_multi_search

APP_NAME = "Litwell"
APP_TITLE = f"{APP_NAME}  v{__version__}"
# Windows taskbar grouping / icon identity (must be set before the window exists).
APP_USER_MODEL_ID = "JKM.Litwell"


def resource_path(relative: str) -> str:
    """Absolute path to a bundled resource, from source or a PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


_stdin_pipe = None  # keeps the pipe below open for the life of the process


def _avoid_tk_console() -> None:
    """macOS: stop Tk opening its hidden debug console when launched from Finder.

    Tk opens that console whenever stdin looks like /dev/null (always true for a
    Finder/Dock launch). Building the console's menu intermittently aborts the
    whole app on recent macOS ("Litwell quit unexpectedly"). Giving the process a
    pipe for stdin makes Tk skip the console. A terminal launch is left alone.
    """
    global _stdin_pipe
    if sys.platform != "darwin":
        return
    try:
        if os.isatty(0):
            return
        r, w = os.pipe()
        os.dup2(r, 0)
        _stdin_pipe = (r, w)
    except OSError:
        pass


def _set_windows_app_id() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # cosmetic only; never stop the app starting
        pass


def _set_window_icon(root: Tk) -> None:
    """Litwell icon for the title bar / Dock / taskbar (best effort)."""
    try:
        from tkinter import PhotoImage

        root._icon_images = [  # keep references or Tk drops them
            PhotoImage(file=resource_path(os.path.join("litwell_icons", n)))
            for n in ("litwell_256.png", "litwell_32.png")
        ]
        root.iconphoto(True, *root._icon_images)
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            root.iconbitmap(resource_path(os.path.join("litwell_icons", "litwell.ico")))
        except Exception:
            pass


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.cfg = load_config()
        if profiles.seed_examples(self.cfg):         # two deletable example profiles, once
            try:
                save_config(self.cfg)
            except RuntimeError:
                pass
        self.msg_queue: "queue.Queue[tuple]" = queue.Queue()
        self.searching = False

        root.title(APP_TITLE)
        _set_window_icon(root)
        root.minsize(800, 760)
        root.geometry("860x860")
        self._build_menu()
        self._build_form()
        self._build_status()
        self._refresh_excel_label()
        self.root.after(120, self._drain_queue)
        self.root.after(250, self._startup_session_check)

        # macOS's *built-in* Python ships Tcl/Tk 8.5.9 (2010), which often opens
        # windows with an unpainted grey content area. Modern Tk (8.6+, e.g. the
        # python.org build) has no such problem, so only apply the workaround on
        # the old toolkit and otherwise leave the window alone.
        try:
            tk_patch = self.root.tk.call("info", "patchlevel")
            tk_major_minor = tuple(int(x) for x in tk_patch.split(".")[:2])
        except Exception:
            tk_major_minor = (8, 6)
        if tk_major_minor < (8, 6):
            self.root.after(50, self._kick_redraw)
            self.root.after(400, lambda: self._jiggle(4))
        else:
            self.root.after(30, self.root.lift)

    def _kick_redraw(self) -> None:
        try:
            self.root.update_idletasks()
            self.root.iconify()
            self.root.update_idletasks()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _jiggle(self, tries: int) -> None:
        try:
            w, h = self.root.winfo_width(), self.root.winfo_height()
            self.root.geometry(f"{w + 1}x{h + 1}")
            self.root.update_idletasks()
            self.root.geometry(f"{w}x{h}")
            self.root.update_idletasks()
        except Exception:
            pass
        if tries > 0:
            self.root.after(250, lambda: self._jiggle(tries - 1))

    # ---------- UI construction ----------------------------------------
    def _build_menu(self) -> None:
        from tkinter import Menu

        m = Menu(self.root)
        if sys.platform == "darwin":
            # Define the application ("Apple") menu ourselves, and first. If it is
            # missing, Tk 8.6.15 copies an un-retained default menu object and the
            # app intermittently aborts at launch ("Litwell quit unexpectedly").
            apple = Menu(m, name="apple", tearoff=0)
            apple.add_command(label=f"About {APP_NAME}", command=self._about)
            m.add_cascade(menu=apple)
        filemenu = Menu(m, tearoff=0)
        filemenu.add_command(label="Set Output File…", command=self.choose_excel)
        filemenu.add_command(label="New Output File…", command=self.new_output_file)
        filemenu.add_command(label="Open Output File", command=self.open_excel)
        filemenu.add_separator()
        filemenu.add_command(label="API Keys & Contact…", command=self.edit_settings)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.root.destroy)
        m.add_cascade(label="File", menu=filemenu)

        toolsmenu = Menu(m, tearoff=0)
        toolsmenu.add_command(
            label="Check for Duplicates (.xlsx)…",
            command=self.check_duplicates,
        )
        m.add_cascade(label="Tools", menu=toolsmenu)

        if sys.platform != "darwin":  # on macOS, About lives in the app menu
            helpmenu = Menu(m, tearoff=0)
            helpmenu.add_command(label="How-to Guide (PDF)", command=self.open_guide)
            helpmenu.add_command(label="About", command=self._about)
            m.add_cascade(label="Help", menu=helpmenu)
        self.root.config(menu=m)

    def _build_form(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="x")

        self.vars = {
            "keyword": StringVar(),
            "author": StringVar(),
            "title": StringVar(),
            "journal": StringVar(),
            "date_start": StringVar(),
            "date_end": StringVar(),
        }

        rows = [
            ("Topic / keyword", "keyword"),
            ("Author", "author"),
            ("Title contains", "title"),
            ("Journal", "journal"),
        ]
        for i, (label, key) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=self.vars[key], width=56).grid(
                row=i, column=1, columnspan=3, sticky="we", pady=3
            )

        r = len(rows)
        ttk.Label(frm, text="Date range").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.vars["date_start"], width=16).grid(
            row=r, column=1, sticky="w", pady=3
        )
        ttk.Label(frm, text="to").grid(row=r, column=2, sticky="w")
        ttk.Entry(frm, textvariable=self.vars["date_end"], width=16).grid(
            row=r, column=3, sticky="w", pady=3
        )
        ttk.Label(
            frm, text="Formats: YYYY, YYYY-MM, or YYYY-MM-DD (both optional)",
            foreground="#666",
        ).grid(row=r + 1, column=1, columnspan=3, sticky="w")

        # precision: match mode, must-contain, exclude, profiles
        prec = ttk.LabelFrame(frm, text="Precision (optional)")
        prec.grid(row=r + 2, column=0, columnspan=4, sticky="we", pady=(10, 0))
        self.match_mode = StringVar(value=self.cfg.get("match_mode", "exact"))
        mrow = ttk.Frame(prec)
        mrow.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))
        ttk.Label(mrow, text="Match topic as").pack(side="left")
        for key, label in MATCH_MODES.items():
            ttk.Radiobutton(mrow, text=label, value=key, variable=self.match_mode).pack(
                side="left", padx=(10, 0))
        self.vars["must_terms"] = StringVar(value=self.cfg.get("must_terms", ""))
        self.vars["exclude_terms"] = StringVar(value=self.cfg.get("exclude_terms", ""))
        self.vars["description"] = StringVar()
        self.profile_boost = ""
        for i, (label, key) in enumerate((
            ("Must also contain (any of)", "must_terms"),
            ("Exclude terms", "exclude_terms"),
            ("What counts as relevant (for AI)", "description"),
        ), start=1):
            ttk.Label(prec, text=label).grid(row=i, column=0, sticky="w", padx=(8, 6), pady=2)
            ttk.Entry(prec, textvariable=self.vars[key], width=52).grid(
                row=i, column=1, columnspan=2, sticky="we", pady=2, padx=(0, 8))
        ttk.Label(prec, text="Separate terms with commas. Must-contain looks in the title and abstract; "
                  "an exclude term in the title or journal removes the record.",
                  foreground="#666").grid(row=4, column=0, columnspan=3, sticky="w", padx=8)
        prow = ttk.Frame(prec)
        prow.grid(row=5, column=0, columnspan=3, sticky="we", padx=8, pady=(4, 6))
        ttk.Label(prow, text="Profile").pack(side="left")
        self.profile_name = StringVar(value=self.cfg.get("last_profile", ""))
        self.profile_box = ttk.Combobox(prow, textvariable=self.profile_name, width=34,
                                        values=profiles.names(self.cfg))
        self.profile_box.pack(side="left", padx=6)
        self.profile_box.bind("<<ComboboxSelected>>", lambda _e: self.load_profile())
        ttk.Button(prow, text="Save", width=6, command=self.save_profile).pack(side="left")
        ttk.Button(prow, text="Delete", width=7, command=self.delete_profile).pack(side="left", padx=4)
        prec.columnconfigure(1, weight=1)

        # sources: tick any number; each is searched with the same fields
        src = ttk.LabelFrame(frm, text="Search in (tick any number of sources)")
        src.grid(row=r + 3, column=0, columnspan=4, sticky="we", pady=(12, 0))
        self._source_labels = {          # label shown -> source key
            "PubMed — biomedical (NCBI)": "pubmed",
            "Crossref — all fields, journals": "crossref",
            "OpenAlex — all fields, widest coverage": "openalex",
            "Europe PMC — biomedical + preprints": "europepmc",
            "arXiv — preprints (physics, math, CS…)": "arxiv",
            "Preprint servers — bioRxiv, SSRN, OSF…": "preprints",
            "USPTO — US patents (needs free key)": "patents",
            "EPO — worldwide patents (needs free key)": "epo",
        }
        ticked = set(selected_sources(self.cfg, SOURCES))
        self.source_vars = {}
        per_col = (len(self._source_labels) + 1) // 2
        for i, (label, key) in enumerate(self._source_labels.items()):
            var = BooleanVar(value=key in ticked)
            self.source_vars[key] = var
            ttk.Checkbutton(src, text=label, variable=var).grid(
                row=i % per_col, column=i // per_col, sticky="w", padx=(8, 16), pady=1
            )
        picks = ttk.Frame(src)
        picks.grid(row=per_col, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 4))
        ttk.Button(picks, text="All", width=7,
                   command=lambda: self._tick_sources(list(SOURCES))).pack(side="left")
        ttk.Button(picks, text="Papers only", width=11,
                   command=lambda: self._tick_sources(
                       [k for k in SOURCES if k not in ("patents", "epo")])).pack(side="left", padx=4)
        ttk.Button(picks, text="None", width=7,
                   command=lambda: self._tick_sources([])).pack(side="left")

        opt = ttk.Frame(frm)
        opt.grid(row=r + 4, column=0, columnspan=4, sticky="we", pady=(8, 0))
        ttk.Label(opt, text="Max results (per source):").pack(side="left")
        self.max_results = StringVar(value=str(self.cfg.get("max_results", 100)))
        ttk.Spinbox(
            opt, from_=1, to=500, width=6, textvariable=self.max_results
        ).pack(side="left", padx=4)
        ttk.Label(opt, text="   Hide scores below:").pack(side="left")
        self.min_score = StringVar(value=str(self.cfg.get("min_score", 0)))
        ttk.Spinbox(opt, from_=0, to=100, width=5, textvariable=self.min_score).pack(side="left", padx=4)
        self.ai_on = BooleanVar(value=bool(self.cfg.get("ai_enabled")))
        ttk.Checkbutton(opt, text="AI triage (local Ollama, optional)", variable=self.ai_on).pack(
            side="left", padx=(16, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=r + 5, column=0, columnspan=4, sticky="we", pady=(12, 0))
        self.search_btn = ttk.Button(btns, text="Search", command=self.on_search)
        self.search_btn.pack(side="left")
        ttk.Button(btns, text="Clear fields", command=self.clear_fields).pack(
            side="left", padx=6
        )
        ttk.Button(btns, text="Help / How-to Guide", command=self.open_guide).pack(side="left", padx=6)
        self.progress = ttk.Progressbar(btns, mode="indeterminate", length=180)
        self.progress.pack(side="right")

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(3, weight=1)

    def _build_status(self) -> None:
        wrap = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Status").pack(anchor="w")
        self.status = ScrolledText(wrap, height=9, wrap="word", state="disabled")
        self.status.pack(fill="both", expand=True)

        bottom = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        bottom.pack(fill="x")
        self.excel_label = ttk.Label(bottom, text="", foreground="#444")
        self.excel_label.pack(side="left")
        ttk.Button(bottom, text="Change…", command=self.choose_excel).pack(
            side="right"
        )
        import sys as _sys

        reveal_label = "Show in Finder" if _sys.platform == "darwin" else "Open Folder"
        self.reveal_btn = ttk.Button(
            bottom, text=reveal_label, command=self.reveal_excel
        )
        self.reveal_btn.pack(side="right", padx=6)
        self.open_btn = ttk.Button(
            bottom, text="Open File", command=self.open_excel
        )
        self.open_btn.pack(side="right", padx=(0, 6))
        self.newfile_btn = ttk.Button(
            bottom, text="New File…", command=self.new_output_file
        )
        self.newfile_btn.pack(side="right", padx=(0, 6))

    # ---------- helpers ------------------------------------------------
    def log(self, text: str) -> None:
        self.status.configure(state="normal")
        self.status.insert("end", text + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def _refresh_excel_label(self) -> None:
        path = self.cfg.get("excel_path", "")
        if path:
            self.excel_label.configure(text=f"Output file: {path}", foreground="#444")
        else:
            self.excel_label.configure(
                text="Output file: not set — use File → Set Output File",
                foreground="#b00",
            )

    def clear_fields(self) -> None:
        for v in self.vars.values():
            v.set("")
        self.profile_boost = ""

    # ---------- menu actions -----------------------------------------
    _FILETYPES = [
        ("Excel workbook", "*.xlsx"),
        ("CSV (spreadsheet)", "*.csv"),
        ("Plain text", "*.txt"),
        ("Markdown", "*.md"),
        ("RIS (EndNote / Zotero / Mendeley)", "*.ris"),
        ("BibTeX", "*.bib"),
    ]

    def _ask_output_path(self, title: str, initialfile: str, initialdir: str):
        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=".xlsx",
            filetypes=self._FILETYPES,
            initialfile=initialfile,
            initialdir=initialdir,
            confirmoverwrite=False,
        )
        if not path:
            return None
        if Path(path).suffix.lower() not in FORMATS:
            messagebox.showwarning(
                "Unsupported file type",
                "Please use one of: " + ", ".join(sorted(FORMATS)),
            )
            return None
        return path

    def _set_output_path(self, path: str, verb: str) -> None:
        self.cfg["excel_path"] = path
        try:
            save_config(self.cfg)
        except RuntimeError as exc:
            messagebox.showerror("Config error", str(exc))
            return
        self._refresh_excel_label()
        self.log(f"Output file {verb}: {path}")

    def choose_excel(self) -> None:
        initial = self.cfg.get("excel_path") or str(Path.home() / "Desktop" / "Litwell Results.xlsx")
        initial_p = Path(initial)
        path = self._ask_output_path(
            "Choose or create the output file",
            initial_p.name if initial_p.suffix else "Litwell Results.xlsx",
            str(initial_p.parent),
        )
        if path:
            self._set_output_path(path, "set to")

    def new_output_file(self) -> None:
        cur = self.cfg.get("excel_path", "")
        cur_p = Path(cur) if cur else (Path.home() / "Desktop" / "Litwell Results.xlsx")
        ext = cur_p.suffix.lower() if cur_p.suffix.lower() in FORMATS else ".xlsx"
        # strip a trailing " YYYY-MM-DD" from the old stem so names don't stack up
        stem = _re.sub(r"\s*\d{4}-\d{2}-\d{2}$", "", cur_p.stem) or "Litwell Results"
        suggested = f"{stem} {_dt.date.today().isoformat()}{ext}"
        path = self._ask_output_path(
            "Start a new output file", suggested, str(cur_p.parent)
        )
        if path:
            self._set_output_path(path, "started")
            self.log("New searches will be saved to this new file. "
                     "Your previous file is untouched.")

    def _startup_session_check(self) -> None:
        if not self.cfg.get("startup_prompt", True):
            return
        path = self.cfg.get("excel_path", "")
        if not path:
            return
        p = Path(path).expanduser()
        if not p.exists():
            return
        try:
            n = count_entries(str(p))
        except Exception:
            n = 0
        if n <= 0:
            return
        StartupSessionDialog(self.root, p, n, self)

    @staticmethod
    def _os_open(target: Path, *, reveal: bool = False) -> None:
        """Open a file/folder with the OS default handler. stdlib only."""
        import subprocess
        import sys

        target = str(target)
        if sys.platform == "darwin":
            args = ["open", "-R", target] if reveal else ["open", target]
            subprocess.run(args, check=False)
        elif sys.platform.startswith("win"):
            if reveal:
                subprocess.run(["explorer", f"/select,{target}"], check=False)
            else:
                import os

                os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", target], check=False)

    def _excel_path_or_warn(self):
        path = self.cfg.get("excel_path", "")
        if not path:
            messagebox.showinfo(
                "No output file set",
                "Choose an output file first (the Change… button, "
                "or File → Set Output File).",
            )
            return None
        p = Path(path).expanduser()
        if not p.exists():
            messagebox.showinfo(
                "Not created yet",
                "The output file doesn't exist yet.\n"
                "Run a search and it will be created.",
            )
            return None
        return p

    def open_excel(self) -> None:
        p = self._excel_path_or_warn()
        if p is None:
            return
        try:
            self._os_open(p)
            self.log(f"Opened {p.name}.")
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Could not open", str(exc))

    def reveal_excel(self) -> None:
        p = self._excel_path_or_warn()
        if p is None:
            return
        try:
            self._os_open(p, reveal=True)
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Could not open folder", str(exc))

    def check_duplicates(self) -> None:
        from litsearch import excel_writer

        p = self._excel_path_or_warn()
        if p is None:
            return
        if p.suffix.lower() != ".xlsx":
            messagebox.showinfo(
                "Excel only",
                "The duplicate cleanup tool works on .xlsx files.\n\n"
                "For .csv / .txt / .ris / .bib files, duplicates are already "
                "skipped automatically every time a search is saved.",
            )
            return
        try:
            dupes = excel_writer.review_duplicates(str(p))
        except (RuntimeError, OSError) as exc:
            messagebox.showerror("Could not read the Excel file", str(exc))
            return

        if not dupes:
            self.log("Duplicate check: none found.")
            messagebox.showinfo(
                "No duplicates",
                "No duplicate rows were found in the Results sheet.\n\n"
                "(New searches already skip papers that are already in the file; "
                "this checks the whole sheet, including rows added by other means.)",
            )
            return

        preview = "\n".join(f"   •  {t[:80]}" for t, _row in dupes[:12])
        more = f"\n   …and {len(dupes) - 12} more" if len(dupes) > 12 else ""
        proceed = messagebox.askyesno(
            "Duplicates found",
            f"Found {len(dupes)} duplicate row(s) in the Results sheet:\n\n"
            f"{preview}{more}\n\n"
            f"Remove them (keeping the first copy of each paper)?\n"
            f"A timestamped backup of the file is saved first.",
        )
        if not proceed:
            self.log(f"Duplicate check: {len(dupes)} found, left in place.")
            return

        try:
            result = excel_writer.remove_duplicates(str(p))
        except (RuntimeError, OSError) as exc:
            messagebox.showerror("Could not update the Excel file", str(exc))
            return

        self.log(
            f"Removed {result['removed']} duplicate row(s). "
            f"Backup: {result['backup']}"
        )
        messagebox.showinfo(
            "Duplicates removed",
            f"Removed {result['removed']} duplicate row(s).\n\n"
            f"Backup saved as:\n{Path(result['backup']).name}",
        )

    def edit_settings(self) -> None:
        SettingsDialog(self.root, self.cfg, on_save=self._after_settings)

    def _after_settings(self) -> None:
        self.log("API keys / contact settings saved.")

    def _about(self) -> None:
        messagebox.showinfo(
            "About",
            f"{APP_TITLE}\n\nSearches papers, preprints and patents — tick any\n"
            f"number of sources and search them all at once —\n"
            f"and saves the results to one file.\n\n"
            f"{CREDIT}\n{LICENSE_LINE}\n\n"
            f"Config file:\n{CONFIG_PATH}",
        )

    # ---------- profiles --------------------------------------------
    def _refresh_profiles(self) -> None:
        self.profile_box.configure(values=profiles.names(self.cfg))

    def load_profile(self) -> None:
        data = profiles.get(self.cfg, self.profile_name.get())
        if not data:
            return
        self.vars["keyword"].set(data.get("keyword", ""))
        self.match_mode.set(data.get("match_mode", "exact") or "exact")
        self.vars["must_terms"].set(data.get("must_terms", ""))
        self.vars["exclude_terms"].set(data.get("exclude_terms", ""))
        self.vars["description"].set(data.get("description", ""))
        self.profile_boost = data.get("boost_terms", "")
        self.min_score.set(str(data.get("min_score", 0) or 0))
        if data.get("sources"):
            self._tick_sources(data["sources"])
        self.log(f"Profile loaded: {self.profile_name.get()}")

    def save_profile(self) -> None:
        name = self.profile_name.get().strip()
        if not name:
            messagebox.showinfo("Save profile", "Type a name for the profile in the Profile box first.")
            return
        try:
            profiles.save(self.cfg, name, {
                "keyword": self.vars["keyword"].get().strip(),
                "match_mode": self.match_mode.get(),
                "must_terms": self.vars["must_terms"].get().strip(),
                "exclude_terms": self.vars["exclude_terms"].get().strip(),
                "boost_terms": self.profile_boost,
                "description": self.vars["description"].get().strip(),
                "sources": self._ticked_sources(),
                "min_score": self._int(self.min_score.get(), 0),
            })
            save_config(self.cfg)
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Save profile", str(exc))
            return
        self._refresh_profiles()
        self.log(f"Profile saved: {name}")

    def delete_profile(self) -> None:
        name = self.profile_name.get().strip()
        if name not in profiles.names(self.cfg):
            messagebox.showinfo("Delete profile", "Pick a saved profile in the Profile box first.")
            return
        if not messagebox.askyesno("Delete profile", f"Delete the profile \"{name}\"?"):
            return
        profiles.delete(self.cfg, name)
        try:
            save_config(self.cfg)
        except RuntimeError:
            pass
        self.profile_name.set("")
        self._refresh_profiles()
        self.log(f"Profile deleted: {name}")

    @staticmethod
    def _int(text, default: int) -> int:
        try:
            return max(0, min(100, int(str(text).strip())))
        except ValueError:
            return default

    # ---------- guide -----------------------------------------------
    def open_guide(self) -> None:
        for rel in ("litwell_docs/Litwell_How_To_Guide.pdf", "docs/Litwell_How_To_Guide.pdf"):
            p = Path(resource_path(rel))
            if p.exists():
                self._os_open(p)
                return
        messagebox.showinfo(
            "How-to Guide",
            "The guide (Litwell_How_To_Guide.pdf) was not found next to the app.\n"
            "It is in the docs folder of the download.",
        )

    def _tick_sources(self, keys) -> None:
        for k, var in self.source_vars.items():
            var.set(k in keys)

    def _ticked_sources(self) -> list:
        return [k for k in SOURCES if self.source_vars[k].get()]   # list order, not click order

    # ---------- search ----------------------------------------------
    def on_search(self) -> None:
        if self.searching:
            return
        try:
            max_results = max(1, min(int(self.max_results.get()), 500))
        except ValueError:
            max_results = 100
        sources = self._ticked_sources()
        params = SearchParams(
            keyword=self.vars["keyword"].get().strip(),
            author=self.vars["author"].get().strip(),
            title=self.vars["title"].get().strip(),
            journal=self.vars["journal"].get().strip(),
            date_start=self.vars["date_start"].get().strip(),
            date_end=self.vars["date_end"].get().strip(),
            source=sources[0] if sources else "pubmed",
            max_results=max_results,
            match_mode=self.match_mode.get(),
            must_terms=self.vars["must_terms"].get().strip(),
            exclude_terms=self.vars["exclude_terms"].get().strip(),
            min_score=self._int(self.min_score.get(), 0),
            profile_name=self.profile_name.get().strip(),
            profile_description=self.vars["description"].get().strip(),
            boost_terms=self.profile_boost,
        )
        if params.is_empty():
            messagebox.showwarning(
                "Empty search", "Enter at least one field before searching."
            )
            return
        if not sources:
            messagebox.showwarning(
                "No source ticked", "Tick at least one source to search."
            )
            return
        if not self.cfg.get("excel_path"):
            messagebox.showwarning(
                "No output file",
                "Set an output file first (File → Set Output File, or the "
                "Change… button).",
            )
            return

        # Remember the ticked sources + max results for next launch.
        self.cfg["default_sources"] = sources
        self.cfg["default_source"] = sources[0]   # older versions read only this
        self.cfg["max_results"] = max_results
        self.cfg.update(match_mode=params.match_mode, must_terms=params.must_terms,
                        exclude_terms=params.exclude_terms, min_score=params.min_score,
                        last_profile=params.profile_name, ai_enabled=bool(self.ai_on.get()))
        try:
            save_config(self.cfg)
        except RuntimeError:
            pass

        self.searching = True
        self.search_btn.configure(state="disabled")
        self.progress.start(12)
        self.log("\n" + "=" * 60)
        names = [SOURCES[k][0] for k in sources]
        self.log(f"Searching {len(names)} source(s): {', '.join(names)} …")
        self.log(f"Topic matched as: {params.mode_label().lower()}"
                 + (f"; must also contain: {params.must_terms}" if params.must_terms else "")
                 + (f"; excluding: {params.exclude_terms}" if params.exclude_terms else ""))
        if self.cfg.get("ai_enabled"):
            self.log("AI triage is on (local Ollama). Rating the results will take a while.")

        t = threading.Thread(target=self._worker, args=(params, sources), daemon=True)
        t.start()

    def _worker(self, params: SearchParams, sources) -> None:
        def progress(msg: str) -> None:
            self.msg_queue.put(("log", msg))

        try:
            outcome = run_multi_search(params, sources, self.cfg, progress=progress)
            self.msg_queue.put(("done", outcome))
        except Exception as exc:  # pragma: no cover - safety net
            self.msg_queue.put(("error", str(exc)))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.log(f"  {payload}")
                elif kind == "error":
                    self._finish()
                    self.log(f"ERROR: {payload}")
                    messagebox.showerror("Search failed", str(payload))
                elif kind == "done":
                    self._finish()
                    self._report(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._drain_queue)

    def _finish(self) -> None:
        self.searching = False
        self.search_btn.configure(state="normal")
        self.progress.stop()

    def _report(self, multi) -> None:
        if multi.error or not multi.succeeded:
            msg = multi.error or "\n\n".join(
                f"{r.name}: {r.outcome.error}" for r in multi.failed
            )
            self.log(f"ERROR: {msg}")
            messagebox.showerror("Search failed", msg)
            return

        self.log("")
        for r in multi.results:
            o = r.outcome
            if o.ok:
                removed = f", {o.removed} removed by your rules" if o.removed else ""
                self.log(
                    f"  {r.name}: matched {o.total_found}, fetched {o.fetched}{removed} — "
                    f"{o.added} new, {o.skipped_duplicates} already known."
                )
            elif o.skipped:
                self.log(f"  {r.name}: SKIPPED — {o.error.splitlines()[0]}")
            else:
                self.log(f"  {r.name}: NOT searched — {o.error.splitlines()[0]}")
        if multi.rules:
            self.log("Filters:")
            for rule, n in multi.rules:
                self.log(f"   • {rule}: {n} removed")
        if multi.merged_copies:
            self.log(f"Merged {multi.merged_copies} copy(ies) of papers found by more than one source.")
        for note in multi.notes:
            self.log(f"Note: {note}")
        self.log(
            f"Kept {multi.kept} record(s): {multi.new_rows} new, {multi.known_rows} already in the file "
            f"(a paper found by two sources is stored once). The file now holds {multi.total_rows}."
        )
        best = sorted(
            {id(a): a for r in multi.succeeded for a in r.outcome.articles}.values(),
            key=lambda a: -(a.score or 0),
        )[:5]
        if best:
            self.log("Best matches:")
            for art in best:
                self.log(f"   • [{art.score}] {art.title[:90]}  ({art.date})")
        self.log(f"Saved to: {self.cfg['excel_path']}")

        if multi.failed:
            lines = "\n\n".join(
                f"{r.name}:\n{r.outcome.error}" for r in multi.failed
            )
            messagebox.showwarning(
                "Some sources could not be searched",
                f"{len(multi.succeeded)} of {len(multi.results)} sources were searched "
                f"and saved. These were not:\n\n{lines}",
            )


class StartupSessionDialog:
    """Asked at launch when the output file already holds results."""

    def __init__(self, parent, path: Path, count: int, app) -> None:
        from tkinter import Toplevel

        self.app = app
        top = self.top = Toplevel(parent)
        top.title("Continue or start fresh?")
        top.transient(parent)
        top.resizable(False, False)
        top.grab_set()
        frm = ttk.Frame(top, padding=16)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text=(
                f"Your output file already has about {count} record(s):\n"
                f"{path.name}\n\n"
                "Add new searches to this file, or start a new one?"
            ),
            justify="left",
        ).pack(anchor="w")

        self.dont_ask = BooleanVar(value=False)
        ttk.Checkbutton(
            frm,
            text="Always keep using the last file — don't ask again",
            variable=self.dont_ask,
        ).pack(anchor="w", pady=(12, 0))

        btns = ttk.Frame(frm)
        btns.pack(anchor="e", pady=(14, 0))
        ttk.Button(btns, text="Start new file…", command=self._new).pack(
            side="right", padx=(6, 0)
        )
        keep = ttk.Button(btns, text="Keep using this file", command=self._keep)
        keep.pack(side="right")
        keep.focus_set()
        top.bind("<Return>", lambda _e: self._keep())

    def _keep(self) -> None:
        if self.dont_ask.get():
            self.app.cfg["startup_prompt"] = False
            try:
                save_config(self.app.cfg)
            except RuntimeError:
                pass
            self.app.log("Startup prompt turned off (File menu still has "
                         "\"New Output File…\").")
        self.top.destroy()

    def _new(self) -> None:
        self.top.destroy()
        self.app.new_output_file()


class SettingsDialog:
    def __init__(self, parent, cfg, on_save) -> None:
        self.cfg = cfg
        self.on_save = on_save
        from tkinter import Toplevel

        top = self.top = Toplevel(parent)
        top.title("API Keys & Contact")
        top.transient(parent)
        top.resizable(False, False)
        frm = ttk.Frame(top, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text=(
                "All optional except where a source needs it.\n"
                "• Contact email — optional; puts you in the faster 'polite' pool at Crossref,\n"
                "   OpenAlex and NCBI. Stored only in your own settings file, never sent anywhere else.\n"
                "• NCBI API key — raises the PubMed rate limit (3 → 10 req/sec).\n"
                "• OpenAlex API key — optional; own daily budget. Free: openalex.org\n"
                "• USPTO API key — for USPTO Patents. Free: data.uspto.gov\n"
                "• EPO OPS key + secret — for worldwide patents. Free: developers.epo.org\n"
                "• Ollama model — optional local AI triage. Leave blank to use an installed model automatically."
            ),
            foreground="#555",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.email = StringVar(value=cfg.get("contact_email", "") or cfg.get("ncbi_email", ""))
        self.ollama_model = StringVar(value=cfg.get("ollama_model", ""))
        self.api_key = StringVar(value=cfg.get("ncbi_api_key", ""))
        self.pv_key = StringVar(
            value=cfg.get("uspto_api_key", "") or cfg.get("patentsview_api_key", "")
        )
        self.oa_key = StringVar(value=cfg.get("openalex_api_key", ""))
        self.epo_key = StringVar(value=cfg.get("epo_ops_key", ""))
        self.epo_secret = StringVar(value=cfg.get("epo_ops_secret", ""))
        rows = [
            ("Contact email", self.email),
            ("NCBI API key", self.api_key),
            ("OpenAlex API key", self.oa_key),
            ("USPTO API key", self.pv_key),
            ("EPO OPS key", self.epo_key),
            ("EPO OPS secret", self.epo_secret),
            ("Ollama model (blank = auto)", self.ollama_model),
        ]
        for i, (label, var) in enumerate(rows, start=1):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(frm, textvariable=var, width=46).grid(row=i, column=1, pady=4)

        btns = ttk.Frame(frm)
        btns.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="right")

    def _save(self) -> None:
        self.cfg["contact_email"] = self.email.get().strip()
        self.cfg["ncbi_email"] = ""
        self.cfg["ollama_model"] = self.ollama_model.get().strip()
        self.cfg["ncbi_api_key"] = self.api_key.get().strip()
        self.cfg["openalex_api_key"] = self.oa_key.get().strip()
        self.cfg["uspto_api_key"] = self.pv_key.get().strip()
        self.cfg["epo_ops_key"] = self.epo_key.get().strip()
        self.cfg["epo_ops_secret"] = self.epo_secret.get().strip()
        try:
            save_config(self.cfg)
        except RuntimeError as exc:
            messagebox.showerror("Config error", str(exc))
            return
        self.on_save()
        self.top.destroy()


def _selftest() -> int:
    """Headless check used to verify a packaged build can reach the network
    and its dependencies are bundled. Run:  "Litwell" --selftest
    """
    import requests  # noqa: F401
    import openpyxl  # noqa: F401
    from litsearch.search import SOURCES

    from litsearch.config import load_config

    cfg = load_config()
    print(f"requests {requests.__version__}, openpyxl {openpyxl.__version__}")
    ok = True
    for key, (name, module) in SOURCES.items():
        if key == "patents" and not (
            cfg.get("uspto_api_key") or cfg.get("patentsview_api_key")
        ):
            print(f"  {name:<22} SKIP — no USPTO API key configured")
            continue
        if key == "epo" and not (cfg.get("epo_ops_key") and cfg.get("epo_ops_secret")):
            print(f"  {name:<22} SKIP — no EPO OPS credentials configured")
            continue
        try:
            params = SearchParams(keyword="machine learning", source=key, max_results=2)
            articles, total = module.search(params, cfg)
            print(f"  {name:<22} OK — {total} matched, {len(articles)} parsed")
        except Exception as exc:  # pragma: no cover
            if "HTTP 5" in str(exc):
                print(f"  {name:<22} SKIP: the service is down right now ({str(exc)[:60]})")
                continue
            if "rate limit reached" in str(exc):
                print(f"  {name:<22} SKIP — rate-limited right now ({str(exc)[:60]}…)")
                continue
            ok = False
            print(f"  {name:<22} FAILED — {exc}")
    print("selftest OK" if ok else "selftest FAILED")
    return 0 if ok else 1


def main() -> None:
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    _set_windows_app_id()
    _avoid_tk_console()
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
