from __future__ import annotations

import socket
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
import webbrowser


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "smj_batch_full"
DEFAULT_ARTIFACT = OUT_DIR / "frontend_artifact_classA.json"
DEFAULT_VIEWS = OUT_DIR / "graph_views.json"
DEFAULT_FRONTEND_DIR = ROOT / "frontend" / "graph_3d"


def _find_free_port(start: int = 8013, end: int = 8100) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free port in range 8013-8100")


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SMJ Graph Desktop Launcher")
        self.root.geometry("780x520")
        self.server_proc: subprocess.Popen[str] | None = None
        self.selected_artifact = DEFAULT_ARTIFACT

        title = tk.Label(root, text="SMJ 图谱桌面启动�?, font=("Microsoft YaHei", 15, "bold"))
        title.pack(anchor="w", padx=12, pady=(12, 6))

        hint = tk.Label(root, text="流程: 1) 导入文件解析 �?导入PostgreSQL 2) 打开展示", fg="#334")
        hint.pack(anchor="w", padx=12, pady=(0, 8))

        btn_wrap = tk.Frame(root)
        btn_wrap.pack(anchor="w", padx=12, pady=4)

        self.btn_file = tk.Button(btn_wrap, text="导入文件并解�?, width=18, command=self.import_file)
        self.btn_file.grid(row=0, column=0, padx=(0, 8))

        self.btn_db = tk.Button(btn_wrap, text="导入 PostgreSQL", width=18, command=self.import_postgres)
        self.btn_db.grid(row=0, column=1, padx=(0, 8))

        self.btn_open = tk.Button(btn_wrap, text="打开展示", width=18, command=self.open_graph)
        self.btn_open.grid(row=0, column=2)

        path_wrap = tk.Frame(root)
        path_wrap.pack(fill="x", padx=12, pady=8)
        tk.Label(path_wrap, text="当前 artifact:").pack(side="left")
        self.path_var = tk.StringVar(value=str(self.selected_artifact))
        tk.Entry(path_wrap, textvariable=self.path_var).pack(side="left", fill="x", expand=True, padx=(8, 0))

        log_frame = tk.Frame(root)
        log_frame.pack(fill="both", expand=True, padx=12, pady=8)
        tk.Label(log_frame, text="日志").pack(anchor="w")
        self.log = tk.Text(log_frame, height=20, wrap="word")
        self.log.pack(fill="both", expand=True, pady=(4, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _append(self, msg: str) -> None:
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _run_cmd(self, cmd: list[str], done_msg: str) -> None:
        def worker() -> None:
            self._append(">>> " + " ".join(cmd))
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.stdout:
                    self._append(proc.stdout.strip())
                if proc.stderr:
                    self._append(proc.stderr.strip())
                if proc.returncode != 0:
                    raise RuntimeError(f"Command failed ({proc.returncode})")
                self._append(done_msg)
            except Exception as exc:
                self._append(f"ERROR: {exc}")
                messagebox.showerror("执行失败", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def import_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 frontend artifact JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(OUT_DIR),
        )
        if not selected:
            return
        self.selected_artifact = Path(selected)
        self.path_var.set(str(self.selected_artifact))
        cmd = [
            "uv",
            "run",
            "python",
            "scripts/smj_pipeline/build_graph_views.py",
            "--input-json",
            str(self.selected_artifact),
            "--output-json",
            str(DEFAULT_VIEWS),
        ]
        self._run_cmd(cmd, "文件解析完成: graph_views.json 已更�?)

    def import_postgres(self) -> None:
        dsn = simpledialog.askstring(
            "PostgreSQL DSN",
            "输入 DSN，例�? postgresql://user:pass@127.0.0.1:5432/dbname",
        )
        if not dsn:
            return
        output_json = OUT_DIR / "frontend_artifact_from_postgres.json"
        cmd = [
            "uv",
            "run",
            "python",
            "scripts/smj_pipeline/export_frontend_artifact_from_postgres.py",
            "--dsn",
            dsn,
            "--output-json",
            str(output_json),
        ]
        self.selected_artifact = output_json
        self.path_var.set(str(self.selected_artifact))

        def chain() -> None:
            self._append(">>> " + " ".join(cmd))
            proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
            if proc.stdout:
                self._append(proc.stdout.strip())
            if proc.stderr:
                self._append(proc.stderr.strip())
            if proc.returncode != 0:
                messagebox.showerror("导入失败", "PostgreSQL 导入失败，请查看日志�?)
                return
            cmd2 = [
                "uv",
                "run",
                "python",
                "scripts/smj_pipeline/build_graph_views.py",
                "--input-json",
                str(output_json),
                "--output-json",
                str(DEFAULT_VIEWS),
            ]
            self._append(">>> " + " ".join(cmd2))
            proc2 = subprocess.run(cmd2, cwd=str(ROOT), capture_output=True, text=True, check=False)
            if proc2.stdout:
                self._append(proc2.stdout.strip())
            if proc2.stderr:
                self._append(proc2.stderr.strip())
            if proc2.returncode != 0:
                messagebox.showerror("构建失败", "graph_views 构建失败，请查看日志�?)
                return
            self._append("PostgreSQL 导入并构建完�?)

        threading.Thread(target=chain, daemon=True).start()

    def open_graph(self) -> None:
        if self.server_proc and self.server_proc.poll() is None:
            self._append("服务已在运行，直接打开浏览�?)
            port = int(self.server_proc.args[self.server_proc.args.index("--port") + 1])  # type: ignore[index]
            webbrowser.open(f"http://127.0.0.1:{port}/healthz")
            return

        if not DEFAULT_VIEWS.exists():
            messagebox.showwarning("缺少数据", "未找�?graph_views.json，请先导入文件或数据库�?)
            return

        port = _find_free_port()
        cmd = [
            "uv",
            "run",
            "python",
            "scripts/smj_pipeline/serve_graph_api.py",
            "--frontend-dir",
            str(DEFAULT_FRONTEND_DIR),
            "--port",
            str(port),
        ]
        self._append(">>> " + " ".join(cmd))
        self.server_proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self._append(f"图谱服务已启�? http://127.0.0.1:{port}/healthz")
        webbrowser.open(f"http://127.0.0.1:{port}/healthz")

    def on_close(self) -> None:
        if self.server_proc and self.server_proc.poll() is None:
            self.server_proc.terminate()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = App(root)
    app._append("启动完成�?)
    app._append("建议先执�? 导入文件并解�?)
    root.mainloop()


if __name__ == "__main__":
    main()


