#!/usr/bin/env bash
# ============================================================
#  安装「日历」桌面快捷方式（应用菜单 + 桌面图标）
#  默认启动原生小窗口应用（不需要浏览器）
#
#    ./install.sh              安装
#    ./install.sh --uninstall  卸载
# ============================================================
set -uo pipefail

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APPS="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
ENTRY="local-calendar.desktop"

say() { printf '%s\n' "$*"; }

write_entry() {
  if ! cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=日历
Name[zh_CN]=日历
Name[en]=Calendar
GenericName=日历工具
Comment=本地日历小窗口：按日 / 周 / 月安排事项
Comment[en]=Local calendar window (day / week / month)
Exec=python3 $DIR/calendar_app.py
Path=$DIR
Icon=$DIR/icon.svg
Terminal=false
Categories=Utility;Calendar;
Keywords=calendar;日历;日程;todo;
StartupNotify=true
StartupWMClass=calendar
EOF
  then
    say "错误：写入失败 $1（无权限或文件系统只读）" >&2
    return 1
  fi
  chmod +x "$1" 2>/dev/null
  return 0
}

do_install() {
  chmod +x "$DIR/calendar.sh" "$DIR/calendar_app.py" 2>/dev/null
  mkdir -p "$APPS" 2>/dev/null
  if write_entry "$APPS/$ENTRY"; then
    say "已安装到应用菜单：$APPS/$ENTRY"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null
  else
    say "提示：应用菜单安装失败，可直接运行 $DIR/calendar.sh 启动。" >&2
  fi

  if [ -d "$DESKTOP_DIR" ]; then
    if write_entry "$DESKTOP_DIR/$ENTRY"; then
      # GNOME 需要标记为「可信」才允许双击直接运行
      command -v gio >/dev/null 2>&1 && gio set "$DESKTOP_DIR/$ENTRY" metadata::trusted true 2>/dev/null
      say "已在桌面创建图标：$DESKTOP_DIR/$ENTRY"
    else
      say "提示：桌面图标创建失败，可从应用菜单启动。" >&2
    fi
  fi

  say ""
  say "完成。现在可以在「显示应用程序」里搜索「日历」，或双击桌面图标打开。"
  say "（若桌面图标显示为“不受信任”，右键选择“允许启动”即可。）"
  say "如需用浏览器打开：$DIR/calendar.sh"
}

do_uninstall() {
  rm -f "$APPS/$ENTRY" "$DESKTOP_DIR/$ENTRY"
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null
  say "已移除桌面快捷方式（日历数据与程序文件保持不变）。"
}

case "${1:-}" in
  --uninstall|-u) do_uninstall ;;
  ""|--install|-i) do_install ;;
  *) say "用法：./install.sh [--uninstall]"; exit 1 ;;
esac
