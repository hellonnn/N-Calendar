# Local Calendar · 本机小窗口应用

一个运行在**原生小窗口**中的本地日历：无需浏览器、无网络请求、无账号登录。界面基于 GTK3 + WebKit2 渲染，事项存储于本地 JSON 文件，内置**农历**与**法定节假日（含调休）**。

![窗口·月视图](preview/window-month.png)

| 窗口·日视图 | 窗口·周视图（议程） |
| :---: | :---: |
| ![日](preview/window-day.png) | ![周](preview/window-week.png) |

> 窗口拉宽后将自动切换为传统日历布局。

---

## 📑 目录

- [快速安装](#-快速安装)
- [功能特性与快捷键](#-功能特性与快捷键)
- [环境与系统适配](#-环境与系统适配)
- [农历与节假日更新](#-农历与节假日更新)
- [数据与文件说明](#-数据与文件说明)
- [自测与卸载](#-自测与卸载)

---

## 🚀 快速安装

### 1. 前置依赖
程序为纯绿色软件，满足以下环境即可运行（Ubuntu 桌面版默认满足）：
- **Python 3.7+**
- **GTK3 + WebKit2 组件** (`gir1.2-gtk-3.0`, `gir1.2-webkit2-4.0`)

Debian / Ubuntu 一键补齐依赖：
```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.0 fonts-noto-cjk
```

### 2. 一键安装（创建桌面图标与应用菜单）
```bash
cd calendar/
./install.sh
```
*注：脚本仅执行用户级操作，不需要 `sudo`。*

### 3. 免安装直接运行
```bash
python3 calendar_app.py                # 启动小窗口
python3 calendar_app.py --size 500x900 # 指定初始尺寸
python3 calendar_app.py --view day     # 指定初始视图
./calendar.sh                          # 浏览器模式运行
```

---

## ⚡ 功能特性与快捷键

### 基本操作
- **新建**：顶栏 `＋`、单击日历空白时间格，或按 <kbd>N</kbd>。
- **拖拽**：直接拖动事项调整时间（重复事项不支持拖拽）。
- **主题**：点击 `🌙` 在跟随系统、浅色、深色模式间循环。
- **视图切换**：窄窗口（<620px）自动启用紧凑布局（月视图色点、周视图议程列表）。

### 快捷键清单
| 快捷键 | 作用 |
| :--- | :--- |
| <kbd>N</kbd> / <kbd>D</kbd> / <kbd>W</kbd> / <kbd>M</kbd> / <kbd>T</kbd> | 新建 / 日 / 周 / 月 / 今天 |
| <kbd>←</kbd> / <kbd>→</kbd> | 上一 / 下一时间段 |
| <kbd>/</kbd> / <kbd>Esc</kbd> | 搜索 / 关闭弹窗与收起搜索 |
| <kbd>Ctrl</kbd> + <kbd>S</kbd> | 弹窗内保存 |
| <kbd>Ctrl</kbd> + <kbd>Q</kbd> / <kbd>W</kbd> | 关闭窗口 |
| <kbd>Ctrl</kbd> + <kbd>+</kbd> / <kbd>-</kbd> / <kbd>0</kbd> | 页面缩放调整 |

---

## 🛠️ 环境与系统适配

- **已验证系统**：Ubuntu 20.04.6 LTS / GNOME Shell (X11 会话) / Python 3.8。
- **降级机制**：若缺少 GTK/WebKit 组件，程序将**自动降级**为浏览器模式运行，不会导致白屏卡死。
- **Wayland 提示**：Wayland 下窗口可正常运行，但任务栏图标类名可能显示为默认图标。

---

## 📅 农历与节假日

- **农历算法**：内置 1900–2100 年完整农历算法（含闰月），支持传统节日显示。
- **法定节假日**：支持国务院公布的调休数据。
  - **休**（红底）：法定放假与调休连休。
  - **班**（灰底）：周末调休上班。
- **每年更新方法**：
  ```bash
  python3 tools/make-holidays.py   # 更新 holidays.json
  ```

---

## 📂 数据与文件说明

### 数据存储路径
- **事项数据**：`~/.local/share/local-calendar/calendar.json`（带自动备份 `calendar.json.bak`）
- **窗口配置**：`~/.config/local-calendar/window.json`

### 核心目录结构
```text
calendar/
├── calendar_app.py       # 小窗口应用入口 (GTK3 + WebKit2)
├── index.html            # 前端界面 (含农历与节假日表)
├── holidays.json         # 节假日配置数据
├── serve.py              # 本地微型服务 (API + 静态托管)
├── calendar.sh           # 命令行启动管理脚本
├── install.sh            # 安装 / 卸载快捷方式脚本
└── tests/                # 自测脚本目录
```

---

## 🧪 自测与卸载

### 运行测试
```bash
./tests/run.sh            # 执行全部测试（逻辑、小窗口布局、存储）
```

### 卸载方式
1. **仅删除快捷方式**：
   ```bash
   ./install.sh --uninstall
   ```
2. **彻底清理程序与数据**：
   ```bash
   rm -rf calendar/
   rm -rf ~/.local/share/local-calendar ~/.config/local-calendar
