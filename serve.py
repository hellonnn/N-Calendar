#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地日历的后台服务（同一份代码同时供「小窗口应用」和「浏览器版」使用）

  · 只监听 127.0.0.1，外部网络无法访问
  · 提供本目录内的静态页面，禁用缓存
  · 事项保存在本地 JSON 文件里（默认 ~/.local/share/local-calendar/calendar.json）

"""
import argparse
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time

MAX_BODY = 8 * 1024 * 1024
MAX_EVENTS = 20000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KNOWN_FIELDS = ("id", "title", "date", "start", "end", "allDay", "color", "note", "done", "repeat", "until", "skip")


# ----------------------------------------------------------------- 数据文件
def default_data_file():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "local-calendar", "calendar.json")


def sanitize_event(raw):
    """只保留已知字段并做基本类型校正，避免坏数据把界面搞崩。"""
    if not isinstance(raw, dict):
        return None
    ev = {}
    for k in KNOWN_FIELDS:
        if k in raw:
            ev[k] = raw[k]
    date = ev.get("date")
    if not isinstance(date, str) or not DATE_RE.match(date):
        return None
    ev["date"] = date
    ev["title"] = str(ev.get("title") or "未命名事项")[:500]
    ev["note"] = str(ev.get("note") or "")[:5000]
    for k in ("start", "end", "until"):
        v = ev.get(k)
        ev[k] = str(v)[:5] if isinstance(v, str) and re.match(r"^\d{1,2}:\d{2}", v) else (str(v)[:10] if k == "until" and isinstance(v, str) else "")
    ev["allDay"] = bool(ev.get("allDay"))
    ev["done"] = bool(ev.get("done"))
    ev["repeat"] = ev.get("repeat") if ev.get("repeat") in ("daily", "weekly", "monthly") else "none"
    ev["color"] = ev.get("color") if isinstance(ev.get("color"), str) else "indigo"
    ev["id"] = str(ev.get("id") or "")[:64]
    skip = ev.get("skip")
    ev["skip"] = [s for s in skip if isinstance(s, str) and DATE_RE.match(s)][:400] if isinstance(skip, list) else []
    return ev


def read_data(path):
    doc = {"version": 1, "updatedAt": 0, "events": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return doc
    except Exception:
        return doc
    events = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(events, list):
        return doc
    doc["events"] = [e for e in (sanitize_event(x) for x in events[:MAX_EVENTS]) if e]
    if isinstance(raw, dict) and raw.get("updatedAt"):
        doc["updatedAt"] = int(raw["updatedAt"])
    elif os.path.exists(path):
        doc["updatedAt"] = int(os.path.getmtime(path) * 1000)
    return doc


def write_data(path, events, updated_at=None):
    """原子写入（落盘的内容一定是清洗过的），并保留上一版为 .bak"""
    events = [e for e in (sanitize_event(x) for x in (events or [])[:MAX_EVENTS]) if e]
    doc = {
        "version": 1,
        "app": "local-calendar",
        "updatedAt": int(updated_at or time.time() * 1000),
        "events": events,
    }
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as src, open(path + ".bak", "w", encoding="utf-8") as dst:
                dst.write(src.read())
        except OSError:
            pass
    os.replace(tmp, path)
    return doc


# ----------------------------------------------------------------- HTTP 处理
class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "LocalCalendar/1.1"
    protocol_version = "HTTP/1.1"
    DATA_FILE = ""
    PORT = 0
    write_lock = threading.Lock()

    # ---------- 工具 ----------
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _same_origin_ok(self):
        """POST 只接受来自本机页面的请求。"""
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not origin:
            return True
        return ("//127.0.0.1:%d" % self.PORT) in origin or ("//localhost:%d" % self.PORT) in origin

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 保持终端安静

    # ---------- 路由 ----------
    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/__alive":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/load":
            doc = read_data(self.DATA_FILE)
            doc["dataFile"] = self.DATA_FILE
            self._json(doc)
            return
        if route == "/api/info":
            self._json({"dataFile": self.DATA_FILE, "port": self.PORT, "app": "local-calendar"})
            return
        return super().do_GET()

    def do_POST(self):
        route = self.path.split("?")[0]
        if route != "/api/save":
            self._json({"ok": False, "error": "未知接口"}, 404)
            return
        if not self._same_origin_ok():
            self._json({"ok": False, "error": "来源不允许"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json({"ok": False, "error": "数据长度不合法"}, 413)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._json({"ok": False, "error": "JSON 解析失败：%s" % e}, 400)
            return
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            self._json({"ok": False, "error": "缺少 events 列表"}, 400)
            return
        clean = [e for e in (sanitize_event(x) for x in events[:MAX_EVENTS]) if e]
        try:
            with Handler.write_lock:
                doc = write_data(self.DATA_FILE, clean, payload.get("updatedAt") if isinstance(payload, dict) else None)
        except Exception as e:
            self._json({"ok": False, "error": "写入失败：%s" % e}, 500)
            return
        self._json({"ok": True, "count": len(clean), "updatedAt": doc["updatedAt"]})


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ----------------------------------------------------------------- 对外接口
def make_handler(directory, data_file, port):
    class Bound(Handler):
        DATA_FILE = data_file
        PORT = port
    return functools.partial(Bound, directory=directory)


def find_free_port(preferred, host="127.0.0.1", span=40):
    import socket
    for port in range(preferred, preferred + span):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            s.close()
            continue
        s.close()
        return port
    raise OSError("找不到可用端口")


def start_server(directory, port=8765, data_file=None, host="127.0.0.1"):
    """创建并返回一个尚未 serve_forever 的服务器（供窗口应用内嵌使用）。"""
    data_file = data_file or default_data_file()
    handler = make_handler(directory, data_file, port)
    return Server((host, port), handler)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="本地日历服务")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--dir", default=here)
    ap.add_argument("--data", default=default_data_file(), help="事项数据文件（JSON）")
    ap.add_argument("--pidfile", default="")
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(args.dir, "index.html")):
        sys.exit("错误：%s 下找不到 index.html" % args.dir)

    try:
        httpd = start_server(args.dir, args.port, args.data, args.host)
    except OSError as e:
        sys.exit("错误：无法监听 %s:%d（%s）" % (args.host, args.port, e))

    if args.pidfile:
        try:
            with open(args.pidfile, "w") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass

    print("本地日历已启动： http://%s:%d/" % (args.host, args.port), flush=True)
    print("数据文件：%s" % args.data, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if args.pidfile:
            try:
                with open(args.pidfile) as f:
                    mine = f.read().strip() == str(os.getpid())
                if mine:
                    os.remove(args.pidfile)
            except OSError:
                pass


if __name__ == "__main__":
    main()
