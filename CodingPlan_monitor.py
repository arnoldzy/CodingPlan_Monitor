#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLM & Minimax Coding Plan Monitor - Windows悬浮窗
支持多模型配额监控、异步数据刷新、精简模式及 .env 配置管理
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import logging
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import ctypes
import ctypes.wintypes
from collections import deque
import socket
import time
import tempfile
import msvcrt

# 配置日志
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger(__name__)
logger.info("--- Coding Plan Monitor Starting ---")

from glm_usage_api import GLMUsageAPI
from minimax_usage_api import MiniMaxUsageAPI
from kimi_usage_api import KimiUsageAPI

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import win32api, win32con, win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

# 主题配置
THEME = {
    'bg_dark': '#1a1a2e',
    'bg_medium': '#16213e',
    'bg_light': '#0f3460',
    'accent': '#4ecca3',
    'accent_alt': '#e94560',
    'text_primary': '#ffffff',
    'text_secondary': '#aaa',
    'text_muted': '#666',
    'warning': '#ffd700'
}

INSTANCE_HOST = "127.0.0.1"
INSTANCE_PORT = 43791
LOCK_FILE_PATH = os.path.join(tempfile.gettempdir(), "CodingPlanMonitor.lock")
TRAY_MSG_ID = 0x0400 + 20
TRAY_SHOW_MENU_MSG = 0x0400 + 21
TRAY_CMD_TOGGLE = 1001
TRAY_CMD_CENTER = 1002
TRAY_CMD_EXIT = 1003

