#!/usr/bin/env python3
"""推送状态更新到微信"""
import urllib.request, json, yaml
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
config = yaml.safe_load((HERMES / "config.yaml").read_text())
token = config.get("pushplus", {}).get("token", "")

msg = """## 长期记忆强制集成完成

### 三个记忆引擎全部真实运行
- **active_memory** — 每次自检循环跑(关键词权重自适应)
- **memory_evolution_v2** — 每30分钟标准集成(情报到记忆/压缩/技能挖掘)
- **unified_memory_orchestrator** — 每60分钟全量集成(RAG索引/6模块)

### 今日数据
- 清洗: 310条(偏好匹配76条)
- AI已评分: 327条
- 记忆进化: +157条新情报入记忆

### 记忆状态
- MEMORY.md: 已更新到2026-05-05
- USER.md: v3.0→v3.1(偏好+自动批准)
- 永恒守护神: PID 809622,心跳正常

### 待继续
1. AI六维评分全量覆盖(2.9%)
2. 全系统76个bug修复(14个致命)
3. Agent Company / 专家系统 恢复
4. 三省六部/Actors 修复
"""

data = json.dumps({
    "token": token,
    "title": "Hermes 长期记忆强制集成完成",
    "content": msg,
    "template": "markdown"
}).encode()

req = urllib.request.Request(
    "https://www.pushplus.plus/send",
    data=data,
    headers={"Content-Type": "application/json"}
)
resp = urllib.request.urlopen(req, timeout=15)
result = json.loads(resp.read().decode())
print(f"Result: {result.get('code')} - {result.get('msg','')}")
