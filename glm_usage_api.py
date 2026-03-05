#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLM Usage API Encapsulation
Ref: query-usage.mjs
"""

import os
import json
import requests
import datetime
import logging
from urllib.parse import urlparse
from dotenv import load_dotenv

# Matplotlib setup for thread-safety and headless mode
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    import numpy as np
    
    # Configure global styles once
    plt.style.use('dark_background')
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial']
    plt.rcParams['axes.unicode_minus'] = False
    
    BRIGHT_GREEN = '#00FF00'
    DARK_GREEN = '#006400'
    AXIS_GREEN = '#32CD32'
    
    plt.rcParams['text.color'] = AXIS_GREEN
    plt.rcParams['axes.labelcolor'] = AXIS_GREEN
    plt.rcParams['xtick.color'] = AXIS_GREEN
    plt.rcParams['ytick.color'] = AXIS_GREEN
    plt.rcParams['axes.edgecolor'] = AXIS_GREEN
    
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from scipy.interpolate import make_interp_spline
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# 配置日志
logger = logging.getLogger(__name__)

class GLMUsageAPI:
    def __init__(self, config_path=None):
        self.base_url = "https://open.bigmodel.cn"
        self.api_key = None
        self._load_env()

    def _load_env(self):
        """加载环境变量"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(current_dir, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            self.api_key = os.getenv("GLM_API_KEY")
            if not self.api_key:
                 logger.warning(".env 文件中未找到 GLM_API_KEY")
        else:
            logger.warning(f".env 文件未找到: {env_path}")

    def _get_headers(self):
        if not self.api_key:
            raise ValueError("API Key not set")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept-Language": "en-US,en"
        }

    def _make_request(self, endpoint, params=None):
        url = f"{self.base_url}{endpoint}"
        try:
            headers = self._get_headers()
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败 [{endpoint}]: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"响应内容: {e.response.text}")
            return None
        except ValueError as e:
            logger.error(f"配置错误: {e}")
            return None

    def get_time_range(self, range_type=None):
        """
        获取时间范围
        range_type: "5h", "24h", "day"
        """
        if range_type is None:
            range_type = os.getenv("GLM_USAGE_TIME_RANGE", "5h")
            
        now = datetime.datetime.now()

        if range_type == "day":
             start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
             end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif range_type == "5h":
             end_date = now.replace(minute=59, second=59, microsecond=999999)
             start_date = end_date - datetime.timedelta(hours=4)
             start_date = start_date.replace(minute=0, second=0, microsecond=0)
        elif range_type == "7d":
             # 7天
             end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
             start_date = end_date - datetime.timedelta(days=6)
             start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        elif range_type == "30d":
             # 30天
             end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
             start_date = end_date - datetime.timedelta(days=29)
             start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
             # 默认 24h
             end_date = now.replace(minute=59, second=59, microsecond=999999)
             start_date = end_date - datetime.timedelta(hours=23)
             start_date = start_date.replace(minute=0, second=0, microsecond=0)
        
        return start_date.strftime("%Y-%m-%d %H:%M:%S"), end_date.strftime("%Y-%m-%d %H:%M:%S")

    def generate_usage_chart(self, model_usage, data_dir, suffix="5h"):
        """生成模型使用量图表"""
        if not HAS_MATPLOTLIB:
            logger.warning("matplotlib not found, skipping chart generation")
            return

        fig = None
        try:
            data = model_usage.get("data", {})
            if not data: return

            x_time = data.get("x_time", [])
            model_calls = [x if x is not None else 0 for x in data.get("modelCallCount", [])]
            tokens_usage = [x if x is not None else 0 for x in data.get("tokensUsage", [])]

            if not x_time: return

            # 确保数据长度一致且只保留最近 N 个点
            target_len = 5
            if suffix == "24h": target_len = 24
            elif suffix == "7d": target_len = 7
            elif suffix == "30d": target_len = 30
            
            # 使用负索引截取，确保拿到的是“最近”的数据点
            x_time = x_time[-target_len:]
            model_calls = model_calls[-target_len:]
            tokens_usage = tokens_usage[-target_len:]
            
            # 如果数据点不足，补齐前面的数据
            if len(x_time) < target_len:
                pad_len = target_len - len(x_time)
                x_time = ["--"] * pad_len + x_time
                model_calls = [0] * pad_len + model_calls
                tokens_usage = [0] * pad_len + tokens_usage
            
            # 处理时间标签
            x_labels = []
            x_indices = np.arange(len(x_time))
            
            for t in x_time:
                try:
                    if suffix in ["7d", "30d"]:
                        if " " in t:
                             x_labels.append(t.split(" ")[0][5:]) 
                        else:
                             x_labels.append(t)
                    elif " " in t:
                        hour_part = t.split(" ")[1].split(":")[0]
                        if suffix == "5h":
                             x_labels.append(f"{hour_part}:00")
                        else:
                             x_labels.append(str(int(hour_part)))
                    else:
                        x_labels.append(t)
                except:
                    x_labels.append(t)

            # 根据数据范围调整图表尺寸
            chart_width = 16 if suffix == "30d" else 12
            # 明确创建 Figure 对象，方便后续关闭
            fig = plt.figure(figsize=(chart_width, 6))
            ax1 = fig.add_subplot(111)
            
            fig.patch.set_facecolor('black')
            ax1.set_facecolor('black')
            ax1.spines['top'].set_visible(False)
            ax1.spines['right'].set_visible(False)
            ax1.set_ylabel('Model Calls', fontweight='bold')
            
            def human_format(num, pos=None):
                if num >= 1000000: return f'{num/1000000:.1f}M'
                elif num >= 1000: return f'{num/1000:.1f}K'
                else: return str(int(num))

            actual_len = len(x_time)
            use_spline = HAS_SCIPY and actual_len > 3 and suffix in ["5h", "24h"]
            if use_spline:
                x_new = np.linspace(x_indices.min(), x_indices.max(), 300)
                try:
                    spl = make_interp_spline(x_indices, model_calls, k=3)
                    y_smooth = spl(x_new)
                    y_smooth = np.maximum(y_smooth, 0)
                    ax1.plot(x_new, y_smooth, color=BRIGHT_GREEN, linewidth=2, label='Model Calls')
                    ax1.plot(x_indices, model_calls, color=BRIGHT_GREEN, marker='o', markersize=6, linestyle='None')
                except Exception as e:
                    logger.warning(f"Spline interpolation failed: {e}")
                    ax1.plot(x_indices, model_calls, color=BRIGHT_GREEN, marker='o', markersize=6, linewidth=2, label='Model Calls')
            else:
                ax1.plot(x_indices, model_calls, color=BRIGHT_GREEN, marker='o', markersize=6, linewidth=2, label='Model Calls')
            
            # 在折线上添加数值标注
            for i, val in enumerate(model_calls):
                if val > 0:
                    ax1.text(i, val, human_format(val), color=BRIGHT_GREEN, 
                            ha='center', va='bottom', fontsize=9, fontweight='bold',
                            bbox=dict(facecolor='black', alpha=0.5, edgecolor='none', pad=1))

            ax1.grid(False)
            ax2 = ax1.twinx()  
            ax2.set_ylabel('Tokens Usage', fontweight='bold')
            ax2.spines['top'].set_visible(False)
            ax2.spines['left'].set_visible(False)
            ax2.bar(x_indices, tokens_usage, color=DARK_GREEN, alpha=0.6, label='Tokens Usage', width=0.6)
            
            # 在柱状图上添加数值标注
            for i, val in enumerate(tokens_usage):
                if val > 0:
                    ax2.text(i, val, human_format(val), color=AXIS_GREEN, 
                            ha='center', va='bottom', fontsize=8, alpha=0.8)

            ax2.yaxis.set_major_formatter(ticker.FuncFormatter(human_format))
            
            # 设置 X 轴刻度
            if suffix == "30d":
                ax1.set_xticks(x_indices)
                ax1.set_xticklabels(x_labels, rotation=45, ha='right')
            elif len(x_indices) > 10:
                step = max(len(x_indices) // 10, 1)
                ticks_to_show = x_indices[::step]
                labels_to_show = [x_labels[i] for i in range(0, len(x_labels), step)]
                ax1.set_xticks(ticks_to_show)
                ax1.set_xticklabels(labels_to_show)
            else:
                ax1.set_xticks(x_indices)
                ax1.set_xticklabels(x_labels)
                
            fig.tight_layout()

            # 保存图片
            filename = f"model_usage_chart_{suffix}.png"
            output_path = os.path.join(data_dir, filename)
            fig.savefig(output_path, dpi=100, facecolor='black')
            logger.info(f"Chart saved to {output_path}")

        except Exception as e:
            logger.error(f"Failed to generate chart: {e}")
        finally:
            # 确保显式关闭 figure，释放内存
            if fig:
                plt.close(fig)

    def _process_usage_data(self, usage_data, range_type="5h"):
        """
        根据模式补齐数据。
        """
        if not usage_data or not usage_data.get("data"):
            return usage_data

        data = usage_data["data"]
        x_time = data.get("x_time", [])
        if not x_time:
            return usage_data

        if range_type == "day":
            try:
                date_str = x_time[0].split(" ")[0]
                full_times = [f"{date_str} {str(i).zfill(2)}:00" for i in range(24)]
                return self._pad_data(usage_data, full_times, 24)
            except:
                return usage_data
        elif range_type == "5h":
            now = datetime.datetime.now()
            full_times = []
            for i in range(4, -1, -1):
                t = now - datetime.timedelta(hours=i)
                full_times.append(t.strftime("%Y-%m-%d %H:00"))
            return self._pad_data(usage_data, full_times, 5)
        elif range_type == "24h":
            now = datetime.datetime.now()
            full_times = []
            for i in range(23, -1, -1):
                t = now - datetime.timedelta(hours=i)
                full_times.append(t.strftime("%Y-%m-%d %H:00"))
            return self._pad_data(usage_data, full_times, 24)
        elif range_type == "7d":
            full_times = self._build_day_full_times(7)
            return self._aggregate_to_days(usage_data, full_times)
        elif range_type == "30d":
            full_times = self._build_day_full_times(30)
            return self._aggregate_to_days(usage_data, full_times)
            
        return usage_data

    def _build_day_full_times(self, day_count):
        now = datetime.datetime.now()
        full_times = []
        for i in range(day_count - 1, -1, -1):
            t = now - datetime.timedelta(days=i)
            full_times.append(t.strftime("%Y-%m-%d 00:00"))
        return full_times

    def _aggregate_to_days(self, usage_data, full_times):
        data = usage_data["data"]
        x_time = data.get("x_time", [])
        day_to_idx = {ts.split(" ")[0]: idx for idx, ts in enumerate(full_times)}

        for key in ["modelCallCount", "tokensUsage", "networkSearchCount", "webReadMcpCount", "zreadMcpCount"]:
            val_list = data.get(key, [])
            if val_list is None:
                val_list = []
            day_sums = [0] * len(full_times)
            has_value = [False] * len(full_times)

            for i, t in enumerate(x_time):
                if i >= len(val_list):
                    continue
                day_key = t.split(" ")[0] if isinstance(t, str) else None
                idx = day_to_idx.get(day_key)
                if idx is None:
                    continue
                val = val_list[i]
                if val is None:
                    continue
                day_sums[idx] += val
                has_value[idx] = True

            data[key] = [day_sums[i] if has_value[i] else None for i in range(len(full_times))]

        data["x_time"] = full_times
        return usage_data

    def _merge_daily_with_existing(self, usage_data, suffix):
        data = usage_data.get("data", {})
        x_time = data.get("x_time", [])
        if not x_time:
            return usage_data

        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "glm")
        old_path = os.path.join(data_dir, f"model_usage_{suffix}.json")
        if not os.path.exists(old_path):
            return usage_data

        try:
            with open(old_path, 'r', encoding='utf-8') as f:
                old = json.load(f)
        except Exception:
            return usage_data

        old_data = old.get("data", {})
        old_x_time = old_data.get("x_time", [])
        if not old_x_time:
            return usage_data

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        for key in ["modelCallCount", "tokensUsage", "networkSearchCount", "webReadMcpCount", "zreadMcpCount"]:
            new_vals = data.get(key, [])
            old_vals = old_data.get(key, [])
            if not isinstance(new_vals, list):
                continue
            old_map = {}
            for i, ts in enumerate(old_x_time):
                if i < len(old_vals):
                    old_map[ts] = old_vals[i]
            for i, ts in enumerate(x_time):
                if i >= len(new_vals):
                    continue
                day = ts.split(" ")[0] if isinstance(ts, str) else ""
                if day == today:
                    continue
                old_val = old_map.get(ts)
                new_val = new_vals[i]
                if old_val is None:
                    continue
                if new_val is None or (isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)) and new_val < old_val):
                    new_vals[i] = old_val
            data[key] = new_vals
        return usage_data

    def _pad_data(self, usage_data, full_times, target_len):
        """通用补齐逻辑"""
        data = usage_data["data"]
        x_time = data.get("x_time", [])
        
        # 补齐其它字段
        for key in ["modelCallCount", "tokensUsage", "networkSearchCount", "webReadMcpCount", "zreadMcpCount"]:
            val_list = data.get(key, [])
            if val_list is None: val_list = []
            new_vals = [None] * target_len
            for i, t in enumerate(x_time):
                if t in full_times:
                    idx = full_times.index(t)
                    if i < len(val_list):
                        new_vals[idx] = val_list[i]
            data[key] = new_vals
            
        data["x_time"] = full_times
        return usage_data

    def get_usage_for_range(self, range_type="5h"):
        """获取指定范围的使用量"""
        start_time, end_time = self.get_time_range(range_type)
        params = {"startTime": start_time, "endTime": end_time}
        logger.info(f"Fetching Model Usage ({range_type}: {start_time} - {end_time})...")
        usage = self._make_request("/api/monitor/usage/model-usage", params)
        return self._process_usage_data(usage, range_type)

    def get_tool_usage(self):
        """获取工具使用量"""
        start_time, end_time = self.get_time_range("day") # 默认工具按天
        params = {"startTime": start_time, "endTime": end_time}
        logger.info(f"Fetching Tool Usage ({start_time} - {end_time})...")
        usage = self._make_request("/api/monitor/usage/tool-usage", params)
        return self._process_usage_data(usage, "day")

    def get_quota_limit(self):
        """获取配额限制"""
        logger.info("Fetching Quota Limit...")
        return self._make_request("/api/monitor/usage/quota/limit")

    def save_usage_data(self, save_to_file=True):
        """获取并保存使用数据"""
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "glm")
        if save_to_file and not os.path.exists(data_dir):
            os.makedirs(data_dir)

        # 1. 生成 5h 图表
        usage_5h = self.get_usage_for_range("5h")
        if usage_5h and usage_5h.get("code") == 200:
            if save_to_file:
                # 同时保存为 model_usage.json (主界面兼容) 和 model_usage_5h.json
                with open(os.path.join(data_dir, "model_usage.json"), 'w', encoding='utf-8') as f:
                    json.dump(usage_5h, f, indent=2, ensure_ascii=False)
                with open(os.path.join(data_dir, "model_usage_5h.json"), 'w', encoding='utf-8') as f:
                    json.dump(usage_5h, f, indent=2, ensure_ascii=False)
                self.generate_usage_chart(usage_5h, data_dir, "5h")
        
        # 2. 生成 24h 图表
        usage_24h = self.get_usage_for_range("24h")
        if usage_24h and usage_24h.get("code") == 200:
            if save_to_file:
                with open(os.path.join(data_dir, "model_usage_24h.json"), 'w', encoding='utf-8') as f:
                    json.dump(usage_24h, f, indent=2, ensure_ascii=False)
                self.generate_usage_chart(usage_24h, data_dir, "24h")

        # 3. 生成 7d 图表
        usage_7d = self.get_usage_for_range("7d")
        if usage_7d and usage_7d.get("code") == 200:
            usage_7d = self._merge_daily_with_existing(usage_7d, "7d")
            if save_to_file:
                with open(os.path.join(data_dir, "model_usage_7d.json"), 'w', encoding='utf-8') as f:
                    json.dump(usage_7d, f, indent=2, ensure_ascii=False)
                self.generate_usage_chart(usage_7d, data_dir, "7d")

        # 4. 生成 30d 图表
        usage_30d = self.get_usage_for_range("30d")
        if usage_30d and usage_30d.get("code") == 200:
            usage_30d = self._merge_daily_with_existing(usage_30d, "30d")
            if save_to_file:
                with open(os.path.join(data_dir, "model_usage_30d.json"), 'w', encoding='utf-8') as f:
                    json.dump(usage_30d, f, indent=2, ensure_ascii=False)
                self.generate_usage_chart(usage_30d, data_dir, "30d")

        # 5. Tool Usage & Quota Limit (保持原样)
        tool_usage = self.get_tool_usage()
        if tool_usage and tool_usage.get("code") == 200 and save_to_file:
            with open(os.path.join(data_dir, "tool_usage.json"), 'w', encoding='utf-8') as f:
                json.dump(tool_usage, f, indent=2, ensure_ascii=False)

        quota_limit = self.get_quota_limit()
        if quota_limit and quota_limit.get("code") == 200 and save_to_file:
            with open(os.path.join(data_dir, "quota_limit.json"), 'w', encoding='utf-8') as f:
                json.dump(quota_limit, f, indent=2, ensure_ascii=False)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="GLM Usage Data Query")
    parser.add_argument("--console", action="store_true", help="Print output to console instead of saving to files")
    args = parser.parse_args()

    api = GLMUsageAPI()
    
    if not api.api_key:
        print("Error: API Key is missing. Please configure GLM_API_KEY in .env file")
        return

    print("-" * 50)
    print("GLM Usage Data Query")
    print("-" * 50)

    api.save_usage_data(save_to_file=not args.console)

if __name__ == "__main__":
    main()
