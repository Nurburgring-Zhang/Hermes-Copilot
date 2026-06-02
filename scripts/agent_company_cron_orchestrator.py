#!/usr/bin/env python3
"""
Agent Company 全自动流水线 — 独立cron模式
===========================================
不再依赖对话层delegate_task,每个部门作为独立cronjob运行。

执行方式:被cronjob工具调用,在独立Hermes会话中运行。
每个部门有完整的tool-call budget(60次),不会被打断。

数据流通过文件系统传递(/mnt/d/Hermes/workspace/)
"""
import json, sys, os, sqlite3, re
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any

# ==================== 配置 ====================
HERMES_ROOT = Path("/mnt/d/Hermes")
DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"
AGENTS_FILE = Path("/home/administrator/.hermes") / "skills" / "agents-company" / "AGENTS.md"
WORKSPACE = HERMES_ROOT / "workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ==================== 员工解析 ====================
def parse_agents() -> Dict[str, List[Dict]]:
    if not AGENTS_FILE.exists():
        return {}
    content = AGENTS_FILE.read_text(encoding='utf-8')
    departments = {}
    current_dept = None
    for line in content.split('\n'):
        line_s = line.strip()
        if not line_s: continue
        dept_match = re.search(r'((\d+_[a-z_]+).+?)', line_s)
        if dept_match and line_s.startswith('## '):
            current_dept = dept_match.group(1)
            departments[current_dept] = []
            continue
        if line_s.startswith('|') and current_dept:
            parts = [p.strip() for p in line_s.split('|') if p.strip()]
            if len(parts) >= 5 and len(parts[0]) > 3:
                departments[current_dept].append({
                    "id": parts[0], "name": parts[1], "role": parts[2],
                    "personality": parts[3], "catchphrase": parts[4]
                })
    return departments

ALL_AGENTS = parse_agents()

def get_dept_name(dept_id: str) -> str:
    names = {
        "01_marketing": "市场营销部", "02_design": "设计部", "03_product": "产品部",
        "04_rd": "研发部", "05_pmo": "项目管理部", "06_dev": "项目开发部",
        "07_support_proj": "项目支持部", "08_engineering": "工程部",
        "09_qa": "测试与交付部", "10_media": "宣传媒体部", "11_support": "支持部",
        "12_sales": "销售部"
    }
    return names.get(dept_id, dept_id)

# ==================== 情报读取 ====================
def get_intelligence_summary(hours: int = 48, limit: int = 30) -> str:
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        c = db.execute(f"""
            SELECT DISTINCT title, platform, importance_score, category
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-{hours} hours')
              AND importance_score >= 1.0
            ORDER BY importance_score DESC
            LIMIT {limit}
        """)
        seen = set()
        lines = []
        for r in c.fetchall():
            t = r[0]
            if t not in seen:
                seen.add(t)
                lines.append(f"- [{r[1]}] [{r[3]}] (评分{r[2]}) {t[:80]}")
        db.close()
        return "\n".join(lines[:20])
    except Exception as e:
        return f"情报读取失败: {e}"

