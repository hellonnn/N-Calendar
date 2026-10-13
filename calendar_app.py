#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日历 · 小窗口应用
可选参数：
  --data PATH    指定数据文件（默认 ~/.local/share/local-calendar/calendar.json）
  --port N       内部服务端口（默认 8765，被占用就顺延）
  --size WxH     初始窗口尺寸（默认 430x760）
  --browser      不用窗口，直接在浏览器里打开（等同 calendar.sh）
"""
import argparse
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ID = "org.local.Calendar"
PRGNAME = "calendar"

# 没有 GPU 直通设备时（虚拟机 / 远程桌面 / 容器）关掉 WebKit 的加速合成，
# 否则 Web 进程可能起不来、界面一直白屏。必须在创建 WebView 之前设置。
if not os.path.exists("/dev/dri"):
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")


def _ensure_writable_data_home():
    """XDG 数据目录不可写时（只读挂载 / 受限容器），WebKit 的 Web 进程会起不来、
    界面一直空白。这里提前把它指到临时目录，保证窗口始终能用（须在导入 GTK 之前）。"""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    try:
        os.makedirs(base, exist_ok=True)
        probe = os.path.join(base, ".local-calendar-write-test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return
    except OSError:
        pass
    import tempfile
    fallback = tempfile.mkdtemp(prefix="local-calendar-xdg-")
    os.environ["XDG_DATA_HOME"] = fallback
    sys.stderr.write("提示：%s 不可写，本次运行改用 %s\n" % (base, fallback))


_ensure_writable_data_home()


def fallback_to_browser(reason):
    """没有 GTK/WebKit 时退回浏览器模式，保证还能用。"""
    sys.stderr.write("提示：%s，改用浏览器打开。\n" % reason)
    os.execv("/bin/bash", ["bash", os.path.join(HERE, "calendar.sh")])


# --------------------------------------------------------------- 依赖检查
try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.0")
    from gi.repository import Gtk, Gdk, GLib, Gio, WebKit2
except Exception as e:                                    # pragma: no cover
    fallback_to_browser("缺少 GTK/WebKit 组件（%s）" % e)

import serve  # noqa: E402  同目录的微型服务

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"),
    "local-calendar")
GEOM_FILE = os.path.join(CONFIG_DIR, "window.json")


def load_geometry():
    import json
    try:
        with open(GEOM_FILE, encoding="utf-8") as f:
            d = json.load(f)
        w, h = int(d.get("width", 0)), int(d.get("height", 0))
        if 320 <= w <= 4000 and 360 <= h <= 4000:
            return w, h, d.get("x"), d.get("y")
    except Exception:
        pass
    return None


def save_geometry(win):
    import json
    if win.is_maximized():
        return          # 最大化时不覆盖上次的普通尺寸
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        x, y = win.get_position()
        w, h = win.get_size()
        with open(GEOM_FILE, "w", encoding="utf-8") as f:
            json.dump({"width": w, "height": h, "x": x, "y": y}, f)
    except Exception:
        pass


class CalendarApp(Gtk.Application):
    def __init__(self, opts):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.opts = opts
        self.win = None
        self.webview = None
        self.httpd = None
        self.port = None
        self.loaded = False

    # ---------- 内部服务 ----------
    def start_backend(self):
        self.port = serve.find_free_port(self.opts.port)
        self.httpd = serve.start_server(HERE, self.port, self.opts.data)
        t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        t.start()

    # ---------- 窗口 ----------
    def do_activate(self):
        if self.win is not None:
            self.win.present()
            return
        self.start_backend()
        self.build_window()
        self.win.show_all()

    def build_window(self):
        geo = load_geometry()
        self.win = Gtk.ApplicationWindow(application=self, title="日历")
        self.win.set_wmclass(PRGNAME, PRGNAME)
        self.win.set_default_size(*self.opts.size if not geo else geo[:2])
        self.win.set_size_request(330, 420)
        if geo and geo[2] is not None and geo[3] is not None:
            self.win.move(geo[2], geo[3])
        try:
            self.win.set_icon_from_file(os.path.join(HERE, "icon.svg"))
        except Exception:
            pass

        # 深色标题栏跟随系统主题
        try:
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme",
                                                    Gtk.Settings.get_default().get_property("gtk-application-prefer-dark-theme"))
        except Exception:
            pass

        # ---- WebKit ----
        data_dir = os.path.join(
            os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
            "local-calendar", "webkit")
        base_data = os.path.join(data_dir, "data")
        base_cache = os.path.join(data_dir, "cache")
        try:
            os.makedirs(base_data, exist_ok=True)
            os.makedirs(base_cache, exist_ok=True)
        except OSError:
            # 家目录不可写时（只读挂载 / 受限容器）退到临时目录，但必须保证目录真的存在，
            # 否则 WebKit 的 Web 进程起不来，界面会一直空白
            import tempfile
            base_data = tempfile.mkdtemp(prefix="local-calendar-webdata-")
            base_cache = tempfile.mkdtemp(prefix="local-calendar-webcache-")
            sys.stderr.write("提示：%s 不可写，改用 %s\n" % (data_dir, base_data))
        manager = WebKit2.WebsiteDataManager(
            base_data_directory=base_data,
            base_cache_directory=base_cache,
        )
        try:
            ctx = WebKit2.WebContext.new_with_website_data_manager(manager)
        except Exception:
            try:
                ctx = WebKit2.WebContext(website_data_manager=manager)
            except Exception:
                ctx = WebKit2.WebContext.get_default()
        ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)

        self.webview = WebKit2.WebView.new_with_context(ctx)
        s = self.webview.get_settings()
        for prop, val in (("enable_page_cache", True),
                          ("enable_smooth_scrolling", True),
                          ("enable_developer_extras", False),
                          ("enable_plugins", False),
                          ("enable_webgl", False),
                          ("allow_universal_access_from_file_urls", False)):
            try:
                s.set_property(prop, val)
            except Exception:
                pass
        self.webview.set_background_color(Gdk.RGBA(0.96, 0.965, 0.976, 1))
        self.webview.connect("context-menu", lambda *_: True)   # 屏蔽右键菜单，更像原生应用
        self.webview.connect("decide-policy", self.on_decide_policy)
        self.webview.connect("load-changed", self.on_load_changed)
        self.webview.connect("load-failed", self.on_load_failed)
        uri = "http://127.0.0.1:%d/" % self.port
        if self.opts.view:
            uri += "?view=" + self.opts.view
        self.webview.load_uri(uri)

        self.win.add(self.webview)
        self.win.connect("delete-event", self.on_delete)
        self.win.connect("key-press-event", self.on_key)
        GLib.timeout_add_seconds(8, self.watchdog)
        if self.opts.screenshot:
            GLib.timeout_add_seconds(30, self.screenshot_timeout)

    def on_delete(self, *args):
        save_geometry(self.win)
        if self.httpd:
            self.httpd.shutdown()
        return False

    def on_load_changed(self, view, event):
        if event == WebKit2.LoadEvent.FINISHED:
            self.loaded = True
            if self.opts.screenshot:
                GLib.timeout_add(1500, self.grab)

    def on_load_failed(self, view, event, uri, error):
        msg = error.message if error else "未知错误"
        sys.stderr.write("页面加载失败：%s（%s）\n" % (msg, uri))
        self.show_problem("页面加载失败", msg)
        if self.opts.screenshot:
            self.cleanup_and_quit(1)
        return True

    def show_problem(self, title, detail):
        """加载不出来时给出可读的提示，而不是白屏"""
        html = (
            "<html><head><meta charset='utf-8'></head>"
            "<body style=\"font:14px/1.7 system-ui,'Noto Sans CJK SC',sans-serif;"
            "padding:28px;color:#333;background:#fafbfd\">"
            "<h2 style='margin:0 0 10px;color:#d92d20'>%s</h2>"
            "<p>%s</p>"
            "<p style='color:#666'>可尝试：重新打开本应用；或用浏览器访问 "
            "<a href='http://127.0.0.1:%d/'>http://127.0.0.1:%d/</a> 查看界面。</p>"
            "<p style='color:#666'>数据文件不受影响：%s</p>"
            "</body></html>" % (title, detail, self.port, self.port, self.opts.data)
        )
        self.webview.load_html(html, "http://127.0.0.1:%d/__error" % self.port)

    def watchdog(self):
        """超时兜底：8 秒还没加载完就提示，避免白屏无响应"""
        if not self.loaded:
            self.show_problem("界面加载超时", "本地服务可能没有正常启动。")
        return False

    def cleanup_and_quit(self, code=0):
        if self.httpd:
            self.httpd.shutdown()
        self.quit()
        return False

    def screenshot_timeout(self):
        print("截图超时：页面未在 30 秒内加载完成", flush=True)
        return self.cleanup_and_quit(1)

    def grab(self):
        try:
            self.win.present()
            gwin = self.win.get_window()
            if gwin is not None:
                w, h = gwin.get_width(), gwin.get_height()
                pb = Gdk.pixbuf_get_from_window(gwin, 0, 0, w, h)
                if pb is not None:
                    pb.savev(self.opts.screenshot, "png", [], [])
                    print("已保存窗口截图：%s (%dx%d)" % (self.opts.screenshot, w, h), flush=True)
                else:
                    print("截图失败：拿不到窗口像素（可能未映射）", flush=True)
        except Exception as e:
            print("截图失败：%s" % e, flush=True)
        finally:
            if self.httpd:
                self.httpd.shutdown()
            self.quit()
        return False

    def on_decide_policy(self, view, decision, dtype):
        # 内部页面之外的链接交给系统浏览器，别把窗口带走
        if dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_request().get_uri() or ""
            if uri.startswith("http") and not uri.startswith("http://127.0.0.1:%d" % self.port):
                decision.ignore()
                Gio.AppInfo.launch_default_for_uri(uri, None)
                return True
        return False

    def on_key(self, win, event):
        key = Gdk.keyval_name(event.keyval) or ""
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and key.lower() in ("q", "w"):
            save_geometry(self.win)
            if self.httpd:
                self.httpd.shutdown()
            self.quit()
            return True
        if ctrl and key.lower() == "r" and self.webview:
            self.webview.reload()
            return True
        if ctrl and key in ("plus", "equal", "KP_Add") and self.webview:
            self.webview.set_zoom_level(min(3.0, self.webview.get_zoom_level() + 0.1))
            return True
        if ctrl and key in ("minus", "KP_Subtract") and self.webview:
            self.webview.set_zoom_level(max(0.6, self.webview.get_zoom_level() - 0.1))
            return True
        if ctrl and key == "0" and self.webview:
            self.webview.set_zoom_level(1.0)
            return True
        if key == "F11":
            if self.win.is_maximized():
                self.win.unmaximize()
            else:
                self.win.maximize()
            return True
        return False


def main():
    ap = argparse.ArgumentParser(description="日历小窗口应用")
    ap.add_argument("--data", default=serve.default_data_file())
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--size", default="430x760")
    ap.add_argument("--browser", action="store_true", help="改用浏览器打开")
    ap.add_argument("--view", default="", choices=["", "day", "week", "month"],
                    help="启动时直接进入某个视图")
    ap.add_argument("--screenshot", default="", help="（开发用）截图窗口到指定 PNG 后退出")
    args = ap.parse_args()

    if args.browser:
        fallback_to_browser("指定了 --browser")

    try:
        w, h = (int(x) for x in args.size.lower().split("x"))
        args.size = (w, h)
    except Exception:
        args.size = (430, 760)

    GLib.set_prgname(PRGNAME)
    GLib.set_application_name("日历")
    app = CalendarApp(args)
    try:
        app.run([])
    except KeyboardInterrupt:
        if app.httpd:
            app.httpd.shutdown()


if __name__ == "__main__":
    main()
