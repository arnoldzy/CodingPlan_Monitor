#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kimi Usage API Encapsulation
"""

import os
import json
import logging
from datetime import datetime

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class KimiUsageAPI:
    def __init__(self):
        self.base_url = "https://api.kimi.com"
        self.api_key = None
        self._load_env()

    def _load_env(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(current_dir, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            self.api_key = os.getenv("KIMI_API_KEY")
            if not self.api_key:
                logger.warning(".env 文件中未找到 KIMI_API_KEY")
        else:
            logger.warning(f".env 文件未找到: {env_path}")

    def _get_headers(self):
        if not self.api_key:
            raise ValueError("API Key not set")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _make_request(self, endpoint):
        url = f"{self.base_url}{endpoint}"
        try:
            headers = self._get_headers()
            response = requests.get(url, headers=headers, timeout=30)
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

    def get_coding_plan_usages(self):
        logger.info("Fetching Kimi Coding Plan Usages...")
        return self._make_request("/coding/v1/usages")

    def _to_number(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return None

    def _to_pct(self, remaining, limit):
        if remaining is None or limit is None or limit <= 0:
            return 0
        pct = int(round((remaining / limit) * 100))
        return max(0, min(100, pct))

    def _iso_to_ms(self, iso_text):
        if not iso_text:
            return 0
        try:
            dt = datetime.fromisoformat(str(iso_text).replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    def _extract_window(self, limits, duration_min):
        if not isinstance(limits, list):
            return None
        for item in limits:
            window = item.get("window", {})
            duration = window.get("duration")
            unit = window.get("timeUnit")
            if unit == "TIME_UNIT_MINUTE" and duration == duration_min:
                return item.get("detail", {})
            if duration_min == 10080 and unit == "TIME_UNIT_DAY" and duration == 7:
                return item.get("detail", {})
            if duration_min == 10080 and unit == "TIME_UNIT_HOUR" and duration == 168:
                return item.get("detail", {})
        return None

    def _build_summary(self, usage_json):
        usage = usage_json.get("usage", {}) if isinstance(usage_json, dict) else {}
        limits = usage_json.get("limits", []) if isinstance(usage_json, dict) else []

        week_limit = self._to_number(usage.get("limit"))
        week_remaining = self._to_number(usage.get("remaining"))
        week_reset = self._iso_to_ms(usage.get("resetTime"))

        five_hour = self._extract_window(limits, 300)
        week_window = self._extract_window(limits, 10080)

        if week_window:
            week_limit = self._to_number(week_window.get("limit"))
            week_remaining = self._to_number(week_window.get("remaining"))
            week_reset = self._iso_to_ms(week_window.get("resetTime"))

        five_limit = self._to_number(five_hour.get("limit")) if five_hour else None
        five_remaining = self._to_number(five_hour.get("remaining")) if five_hour else None
        five_reset = self._iso_to_ms(five_hour.get("resetTime")) if five_hour else 0

        if five_limit is None and isinstance(limits, list) and len(limits) > 0:
            fallback_detail = limits[0].get("detail", {})
            five_limit = self._to_number(fallback_detail.get("limit"))
            five_remaining = self._to_number(fallback_detail.get("remaining"))
            five_reset = self._iso_to_ms(fallback_detail.get("resetTime"))

        summary = {
            "FiveHour": {
                "quota": self._to_pct(five_remaining, five_limit),
                "reset_time": five_reset
            },
            "Week": {
                "quota": self._to_pct(week_remaining, week_limit),
                "reset_time": week_reset
            }
        }
        return summary

    def save_usage_data(self, save_to_file=True):
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kimi")
        if save_to_file and not os.path.exists(data_dir):
            os.makedirs(data_dir)

        usage = self.get_coding_plan_usages()
        if not usage:
            logger.error("Failed to fetch Kimi Coding Plan usages: empty response")
            return
        if isinstance(usage, dict) and usage.get("error"):
            logger.error(f"Failed to fetch Kimi Coding Plan usages: {usage.get('error')}")
            return

        summary = self._build_summary(usage)
        if save_to_file:
            with open(os.path.join(data_dir, "coding_plan_usages.json"), 'w', encoding='utf-8') as f:
                json.dump(usage, f, indent=2, ensure_ascii=False)
            with open(os.path.join(data_dir, "coding_plan_summary.json"), 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            logger.info("Kimi usages saved to data/kimi/")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Kimi Usage Data Query")
    parser.add_argument("--console", action="store_true", help="Print output to console instead of saving to files")
    args = parser.parse_args()

    api = KimiUsageAPI()
    if not api.api_key:
        print("Error: API Key is missing. Please configure KIMI_API_KEY in .env file")
        return

    print("-" * 50)
    print("Kimi Usage Data Query")
    print("-" * 50)

    usage = api.get_coding_plan_usages()
    if args.console:
        print(json.dumps(usage, indent=2, ensure_ascii=False))
    else:
        api.save_usage_data(save_to_file=True)


if __name__ == "__main__":
    main()
