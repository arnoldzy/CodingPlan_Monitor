# GLM Coding Plan Monitor

Windows 悬浮窗监控工具，用于实时显示智谱 GLM API 的配额使用情况。

## 功能

- 实时显示 API 配额使用情况
- 支持小时/周/月配额监控
- 支持多种套餐类型 (Lite/Pro/Max)
- 模型使用分布可视化
- 悬浮窗设计，不影响其他工作

## 安装

```bash
pip install -r requirements.txt
```

## 配置

1. 复制示例配置文件：
```bash
copy glm_monitor_config.example.json glm_monitor_config.json
```

2. 编辑 `glm_monitor_config.json`，填入你的 API 密钥：
```json
{
  "api_key": "YOUR_API_KEY_HERE",
  "plan_type": "Max",
  ...
}
```

## 运行

```bash
python glm_plan_monitor.py
```

或使用 Windows 启动脚本：
```bash
start_monitor.bat
```

## 套餐类型

| 套餐 | 小时配额 | 周配额 | 月配额 |
|------|----------|--------|--------|
| Lite | 1,200 | 25,000 | 100,000 |
| Pro | 6,000 | 125,000 | 500,000 |
| Max | 20,000 | 420,000 | 2,000,000 |

## API 端点

- 配额查询: `https://open.bigmodel.cn/api/monitor/usage/quota/limit`
- 基础 URL: `https://open.bigmodel.cn/api/paas/v4`

## License

MIT
