from __future__ import annotations

import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .engine import run_investigation
from .exporting import legion_results_to_maltego_rows, write_maltego_csv
from .learning import build_features, train_model
from .memory import OsintMemory
from .legion import PhantomLegion
import json


class OsintApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OSINT Agent")
        self.geometry("1100x760")
        self.minsize(1000, 700)
        self._bg = "#050905"
        self._panel = "#0b120b"
        self._panel2 = "#091509"
        self._text = "#d9ffe6"
        self._muted = "#73a986"
        self._accent = "#00ff9c"
        self._accent2 = "#79ffbf"
        self.configure(bg=self._bg)
        self._style = ttk.Style(self)
        try:
            self._style.theme_use("clam")
        except tk.TclError:
            pass
        self._style.configure("TFrame", background=self._bg)
        self._style.configure("TLabelframe", background=self._bg, foreground=self._accent, borderwidth=1, relief="solid")
        self._style.configure("TLabelframe.Label", background=self._bg, foreground=self._accent, font=("Consolas", 10, "bold"))
        self._style.configure("TLabel", background=self._bg, foreground=self._text, font=("Consolas", 10))
        self._style.configure("Header.TLabel", background=self._bg, foreground=self._accent, font=("Consolas", 18, "bold"))
        self._style.configure("SubHeader.TLabel", background=self._bg, foreground=self._muted, font=("Consolas", 9))
        self._style.configure("TButton", background=self._panel, foreground=self._accent, bordercolor=self._accent, font=("Consolas", 10, "bold"))
        self._style.map("TButton", foreground=[("active", self._bg)], background=[("active", self._accent)])
        self._style.configure("TEntry", fieldbackground=self._panel, foreground=self._text, insertcolor=self._accent, bordercolor=self._accent)
        self._style.configure("TCombobox", fieldbackground=self._panel, foreground=self._text, background=self._panel, arrowcolor=self._accent)
        self._style.configure("Treeview", background=self._panel, fieldbackground=self._panel, foreground=self._text, bordercolor=self._accent, rowheight=26)
        self._style.configure("Treeview.Heading", background=self._panel2, foreground=self._accent, font=("Consolas", 10, "bold"))

        self.subject_var = tk.StringVar()
        self.web_limit_var = tk.IntVar(value=10)
        self.archive_limit_var = tk.IntVar(value=10)
        self.crawl_depth_var = tk.IntVar(value=1)
        self.max_pages_var = tk.IntVar(value=30)
        self.link_limit_var = tk.IntVar(value=20)
        self.follow_links_var = tk.BooleanVar(value=True)
        self.track_target_var = tk.BooleanVar(value=True)
        self.allow_domains_var = tk.StringVar()
        self.deny_domains_var = tk.StringVar()
        self.open_crawl_var = tk.BooleanVar(value=False)
        self.memory_db_var = tk.StringVar(value=".osint_memory.sqlite3")
        self.output_var = tk.StringVar()
        self.json_output_var = tk.StringVar()
        self.csv_output_var = tk.StringVar()
        self.pdf_list: list[str] = []
        self.feedback_url_var = tk.StringVar()
        self.feedback_kind_var = tk.StringVar(value="web")
        self.feedback_label_var = tk.DoubleVar(value=1.0)
        self.feedback_title_var = tk.StringVar()
        self.feedback_reason_var = tk.StringVar()
        self.feedback_trail_depth_var = tk.IntVar(value=0)
        self.feedback_trail_score_var = tk.DoubleVar(value=0.0)
        self.feedback_trail_strayed_var = tk.BooleanVar(value=False)
        self.train_epochs_var = tk.IntVar(value=100)
        self.train_lr_var = tk.DoubleVar(value=0.001)
        self.train_margin_var = tk.DoubleVar(value=0.1)
        self.train_pairs_strategy = tk.StringVar(value="all")
        self.train_pairs_per_subject = tk.IntVar(value=200)
        self.train_val_split = tk.DoubleVar(value=0.2)
        self.train_device = tk.StringVar(value="cpu")
        # Legion controls
        self.legion_subjects_var = tk.StringVar()
        self.legion_num_agents = tk.IntVar(value=1)
        self.legion_mode = tk.StringVar(value="parallel")
        self.legion_targets = tk.StringVar()
        self.legion_worker_urls = tk.StringVar()
        self.legion_coordinator_url = tk.StringVar(value=os.environ.get("OSINT_AGENT_COORDINATOR_URL", ""))
        self.legion_token = tk.StringVar(value=os.environ.get("OSINT_AGENT_COORDINATOR_TOKEN", "phantom"))
        self.legion_remote_cmd = tk.StringVar(value="python -m osint_agent.cli investigate {subject}")
        self.legion_selected_subject = tk.StringVar()

        self._build_ui()

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=self._bg)
        header.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(header, text="PHANTOM_LEGION", bg=self._bg, fg=self._accent, font=("Consolas", 20, "bold")).pack(anchor="w")
        tk.Label(header, text="signal console // distributed OSINT // local control", bg=self._bg, fg=self._muted, font=("Consolas", 10)).pack(anchor="w")

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Subject").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.subject_var, width=70).grid(row=0, column=1, columnspan=4, sticky="we", padx=6)

        ttk.Label(top, text="Web").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(top, from_=1, to=100, textvariable=self.web_limit_var, width=8).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(top, text="Archive").grid(row=1, column=2, sticky="w")
        ttk.Spinbox(top, from_=1, to=100, textvariable=self.archive_limit_var, width=8).grid(row=1, column=3, sticky="w", padx=6)
        ttk.Checkbutton(top, text="Follow links", variable=self.follow_links_var).grid(row=1, column=4, sticky="w")
        ttk.Checkbutton(top, text="Track target trails", variable=self.track_target_var).grid(row=1, column=5, sticky="w")

        ttk.Label(top, text="Crawl depth").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(top, from_=0, to=5, textvariable=self.crawl_depth_var, width=8).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(top, text="Max pages").grid(row=2, column=2, sticky="w")
        ttk.Spinbox(top, from_=1, to=500, textvariable=self.max_pages_var, width=8).grid(row=2, column=3, sticky="w", padx=6)
        ttk.Label(top, text="Link limit").grid(row=2, column=4, sticky="w")
        ttk.Spinbox(top, from_=1, to=100, textvariable=self.link_limit_var, width=8).grid(row=2, column=5, sticky="w", padx=6)

        ttk.Label(top, text="Allow domains").grid(row=3, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.allow_domains_var, width=40).grid(row=3, column=1, columnspan=2, sticky="we", padx=6)
        ttk.Label(top, text="Deny domains").grid(row=3, column=3, sticky="w")
        ttk.Entry(top, textvariable=self.deny_domains_var, width=40).grid(row=3, column=4, columnspan=2, sticky="we", padx=6)

        ttk.Label(top, text="Memory DB").grid(row=4, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.memory_db_var, width=40).grid(row=4, column=1, columnspan=2, sticky="we", padx=6)
        ttk.Button(top, text="Browse", command=self._choose_memory_db).grid(row=4, column=3, sticky="w")
        ttk.Checkbutton(top, text="Open crawl", variable=self.open_crawl_var).grid(row=4, column=4, sticky="w")
        ttk.Button(top, text="Add PDF", command=self._add_pdf).grid(row=4, column=5, sticky="w")

        ttk.Label(top, text="Output report").grid(row=5, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.output_var, width=40).grid(row=5, column=1, columnspan=2, sticky="we", padx=6)
        ttk.Button(top, text="Browse", command=self._choose_output).grid(row=5, column=3, sticky="w")
        ttk.Label(top, text="JSON export").grid(row=5, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.json_output_var, width=24).grid(row=5, column=5, sticky="we", padx=6)

        ttk.Label(top, text="CSV export").grid(row=6, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.csv_output_var, width=40).grid(row=6, column=1, columnspan=2, sticky="we", padx=6)
        ttk.Button(top, text="Browse", command=self._choose_csv_output).grid(row=6, column=3, sticky="w")
        ttk.Button(top, text="Run", command=self._run).grid(row=6, column=5, sticky="e")

        self.pdf_label = ttk.Label(top, text="PDFs: none")
        self.pdf_label.grid(row=7, column=0, columnspan=6, sticky="w", pady=(6, 0))

        top.columnconfigure(1, weight=1)
        top.columnconfigure(2, weight=1)
        top.columnconfigure(4, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, padding=(12, 4)).pack(fill="x")

        # Split view: tree (left) and textual crawl report (right)
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=12, pady=12)

        left_frame = ttk.Frame(paned)
        right_frame = ttk.Frame(paned)

        paned.add(left_frame, weight=1)
        paned.add(right_frame, weight=3)

        self.output_text = tk.Text(right_frame, wrap="word")
        self.output_text.configure(bg=self._panel, fg=self._text, insertbackground=self._accent, relief="flat", font=("Consolas", 10), padx=8, pady=8)
        self.output_text.pack(fill="both", expand=True)

        # Crawl tree view
        self.crawl_tree = ttk.Treeview(left_frame, columns=("url", "depth"), show="tree")
        self.crawl_tree.heading("url", text="URL")
        self.crawl_tree.column("url", width=400)
        self.crawl_tree.pack(fill="both", expand=True)

        self.crawl_text = tk.Text(right_frame, height=10, wrap="word")
        self.crawl_text.configure(bg=self._panel2, fg=self._accent2, insertbackground=self._accent, relief="flat", font=("Consolas", 10), padx=8, pady=8)
        self.crawl_text.pack(fill="x", pady=(6, 0))

        feedback = ttk.LabelFrame(self, text="Learning Feedback", padding=12)
        feedback.pack(fill="x", padx=12, pady=(0, 12))

        ttk.Label(feedback, text="URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(feedback, textvariable=self.feedback_url_var, width=70).grid(row=0, column=1, columnspan=3, sticky="we", padx=6)
        ttk.Label(feedback, text="Kind").grid(row=0, column=4, sticky="w")
        ttk.Combobox(feedback, textvariable=self.feedback_kind_var, values=["web", "archive", "pdf", "link", "linked_pdf"], width=12, state="readonly").grid(row=0, column=5, sticky="w")

        ttk.Label(feedback, text="Title").grid(row=1, column=0, sticky="w")
        ttk.Entry(feedback, textvariable=self.feedback_title_var, width=40).grid(row=1, column=1, columnspan=2, sticky="we", padx=6)
        ttk.Label(feedback, text="Label 0-1").grid(row=1, column=3, sticky="w")
        ttk.Spinbox(feedback, from_=0.0, to=1.0, increment=0.1, textvariable=self.feedback_label_var, width=8).grid(row=1, column=4, sticky="w")
        ttk.Button(feedback, text="Save Feedback", command=self._save_feedback).grid(row=1, column=5, sticky="e")

        ttk.Label(feedback, text="Reason / excerpt").grid(row=2, column=0, sticky="w")
        ttk.Entry(feedback, textvariable=self.feedback_reason_var, width=70).grid(row=2, column=1, columnspan=4, sticky="we", padx=6)
        ttk.Button(feedback, text="Train Model", command=self._train_model).grid(row=2, column=5, sticky="e")
        ttk.Label(feedback, text="Trail depth").grid(row=3, column=0, sticky="w")
        ttk.Entry(feedback, textvariable=self.feedback_trail_depth_var, width=8).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Label(feedback, text="Trail score").grid(row=3, column=2, sticky="w")
        ttk.Entry(feedback, textvariable=self.feedback_trail_score_var, width=8).grid(row=3, column=3, sticky="w", padx=6)
        ttk.Checkbutton(feedback, text="Strayed", variable=self.feedback_trail_strayed_var).grid(row=3, column=4, sticky="w")
        # Training hyperparameters row
        ttk.Label(feedback, text="Epochs").grid(row=4, column=0, sticky="w")
        ttk.Entry(feedback, textvariable=self.train_epochs_var, width=8).grid(row=4, column=1, sticky="w", padx=6)
        ttk.Label(feedback, text="LR").grid(row=4, column=2, sticky="w")
        ttk.Entry(feedback, textvariable=self.train_lr_var, width=8).grid(row=4, column=3, sticky="w", padx=6)
        ttk.Label(feedback, text="Margin").grid(row=4, column=4, sticky="w")
        ttk.Entry(feedback, textvariable=self.train_margin_var, width=8).grid(row=4, column=5, sticky="w", padx=6)

        ttk.Label(feedback, text="Pairs").grid(row=5, column=0, sticky="w")
        ttk.Combobox(feedback, textvariable=self.train_pairs_strategy, values=["all", "random"], width=8, state="readonly").grid(row=5, column=1, sticky="w", padx=6)
        ttk.Label(feedback, text="Per-subject").grid(row=5, column=2, sticky="w")
        ttk.Entry(feedback, textvariable=self.train_pairs_per_subject, width=8).grid(row=5, column=3, sticky="w", padx=6)
        ttk.Label(feedback, text="Val split").grid(row=5, column=4, sticky="w")
        ttk.Entry(feedback, textvariable=self.train_val_split, width=8).grid(row=5, column=5, sticky="w", padx=6)

        ttk.Label(feedback, text="Device").grid(row=6, column=0, sticky="w")
        ttk.Combobox(feedback, textvariable=self.train_device, values=["cpu", "cuda"], width=8, state="readonly").grid(row=6, column=1, sticky="w", padx=6)
        # Metrics display and export
        self.metric_ndcg = tk.StringVar(value="NDCG@10: -")
        self.metric_mrr = tk.StringVar(value="MRR: -")
        ttk.Label(feedback, textvariable=self.metric_ndcg).grid(row=6, column=2, sticky="w", pady=(6, 0))
        ttk.Label(feedback, textvariable=self.metric_mrr).grid(row=6, column=3, sticky="w", pady=(6, 0))
        ttk.Button(feedback, text="Export Checkpoint", command=self._export_checkpoint).grid(row=6, column=5, sticky="e")

        # PHANTOM_LEGION controls
        legion_frame = ttk.LabelFrame(self, text="PHANTOM_LEGION", padding=12)
        legion_frame.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Label(legion_frame, text="Subjects (comma-separated)").grid(row=0, column=0, sticky="w")
        ttk.Entry(legion_frame, textvariable=self.legion_subjects_var, width=60).grid(row=0, column=1, columnspan=3, sticky="we", padx=6)
        ttk.Label(legion_frame, text="Agents").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(legion_frame, from_=1, to=16, textvariable=self.legion_num_agents, width=6).grid(row=0, column=5, sticky="w", padx=6)
        ttk.Label(legion_frame, text="Mode").grid(row=1, column=0, sticky="w")
        ttk.Combobox(legion_frame, textvariable=self.legion_mode, values=["parallel", "collaborative"], width=12, state="readonly").grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(legion_frame, text="Coordinator").grid(row=1, column=2, sticky="w")
        ttk.Entry(legion_frame, textvariable=self.legion_coordinator_url, width=30).grid(row=1, column=3, sticky="we", padx=6)
        ttk.Button(legion_frame, text="Run Legion", command=self._run_legion).grid(row=1, column=5, sticky="e")
        ttk.Label(legion_frame, text="SSH hosts").grid(row=2, column=0, sticky="w")
        ttk.Entry(legion_frame, textvariable=self.legion_targets, width=30).grid(row=2, column=1, sticky="we", padx=6)
        ttk.Label(legion_frame, text="Token").grid(row=2, column=2, sticky="w")
        ttk.Entry(legion_frame, textvariable=self.legion_token, width=16, show="*").grid(row=2, column=3, sticky="we", padx=6)
        ttk.Button(legion_frame, text="Export Maltego CSV", command=self._export_legion_maltego).grid(row=2, column=4, sticky="e")
        ttk.Button(legion_frame, text="Export Legion Report", command=self._export_legion_report).grid(row=2, column=5, sticky="e")
        ttk.Label(legion_frame, text="Remote cmd").grid(row=3, column=0, sticky="w")
        ttk.Entry(legion_frame, textvariable=self.legion_remote_cmd, width=60).grid(row=3, column=1, columnspan=4, sticky="we", padx=6)

        self.legion_tree = ttk.Treeview(legion_frame, columns=("score", "path", "drift", "freq", "kind", "title"), show="tree headings")
        self.legion_tree.heading("#0", text="URL")
        self.legion_tree.heading("score", text="Score")
        self.legion_tree.heading("path", text="Path")
        self.legion_tree.heading("drift", text="Drift")
        self.legion_tree.heading("freq", text="Freq")
        self.legion_tree.heading("kind", text="Kinds")
        self.legion_tree.heading("title", text="Title")
        self.legion_tree.column("#0", width=520)
        self.legion_tree.column("score", width=70, anchor="e")
        self.legion_tree.column("path", width=70, anchor="e")
        self.legion_tree.column("drift", width=70, anchor="e")
        self.legion_tree.column("freq", width=50, anchor="e")
        self.legion_tree.column("kind", width=120)
        self.legion_tree.column("title", width=220)
        self.legion_tree.grid(row=4, column=0, columnspan=6, sticky="we", pady=(6, 0))
        self.legion_tree.bind("<<TreeviewSelect>>", self._on_legion_select)

        self.legion_preview = tk.Text(legion_frame, height=6, wrap="word")
        self.legion_preview.configure(bg=self._panel, fg=self._text, insertbackground=self._accent, relief="flat", font=("Consolas", 10), padx=8, pady=8)
        self.legion_preview.grid(row=5, column=0, columnspan=6, sticky="we", pady=(6, 0))

    def _choose_memory_db(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".sqlite3", filetypes=[("SQLite database", "*.sqlite3"), ("All files", "*")])
        if path:
            self.memory_db_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown", "*.md"), ("All files", "*")])
        if path:
            self.output_var.set(path)

    def _choose_csv_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("All files", "*")])
        if path:
            self.csv_output_var.set(path)

    def _add_pdf(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf"), ("All files", "*")])
        if not paths:
            return
        self.pdf_list.extend(paths)
        self.pdf_label.configure(text=f"PDFs: {len(self.pdf_list)} selected")

    def _run(self) -> None:
        subject = self.subject_var.get().strip()
        if not subject:
            messagebox.showerror("OSINT Agent", "Enter a subject first.")
            return

        self.status_var.set("Running investigation...")
        self.output_text.delete("1.0", tk.END)

        thread = threading.Thread(target=self._run_worker, daemon=True)
        thread.start()

    def _run_worker(self) -> None:
        try:
            result = run_investigation(
                self.subject_var.get().strip(),
                pdf_sources=list(self.pdf_list),
                web_limit=self.web_limit_var.get(),
                archive_limit=self.archive_limit_var.get(),
                follow_links=self.follow_links_var.get(),
                track_trails=self.track_target_var.get(),
                crawl_depth=self.crawl_depth_var.get(),
                max_pages=self.max_pages_var.get(),
                link_limit=self.link_limit_var.get(),
                allow_domains=_split_domains(self.allow_domains_var.get()),
                deny_domains=_split_domains(self.deny_domains_var.get()),
                open_crawl=self.open_crawl_var.get(),
                memory_db=self.memory_db_var.get().strip() or ".osint_memory.sqlite3",
                json_output=self.json_output_var.get().strip() or None,
                csv_output=self.csv_output_var.get().strip() or None,
            )
            report = result.report
            if self.output_var.get().strip():
                Path(self.output_var.get().strip()).write_text(report, encoding="utf-8")
            self.after(0, self._show_result, report, result.memory_stats, result.crawl_result)
        except Exception as exc:
            self.after(0, self._show_error, exc)

    def _show_result(self, report: str, memory_stats: dict[str, int], crawl_result) -> None:
        self.status_var.set(
            "Done. Memory: queries={queries}, pages={pages}, links={links}, pdfs={pdfs}, visits={visits}".format(**memory_stats)
        )
        self.output_text.insert(tk.END, report)
        # populate textual crawl section
        self.crawl_text.delete("1.0", tk.END)
        self.crawl_text.insert(tk.END, report.split("## Crawl Tree", 1)[1] if "## Crawl Tree" in report else "No crawl tree available.")

        # populate tree view from crawl_result if available
        try:
            self.crawl_tree.delete(*self.crawl_tree.get_children())
            visited = getattr(crawl_result, "visited_urls", []) or []
            discovered = getattr(crawl_result, "discovered_links", []) or []
            # Insert visited URLs as top-level nodes
            for i, url in enumerate(visited):
                node_id = self.crawl_tree.insert("", "end", text=url)
                # attach discovered links that match this host
                for link in discovered:
                    link_url = getattr(link, "url", None) or link.get("url") if isinstance(link, dict) else None
                    if link_url and link_url.startswith(url.split("/", 3)[0]):
                        self.crawl_tree.insert(node_id, "end", text=link_url)
        except Exception:
            # best-effort: don't block UI if structure differs
            pass

    def _save_feedback(self) -> None:
        if not self.feedback_url_var.get().strip():
            messagebox.showerror("OSINT Agent", "Enter a feedback URL first.")
            return
        if not self.subject_var.get().strip():
            messagebox.showerror("OSINT Agent", "Enter a subject first.")
            return
        with OsintMemory(self.memory_db_var.get().strip() or ".osint_memory.sqlite3") as memory:
            features = build_features(
                self.subject_var.get().strip(),
                kind=self.feedback_kind_var.get().strip(),
                title=self.feedback_title_var.get().strip(),
                url=self.feedback_url_var.get().strip(),
                text=self.feedback_reason_var.get().strip(),
                source_score=float(self.feedback_label_var.get()) * 100.0,
                trail_depth=int(self.feedback_trail_depth_var.get()),
                trail_score=float(self.feedback_trail_score_var.get()),
                trail_strayed=bool(self.feedback_trail_strayed_var.get()),
            )
            payload = {
                "features": features.tolist(),
                "kind": self.feedback_kind_var.get().strip(),
                "title": self.feedback_title_var.get().strip(),
                "url": self.feedback_url_var.get().strip(),
                "reason": self.feedback_reason_var.get().strip(),
                "trail_depth": int(self.feedback_trail_depth_var.get()),
                "trail_score": float(self.feedback_trail_score_var.get()),
                "trail_strayed": bool(self.feedback_trail_strayed_var.get()),
            }
            memory.add_feedback(self.subject_var.get().strip(), self.feedback_url_var.get().strip(), self.feedback_kind_var.get().strip(), float(self.feedback_label_var.get()), json.dumps(payload))
        self.status_var.set("Feedback saved")

    def _train_model(self) -> None:
        with OsintMemory(self.memory_db_var.get().strip() or ".osint_memory.sqlite3") as memory:
            stats, metrics, ck = train_model(
                memory,
                epochs=int(self.train_epochs_var.get()),
                lr=float(self.train_lr_var.get()),
                margin=float(self.train_margin_var.get()),
                checkpoint_path=None,
                device=self.train_device.get(),
                pairs_strategy=self.train_pairs_strategy.get(),
                pairs_per_subject=int(self.train_pairs_per_subject.get()),
                val_split=float(self.train_val_split.get()),
            )
        self.status_var.set(f"Trained model on {stats.examples} pair(s); loss={stats.loss:.4f}")
        self.metric_ndcg.set(f"NDCG@10: {metrics.ndcg_at_10:.4f}")
        self.metric_mrr.set(f"MRR: {metrics.mrr:.4f}")
        self._last_checkpoint = ck

    def _export_checkpoint(self) -> None:
        try:
            ck = getattr(self, "_last_checkpoint", None)
            if not ck:
                # try reading from memory
                with OsintMemory(self.memory_db_var.get().strip() or ".osint_memory.sqlite3") as memory:
                    state = memory.get_model_state()
                    if not state:
                        messagebox.showinfo("OSINT Agent", "No trained model available to export.")
                        return
                    payload = json.loads(state.payload_json)
                    ck = payload.get("checkpoint")
            if not ck or not Path(ck).exists():
                messagebox.showinfo("OSINT Agent", "No checkpoint file found to export.")
                return
            path = filedialog.asksaveasfilename(defaultextension=".pt", filetypes=[("PyTorch checkpoint", "*.pt"), ("All files", "*")])
            if not path:
                return
            with open(ck, "rb") as rf, open(path, "wb") as wf:
                wf.write(rf.read())
            messagebox.showinfo("OSINT Agent", f"Exported checkpoint to {path}")
        except Exception as exc:
            messagebox.showerror("OSINT Agent", str(exc))

    def _show_error(self, exc: Exception) -> None:
        self.status_var.set("Failed")
        messagebox.showerror("OSINT Agent", str(exc))

    def _run_legion(self) -> None:
        subjects = [s.strip() for s in self.legion_subjects_var.get().split(",") if s.strip()]
        if not subjects:
            messagebox.showerror("OSINT Agent", "Enter at least one subject for PHANTOM_LEGION.")
            return
        self.status_var.set("Dispatching PHANTOM_LEGION...")
        self.legion_preview.delete("1.0", tk.END)
        thread = threading.Thread(target=self._run_legion_worker, args=(subjects,), daemon=True)
        thread.start()

    def _run_legion_worker(self, subjects: list[str]) -> None:
        try:
            legion = PhantomLegion(max_workers=min(8, max(1, int(self.legion_num_agents.get()))))
            coordinator_url = self.legion_coordinator_url.get().strip()
            worker_urls = [u.strip() for u in self.legion_worker_urls.get().split(",") if u.strip()]
            targets = [t.strip() for t in self.legion_targets.get().split(",") if t.strip()]
            if coordinator_url:
                results = legion.dispatch_cluster(subjects, coordinator_url, token=self.legion_token.get().strip() or "phantom", memory_db=self.memory_db_var.get().strip() or ".osint_memory.sqlite3", track_trails=self.track_target_var.get())
            elif worker_urls:
                results = legion.dispatch_workers(subjects, worker_urls, num_agents=int(self.legion_num_agents.get()), mode=self.legion_mode.get(), memory_db=self.memory_db_var.get().strip() or ".osint_memory.sqlite3", track_trails=self.track_target_var.get())
            elif targets:
                results = legion.dispatch_remote(subjects, targets, ssh_user=None, remote_cmd=self.legion_remote_cmd.get().strip() or None)
            else:
                results = legion.dispatch(subjects, num_agents=int(self.legion_num_agents.get()), mode=self.legion_mode.get(), memory_db=self.memory_db_var.get().strip() or ".osint_memory.sqlite3", track_trails=self.track_target_var.get())
            # display merged reports
            self._last_legion_results = results
            self.after(0, self._populate_legion_view, results)
            self.status_var.set("PHANTOM_LEGION complete")
        except Exception as exc:
            self.after(0, self._show_error, exc)

    def _populate_legion_view(self, results: list) -> None:
        self.legion_tree.delete(*self.legion_tree.get_children())
        self.legion_preview.delete("1.0", tk.END)
        for res in results:
            parent = self.legion_tree.insert("", "end", text=f"{res.subject}", values=("", "", "", "", "", ""))
            for item in getattr(res, "merged_sources", []) or []:
                kinds = ", ".join(item.get("kinds", [])) if isinstance(item, dict) else ""
                titles = item.get("titles", []) if isinstance(item, dict) else []
                title = titles[0] if titles else ""
                score = item.get("weight", item.get("avg_score", 0.0)) if isinstance(item, dict) else ""
                freq = item.get("freq", 0) if isinstance(item, dict) else 0
                url = item.get("url", "") if isinstance(item, dict) else ""
                path_conf = item.get("avg_path_confidence", 0.0) if isinstance(item, dict) else 0.0
                drift = item.get("avg_drift_score", 0.0) if isinstance(item, dict) else 0.0
                node = self.legion_tree.insert(parent, "end", text=url, values=(f"{float(score):.2f}" if score != "" else "", f"{float(path_conf):.1f}", f"{float(drift):.1f}", str(freq), kinds, title))
                self.legion_tree.set(node, "score", f"{float(score):.2f}" if score != "" else "")
        if results:
            first = results[0]
            self.legion_preview.insert(tk.END, first.merged_report)

    def _on_legion_select(self, event) -> None:
        selection = self.legion_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        text = self.legion_tree.item(item_id, "text")
        values = self.legion_tree.item(item_id, "values")
        self.legion_preview.delete("1.0", tk.END)
        self.legion_preview.insert(tk.END, f"{text}\n\n{values}")

    def _export_legion_report(self) -> None:
        results = getattr(self, "_last_legion_results", None)
        if not results:
            messagebox.showinfo("OSINT Agent", "Run PHANTOM_LEGION first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown", "*.md"), ("All files", "*")])
        if not path:
            return
        merged = []
        for res in results:
            merged.append(f"# {res.subject}\n\n{res.merged_report}")
        Path(path).write_text("\n\n---\n\n".join(merged), encoding="utf-8")
        messagebox.showinfo("OSINT Agent", f"Exported legion report to {path}")

    def _export_legion_maltego(self) -> None:
        results = getattr(self, "_last_legion_results", None)
        if not results:
            messagebox.showinfo("OSINT Agent", "Run PHANTOM_LEGION first.")
            return
        project_root = Path(__file__).resolve().parents[2]
        output_path = project_root / "reports" / "maltego" / f"phantom_{results[0].subject.replace(' ', '_')}.csv"
        rows = legion_results_to_maltego_rows(results)
        write_maltego_csv(output_path, rows)
        messagebox.showinfo("OSINT Agent", f"Exported Maltego CSV to {output_path}")


def _split_domains(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    OsintApp().mainloop()