# ==================== 产出来读取 ====================
def get_previous_output(dept_id: str) -> str:
    """读取上一阶段的产出作为输入"""
    stage_map = {
        "02_design": "demands", "03_product": "designs", "04_rd": "products",
        "05_pmo": "rd", "06_dev": "projects", "07_support_proj": "dev",
        "08_engineering": "support_proj", "09_qa": "engineering",
        "10_media": "qa", "11_support": "media", "12_sales": "support"
    }
    dir_name = stage_map.get(dept_id, "")
    if not dir_name:
        return "<首阶段:无上游输入>"
    target_dir = HERMES_ROOT / dir_name
    if not target_dir.exists():
        return "<上游目录不存在>"
    files = sorted(target_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        files = sorted(target_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return "<无上游产出文件>"
    try:
        content = files[0].read_text(encoding='utf-8')[:3000]
        return content
    except:
        return "<读取上游产出失败>"

# ==================== 主执行逻辑 ====================
def run_phase(dept_id: str):
    """运行单个部门阶段"""
    dept_name = get_dept_name(dept_id)
    agents = ALL_AGENTS.get(dept_id, [])
    
    log(f"{'='*60}")
    log(f"▶ 阶段: {dept_name} ({len(agents)}人)")
    log(f"{'='*60}")
    
    if not agents:
        log(f"❌ {dept_name}: 无员工数据")
        return {"status": "error", "message": "无员工数据"}
    
    # 获取输入数据
    if dept_id == "01_marketing":
        input_data = get_intelligence_summary()
    else:
        input_data = get_previous_output(dept_id)
    
    log(f"输入数据: {len(input_data)} 字符")
    
    # 部门提示词
    DEPT_TASKS = {
        "01_marketing": "从以下情报数据中挖掘真实的市场需求和产品机会。每个需求必须明确目标用户,痛点,市场规模和优先级(1-5)。请以你的专业视角分析,输出JSON格式。",
        "02_design": "基于市场营销部产出的需求,设计具体的产品功能方案。包括功能规格,交互流程,用户体验。输出JSON格式。",
        "03_product": "基于设计部的功能方案,制定完整的产品定义。包括产品定位,目标用户,MVP/V2/V3路线图,商业模式。输出JSON格式。",
        "04_rd": "对产品定义进行技术可行性研究。给出技术栈选型,架构设计,AI方案,风险评级和研发周期。输出JSON格式。",
        "05_pmo": "制定详细的项目开发计划。包括里程碑,关键路径,资源分配,风险登记册。输出JSON格式。",
        "06_dev": "根据开发计划进行代码开发。为每个产品编写核心后端/前端代码。输出可运行的代码。",
        "07_support_proj": "提供基础设施支持方案。包括部署架构,扩展方案,监控方案和成本估算。输出JSON格式。",
        "08_engineering": "对所有产品做最终工程审计。评估架构完整性,技术风险,安全性,性能。输出JSON格式。",
        "09_qa": "对所有产品做最终质量评估。包括测试策略,性能基准,已知问题。输出JSON格式。",
        "10_media": "制定媒体宣传方案。包括宣传定位,渠道策略,内容矩阵,发布节奏。输出JSON格式。",
        "11_support": "汇总全链路产出,做综合支持报告。确保从情报到销售的全链路闭环。输出JSON格式。",
        "12_sales": "制定最终销售方案。包括发布平台,定价策略,目标客户,12个月收入预测。输出JSON格式。"
    }
    
    task = DEPT_TASKS.get(dept_id, "完成以下分析任务")
    
    # 在cron会话中,无法直接调delegate_task
    # 所以此处输出所有员工的提示词,由cron任务的Hermes会话逐一处理
    # 但更关键的是:cron任务已经是一个独立的Hermes会话
    # 在这个会话里可以直接用delegate_task唤醒员工
    
    print(f"\n## 任务: {dept_name}")
    print(f"\n### 你的身份")
    print(f"你是 Hermes Agent Company 的{Orim}调度器。你的任务是唤醒{dept_name}的{len(agents)}名员工。")
    print(f"\n### 员工列表")
    for a in agents:
        print(f"- {a['id']}: {a['name']}({a['role']}) — {a['personality']}")
    print(f"\n### 输入数据")
    print(input_data[:2000])
    print(f"\n### 执行方式")
    print(f"对每名员工使用delegate_task创建独立子Agent。")
    print(f"每个子Agent获得:独立身份,独立会话,独立工具集。")
    print(f"全部完成后汇总输出到 /mnt/d/Hermes/{dept_id.split('_')[1] if '_' in dept_id else dept_id}/")
    print(f"\n### 任务描述")
    print(task)
    
    # 保存到workspace
    phase_data = {
        "dept_id": dept_id,
        "dept_name": dept_name,
        "timestamp": datetime.now().isoformat(),
        "agent_count": len(agents),
        "agents": agents,
        "task": task,
        "input_preview": input_data[:500]
    }
    phase_file = WORKSPACE / f"phase_{dept_id}_{datetime.now().strftime('%H%M%S')}.json"
    phase_file.write_text(json.dumps(phase_data, ensure_ascii=False, indent=2))
    
    log(f"✅ {dept_name} 就绪 — {len(agents)}名员工待唤醒")
    
    return {"status": "ready", "agent_count": len(agents)}

# ==================== 全流水线 ====================
DEPARTMENT_ORDER = [
    "01_marketing", "02_design", "03_product", "04_rd", "05_pmo",
    "06_dev", "07_support_proj", "08_engineering", "09_qa",
    "10_media", "11_support", "12_sales"
]

def run_full_pipeline():
    log("🚀 Agent Company 全自动流水线 (独立cron模式)")
    for dept_id in DEPARTMENT_ORDER:
        run_phase(dept_id)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--phase":
        dept_id = sys.argv[2] if len(sys.argv) > 2 else "01_marketing"
        run_phase(dept_id)
    else:
        run_full_pipeline()