class CodingPlanMonitor:
    """编码计划监控悬浮窗类"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Coding Plan Monitor")
        
        # 初始化 API 客户端
        self.glm_api = GLMUsageAPI()
        self.minimax_api = MiniMaxUsageAPI()
        self.kimi_api = KimiUsageAPI()
        
        # 配置路径
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glm_monitor_config.json")
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        self.assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        
        # 运行时状态
        self.config = self.load_config()
        self.glm_data = {"level": "Lite", "FiveHour": {}, "Week": {}, "MCP": {}}
        self.minimax_data = {"FiveHour": {}}
        self.kimi_data = {"FiveHour": {}, "Week": {}}
        self.data = {"status": "连接中...", "time": "--"}
        self.running = True
        self.compact_mode = False
        self._is_fetching = False
        self._after_id = None
        self._fetch_future = None
        self._dynamic = {"fast": 30, "slow": 60, "override": None, "no_change_steps": 0}
        self._hist = {"glm_pct": deque(maxlen=5), "mm_used": deque(maxlen=5), "kimi_pct": deque(maxlen=5)}
        self._instance_server = None
        self._instance_thread = None
        self._window_visible = True
        self._tray_hwnd = None
        self._tray_nid = None
        self._tray_thread = None
        self._tray_last_menu_ts = 0.0
        self._chart_win = None
        self._settings_win = None
        
        # 异步线程池与事件循环
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.loop_thread.start()

        # 初始化 API Key
        self._sync_api_keys()
        self.start_instance_listener()
        
        # UI 构建
        self.setup_styles()
        self.setup_window()
        self.setup_ui()
        self.start_tray_icon()
        
        # 初始加载与调度
        self.load_all_data()
        self.schedule_fetch()

        # 窗口事件绑定
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        self.make_draggable()

    # --- 核心逻辑 ---

    def _sync_api_keys(self):
        """同步配置中的 API Key 到 API 实例"""
        if self.config.get("api_key"):
            self.glm_api.api_key = self.config["api_key"]
        if self.config.get("minimax_api_key"):
            self.minimax_api.api_key = self.config["minimax_api_key"]
        if self.config.get("kimi_api_key"):
            self.kimi_api.api_key = self.config["kimi_api_key"]

    def _run_async_loop(self):
        """运行后台事件循环"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start_instance_listener(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((INSTANCE_HOST, INSTANCE_PORT))
            server.listen(5)
            server.settimeout(1.0)
            self._instance_server = server
        except Exception as e:
            self._instance_server = None
            logger.warning(f"单例监听启动失败: {e}")
            return

        def loop():
            while self.running and self._instance_server:
                try:
                    conn, _ = self._instance_server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                except Exception:
                    continue
                try:
                    payload = conn.recv(1024).decode('utf-8', errors='ignore').strip().upper()
                    if payload == "SHOW":
                        self.root.after(0, self.focus_and_shake)
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

        self._instance_thread = threading.Thread(target=loop, daemon=True)
        self._instance_thread.start()

    def focus_and_shake(self):
        try:
            self._window_visible = True
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.lift()
            self.root.focus_force()
            base_x = self.root.winfo_x()
            base_y = self.root.winfo_y()
            offsets = [18, -18, 18, -18, 18, -18, 0]

            def shake_step(i):
                if i >= len(offsets):
                    return
                self.root.geometry(f"+{base_x + offsets[i]}+{base_y}")
                self.root.after(60, lambda: shake_step(i + 1))

            shake_step(0)
        except Exception as e:
            logger.error(f"窗口激活失败: {e}")

    def show_main_window(self):
        self._window_visible = True
        self.root.deiconify()
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.root.focus_force()

    def hide_main_window(self):
        self._window_visible = False
        self.root.withdraw()

    def on_window_close(self):
        self.hide_main_window()

    def toggle_main_window(self):
        if self.root.state() == "withdrawn":
            self.show_main_window()
        else:
            self.hide_main_window()

    def center_main_window(self):
        self.show_main_window()
        self.root.update_idletasks()
        w = self.root.winfo_width() or 390
        h = self.root.winfo_height() or 460
        self.center_window(self.root, w, h)

    def start_tray_icon(self):
        if not HAS_WIN32:
            return
        if self._tray_thread and self._tray_thread.is_alive():
            return
        self._tray_thread = threading.Thread(target=self._run_tray_loop, daemon=True)
        self._tray_thread.start()

    def _run_tray_loop(self):
        try:
            class_name = f"CodingPlanMonitorTray_{os.getpid()}"
            message_map = {
                TRAY_MSG_ID: self._on_tray_notify,
                TRAY_SHOW_MENU_MSG: self._on_tray_show_menu,
                win32con.WM_COMMAND: self._on_tray_command,
                win32con.WM_DESTROY: self._on_tray_destroy
            }
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = class_name
            wc.lpfnWndProc = message_map
            class_atom = win32gui.RegisterClass(wc)
            hwnd = win32gui.CreateWindow(class_atom, class_name, 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
            self._tray_hwnd = hwnd
            icon_path = os.path.join(self.assets_dir, "tray.ico")
            icon = None
            if os.path.exists(icon_path):
                try:
                    icon = win32gui.LoadImage(
                        0,
                        icon_path,
                        win32con.IMAGE_ICON,
                        0,
                        0,
                        win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
                    )
                except Exception as e:
                    logger.warning(f"加载托盘图标失败: {e}")
            if not icon:
                icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            self._tray_nid = (hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP, TRAY_MSG_ID, icon, "Coding Plan Monitor")
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self._tray_nid)
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_SETVERSION, (hwnd, 0, 0, 0, 0, "Coding Plan Monitor", win32con.NOTIFYICON_VERSION_4))
            except Exception:
                pass
            win32gui.PumpMessages()
        except Exception as e:
            logger.warning(f"托盘启动失败: {e}")

    def _on_tray_notify(self, hwnd, msg, wparam, lparam):
        try:
            if lparam == win32con.WM_LBUTTONDBLCLK:
                self.root.after(0, self.show_main_window)
            elif lparam in (win32con.WM_RBUTTONUP, win32con.WM_CONTEXTMENU):
                now = time.time()
                if now - self._tray_last_menu_ts > 0.2:
                    self._tray_last_menu_ts = now
                    win32gui.PostMessage(hwnd, TRAY_SHOW_MENU_MSG, 0, 0)
        except Exception as e:
            logger.warning(f"托盘事件处理失败: {e}")
        return 0

    def _on_tray_show_menu(self, hwnd, msg, wparam, lparam):
        try:
            self._show_tray_menu(hwnd)
        except Exception as e:
            logger.warning(f"托盘菜单显示失败: {e}")
        return 0

    def _show_tray_menu(self, hwnd):
        menu = win32gui.CreatePopupMenu()
        toggle_label = "隐藏窗口" if self._window_visible else "显示窗口"
        win32gui.AppendMenu(menu, win32con.MF_STRING, TRAY_CMD_TOGGLE, toggle_label)
        win32gui.AppendMenu(menu, win32con.MF_STRING, TRAY_CMD_CENTER, "显示在主窗口")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, TRAY_CMD_EXIT, "退出程序")
        try:
            win32gui.SetForegroundWindow(hwnd)
            x, y = win32gui.GetCursorPos()
            cmd = win32gui.TrackPopupMenu(menu, win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY, x, y, 0, hwnd, None)
            if cmd:
                win32gui.PostMessage(hwnd, win32con.WM_COMMAND, cmd, 0)
            win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        finally:
            win32gui.DestroyMenu(menu)

    def _on_tray_command(self, hwnd, msg, wparam, lparam):
        cmd = wparam & 0xFFFF
        if cmd == TRAY_CMD_TOGGLE:
            self.root.after(0, self.toggle_main_window)
        elif cmd == TRAY_CMD_CENTER:
            self.root.after(0, self.center_main_window)
        elif cmd == TRAY_CMD_EXIT:
            self.root.after(0, self.close)
        return 0

    def _on_tray_destroy(self, hwnd, msg, wparam, lparam):
        try:
            if self._tray_nid:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, self._tray_nid)
                self._tray_nid = None
        except Exception:
            pass
        try:
            win32gui.PostQuitMessage(0)
        except Exception:
            pass
        return 0

    def load_config(self):
        """加载配置：统一从 .env 读取（兼容旧 JSON 的 refresh_interval）"""
        config = {"refresh_interval": 30, "api_key": "", "minimax_api_key": "", "kimi_api_key": ""}
        legacy_refresh = None
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    legacy = json.load(f)
                    if isinstance(legacy, dict):
                        legacy_refresh = legacy.get("refresh_interval")
        except Exception as e:
            logger.warning(f"加载旧 JSON 配置失败: {e}")

        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        has_refresh_env = False
        if os.path.exists(env_path):
            try:
                from dotenv import dotenv_values
                env_vars = dotenv_values(env_path)
                if env_vars.get("GLM_API_KEY"): config["api_key"] = env_vars["GLM_API_KEY"]
                if env_vars.get("MINIMAX_API_KEY"): config["minimax_api_key"] = env_vars["MINIMAX_API_KEY"]
                if env_vars.get("KIMI_API_KEY"): config["kimi_api_key"] = env_vars["KIMI_API_KEY"]
                if env_vars.get("MONITOR_REFRESH_INTERVAL"):
                    has_refresh_env = True
                    try: config["refresh_interval"] = int(env_vars["MONITOR_REFRESH_INTERVAL"])
                    except: pass
            except ImportError:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line:
                            k, v = line.strip().split('=', 1)
                            v = v.strip("'\"")
                            if k == "GLM_API_KEY": config["api_key"] = v.strip("'\"")
                            elif k == "MINIMAX_API_KEY": config["minimax_api_key"] = v.strip("'\"")
                            elif k == "KIMI_API_KEY": config["kimi_api_key"] = v.strip("'\"")
                            elif k == "MONITOR_REFRESH_INTERVAL":
                                has_refresh_env = True
                                try: config["refresh_interval"] = int(v)
                                except: pass
        if not has_refresh_env and legacy_refresh is not None:
            try: config["refresh_interval"] = int(legacy_refresh)
            except: pass
        return config

    def save_config(self):
        """保存配置到 .env"""

        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        env_lines = []
        keys = {
            "GLM_API_KEY": self.config["api_key"],
            "MINIMAX_API_KEY": self.config["minimax_api_key"],
            "KIMI_API_KEY": self.config["kimi_api_key"],
            "MONITOR_REFRESH_INTERVAL": str(self.config["refresh_interval"])
        }
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    found = False
                    for k in list(keys.keys()):
                        if line.startswith(f"{k}="):
                            env_lines.append(f"{k}={keys.pop(k)}\n")
                            found = True; break
                    if not found: env_lines.append(line)
        for k, v in keys.items(): env_lines.append(f"{k}={v}\n")
        try:
            with open(env_path, 'w', encoding='utf-8') as f: f.writelines(env_lines)
        except Exception as e: logger.error(f"保存 .env 失败: {e}")
        try:
            if os.path.exists(self.config_file):
                os.remove(self.config_file)
        except Exception as e:
            logger.warning(f"删除旧 JSON 配置失败: {e}")

    def load_all_data(self):
        """从 JSON 加载 GLM/Minimax/Kimi 的实时数据"""
        # 1. GLM 数据加载
        glm_quota_path = os.path.join(self.data_dir, "glm", "quota_limit.json")
        if os.path.exists(glm_quota_path):
            try:
                with open(glm_quota_path, 'r', encoding='utf-8') as f:
                    q_json = json.load(f)
                    if q_json.get("success"):
                        data = q_json["data"]
                        self.glm_data["level"] = data.get("level", "Lite").capitalize()
                        self.data["time"] = datetime.now().strftime("%H:%M:%S")
                        for limit in data.get("limits", []):
                            u, p, r = limit.get("unit"), limit.get("percentage", 0), limit.get("nextResetTime", 0)
                            rem_pct = 100 - p
                            if u == 5: self.glm_data["MCP"] = {"quota": limit.get("usage", 0), "used": limit.get("currentValue", 0), "percentage": rem_pct, "reset_time": r}
                            elif u == 3: self.glm_data["FiveHour"] = {"quota": rem_pct, "reset_time": r}
                            elif u == 6: self.glm_data["Week"] = {"quota": rem_pct, "reset_time": r}
            except Exception as e: logger.error(f"GLM 数据加载失败: {e}")

        # 2. Minimax 数据加载
        mm_remains_path = os.path.join(self.data_dir, "minimax", "coding_plan_remains.json")
        if os.path.exists(mm_remains_path):
            try:
                with open(mm_remains_path, 'r', encoding='utf-8') as f:
                    mm_json = json.load(f)
                    remains = mm_json.get("model_remains", [])
                    if remains:
                        m = remains[0]
                        tot, rem = m.get("current_interval_total_count", 0), m.get("current_interval_usage_count", 0)
                        pct = int((rem / tot) * 100) if tot > 0 else 0
                        self.minimax_data["FiveHour"] = {"quota": pct, "used": tot - rem, "total": tot, "reset_time": m.get("end_time", 0)}
            except Exception as e: logger.error(f"Minimax 数据加载失败: {e}")

        # 3. Kimi 数据加载
        kimi_summary_path = os.path.join(self.data_dir, "kimi", "coding_plan_summary.json")
        if os.path.exists(kimi_summary_path):
            try:
                with open(kimi_summary_path, 'r', encoding='utf-8') as f:
                    kimi_json = json.load(f)
                    self.kimi_data["FiveHour"] = kimi_json.get("FiveHour", {}) or {}
                    self.kimi_data["Week"] = kimi_json.get("Week", {}) or {}
            except Exception as e: logger.error(f"Kimi 数据加载失败: {e}")

        self.update_ui_panels()

    def fetch_data(self):
        """执行异步数据抓取"""
        if not self.running or self._is_fetching: return
        self._is_fetching = True
        if hasattr(self, 'glm_status_label'): self.glm_status_label.config(text="● 正在刷新...", fg=THEME['warning'])

        async def do_fetch():
            try:
                def run_apis():
                    if self.glm_api.api_key:
                        self.glm_api.save_usage_data(save_to_file=True)
                    if self.minimax_api.api_key:
                        self.minimax_api.save_usage_data(save_to_file=True)
                    if self.kimi_api.api_key:
                        self.kimi_api.save_usage_data(save_to_file=True)
                await self.loop.run_in_executor(self.executor, run_apis)
                self.root.after(0, self._on_fetch_success)
            except Exception as e:
                logger.error(f"异步刷新失败: {e}")
                self.root.after(0, lambda: self._on_fetch_error(str(e)))

        self._fetch_future = asyncio.run_coroutine_threadsafe(do_fetch(), self.loop)

    def _on_fetch_success(self):
        self._is_fetching = False
        self.load_all_data()
        self._update_dynamic_refresh()
        if hasattr(self, 'time_label'): self.time_label.config(text=f"更新: {self.data.get('time', '--')}")
        if hasattr(self, 'glm_status_label'): self.glm_status_label.config(text="● API已连接", fg=THEME['accent'])

    def _on_fetch_error(self, err):
        self._is_fetching = False
        if hasattr(self, 'glm_status_label'): self.glm_status_label.config(text=f"● 错误: {err[:20]}...", fg=THEME['accent_alt'])

    def schedule_fetch(self):
        if self.running:
            self.fetch_data()
            interval = self._dynamic.get("override") or self.config.get("refresh_interval", 30)
            self._after_id = self.root.after(interval * 1000, self.schedule_fetch)
    
    def reschedule_fetch(self):
        try:
            if self._after_id:
                self.root.after_cancel(self._after_id)
        except:
            pass
        if self.running:
            interval = self._dynamic.get("override") or self.config.get("refresh_interval", 30)
            self._after_id = self.root.after(interval * 1000, self.schedule_fetch)

    # --- UI 构建组件 ---

    def setup_styles(self):
        style = ttk.Style(); style.theme_use('clam')
        style.configure("Custom.Horizontal.TProgressbar", troughcolor=THEME['bg_medium'], background=THEME['accent'], thickness=8)
        style.configure("Custom.TCombobox", fieldbackground=THEME['bg_medium'], background=THEME['bg_light'], foreground=THEME['text_primary'], borderwidth=0)

    def setup_window(self):
        self.root.attributes('-topmost', True); self.root.overrideredirect(True)
        # 初始宽度 390
        self.root.geometry("390x460"); self.root.attributes('-alpha', 0.95); self.root.configure(bg=THEME['bg_dark'])
        # 居中显示
        self.center_window(self.root, 390, 460)
        if HAS_WIN32: self.root.after(100, self._set_tool_window_style)

    def center_window(self, window, width, height):
        """将窗口居中显示在屏幕上"""
        window.update_idletasks()
        sw = window.winfo_screenwidth()
        sh = window.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _set_tool_window_style(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_TOOLWINDOW)
        except: pass

    def setup_ui(self):
        self.main_frame = tk.Frame(self.root, bg=THEME['bg_dark'], padx=12, pady=12)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 1. 顶部标题栏
        self.setup_title_bar()
        # 2. GLM 区域
        self.glm_Panel = self.create_model_panel("GLM", "glm")
        # 3. Minimax 区域
        self.minimax_Panel = self.create_model_panel("Minimax", "minimax")
        # 4. Kimi 区域
        self.kimi_Panel = self.create_model_panel("Kimi", "kimi")
        # 5. 底部
        self.setup_footer()
        self.setup_context_menu()

    def setup_title_bar(self):
        self.title_frame = tk.Frame(self.main_frame, bg=THEME['bg_dark'])
        self.title_frame.pack(fill=tk.X, pady=(0, 2))
        tk.Label(self.title_frame, text="Coding Plan Monitor", font=("Microsoft YaHei UI", 11, "bold"), fg=THEME['accent'], bg=THEME['bg_dark']).pack(side=tk.LEFT)
        
        btn_frame = tk.Frame(self.title_frame, bg=THEME['bg_dark'])
        btn_frame.pack(side=tk.RIGHT)
        self.glm_status_label = tk.Label(self.title_frame, text="● 连接中...", font=("Microsoft YaHei UI", 10, "bold"), fg=THEME['accent'], bg=THEME['bg_dark'])
        self.glm_status_label.pack(side=tk.RIGHT, padx=(0, 6))
        
        self.compact_btn = self._create_icon_btn(btn_frame, "▲", self.toggle_compact_mode, THEME['text_secondary'])
        self._create_icon_btn(btn_frame, "⚙", self.show_settings, THEME['text_secondary'], font_size=12)
        self._create_icon_btn(btn_frame, "×", self.on_window_close, THEME['accent_alt'], font_size=14, bold=True)

    def _create_icon_btn(self, parent, text, cmd, color, font_size=10, bold=False):
        font = ("Arial", font_size, "bold" if bold else "normal")
        btn = tk.Label(parent, text=text, font=font, fg=color, bg=THEME['bg_dark'], cursor='hand2')
        btn.pack(side=tk.LEFT, padx=2)
        btn.bind('<Button-1>', lambda e: cmd())
        btn.bind('<Enter>', lambda e: btn.config(fg=THEME['accent']))
        btn.bind('<Leave>', lambda e: btn.config(fg=color))
        return btn

    def create_model_panel(self, name, panel_type):
        is_glm = panel_type == "glm"
        is_minimax = panel_type == "minimax"
        is_kimi = panel_type == "kimi"
        panel = {}
        frame = tk.Frame(self.main_frame, bg=THEME['bg_dark'])
        frame.pack(fill=tk.X, pady=(4 if not is_glm else 0, 2))
        panel['frame'] = frame

        # 标题行
        title_f = tk.Frame(frame, bg=THEME['bg_dark'])
        title_f.pack(fill=tk.X, pady=(0, 2))
        panel['title_frame'] = title_f
        
        left_f = tk.Frame(title_f, bg=THEME['bg_dark']); left_f.pack(side=tk.LEFT)
        
        # 尝试加载 Logo 图片
        logo_img = None
        if HAS_PIL:
            try:
                if is_glm:
                    svg_path = os.path.join(self.assets_dir, "glm_logo.svg")
                    if os.path.exists(svg_path):
                        try:
                            from svglib.svglib import svg2rlg
                            from reportlab.graphics import renderPM
                            import io
                            drawing = svg2rlg(svg_path)
                            # 缩放 SVG 绘图以适应 20 像素高度
                            scale = 20 / drawing.height
                            drawing.width *= scale
                            drawing.height *= scale
                            drawing.scale(scale, scale)
                            img_data = renderPM.drawToString(drawing, fmt='PNG')
                            img = Image.open(io.BytesIO(img_data))
                            logo_img = ImageTk.PhotoImage(img)
                        except ImportError:
                            logger.warning(f"缺少 svglib 或 reportlab，无法渲染 GLM SVG Logo")
                elif is_minimax:
                    logo_path = os.path.join(self.assets_dir, "minimax_logo.png")
                    if os.path.exists(logo_path):
                        img = Image.open(logo_path)
                        aspect = img.width / img.height
                        img = img.resize((int(20 * aspect), 20), Image.Resampling.LANCZOS)
                        logo_img = ImageTk.PhotoImage(img)
                elif is_kimi:
                    logo_path = os.path.join(self.assets_dir, "kimi_logo.png")
                    if os.path.exists(logo_path):
                        img = Image.open(logo_path)
                        aspect = img.width / img.height
                        img = img.resize((int(20 * aspect), 20), Image.Resampling.LANCZOS)
                        logo_img = ImageTk.PhotoImage(img)
            except Exception as e:
                logger.warning(f"加载 {name} Logo 失败: {e}")

        if logo_img:
            lbl = tk.Label(left_f, image=logo_img, bg=THEME['bg_dark'])
            lbl.image = logo_img # 保持引用
            lbl.pack(side=tk.LEFT, padx=(0, 5))
        
        tk.Label(left_f, text=name, font=("Microsoft YaHei UI", 11, "bold"), 
                fg=THEME['accent'], bg=THEME['bg_dark']).pack(side=tk.LEFT)
        
        if is_glm:
            panel['plan_label'] = tk.Label(left_f, text="[Lite]", font=("Microsoft YaHei UI", 9, "bold"), fg=THEME['warning'], bg=THEME['bg_dark'])
            panel['plan_label'].pack(side=tk.LEFT, padx=(5, 0))

        right_f = tk.Frame(title_f, bg=THEME['bg_dark']); right_f.pack(side=tk.RIGHT)
        panel['reset_short'] = tk.Label(right_f, text="--:--", font=("Microsoft YaHei UI", 9), fg=THEME['text_secondary'], bg=THEME['bg_medium'], width=20, anchor='center')
        panel['reset_short'].pack(side=tk.LEFT)
        
        btn_f = tk.Frame(right_f, bg=THEME['bg_dark']); btn_f.pack(side=tk.RIGHT)
        panel['5h_pct_short'] = tk.Label(btn_f, text="5H:--%", font=("Microsoft YaHei UI", 9), fg=THEME['text_secondary'], bg=THEME['bg_medium'], width=10, anchor='w')
        panel['5h_pct_short'].pack(side=tk.LEFT)
        
        refresh = tk.Label(btn_f, text="↻", font=("Arial", 12), fg=THEME['text_secondary'], bg=THEME['bg_dark'], cursor='hand2')
        refresh.pack(side=tk.RIGHT); refresh.bind('<Button-1>', lambda e: self.fetch_data())
        refresh.bind('<Enter>', lambda e: refresh.config(fg=THEME['accent'])); refresh.bind('<Leave>', lambda e: refresh.config(fg=THEME['text_secondary']))

        # 配额区
        quota_f = tk.Frame(self.main_frame, bg=THEME['bg_medium'], padx=4, pady=2)
        quota_f.pack(fill=tk.X, pady=(0, 2))
        panel['quota_frame'] = quota_f
        
        if is_glm:
            self._add_quota_row(panel, quota_f, "5小时：", "#4ecdc4", "glm_5h")
            self._add_quota_row(panel, quota_f, "周限额：", "#45b7d1", "glm_weekly")
            self._add_quota_row(panel, quota_f, "MCP：", "#45b7d1", "glm_mcp")
            
            # 新增：最近5小时统计标签行
            usage_info_f = tk.Frame(quota_f, bg=THEME['bg_medium'])
            usage_info_f.pack(fill=tk.X, pady=(10, 0))
            panel['calls_label'] = tk.Label(usage_info_f, text="次数: --", font=("Microsoft YaHei UI", 9), fg=THEME['text_secondary'], bg=THEME['bg_medium'])
            panel['calls_label'].pack(side=tk.LEFT)
            panel['tokens_label'] = tk.Label(usage_info_f, text="Tokens: --", font=("Microsoft YaHei UI", 9), fg=THEME['text_secondary'], bg=THEME['bg_medium'])
            panel['tokens_label'].pack(side=tk.RIGHT)

            panel['chart_label'] = tk.Label(quota_f, bg=THEME['bg_medium'], cursor='hand2')
            panel['chart_label'].pack(fill=tk.X, pady=(2, 0))
            panel['chart_label'].bind('<Double-Button-1>', lambda e: self._show_large_chart())
        elif is_minimax:
            self._add_quota_row(panel, quota_f, "5小时：", "#4ecdc4", "mm_5h")
        elif is_kimi:
            self._add_quota_row(panel, quota_f, "5小时：", "#4ecdc4", "kimi_5h")
            self._add_quota_row(panel, quota_f, "周限额：", "#45b7d1", "kimi_weekly")
        
        return panel

    def _add_quota_row(self, panel, parent, label, color, key):
        row = tk.Frame(parent, bg=THEME['bg_medium']); row.pack(fill=tk.X, pady=2)
        p_f = tk.Frame(row, bg=THEME['bg_medium']); p_f.pack(fill=tk.X, padx=(5, 0))
        tk.Label(p_f, text=label, font=("Microsoft YaHei UI", 9), fg=THEME['text_secondary'], bg=THEME['bg_medium'], width=8).pack(side=tk.LEFT)
        bar = ttk.Progressbar(p_f, mode='determinate', style="Custom.Horizontal.TProgressbar"); bar.pack(fill=tk.X)
        val = tk.Label(row, text="--%", font=("Microsoft YaHei UI", 9, "bold"), fg=color, bg=THEME['bg_medium'], anchor='e'); val.pack(side=tk.RIGHT)
        reset = tk.Label(row, text="--", font=("Microsoft YaHei UI", 8), fg=THEME['text_muted'], bg=THEME['bg_medium']); reset.pack(side=tk.LEFT, padx=(65, 0))
        panel[f'{key}_row'], panel[f'{key}_bar'], panel[f'{key}_label'], panel[f'{key}_reset'] = row, bar, val, reset

    def setup_footer(self):
        self.footer_frame = tk.Frame(self.main_frame, bg=THEME['bg_dark']); self.footer_frame.pack(fill=tk.X)
        self.time_label = tk.Label(self.footer_frame, text="更新: --", font=("Microsoft YaHei UI", 8), fg=THEME['text_muted'], bg=THEME['bg_dark'])
        self.time_label.pack(anchor='e')

    def setup_context_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=THEME['bg_medium'], fg=THEME['text_primary'], font=("Microsoft YaHei UI", 9))
        m.add_command(label="🔄 刷新", command=self.fetch_data); m.add_command(label="⚙ 设置", command=self.show_settings)
        m.add_separator(); m.add_command(label="✕ 退出", command=self.close)
        self.root.bind('<Button-3>', lambda e: m.tk_popup(e.x_root, e.y_root))

    # --- UI 更新 ---

    def update_ui_panels(self):
        self._update_glm_ui()
        self._update_minimax_ui()
        self._update_kimi_ui()
        self.update_glm_chart()
    
    def _update_dynamic_refresh(self):
        try:
            glm_pct = self.glm_data.get("FiveHour", {}).get("quota", 0)
            mm_used = self.minimax_data.get("FiveHour", {}).get("used", 0)
            kimi_pct = self.kimi_data.get("FiveHour", {}).get("quota", 0)
            change = False
            if len(self._hist["glm_pct"]) > 0 and glm_pct != self._hist["glm_pct"][-1]:
                change = True
            if len(self._hist["mm_used"]) > 0 and mm_used > self._hist["mm_used"][-1]:
                change = True
            if len(self._hist["kimi_pct"]) > 0 and kimi_pct != self._hist["kimi_pct"][-1]:
                change = True
            self._hist["glm_pct"].append(glm_pct)
            self._hist["mm_used"].append(mm_used)
            self._hist["kimi_pct"].append(kimi_pct)
            if change:
                self._dynamic["override"] = self._dynamic["fast"]
                self._dynamic["no_change_steps"] = 0
            else:
                self._dynamic["no_change_steps"] += 1
                if self._dynamic["no_change_steps"] >= 5:
                    self._dynamic["override"] = self._dynamic["slow"]
            self.reschedule_fetch()
        except:
            pass

    def _update_glm_ui(self):
        p = self.glm_Panel
        p['plan_label'].config(text=f"[{self.glm_data['level']}]")
        # 5H
        fh = self.glm_data.get("FiveHour", {})
        pct = fh.get('quota', 0); color = self.get_usage_color(pct); rt = self.format_reset_time(fh.get('reset_time', 0))
        p['glm_5h_label'].config(text=f"{pct}%", fg=color); p['glm_5h_bar']['value'] = pct; p['glm_5h_reset'].config(text=rt)
        p['5h_pct_short'].config(text=f"5H:{pct}%", fg=color); p['reset_short'].config(text=rt.replace("(","").replace(")",""))
        # Week
        w = self.glm_data.get("Week")
        if w:
            p['glm_weekly_row'].pack(fill=tk.X, pady=2, after=p['glm_5h_row'])
            wp = w.get('quota', 0); p['glm_weekly_label'].config(text=f"{wp}%", fg=self.get_usage_color(wp))
            p['glm_weekly_bar']['value'] = wp; p['glm_weekly_reset'].config(text=self.format_reset_time(w.get('reset_time', 0)))
        else: p['glm_weekly_row'].pack_forget()
        # MCP
        m = self.glm_data.get("MCP", {})
        mp = m.get('percentage', 0); p['glm_mcp_label'].config(text=f"{m.get('used',0)}/{m.get('quota',0)}", fg=self.get_usage_color(mp))
        p['glm_mcp_bar']['value'] = mp; p['glm_mcp_reset'].config(text=self.format_reset_time(m.get('reset_time', 0)))

        # 更新最近5小时统计标签
        self._update_glm_usage_stats()

    def _update_glm_usage_stats(self):
        """更新 GLM 最近 5 小时使用统计"""
        try:
            path = os.path.join(self.data_dir, "glm", "model_usage.json")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    usage_json = json.load(f)
                    data = usage_json.get("data", {})
                    calls = data.get("modelCallCount", [])
                    tokens = data.get("tokensUsage", [])
                    
                    # 过滤掉 None 并求和
                    total_calls = sum([c for c in calls if c is not None])
                    total_tokens = sum([t for t in tokens if t is not None])
                    
                    def human_format(num):
                        if num >= 1000000: return f'{num/1000000:.1f}M'
                        if num >= 1000: return f'{num/1000:.1f}K'
                        return str(int(num))

                    p = self.glm_Panel
                    if 'calls_label' in p: p['calls_label'].config(text=f"次数: {total_calls}")
                    if 'tokens_label' in p: p['tokens_label'].config(text=f"Tokens: {human_format(total_tokens)}")
        except: pass

    def _update_minimax_ui(self):
        p = self.minimax_Panel; fh = self.minimax_data.get("FiveHour", {})
        pct = fh.get('quota', 0); color = self.get_usage_color(pct); rt = self.format_reset_time(fh.get('reset_time', 0))
        p['mm_5h_label'].config(text=f"{fh.get('used',0)}/{fh.get('total',0)}", fg=color)
        p['mm_5h_bar']['value'] = pct; p['mm_5h_reset'].config(text=rt)
        p['5h_pct_short'].config(text=f"5H:{pct}%", fg=color); p['reset_short'].config(text=rt.replace("(","").replace(")",""))

    def _update_kimi_ui(self):
        p = self.kimi_Panel
        fh = self.kimi_data.get("FiveHour", {})
        pct = fh.get('quota', 0)
        color = self.get_usage_color(pct)
        rt = self.format_reset_time(fh.get('reset_time', 0))
        p['kimi_5h_label'].config(text=f"{pct}%", fg=color)
        p['kimi_5h_bar']['value'] = pct
        p['kimi_5h_reset'].config(text=rt)
        p['5h_pct_short'].config(text=f"5H:{pct}%", fg=color)
        p['reset_short'].config(text=rt.replace("(", "").replace(")", ""))

        w = self.kimi_data.get("Week", {})
        if w:
            wp = w.get('quota', 0)
            p['kimi_weekly_label'].config(text=f"{wp}%", fg=self.get_usage_color(wp))
            p['kimi_weekly_bar']['value'] = wp
            p['kimi_weekly_reset'].config(text=self.format_reset_time(w.get('reset_time', 0)))
            p['kimi_weekly_row'].pack(fill=tk.X, pady=2, after=p['kimi_5h_row'])
        else:
            p['kimi_weekly_row'].pack_forget()

    def update_glm_chart(self):
        if not HAS_PIL or 'chart_label' not in self.glm_Panel: return
        try:
            # 默认显示 5h 图表
            path = os.path.join(self.data_dir, "glm", "model_usage_chart_5h.png")
            if os.path.exists(path):
                img = Image.open(path); w, h = img.size; tw = 290; th = int(h * (tw / w))
                img = img.resize((tw, th), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img); lbl = self.glm_Panel['chart_label']
                lbl.config(image=photo); lbl.image = photo
                if not self.compact_mode: lbl.pack(fill=tk.X, pady=(10, 0))
                self.adjust_window_height()
            else: self.glm_Panel['chart_label'].pack_forget()
        except: self.glm_Panel['chart_label'].pack_forget()

    def _show_large_chart(self):
        """双击显示高清大图，支持 5H/24H 切换"""
        if not HAS_PIL: return
        
        # 防止重复打开
        if self._chart_win and self._chart_win.winfo_exists():
            self._chart_win.lift()
            self._chart_win.focus_force()
            return

        # 创建大图窗口
        win = tk.Toplevel(self.root)
        self._chart_win = win
        win.title("GLM Usage Analysis (High Res)")
        win.attributes('-topmost', True)
        win.configure(bg='#000') # 纯黑背景
        
        def on_chart_close():
            self._chart_win = None
            win.destroy()
        
        win.protocol("WM_DELETE_WINDOW", on_chart_close)
        
        current_suffix = tk.StringVar(value="5h")
        
        # 顶层容器
        top_bar = tk.Frame(win, bg='#111', pady=5)
        top_bar.pack(fill=tk.X)
        
        # 切换按钮容器
        btn_frame = tk.Frame(top_bar, bg='#111')
        btn_frame.pack(side=tk.TOP)
        
        # 统计信息显示
        stats_lbl = tk.Label(top_bar, text="正在加载统计...", font=("Microsoft YaHei UI", 11, "bold"),
                           fg=THEME['accent'], bg='#111', pady=5)
        stats_lbl.pack(side=tk.TOP)
        
        def update_large_img():
            suffix = current_suffix.get()
            # 1. 更新统计数据
            try:
                json_path = os.path.join(self.data_dir, "glm", f"model_usage_{suffix}.json")
                if os.path.exists(json_path):
                    with open(json_path, 'r', encoding='utf-8') as f:
                        usage_json = json.load(f)
                        data = usage_json.get("data", {})
                        calls = data.get("modelCallCount", [])
                        tokens = data.get("tokensUsage", [])
                        total_calls = sum([c for c in calls if c is not None])
                        total_tokens = sum([t for t in tokens if t is not None])
                        
                        def human_format(num):
                            if num >= 1000000: return f'{num/1000000:.1f}M'
                            if num >= 1000: return f'{num/1000:.1f}K'
                            return str(int(num))
                        
                        time_labels = {
                            "5h": "最近 5 小时",
                            "24h": "最近 24 小时",
                            "7d": "最近 7 天",
                            "30d": "最近 30 天"
                        }
                        time_label = time_labels.get(suffix, suffix)
                        stats_lbl.config(text=f"{time_label} 统计： 调用次数 {total_calls} | Tokens {human_format(total_tokens)}")
            except Exception as e:
                logger.error(f"加载大图统计失败: {e}")
                stats_lbl.config(text="统计数据加载失败")

            # 2. 更新图片
            path = os.path.join(self.data_dir, "glm", f"model_usage_chart_{suffix}.png")
            if not os.path.exists(path): return
            
            img = Image.open(path)
            # 统一使用最大宽度 1300
            target_width = 1300
            
            w, h = img.size
            th = int(h * (target_width / w))
            img = img.resize((target_width, th), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            
            large_lbl.config(image=photo)
            large_lbl.image = photo # 保持引用
            
            # 更新按钮样式
            for btn, s in [(btn_5h, "5h"), (btn_24h, "24h"), (btn_7d, "7d"), (btn_30d, "30d")]:
                btn.config(fg=THEME['accent'] if suffix == s else THEME['text_secondary'],
                          bg='#222' if suffix == s else '#111')
            
            # 动态调整窗口大小并居中
            win.update_idletasks()
            win_w = target_width + 40 # 加上边距
            win_h = th + 100 # 加上顶部栏和边距
            self.center_window(win, win_w, win_h)

        # 按钮创建
        btn_5h = tk.Button(btn_frame, text="最近 5H", font=("Microsoft YaHei UI", 10, "bold"),
                          bg='#111', fg=THEME['text_secondary'], bd=0, padx=15,
                          command=lambda: [current_suffix.set("5h"), update_large_img()])
        btn_5h.pack(side=tk.LEFT, padx=5)
        
        btn_24h = tk.Button(btn_frame, text="最近 24H", font=("Microsoft YaHei UI", 10, "bold"),
                           bg='#111', fg=THEME['text_secondary'], bd=0, padx=15,
                           command=lambda: [current_suffix.set("24h"), update_large_img()])
        btn_24h.pack(side=tk.LEFT, padx=5)

        btn_7d = tk.Button(btn_frame, text="最近 7天", font=("Microsoft YaHei UI", 10, "bold"),
                           bg='#111', fg=THEME['text_secondary'], bd=0, padx=15,
                           command=lambda: [current_suffix.set("7d"), update_large_img()])
        btn_7d.pack(side=tk.LEFT, padx=5)

        btn_30d = tk.Button(btn_frame, text="最近 30天", font=("Microsoft YaHei UI", 10, "bold"),
                           bg='#111', fg=THEME['text_secondary'], bd=0, padx=15,
                           command=lambda: [current_suffix.set("30d"), update_large_img()])
        btn_30d.pack(side=tk.LEFT, padx=5)

        large_lbl = tk.Label(win, bg='#000')
        large_lbl.pack(padx=10, pady=10)

        # 绑定快捷键
        win.bind('<Escape>', lambda e: on_chart_close())
        
        # 初始加载
        update_large_img()

    # --- 辅助方法 ---

    def format_reset_time(self, ts_ms):
        if not ts_ms: return "--:--"
        try:
            diff = datetime.fromtimestamp(ts_ms/1000) - datetime.now()
            if diff.total_seconds() <= 0: return "(即将)"
            m = int(diff.total_seconds() // 60)
            return f"({m//60}h{m%60}m)" if m >= 60 else f"({m}m)"
        except: return ""

    def get_usage_color(self, pct):
        if pct <= 20: return THEME['accent_alt']
        return THEME['warning'] if pct <= 50 else THEME['accent']

    def toggle_compact_mode(self):
        self.compact_mode = not self.compact_mode
        self.compact_btn.config(text="▼" if self.compact_mode else "▲")
        # 批量隐藏/显示
        for p in [self.glm_Panel, self.minimax_Panel, self.kimi_Panel]:
            if self.compact_mode: p['quota_frame'].pack_forget()
            else: p['quota_frame'].pack(fill=tk.X, pady=(0, 2), after=p['frame'])
        if HAS_PIL:
            if self.compact_mode: self.glm_Panel['chart_label'].pack_forget()
            else: self.update_glm_chart()
        self.adjust_window_height()

    def adjust_window_height(self):
        self.root.update_idletasks(); h = 24
        for f in [self.title_frame, self.glm_Panel['frame'], self.glm_Panel['quota_frame'], self.minimax_Panel['frame'], self.minimax_Panel['quota_frame'], self.kimi_Panel['frame'], self.kimi_Panel['quota_frame'], self.footer_frame]:
            if f.winfo_manager(): h += f.winfo_reqheight() + 2
        self.root.geometry(f"390x{max(h, 120)}")

    def make_draggable(self):
        x, y = 0, 0
        def start(e): nonlocal x, y; x, y = e.x, e.y
        def drag(e): self.root.geometry(f"+{self.root.winfo_x() + e.x - x}+{self.root.winfo_y() + e.y - y}")
        self.root.bind('<Button-1>', start); self.root.bind('<B1-Motion>', drag)

    def show_settings(self):
        # 防止重复打开
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return

        win = tk.Toplevel(self.root); win.title("设置"); win.attributes('-topmost', True)
        self._settings_win = win
        win.configure(bg=THEME['bg_dark']); win.resizable(False, False)
        
        def on_settings_close():
            self._settings_win = None
            win.destroy()
        
        win.protocol("WM_DELETE_WINDOW", on_settings_close)
        # 居中显示
        self.center_window(win, 400, 560)
        tk.Label(win, text="⚙ 设置", font=("Microsoft YaHei UI", 14, "bold"), fg=THEME['accent'], bg=THEME['bg_dark']).pack(pady=15)
        content = tk.Frame(win, bg=THEME['bg_dark'], padx=25); content.pack(fill=tk.BOTH, expand=True)
        
        self.setting_vars = {}
        self._add_set_row(content, "GLM API Key:", "api_key", self.config["api_key"], True)
        self._add_set_row(content, "Minimax API Key:", "minimax_api_key", self.config["minimax_api_key"], True)
        self._add_set_row(content, "Kimi API Key:", "kimi_api_key", self.config["kimi_api_key"], True)
        self._add_set_row(content, "刷新间隔(秒):", "refresh_interval", str(self.config["refresh_interval"]))

        def save():
            for k in ["api_key", "minimax_api_key", "kimi_api_key"]: self.config[k] = self.setting_vars[k].get()
            try: self.config["refresh_interval"] = int(self.setting_vars["refresh_interval"].get())
            except: self.config["refresh_interval"] = 30
            self._sync_api_keys(); self.save_config(); self._settings_win = None; win.destroy(); self.fetch_data(); self.reschedule_fetch(); messagebox.showinfo("成功", "设置已保存!")

        btn_wrap = tk.Frame(win, bg=THEME['bg_dark'])
        btn_wrap.pack(fill=tk.X, pady=(0, 16))
        tk.Button(btn_wrap, text="💾 保存设置", font=("Microsoft YaHei UI", 11, "bold"), bg=THEME['accent'], fg='#000', width=15, height=2, bd=0, command=save).pack()

    def _add_set_row(self, parent, label, key, val, is_pwd=False):
        f = tk.Frame(parent, bg=THEME['bg_dark']); f.pack(fill=tk.X, pady=6)
        tk.Label(f, text=label, font=("Microsoft YaHei UI", 10), fg=THEME['text_primary'], bg=THEME['bg_dark']).pack(anchor='w')
        var = tk.StringVar(value=val); self.setting_vars[key] = var
        entry = tk.Entry(f, textvariable=var, font=("Microsoft YaHei UI", 10), bg=THEME['bg_medium'], fg=THEME['text_primary'], bd=0, highlightthickness=1, show="*" if is_pwd else "")
        entry.pack(fill=tk.X, ipady=5)
        if is_pwd:
            def toggle():
                if entry.cget('show') == '*': entry.config(show=''); t.config(text='隐藏')
                else: entry.config(show='*'); t.config(text='显示')
            t = tk.Button(f, text="显示", font=("Microsoft YaHei UI", 8), bg=THEME['bg_light'], fg=THEME['text_secondary'], bd=0, command=toggle)
            t.pack(anchor='w', pady=2)

    def close(self):
        self.running = False
        try:
            if HAS_WIN32 and self._tray_hwnd:
                win32gui.PostMessage(self._tray_hwnd, win32con.WM_CLOSE, 0, 0)
                self._tray_hwnd = None
        except Exception:
            pass
        try:
            if self._instance_server:
                self._instance_server.close()
                self._instance_server = None
        except:
            pass
        try:
            if self._after_id:
                self.root.after_cancel(self._after_id)
        except:
            pass
        
        # 尝试取消正在进行的异步任务
        if self._fetch_future and not self._fetch_future.done():
            self._fetch_future.cancel()

        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.executor.shutdown(wait=False)
        except: pass
        self.root.destroy()

    def run(self):
        if not self.config.get("api_key"): self.root.after(500, self.show_settings)
        self.show_main_window()
        self.root.mainloop()

if __name__ == "__main__":
    def activate_existing_window():
        if not HAS_WIN32:
            return False
        try:
            hwnd = win32gui.FindWindow(None, "Coding Plan Monitor")
            if not hwnd:
                return False
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            offsets = [18, -18, 18, -18, 18, -18, 0]
            for off in offsets:
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOP,
                    left + off,
                    top,
                    width,
                    height,
                    win32con.SWP_NOACTIVATE
                )
                time.sleep(0.06)
            return True
        except Exception:
            return False

    def acquire_lock_file():
        try:
            f = open(LOCK_FILE_PATH, "a+")
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return f, True
        except Exception:
            try:
                f.close()
            except Exception:
                pass
            return None, False

    def release_lock_file(f):
        if not f:
            return
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        try:
            f.close()
        except Exception:
            pass

    def notify_existing_instance(wait_seconds=3.0):
        end_at = time.time() + wait_seconds
        while time.time() < end_at:
            try:
                with socket.create_connection((INSTANCE_HOST, INSTANCE_PORT), timeout=0.6) as s:
                    s.sendall(b"SHOW")
                return True
            except Exception:
                time.sleep(0.15)
        return False

    # 全局异常捕获
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    
    import sys
    sys.excepthook = handle_exception

    if activate_existing_window():
        sys.exit(0)

    lock_file, acquired = acquire_lock_file()
    if not acquired:
        notify_existing_instance()
        sys.exit(0)

    app = CodingPlanMonitor()
    try:
        app.run()
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
    finally:
        try:
            app.close()
        except:
            pass
        release_lock_file(lock_file)
