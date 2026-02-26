#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLM Coding Plan Monitor - Windows悬浮窗
按照5小时/每周/每月配额 + 模型使用分布显示
支持API Key配置和模型选择
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import logging
from datetime import datetime
import ctypes

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.warning("requests库未安装，API功能将不可用")

try:
    import win32api, win32con, win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    logger.info("pywin32未安装，部分Windows特性将不可用")

# 主流模型列表
AVAILABLE_MODELS = [
    "GLM",
    "Claude",
    "GPT-4",
    "GPT-3.5",
    "DeepSeek",
    "Doubao",
    "Gemini",
    "Llama",
    "Qwen",
    "Yi",
    "Baichuan",
    "Moonshot"
]

# 主题颜色
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


class GLMAPIClient:
    """API客户端"""

    def __init__(self):
        self.api_key = None
        self.base_url = "https://open.bigmodel.cn/api/paas/v4"
        self.quota_url = "https://open.bigmodel.cn/api/monitor/usage/quota/limit"
        self.stats_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glm_usage_stats.json")
        self.stats = self.load_stats()

    def load_stats(self):
        """加载统计数据"""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"加载统计数据失败: {e}")
        return self.get_default_stats()

    def get_default_stats(self):
        """获取默认统计数据"""
        return {
            "total_tokens": 0,
            "call_count": 0,
            "model_usage": {"GLM": {"calls": 0, "tokens": 0}}
        }

    def save_stats(self):
        """保存统计数据"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"保存统计数据失败: {e}")

    def get_quota(self):
        """获取真实的Coding Plan配额数据"""
        if not self.api_key:
            return None, "未配置API Key"
        if not HAS_REQUESTS:
            return None, "缺少requests库，请运行: pip install requests"

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            response = requests.get(self.quota_url, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("code") == 200:
                    return result.get("data"), "成功"
                else:
                    return None, result.get("msg", "获取失败")
            elif response.status_code == 401:
                return None, "API Key无效"
            elif response.status_code == 429:
                return None, "请求过于频繁"
            else:
                return None, f"API错误: {response.status_code}"
        except requests.Timeout:
            return None, "请求超时"
        except requests.ConnectionError:
            return None, "网络连接失败"
        except requests.RequestException as e:
            return None, f"请求失败: {str(e)}"

    def test_connection(self):
        """测试API连接"""
        if not self.api_key:
            return False, "未配置API Key"
        if not HAS_REQUESTS:
            return False, "缺少requests库"

        try:
            data, msg = self.get_quota()
            if data:
                return True, "API已连接"
            else:
                return False, msg
        except Exception as e:
            return False, f"连接失败: {str(e)}"

    def get_usage(self):
        """获取使用数据"""
        return {
            "model_usage": self.stats.get("model_usage", {"GLM": {"calls": 0, "tokens": 0}})
        }


class GLMPlanMonitor:
    """监控悬浮窗"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GLM Plan Monitor")
        self.api = GLMAPIClient()
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glm_monitor_config.json")
        self.config = self.load_config()

        # 设置API Key
        if self.config.get("api_key"):
            self.api.api_key = self.config["api_key"]

        self.mcp_labels = {}
        self.mcp_bars = {}
        self.data = {}
        self.running = True
        self.compact_mode = False  # 精简模式状态

        self.setup_styles()
        self.setup_window()
        self.setup_ui()

        # 使用after代替线程直接调用，确保线程安全
        self.schedule_fetch()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.make_draggable()

    def setup_styles(self):
        """配置ttk样式"""
        style = ttk.Style()
        style.theme_use('clam')

        # 进度条样式
        style.configure("Custom.Horizontal.TProgressbar",
                       troughcolor=THEME['bg_medium'],
                       background=THEME['accent'],
                       thickness=8)

        # 下拉框样式
        style.configure("Custom.TCombobox",
                       fieldbackground=THEME['bg_medium'],
                       background=THEME['bg_light'],
                       foreground=THEME['text_primary'],
                       arrowcolor=THEME['text_primary'],
                       borderwidth=0,
                       relief='flat')

        style.map("Custom.TCombobox",
                 fieldbackground=[('readonly', THEME['bg_medium'])],
                 selectbackground=[('readonly', THEME['bg_light'])],
                 selectforeground=[('readonly', THEME['text_primary'])])

        # 滚动条样式
        style.configure("Custom.Vertical.TScrollbar",
                       background=THEME['bg_light'],
                       troughcolor=THEME['bg_medium'],
                       arrowcolor=THEME['text_primary'])

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"加载配置失败: {e}")

        return {
            "refresh_interval": 30,
            "plan_type": "Lite",
            "api_key": "",
            "models": ["GLM"],
            "plan_quotas": {
                "Lite": {"hourly": 1200, "weekly": 25000, "monthly": 100000},
                "Pro": {"hourly": 6000, "weekly": 125000, "monthly": 500000},
                "Max": {"hourly": 20000, "weekly": 420000, "monthly": 2000000}
            }
        }

    def save_config(self):
        """保存配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"保存配置失败: {e}")

    def setup_window(self):
        """设置窗口属性"""
        self.root.attributes('-topmost', True)
        self.root.geometry(f"320x460+50+50")
        self.root.overrideredirect(True)
        self.root.attributes('-alpha', 0.95)
        self.root.configure(bg=THEME['bg_dark'])
        if HAS_WIN32:
            self.root.after(100, self.set_win_style)

    def set_win_style(self):
        """设置Windows窗口样式"""
        if HAS_WIN32:
            try:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_TOOLWINDOW)
            except Exception as e:
                logger.warning(f"设置窗口样式失败: {e}")

    def setup_ui(self):
        """设置UI界面"""
        # 主框架
        self.main_frame = tk.Frame(self.root, bg=THEME['bg_dark'], padx=12, pady=12)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题栏
        self.setup_title_bar()

        # 状态栏
        self.setup_status_bar()

        # 配额使用区块
        self.setup_quota_section()

        # MCP使用分布区块
        self.setup_mcp_section()

        # 底部信息
        self.setup_footer()

        # 右键菜单
        self.setup_context_menu()

    def setup_title_bar(self):
        """设置标题栏"""
        self.title_frame = tk.Frame(self.main_frame, bg=THEME['bg_dark'])
        self.title_frame.pack(fill=tk.X, pady=(0, 8))

        # 左侧标题
        left_frame = tk.Frame(self.title_frame, bg=THEME['bg_dark'])
        left_frame.pack(side=tk.LEFT)

        self.title_label = tk.Label(left_frame, text="GLM Coding Plan",
                font=("Microsoft YaHei UI", 11, "bold"),
                fg=THEME['accent'], bg=THEME['bg_dark'])
        self.title_label.pack(side=tk.LEFT)

        self.plan_label = tk.Label(left_frame,
                                   text=f"[{self.config.get('plan_type', 'Lite')}]",
                                   font=("Microsoft YaHei UI", 9),
                                   fg=THEME['warning'], bg=THEME['bg_dark'])
        self.plan_label.pack(side=tk.LEFT, padx=(6, 0))

        # 小窗口模式下的配额显示（初始隐藏）
        self.hourly_brief_label = tk.Label(left_frame, text="",
                                   font=("Microsoft YaHei UI", 11, "bold"),
                                   fg="#4ecdc4", bg=THEME['bg_dark'])
        self.weekly_brief_label = tk.Label(left_frame, text="",
                                   font=("Microsoft YaHei UI", 11, "bold"),
                                   fg="#45b7d1", bg=THEME['bg_dark'])

        # 右侧按钮
        right_frame = tk.Frame(self.title_frame, bg=THEME['bg_dark'])
        right_frame.pack(side=tk.RIGHT)

        # 小窗口模式切换按钮
        self.compact_btn = tk.Label(right_frame, text="▼",
                               font=("Arial", 10),
                               fg=THEME['text_secondary'], bg=THEME['bg_dark'],
                               cursor='hand2')
        self.compact_btn.pack(side=tk.LEFT, padx=2)
        self.compact_btn.bind('<Button-1>', lambda e: self.toggle_compact_mode())
        self.compact_btn.bind('<Enter>', lambda e: self.compact_btn.config(fg=THEME['accent']))
        self.compact_btn.bind('<Leave>', lambda e: self.compact_btn.config(fg=THEME['text_secondary']))

        settings_btn = tk.Label(right_frame, text="⚙",
                               font=("Arial", 12),
                               fg=THEME['text_secondary'], bg=THEME['bg_dark'],
                               cursor='hand2')
        settings_btn.pack(side=tk.LEFT, padx=2)
        settings_btn.bind('<Button-1>', lambda e: self.show_settings())
        settings_btn.bind('<Enter>', lambda e: settings_btn.config(fg=THEME['accent']))
        settings_btn.bind('<Leave>', lambda e: settings_btn.config(fg=THEME['text_secondary']))

        close_btn = tk.Label(right_frame, text="×",
                            font=("Arial", 14, "bold"),
                            fg=THEME['accent_alt'], bg=THEME['bg_dark'],
                            cursor='hand2')
        close_btn.pack(side=tk.LEFT, padx=2)
        close_btn.bind('<Button-1>', lambda e: self.close())

    def setup_status_bar(self):
        """设置状态栏"""
        self.status_frame = tk.Frame(self.main_frame, bg=THEME['bg_dark'])
        self.status_frame.pack(fill=tk.X, pady=(0, 8))

        # 左侧：状态点和状态文字
        left_status = tk.Frame(self.status_frame, bg=THEME['bg_dark'])
        left_status.pack(side=tk.LEFT)

        self.status_dot = tk.Label(left_status, text="●",
                                   font=("Arial", 8),
                                   fg=THEME['accent'], bg=THEME['bg_dark'])
        self.status_dot.pack(side=tk.LEFT)

        self.status_label = tk.Label(left_status, text=" 连接中...",
                                     font=("Microsoft YaHei UI", 9),
                                     fg=THEME['text_secondary'], bg=THEME['bg_dark'])
        self.status_label.pack(side=tk.LEFT)

        # 右侧：刷新按钮
        refresh_btn = tk.Label(self.status_frame, text="↻",
                               font=("Arial", 12),
                               fg=THEME['text_secondary'], bg=THEME['bg_dark'],
                               cursor='hand2')
        refresh_btn.pack(side=tk.RIGHT)
        refresh_btn.bind('<Button-1>', lambda e: self.fetch_data())
        refresh_btn.bind('<Enter>', lambda e: refresh_btn.config(fg=THEME['accent']))
        refresh_btn.bind('<Leave>', lambda e: refresh_btn.config(fg=THEME['text_secondary']))

    def setup_quota_section(self):
        """设置配额区块"""
        self.quota_frame = tk.Frame(self.main_frame, bg=THEME['bg_medium'], padx=10, pady=8)
        self.quota_frame.pack(fill=tk.X, pady=(0, 8))

        # 区块标题
        tk.Label(self.quota_frame, text="📊 配额使用",
                font=("Microsoft YaHei UI", 10, "bold"),
                fg=THEME['text_primary'], bg=THEME['bg_medium']).pack(anchor='w', pady=(0, 8))

        # 配额行
        self.create_quota_row(self.quota_frame, "每5小时:", "#4ecdc4", "hourly")
        self.create_quota_row(self.quota_frame, "每周:", "#45b7d1", "weekly")
        self.create_quota_row(self.quota_frame, "月度MCP:", "#a6e3a1", "monthly_mcp")
        self.create_quota_row(self.quota_frame, "Token消耗:", "#f38ba8", "tokens")

    def create_quota_row(self, parent, label_text, color, key):
        """创建配额行"""
        row = tk.Frame(parent, bg=THEME['bg_medium'])
        row.pack(fill=tk.X, pady=2)

        # 标签
        tk.Label(row, text=label_text,
                font=("Microsoft YaHei UI", 9),
                fg=THEME['text_secondary'], bg=THEME['bg_medium'],
                width=10, anchor='w').pack(side=tk.LEFT)

        # 数值
        label = tk.Label(row, text="--",
                        font=("Microsoft YaHei UI", 9, "bold"),
                        fg=color, bg=THEME['bg_medium'])
        label.pack(side=tk.LEFT)

        # 重置时间
        reset_label = tk.Label(row, text="",
                              font=("Microsoft YaHei UI", 8),
                              fg=THEME['text_muted'], bg=THEME['bg_medium'])
        reset_label.pack(side=tk.LEFT, padx=(5, 0))

        # 进度条
        bar = ttk.Progressbar(row, length=60, mode='determinate',
                             style="Custom.Horizontal.TProgressbar")
        bar.pack(side=tk.RIGHT)

        setattr(self, f"{key}_row", row)
        setattr(self, f"{key}_label", label)
        setattr(self, f"{key}_bar", bar)
        setattr(self, f"{key}_reset", reset_label)

    def setup_mcp_section(self):
        """设置MCP区块"""
        self.mcp_frame = tk.Frame(self.main_frame, bg=THEME['bg_medium'], padx=10, pady=8)
        self.mcp_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # 区块标题
        tk.Label(self.mcp_frame, text="🔧 MCP使用分布",
                font=("Microsoft YaHei UI", 10, "bold"),
                fg=THEME['text_primary'], bg=THEME['bg_medium']).pack(anchor='w', pady=(0, 8))

        # MCP行容器
        self.mcp_rows_frame = tk.Frame(self.mcp_frame, bg=THEME['bg_medium'])
        self.mcp_rows_frame.pack(fill=tk.BOTH, expand=True)

    def setup_footer(self):
        """设置底部信息"""
        self.footer_frame = tk.Frame(self.main_frame, bg=THEME['bg_dark'])
        self.footer_frame.pack(fill=tk.X)

        self.time_label = tk.Label(self.footer_frame, text="更新: --",
                                   font=("Microsoft YaHei UI", 8),
                                   fg=THEME['text_muted'], bg=THEME['bg_dark'])
        self.time_label.pack(anchor='w')

    def setup_context_menu(self):
        """设置右键菜单"""
        menu = tk.Menu(self.root, tearoff=0,
                      bg=THEME['bg_medium'], fg=THEME['text_primary'],
                      activebackground=THEME['bg_light'],
                      activeforeground=THEME['text_primary'],
                      font=("Microsoft YaHei UI", 9))
        menu.add_command(label="🔄 刷新", command=self.fetch_data)
        menu.add_command(label="⚙ 设置", command=self.show_settings)
        menu.add_separator()
        menu.add_command(label="✕ 退出", command=self.close)
        self.root.bind('<Button-3>', lambda e: menu.tk_popup(e.x_root, e.y_root))

    def update_mcp_rows(self, usage_details):
        """更新MCP使用分布"""
        # 清除旧内容
        for widget in self.mcp_rows_frame.winfo_children():
            widget.destroy()

        self.mcp_labels = {}
        self.mcp_bars = {}

        if not usage_details:
            tk.Label(self.mcp_rows_frame, text="暂无使用数据",
                    font=("Microsoft YaHei UI", 9),
                    fg=THEME['text_muted'], bg=THEME['bg_medium']).pack(anchor='w')
            return

        colors = ['#cba6f7', '#f38ba8', '#a6e3a1', '#f9e2af', '#89b4fa', '#94e2d5', '#fab387']

        total_usage = sum(d.get("usage", 0) for d in usage_details) or 1

        # 动态调整窗口高度（仅在非精简模式下）
        self.adjust_window_height()

        for i, detail in enumerate(usage_details):
            model_code = detail.get("modelCode", "unknown")
            usage = detail.get("usage", 0)
            percentage = (usage / total_usage) * 100
            color = colors[i % len(colors)]

            row = tk.Frame(self.mcp_rows_frame, bg=THEME['bg_medium'])
            row.pack(fill=tk.X, pady=1)

            # 模型名称
            tk.Label(row, text=f"{model_code}:",
                    font=("Microsoft YaHei UI", 9),
                    fg=THEME['text_secondary'], bg=THEME['bg_medium'],
                    width=14, anchor='w').pack(side=tk.LEFT)

            # 使用量
            label = tk.Label(row, text=f"{usage} ({percentage:.1f}%)",
                            font=("Microsoft YaHei UI", 9, "bold"),
                            fg=color, bg=THEME['bg_medium'])
            label.pack(side=tk.LEFT)

            # 进度条
            bar = ttk.Progressbar(row, length=50, mode='determinate',
                                 style="Custom.Horizontal.TProgressbar")
            bar.pack(side=tk.RIGHT)
            bar['value'] = percentage

            self.mcp_labels[model_code] = label
            self.mcp_bars[model_code] = bar

    def make_draggable(self):
        """使窗口可拖动"""
        x, y = 0, 0

        def start(e):
            nonlocal x, y
            x, y = e.x, e.y

        def drag(e):
            self.root.geometry(f"+{self.root.winfo_x() + e.x - x}+{self.root.winfo_y() + e.y - y}")

        self.root.bind('<Button-1>', start)
        self.root.bind('<B1-Motion>', drag)

    def toggle_compact_mode(self):
        """切换小窗口模式"""
        self.compact_mode = not self.compact_mode

        if self.compact_mode:
            # === 小窗口模式 ===
            self.compact_btn.config(text="▲")

            # 隐藏标题文字，显示配额
            self.title_label.pack_forget()
            self.plan_label.pack_forget()
            h_pct = self.data.get('hourly_percentage', 0)
            w_pct = self.data.get('weekly_percentage', 0)
            self.hourly_brief_label.config(text=f"5h: {h_pct}%")
            self.weekly_brief_label.config(text=f"周: {w_pct}%")
            self.hourly_brief_label.pack(side=tk.LEFT)
            self.weekly_brief_label.pack(side=tk.LEFT, padx=(12, 0))

            # 隐藏所有详细区块
            self.status_frame.pack_forget()
            self.quota_frame.pack_forget()
            self.mcp_frame.pack_forget()
            self.footer_frame.pack_forget()

            # 设置小窗口模式窗口大小（只显示标题栏）
            self.root.geometry("320x45")
        else:
            # === 展开模式 ===
            self.compact_btn.config(text="▼")

            # 恢复标题文字，隐藏配额
            self.hourly_brief_label.pack_forget()
            self.weekly_brief_label.pack_forget()
            self.title_label.pack(side=tk.LEFT)
            self.plan_label.pack(side=tk.LEFT, padx=(6, 0))

            # 按原始顺序重新显示所有区块
            self.status_frame.pack(fill=tk.X, pady=(0, 8))
            self.quota_frame.pack(fill=tk.X, pady=(0, 8))
            self.mcp_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
            self.footer_frame.pack(fill=tk.X)

            # 恢复正常窗口高度
            self.adjust_window_height()

    def adjust_window_height(self):
        """根据内容动态调整窗口高度"""
        if self.compact_mode:
            return

        mcp_count = len(self.data.get('usage_details', []))
        base_height = 330
        new_height = base_height + mcp_count * 24
        self.root.geometry(f"320x{new_height}")

    def show_settings(self):
        """显示设置窗口"""
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.geometry("400x580")
        win.attributes('-topmost', True)
        win.configure(bg=THEME['bg_dark'])
        win.resizable(False, False)

        # 标题
        tk.Label(win, text="⚙ 设置",
                font=("Microsoft YaHei UI", 14, "bold"),
                fg=THEME['accent'], bg=THEME['bg_dark']).pack(pady=15)

        content_frame = tk.Frame(win, bg=THEME['bg_dark'], padx=25)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # API Key
        self.create_setting_row(content_frame, "API Key:", "api_key",
                               self.config.get("api_key", ""), show="*")

        # 套餐类型
        self.create_setting_combobox(content_frame, "套餐类型:", "plan_type",
                                    ["Lite", "Pro", "Max"], self.config.get("plan_type", "Lite"))

        # 刷新间隔
        self.create_setting_row(content_frame, "刷新间隔(秒):", "refresh_interval",
                               str(self.config.get("refresh_interval", 30)))

        # 模型选择区域
        model_frame = tk.LabelFrame(content_frame, text=" 已选模型 ",
                                    font=("Microsoft YaHei UI", 9),
                                    fg=THEME['text_secondary'], bg=THEME['bg_dark'],
                                    bd=1, relief='solid')
        model_frame.pack(fill=tk.X, pady=10)

        # 列表框
        list_frame = tk.Frame(model_frame, bg=THEME['bg_dark'])
        list_frame.pack(fill=tk.X, padx=8, pady=8)

        listbox = tk.Listbox(list_frame, height=4,
                            bg=THEME['bg_medium'], fg=THEME['text_primary'],
                            selectbackground=THEME['accent'], selectforeground='#000',
                            font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=0)
        listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                command=listbox.yview, bg=THEME['bg_medium'])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)

        for model in self.config.get("models", ["GLM"]):
            listbox.insert(tk.END, model)

        # 添加/删除按钮行
        btn_row = tk.Frame(model_frame, bg=THEME['bg_dark'])
        btn_row.pack(fill=tk.X, padx=8, pady=(0, 8))

        add_var = tk.StringVar()
        add_combo = ttk.Combobox(btn_row, textvariable=add_var,
                                values=AVAILABLE_MODELS, state="readonly",
                                width=12, style="Custom.TCombobox",
                                font=("Microsoft YaHei UI", 9))
        add_combo.pack(side=tk.LEFT)

        def add_model():
            model = add_var.get()
            if model and model not in listbox.get(0, tk.END):
                listbox.insert(tk.END, model)

        tk.Button(btn_row, text="添加",
                 font=("Microsoft YaHei UI", 8),
                 bg=THEME['accent'], fg='#000',
                 activebackground=THEME['accent'],
                 command=add_model, bd=0, padx=8, pady=2).pack(side=tk.LEFT, padx=5)

        def remove_model():
            selection = listbox.curselection()
            if selection:
                listbox.delete(selection[0])

        tk.Button(btn_row, text="删除",
                 font=("Microsoft YaHei UI", 8),
                 bg=THEME['accent_alt'], fg='#fff',
                 activebackground=THEME['accent_alt'],
                 command=remove_model, bd=0, padx=8, pady=2).pack(side=tk.RIGHT)

        # 保存按钮
        def save():
            self.config["api_key"] = self.setting_vars["api_key"].get()
            self.config["plan_type"] = self.setting_vars["plan_type"].get()
            try:
                self.config["refresh_interval"] = int(self.setting_vars["refresh_interval"].get() or 30)
            except ValueError:
                self.config["refresh_interval"] = 30

            models = list(listbox.get(0, tk.END))
            if not models:
                models = ["GLM"]
            self.config["models"] = models

            self.api.api_key = self.config["api_key"]
            self.save_config()
            self.plan_label.config(text=f"[{self.config['plan_type']}]")

            win.destroy()
            self.fetch_data()
            messagebox.showinfo("成功", "设置已保存!")

        save_btn = tk.Button(win, text="💾 保存设置",
                            font=("Microsoft YaHei UI", 11, "bold"),
                            bg=THEME['accent'], fg='#000',
                            activebackground=THEME['accent'],
                            width=15, height=2, bd=0,
                            command=save)
        save_btn.pack(pady=20)

    def create_setting_row(self, parent, label_text, key, default_value, show=None):
        """创建设置行"""
        if not hasattr(self, 'setting_vars'):
            self.setting_vars = {}

        frame = tk.Frame(parent, bg=THEME['bg_dark'])
        frame.pack(fill=tk.X, pady=6)

        tk.Label(frame, text=label_text,
                font=("Microsoft YaHei UI", 10),
                fg=THEME['text_primary'], bg=THEME['bg_dark']).pack(anchor='w')

        entry_frame = tk.Frame(frame, bg=THEME['bg_dark'])
        entry_frame.pack(fill=tk.X, pady=2)

        var = tk.StringVar(value=default_value)
        entry = tk.Entry(entry_frame, textvariable=var,
                        font=("Microsoft YaHei UI", 10),
                        bg=THEME['bg_medium'], fg=THEME['text_primary'],
                        insertbackground=THEME['text_primary'],
                        bd=0, highlightthickness=1,
                        highlightbackground=THEME['bg_light'],
                        highlightcolor=THEME['accent'],
                        show=show)
        entry.pack(fill=tk.X, ipady=5)

        self.setting_vars[key] = var

        # 显示/隐藏按钮（仅对密码字段）
        if show:
            def toggle():
                if entry.cget('show') == '':
                    entry.config(show='*')
                    toggle_btn.config(text='显示')
                else:
                    entry.config(show='')
                    toggle_btn.config(text='隐藏')

            toggle_btn = tk.Button(entry_frame, text="显示",
                                  font=("Microsoft YaHei UI", 8),
                                  bg=THEME['bg_light'], fg=THEME['text_secondary'],
                                  activebackground=THEME['bg_light'],
                                  bd=0, padx=6, pady=1,
                                  command=toggle)
            toggle_btn.pack(anchor='w', pady=2)

    def create_setting_combobox(self, parent, label_text, key, values, default_value):
        """创建设置下拉框"""
        if not hasattr(self, 'setting_vars'):
            self.setting_vars = {}

        frame = tk.Frame(parent, bg=THEME['bg_dark'])
        frame.pack(fill=tk.X, pady=6)

        tk.Label(frame, text=label_text,
                font=("Microsoft YaHei UI", 10),
                fg=THEME['text_primary'], bg=THEME['bg_dark']).pack(anchor='w')

        var = tk.StringVar(value=default_value)
        combo = ttk.Combobox(frame, textvariable=var,
                            values=values, state="readonly",
                            style="Custom.TCombobox",
                            font=("Microsoft YaHei UI", 10))
        combo.pack(fill=tk.X, pady=2)

        self.setting_vars[key] = var

    def schedule_fetch(self):
        """调度数据获取"""
        if self.running:
            self.fetch_data()
            interval = self.config.get("refresh_interval", 30) * 1000
            self.root.after(interval, self.schedule_fetch)

    def fetch_data(self):
        """获取数据"""
        try:
            quota_data, msg = self.api.get_quota()

            if quota_data:
                limits = quota_data.get("limits", [])
                level = quota_data.get("level", "lite").upper()

                self.plan_label.config(text=f"[{level}]")

                hourly_data = {}
                hourly_token_data = {}
                weekly_data = {}
                monthly_mcp_data = {}
                tokens_data = {}

                for limit in limits:
                    limit_type = limit.get("type")
                    unit = limit.get("unit")

                    if limit_type == "TIME_LIMIT" and unit == 5:
                        hourly_data = {
                            "percentage": limit.get("percentage", 0),
                            "usage_details": limit.get("usageDetails", [])
                        }
                        # MCP月度配额
                        monthly_mcp_data = {
                            "used": limit.get("currentValue", 0),
                            "total": limit.get("usage", 0),
                            "next_reset": limit.get("nextResetTime", 0)
                        }
                    elif limit_type == "TOKENS_LIMIT":
                        if unit == 3:
                            hourly_token_data = {
                                "percentage": limit.get("percentage", 0),
                                "next_reset": limit.get("nextResetTime", 0),
                                "used": limit.get("currentValue", 0),
                                "total": limit.get("limit", 0)
                            }
                            # Token消耗数据
                            tokens_data = {
                                "used": limit.get("currentValue", 0),
                                "total": limit.get("limit", 0)
                            }
                        elif unit == 6:
                            weekly_data = {
                                "percentage": limit.get("percentage", 0),
                                "next_reset": limit.get("nextResetTime", 0)
                            }

                hourly_pct = hourly_token_data.get("percentage", 0) if hourly_token_data else hourly_data.get("percentage", 0)

                self.data = {
                    "hourly_percentage": hourly_pct,
                    "hourly_reset": hourly_token_data.get("next_reset", 0) if hourly_token_data else 0,
                    "weekly_percentage": weekly_data.get("percentage", 0) if weekly_data else 0,
                    "weekly_reset": weekly_data.get("next_reset", 0) if weekly_data else 0,
                    "monthly_mcp_used": monthly_mcp_data.get("used", 0),
                    "monthly_mcp_total": monthly_mcp_data.get("total", 0),
                    "monthly_mcp_reset": monthly_mcp_data.get("next_reset", 0),
                    "tokens_used": tokens_data.get("used", 0),
                    "tokens_total": tokens_data.get("total", 0),
                    "usage_details": hourly_data.get("usage_details", []),
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "status": "API已连接",
                    "level": level
                }

            else:
                self.data = {
                    "status": f"错误: {msg}",
                    "hourly_percentage": 0,
                    "hourly_reset": 0,
                    "weekly_percentage": 0,
                    "weekly_reset": 0,
                    "monthly_mcp_used": 0,
                    "monthly_mcp_total": 0,
                    "monthly_mcp_reset": 0,
                    "tokens_used": 0,
                    "tokens_total": 0,
                    "usage_details": [],
                    "time": datetime.now().strftime("%H:%M:%S")
                }

        except Exception as e:
            logger.error(f"数据获取错误: {e}")
            self.data = {"status": f"错误: {e}"}

        self.update_ui()

    def format_reset_time(self, timestamp_ms):
        """格式化重置时间"""
        if not timestamp_ms:
            return ""
        try:
            reset_ts = timestamp_ms / 1000
            reset_dt = datetime.fromtimestamp(reset_ts)
            now = datetime.now()
            diff = reset_dt - now
            if diff.total_seconds() > 0:
                total_mins = int(diff.total_seconds() // 60)
                if total_mins >= 60:
                    hours = total_mins // 60
                    mins = total_mins % 60
                    return f"({hours}h{mins}m)"
                else:
                    return f"({total_mins}m)"
            else:
                return "(即将)"
        except (ValueError, OSError):
            return ""

    def get_usage_color(self, percentage):
        """根据使用率返回颜色"""
        if percentage >= 80:
            return '#e94560'  # 红色 - 高使用率
        elif percentage >= 50:
            return '#ffd700'  # 黄色 - 中等使用率
        else:
            return '#4ecca3'  # 绿色 - 低使用率

    def update_ui(self):
        """更新UI显示"""
        try:
            d = getattr(self, 'data', {})
            status = d.get("status", "未知")
            self.status_label.config(text=f" {status}")

            if '错误' in status:
                self.status_dot.config(fg=THEME['accent_alt'])
                self.status_label.config(fg=THEME['accent_alt'])
            elif 'API已连接' in status:
                self.status_dot.config(fg=THEME['accent'])
                self.status_label.config(fg=THEME['accent'])
            else:
                self.status_dot.config(fg=THEME['warning'])
                self.status_label.config(fg=THEME['text_secondary'])

            # 每小时配额
            h_pct = d.get('hourly_percentage', 0)
            h_color = self.get_usage_color(h_pct)
            self.hourly_label.config(text=f"{h_pct}%", fg=h_color)
            self.hourly_bar['value'] = h_pct
            self.hourly_reset.config(text=self.format_reset_time(d.get('hourly_reset', 0)))

            # 周配额
            w_pct = d.get('weekly_percentage', 0)
            w_color = self.get_usage_color(w_pct)
            self.weekly_label.config(text=f"{w_pct}%", fg=w_color)
            self.weekly_bar['value'] = w_pct
            self.weekly_reset.config(text=self.format_reset_time(d.get('weekly_reset', 0)))

            # 月度MCP配额
            m_used = d.get('monthly_mcp_used', 0)
            m_total = d.get('monthly_mcp_total', 0)
            m_pct = (m_used / m_total * 100) if m_total > 0 else 0
            m_color = self.get_usage_color(m_pct)
            self.monthly_mcp_label.config(text=f"{m_used}/{m_total}", fg=m_color)
            if m_total > 0:
                self.monthly_mcp_bar['value'] = m_pct
            else:
                self.monthly_mcp_bar['value'] = 0
            self.monthly_mcp_reset.config(text=self.format_reset_time(d.get('monthly_mcp_reset', 0)))

            # Token消耗
            t_used = d.get('tokens_used', 0)
            t_total = d.get('tokens_total', 0)
            t_pct = (t_used / t_total * 100) if t_total > 0 else 0
            t_color = self.get_usage_color(t_pct)
            # 格式化显示：大数字用K单位
            def format_tokens(n):
                if n >= 1000000:
                    return f"{n/1000000:.1f}M"
                elif n >= 1000:
                    return f"{n/1000:.1f}K"
                return str(n)
            self.tokens_label.config(text=f"{format_tokens(t_used)}/{format_tokens(t_total)}", fg=t_color)
            self.tokens_bar['value'] = t_pct

            # 小窗口模式下更新配额显示
            if self.compact_mode:
                self.hourly_brief_label.config(text=f"5h: {h_pct}%", fg=h_color)
                self.weekly_brief_label.config(text=f"周: {w_pct}%", fg=w_color)

            # MCP使用分布
            self.update_mcp_rows(d.get('usage_details', []))

            # 只显示更新时间
            self.time_label.config(text=f"更新: {d.get('time', '--')}")

        except Exception as e:
            logger.error(f"UI更新错误: {e}")

    def close(self):
        """关闭窗口"""
        self.running = False
        self.root.destroy()

    def run(self):
        """运行程序"""
        if not self.config.get("api_key"):
            self.root.after(500, self.show_settings)
        self.root.mainloop()


if __name__ == "__main__":
    try:
        import sys, io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except Exception:
        pass

    print("GLM Coding Plan Monitor 启动...")
    logger.info("程序启动")
    GLMPlanMonitor().run()
