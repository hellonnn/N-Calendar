#!/usr/bin/env bash
# ============================================================
#  本地日历 1.0 · 一键启动器（Ubuntu / 任何带 Python3 的 Linux）
#
#  用法：
#    ./calendar.sh            启动服务并打开日历
#    ./calendar.sh --no-open  只启动服务（不开浏览器）
#    ./calendar.sh --stop     停止后台服务
#    ./calendar.sh --status   查看运行状态
#    ./calendar.sh --port 9000  指定端口
#    ./calendar.sh --window   改用原生小窗口（不需要浏览器）
# ============================================================
set -uo pipefail

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOST="127.0.0.1"
PORTFILE="$DIR/.port"
PIDFILE="$DIR/.server.pid"
LOGFILE="$DIR/.server.log"
DEFAULT_PORT=8766

say()  { printf '%s\n' "$*"; }
die()  { printf '错误：%s\n' "$*" >&2; exit 1; }

# ---------- 健康检查：服务是否在指定端口上响应 ----------
alive() {
  python3 - "$HOST" "$1" <<'PY' >/dev/null 2>&1
import sys, urllib.request
try:
    urllib.request.urlopen("http://%s:%s/__alive" % (sys.argv[1], sys.argv[2]), timeout=1).read()
except Exception:
    sys.exit(1)
PY
}

# ---------- 找一个可用的端口 ----------
free_port() {
  python3 - "$1" <<'PY'
import socket, sys
start = int(sys.argv[1])
for port in range(start, start + 40):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        continue
    s.close()
    print(port)
    sys.exit(0)
sys.exit(1)
PY
}

current_port() {
  local p=""
  [ -f "$PORTFILE" ] && p="$(cat "$PORTFILE" 2>/dev/null)"
  [[ "$p" =~ ^[0-9]+$ ]] || p="$DEFAULT_PORT"
  printf '%s' "$p"
}

server_pid() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s' "$pid"
}

stop_server() {
  local pid
  if pid="$(server_pid)"; then
    kill "$pid" 2>/dev/null
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
    say "已停止本地日历服务（PID $pid）"
  else
    say "本地日历服务当前未运行。"
  fi
  rm -f "$PIDFILE"
}

start_server() {
  local want="${1:-$(current_port)}" port
  command -v python3 >/dev/null 2>&1 || return 1
  if alive "$want"; then
    printf '%s' "$want"; return 0
  fi
  port="$(free_port "$want")" || die "找不到可用端口"
  # 用 setsid 让服务脱离当前终端/进程组：关闭终端后依然可用
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup python3 "$DIR/serve.py" --port "$port" --dir "$DIR" --pidfile "$PIDFILE" \
      >"$LOGFILE" 2>&1 <"/dev/null" &
  else
    nohup python3 "$DIR/serve.py" --port "$port" --dir "$DIR" --pidfile "$PIDFILE" \
      >"$LOGFILE" 2>&1 <"/dev/null" &
  fi
  printf '%s' "$port" >"$PORTFILE"

  for _ in $(seq 1 60); do
    alive "$port" && { printf '%s' "$port"; return 0; }
    sleep 0.1
  done
  rm -f "$PIDFILE"
  say "服务启动失败，日志：$LOGFILE" >&2
  [ -s "$LOGFILE" ] && tail -n 5 "$LOGFILE" >&2
  return 1
}

open_url() {
  local url="$1" b
  # Chromium 系浏览器可以用应用窗口模式，看起来更像原生程序
  for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge; do
    if command -v "$b" >/dev/null 2>&1; then
      setsid "$b" --app="$url" >/dev/null 2>&1 &
      return 0
    fi
  done
  if command -v firefox >/dev/null 2>&1; then
    setsid firefox --new-window "$url" >/dev/null 2>&1 &
    return 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    setsid xdg-open "$url" >/dev/null 2>&1 &
    return 0
  fi
  return 1
}

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ============================ 主流程 ============================
WANT_PORT=""
DO_OPEN=1
ACTION="start"
PASSTHRU=()

while [ $# -gt 0 ]; do
  case "$1" in
    --stop|-s)    ACTION="stop" ;;
    --status)     ACTION="status" ;;
    --no-open)    DO_OPEN=0 ;;
    --window|-w)  ACTION="window" ;;
    --port|-p)    shift; WANT_PORT="${1:-}" ;;
    --port=*)     WANT_PORT="${1#*=}" ;;
    -h|--help)    usage; exit 0 ;;
    *)            PASSTHRU+=("$1") ;;
  esac
  shift
done

case "$ACTION" in
  stop) stop_server; exit 0 ;;
  window)
    # 交给原生小窗口应用（内部自带服务，不需要浏览器）
    if [ -f "$DIR/calendar_app.py" ] && command -v python3 >/dev/null 2>&1; then
      exec python3 "$DIR/calendar_app.py" ${PASSTHRU[@]+"${PASSTHRU[@]}"}
    fi
    say "未找到窗口应用，改用浏览器打开。"
    ACTION="start" ;;
  status)
    if pid="$(server_pid)" && alive "$(current_port)"; then
      say "运行中： http://$HOST:$(current_port)/  (PID $pid)"
    else
      say "未运行。"
    fi
    exit 0 ;;
esac

if [ "$ACTION" != "window" ] && [ "${#PASSTHRU[@]}" -gt 0 ]; then
  die "未知参数：${PASSTHRU[*]}（用 --help 查看用法）"
fi

PORT="$(start_server "${WANT_PORT:-$(current_port)}")" || {
  # 没有 Python3 时的兜底：直接用浏览器打开本地文件（数据仍保存在本机浏览器里）
  say "未找到 python3，改用文件方式打开（部分浏览器可能限制本地存储）。"
  open_url "file://$DIR/index.html" || die "无法打开浏览器，请手动打开 $DIR/index.html"
  exit 0
}

URL="http://$HOST:$PORT/"
say "本地日历 1.0： $URL"
say "数据文件： ${XDG_DATA_HOME:-$HOME/.local/share}/local-calendar/calendar-1.0.json"
say "（数据保存在本机浏览器中，不会上传；关闭浏览器后服务仍在后台，停止请执行 ./calendar.sh --stop）"

if [ "$DO_OPEN" = "1" ]; then
  open_url "$URL" || say "请手动在浏览器中打开：$URL"
fi
