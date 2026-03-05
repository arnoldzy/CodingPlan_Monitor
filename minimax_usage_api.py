#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniMax Usage API Encapsulation
"""

import os
import json
import requests
import logging
from dotenv import load_dotenv

# 配置日志
logger = logging.getLogger(__name__)

class MiniMaxUsageAPI:
    def __init__(self):
        self.base_url = "https://www.minimaxi.com"
        self.api_key = None
        self._load_env()

    def _load_env(self):
        """加载环境变量"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(current_dir, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            self.api_key = os.getenv("MINIMAX_API_KEY")
            if not self.api_key:
                 logger.warning(".env 文件中未找到 MINIMAX_API_KEY")
        else:
            logger.warning(f".env 文件未找到: {env_path}")

    def _get_headers(self):
        if not self.api_key:
            raise ValueError("API Key not set")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
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

    def get_coding_plan_remains(self):
        """获取Coding Plan剩余配额"""
        logger.info("Fetching Coding Plan Remains...")
        return self._make_request("/v1/api/openplatform/coding_plan/remains")

    def save_usage_data(self, save_to_file=True):
        """获取并保存使用数据"""
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "minimax")
        if save_to_file and not os.path.exists(data_dir):
            os.makedirs(data_dir)

        # 1. Coding Plan Remains
        remains = self.get_coding_plan_remains()
        if remains and remains.get("base_resp", {}).get("status_code") == 0:
            if save_to_file:
                with open(os.path.join(data_dir, "coding_plan_remains.json"), 'w', encoding='utf-8') as f:
                    json.dump(remains, f, indent=2, ensure_ascii=False)
                logger.info("Coding Plan remains saved to data/minimax/coding_plan_remains.json")
            else:
                 print("\n[Coding Plan Remains Data]:")
                 print(json.dumps(remains, indent=2, ensure_ascii=False))
        else:
            msg = remains.get("base_resp", {}).get("status_msg") if remains else "Unknown error"
            logger.error(f"Failed to fetch Coding Plan Remains: {msg}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MiniMax Usage Data Query")
    parser.add_argument("--console", action="store_true", help="Print output to console instead of saving to files")
    args = parser.parse_args()

    api = MiniMaxUsageAPI()
    
    if not api.api_key:
        print("Error: API Key is missing. Please configure MINIMAX_API_KEY in .env file")
        return

    print("-" * 50)
    print("MiniMax Usage Data Query")
    print("-" * 50)

    api.save_usage_data(save_to_file=not args.console)

if __name__ == "__main__":
    main()
