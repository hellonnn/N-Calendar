#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
KNOWN_FIELDS = ("id", "title", "date", "start", "end", "allDay", "color", "note", "done", "repeat", "until", "skip",
                "tags", "priority", "due", "skipRest")


# ----------------------------------------------------------------- 数据文件
def default_data_file():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "local-calendar", "calendar-1.0.json")


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
    # 标签：去空白、去重、限制数量与长度
    tags = ev.get("tags")
    if isinstance(tags, list):
        seen, clean = set(), []
        for t in tags:
            t = str(t).strip()[:24]
            if t and t not in seen:
                seen.add(t); clean.append(t)
        ev["tags"] = clean[:8]
    else:
        ev["tags"] = []
    # 优先级 0=无 1=低 2=中 3=高
    try:
        ev["priority"] = max(0, min(3, int(ev.get("priority") or 0)))
    except (TypeError, ValueError):
        ev["priority"] = 0
    # 截止日（可覆盖事项日期）
    due = ev.get("due")
    ev["due"] = due if isinstance(due, str) and DATE_RE.match(due) else ""
    # 重复时是否跳过周末与法定假日
    ev["skipRest"] = bool(ev.get("skipRest"))
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


# ----------------------------------------------------------------- 版本历史（自动备份）
BACKUP_DIRNAME = "backups"
BACKUP_INTERVAL = 60        # 两次自动备份之间至少间隔的秒数
BACKUP_KEEP = 40            # 最多保留的备份份数
BACKUP_RE = re.compile(r"^calendar-\d{8}-\d{6}(?:-\d+)?\.json$")


def backup_dir(path):
    return os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIRNAME)


def list_backups(path):
    """按时间倒序列出备份：名称、时间戳、条目数、大小"""
    folder = backup_dir(path)
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        if not BACKUP_RE.match(name):
            continue
        full = os.path.join(folder, name)
        try:
            st = os.stat(full)
            with open(full, "r", encoding="utf-8") as f:
                doc = json.load(f)
            count = len(doc.get("events") or [])
        except Exception:
            continue
        out.append({"name": name, "mtime": int(st.st_mtime * 1000), "size": st.st_size, "count": count})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def prune_backups(path, keep=BACKUP_KEEP):
    for old in list_backups(path)[keep:]:
        try:
            os.remove(os.path.join(backup_dir(path), old["name"]))
        except OSError:
            pass


def make_backup(path, force=False):
    """把当前数据文件复制成一份带时间戳的快照（受最小间隔限制）"""
    if not os.path.exists(path):
        return None
    folder = backup_dir(path)
    os.makedirs(folder, exist_ok=True)
    if not force:
        existing = list_backups(path)
        if existing and (time.time() * 1000 - existing[0]["mtime"]) < BACKUP_INTERVAL * 1000:
            return None                                  # 间隔太短，跳过
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "calendar-%s.json" % stamp
    seq = 1
    while os.path.exists(os.path.join(folder, name)):
        name = "calendar-%s-%d.json" % (stamp, seq)
        seq += 1
    try:
        with open(path, "r", encoding="utf-8") as src, open(os.path.join(folder, name), "w", encoding="utf-8") as dst:
            dst.write(src.read())
    except OSError:
        return None
    prune_backups(path)
    return name


def restore_backup(path, name):
    """从备份恢复（会先给当前状态再存一份，避免恢复本身不可逆）"""
    if not BACKUP_RE.match(name or ""):
        raise ValueError("备份名称不合法")
    full = os.path.join(backup_dir(path), name)
    if not os.path.isfile(full):
        raise FileNotFoundError(name)
    make_backup(path, force=True)          # 恢复前先保存当前状态
    with open(full, "r", encoding="utf-8") as f:
        doc = json.load(f)
    write_data(path, doc.get("events") or [], int(time.time() * 1000))
    return read_data(path)


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
        if route == "/api/backups":
            self._json({"backups": list_backups(self.DATA_FILE), "keep": BACKUP_KEEP, "interval": BACKUP_INTERVAL})
            return
        if route == "/api/info":
            self._json({"dataFile": self.DATA_FILE, "port": self.PORT, "app": "local-calendar"})
            return
        return super().do_GET()

    def do_POST(self):
        route = self.path.split("?")[0]
        if route == "/api/backup-now":
            if not self._same_origin_ok():
                self._json({"ok": False, "error": "来源不允许"}, 403); return
            name = make_backup(self.DATA_FILE, force=True)
            self._json({"ok": bool(name), "name": name, "backups": list_backups(self.DATA_FILE)})
            return
        if route == "/api/restore":
            if not self._same_origin_ok():
                self._json({"ok": False, "error": "来源不允许"}, 403); return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception as e:
                self._json({"ok": False, "error": "请求解析失败：%s" % e}, 400); return
            try:
                with Handler.write_lock:
                    doc = restore_backup(self.DATA_FILE, (payload or {}).get("name", ""))
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400); return
            doc["dataFile"] = self.DATA_FILE
            self._json({"ok": True, "doc": doc, "backups": list_backups(self.DATA_FILE)})
            return
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
                make_backup(self.DATA_FILE)               # 覆盖前留一份快照（自动限频）
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
