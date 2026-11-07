"""连续计时器 - 服务控制台（GUI）

用法：python gui_console.py
功能：启动/停止本地 HTTP 服务，查看正在使用服务的客户端。
"""
import socket
import threading
import time
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def lan_ip():
    """获取本机局域网 IP（不实际发包）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class ClientTracker:
    """线程安全地记录客户端访问情况"""

    def __init__(self):
        self._lock = threading.Lock()
        self.clients = {}   # ip -> {count, first_seen, last_seen, user_agent}
        self.events = []    # 未被 GUI 取走的请求日志 (time, ip, method, path, code)

    def record(self, ip, method, path, code, user_agent):
        now = time.time()
        with self._lock:
            c = self.clients.setdefault(
                ip, {"count": 0, "first_seen": now, "last_seen": now, "user_agent": ""}
            )
            c["count"] += 1
            c["last_seen"] = now
            if user_agent:
                c["user_agent"] = user_agent
            self.events.append((now, ip, method, path, code))

    def snapshot(self):
        """返回 (clients 副本, 新事件列表) 并清空事件队列"""
        with self._lock:
            clients = {ip: dict(c) for ip, c in self.clients.items()}
            events, self.events = self.events, []
        return clients, events

    def reset(self):
        with self._lock:
            self.clients.clear()
            self.events.clear()


class TrackingHandler(SimpleHTTPRequestHandler):
    """记录每个请求的处理器；tracker 由服务注入"""

    tracker = None

    def log_message(self, fmt, *args):
        pass  # 不在控制台输出

    def log_request(self, code="-", size="-"):
        if self.tracker is not None:
            try:
                code = getattr(code, "value", code)
                self.tracker.record(
                    self.client_address[0],
                    self.command or "-",
                    self.path or "-",
                    code,
                    self.headers.get("User-Agent", "") if self.headers else "",
                )
            except Exception:
                pass


class TimerService:
    """可启动/停止的计时器 HTTP 服务"""

    def __init__(self):
        self.tracker = ClientTracker()
        self._server = None
        self._thread = None

    @property
    def running(self):
        return self._server is not None

    def start(self, port):
        if self.running:
            raise RuntimeError("服务已在运行")
        handler = partial(TrackingHandler, directory=str(ROOT))
        TrackingHandler.tracker = self.tracker
        self._server = ThreadingHTTPServer(("0.0.0.0", port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.running:
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        self._server = None
        self._thread = None


def fmt_time(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


class ConsoleApp:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk, messagebox

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.service = TimerService()

        self.root = tk.Tk()
        self.root.title("连续计时器 - 服务控制台")
        self.root.geometry("760x520")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ── 顶部：端口 + 启动/停止 + 状态 ──
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="端口:").pack(side="left")
        self.port_var = tk.StringVar(value="8080")
        self.port_entry = ttk.Entry(top, textvariable=self.port_var, width=7)
        self.port_entry.pack(side="left", padx=(4, 12))
        self.start_btn = ttk.Button(top, text="▶ 启动服务", command=self.start_service)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(top, text="■ 停止服务", command=self.stop_service, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.clear_btn = ttk.Button(top, text="清空记录", command=self.clear_records)
        self.clear_btn.pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="状态：⬤ 已停止")
        status = ttk.Frame(self.root, padding=(10, 0))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_var, foreground="#555").pack(side="left")
        self.url_var = tk.StringVar(value="")
        self.url_label = ttk.Label(status, textvariable=self.url_var, foreground="#0a64c8")
        self.url_label.pack(side="left", padx=10)

        # ── 中部：客户端列表 ──
        mid = ttk.LabelFrame(self.root, text="客户端", padding=6)
        mid.pack(fill="both", expand=True, padx=10, pady=(8, 4))
        cols = ("ip", "count", "first", "last", "ua")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=8)
        for cid, text, w, anchor in (
            ("ip", "IP 地址", 130, "w"),
            ("count", "请求数", 60, "center"),
            ("first", "首次访问", 80, "center"),
            ("last", "最后访问", 80, "center"),
            ("ua", "User-Agent", 330, "w"),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=w, anchor=anchor)
        tree_scroll = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # ── 底部：请求日志 ──
        bottom = ttk.LabelFrame(self.root, text="请求日志", padding=6)
        bottom.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.log = tk.Text(bottom, height=8, state="disabled", font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(bottom, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.root.after(500, self.poll)

    # ── 操作 ──
    def start_service(self):
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.messagebox.showerror("错误", "端口必须是 1-65535 的数字")
            return
        try:
            self.service.start(port)
        except OSError as e:
            self.messagebox.showerror("启动失败", f"无法监听端口 {port}：\n{e}")
            return
        self.status_var.set("状态：🟢 运行中")
        self.url_var.set(f"本机 http://localhost:{port}   局域网 http://{lan_ip()}:{port}")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.port_entry.config(state="disabled")
        self.append_log(f"[{fmt_time(time.time())}] 服务已启动，端口 {port}")

    def stop_service(self):
        self.service.stop()
        self.status_var.set("状态：⬤ 已停止")
        self.url_var.set("")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.port_entry.config(state="normal")
        self.append_log(f"[{fmt_time(time.time())}] 服务已停止")

    def clear_records(self):
        self.service.tracker.reset()
        self.tree.delete(*self.tree.get_children())
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def append_log(self, line):
        self.log.config(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    # ── 定时刷新 ──
    def poll(self):
        clients, events = self.service.tracker.snapshot()
        for ts, ip, method, path, code in events:
            self.append_log(f"[{fmt_time(ts)}] {ip}  {method} {path}  → {code}")
        existing = {self.tree.set(item, "ip"): item for item in self.tree.get_children()}
        for ip, c in sorted(clients.items(), key=lambda kv: -kv[1]["last_seen"]):
            values = (ip, c["count"], fmt_time(c["first_seen"]), fmt_time(c["last_seen"]), c["user_agent"])
            if ip in existing:
                self.tree.item(existing[ip], values=values)
            else:
                self.tree.insert("", "end", values=values)
        self.root.after(500, self.poll)

    def on_close(self):
        self.service.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    ConsoleApp().run()
