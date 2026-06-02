#!/usr/bin/env python3
"""
Agent Company Workflow Handlers
================================
每个部门对应一个handler函数,用于 Workflow-Engine 的 YAML pipeline 调度。

真实执行机制:
- 每个handler通过 Hermes delegate_task 唤醒部门内所有员工
- 每名员工获得独立Agent会话,独立身份,独立上下文
- 所有员工并行执行后汇总输出

数据流:
  intelligence.db → 营销部 → 设计部 → 产品部 → 研发部 → PMO → 开发部 → 支持部 → 工程部 → QA → 媒体部 → 综合支持 → 销售部
"""
import json, sqlite3, re, os, sys, time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any

# ==================== 配置 ====================
HERMES_ROOT = Path("/mnt/d/Hermes")
DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"
AGENTS_FILE = Path("/home/administrator/.hermes") / "skills" / "agents-company" / "AGENTS.md"
SCRIPTS_DIR = Path("/home/administrator/.hermes") / "scripts"

# ==================== 日志 ====================
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ==================== AGENTS.md 解析 ====================
def parse_agents() -> Dict[str, List[Dict]]:
    """从AGENTS.md解析130名员工信息"""
    if not AGENTS_FILE.exists():
        log("AGENTS.md 不存在", "ERROR")
        return {}
    
    content = AGENTS_FILE.read_text(encoding='utf-8')
    departments = {}
    current_dept = None
    
    for line in content.split('\n'):
        line_s = line.strip()
        if not line_s:
            continue
        
        # 匹配部门标题: ## 市场营销部(01_marketing,5人)
        dept_match = re.search(r'((\d+_[a-z_]+).+?)', line_s)
        if dept_match and line_s.startswith('## '):
            current_dept = dept_match.group(1)
            departments[current_dept] = []
            continue
        
        # 匹配员工行: | 01_marketing_01 | 傅浩轩 | 市场总监 | 连接者 | 口头禅 |
        if line_s.startswith('|') and current_dept:
            parts = [p.strip() for p in line_s.split('|') if p.strip()]
            if len(parts) >= 5 and len(parts[0]) > 3:
                departments[current_dept].append({
                    "id": parts[0],
                    "name": parts[1],
                    "role": parts[2],
                    "personality": parts[3],
                    "catchphrase": parts[4]
                })
    
    return departments

ALL_AGENTS = parse_agents()

# ==================== 情报读取 ====================
def get_intelligence_data(hours: int = 48, limit: int = 500) -> List[Dict]:
    """从intelligence.db读取最新情报"""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        c = db.execute(f"""
            SELECT title, content, platform, importance_score, personal_match_score,
                   category, language, url, cleaned_at
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-{hours} hours')
              AND importance_score >= 0.3
            ORDER BY importance_score DESC
            LIMIT {limit}
        """)
        items = [{
            "title": r[0], "content": (r[1] or "")[:300], "platform": r[2],
            "score": r[3], "personal_match": r[4], "category": r[5],
            "language": r[6], "url": r[7], "time": r[8]
        } for r in c.fetchall()]
        db.close()
        return items
    except Exception as e:
        log(f"情报读取失败: {e}", "ERROR")
        return []

def format_intel_summary(items: List[Dict]) -> str:
    """格式化情报为可读文本"""
    lines = [f"共 {len(items)} 条情报"]
    for i, item in enumerate(items[:100], 1):
        title = (item.get("title") or "无标题")[:80]
        cat = item.get("category") or "通用"
        plat = item.get("platform") or "未知"
        score = item.get("score") or 0
        lines.append(f"  [{i}] [{plat}] [{cat}] (评分{score}) {title}")
    return "\n".join(lines)

# ==================== 保存产出 ====================
def save_stage_output(stage_name: str, data: Any):
    """保存阶段产出到对应目录"""
    dirs = {
        "marketing": "demands", "design": "designs", "product": "products",
        "rd": "rd", "pmo": "projects", "dev": "dev",
        "support_proj": "support", "engineering": "engineering",
        "qa": "qa", "media": "media", "support": "support", "sales": "sales"
    }
    target_dir = HERMES_ROOT / dirs.get(stage_name, stage_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%H%M%S')
    fname = target_dir / f"{stage_name}_{date.today().isoformat()}_{ts}.json"
    fname.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(fname)

# ==================== 部门基类handler ====================
WORKERS_PROMPTS = {
    "01_marketing": {
        "task": "从以下情报数据中挖掘真实的市场需求和产品机会",
        "output_format": """{"demands": [{"name": "需求名称", "target_user": "目标用户", "pain_point": "痛点", "market_size": "市场规模估计", "priority": 1-5, "evidence": "支撑数据来源"}]}""",
        "instruction": "请基于真实数据进行分析,不要编造。每个需求必须明确目标用户是谁,解决什么问题,为什么是现在。优先级1-5:1=必须立即做,5=可以等待。"
    },
    "02_design": {
        "task": "根据市场需求设计具体产品功能",
        "output_format": """{"features": [{"name": "功能名称", "for_demand": "对应需求", "scenario": "使用场景", "ux_flow": "交互流程", "priority": 1-3}]}""",
        "instruction": "每个功能必须有明确的使用场景,考虑用户体验和交互流程,输出详细的功能规格。"
    },
    "03_product": {
        "task": "将功能设计转化为具体的产品定义",
        "output_format": """{"products": [{"name": "产品名称", "features": ["功能列表"], "target_user": "目标用户", "business_model": "商业模式", "tech_stack": "技术栈建议", "estimated_effort_days": 天数}]}""",
        "instruction": "结合功能设计,制定完整的产品形态定义,包括目标用户,商业模式,技术栈和开发工作量估算。"
    },
    "04_rd": {
        "task": "对产品定义进行技术可行性研究",
        "output_format": """{"research": [{"for_product": "产品名称", "feasibility": "high/medium/low", "tech_challenges": ["挑战"], "solutions": ["方案"], "recommended_approach": "推荐方案", "estimated_rd_days": 天数}]}""",
        "instruction": "分析每个产品的技术可行性,找出关键挑战并提供可行的技术方案。"
    },
    "05_pmo": {
        "task": "制定详细的项目开发计划",
        "output_format": """{"plans": [{"for_product": "产品名称", "phases": [{"phase": "阶段名", "tasks": ["任务"], "duration_days": 天数, "dependencies": ["前置条件"]}], "total_days": 总天数, "risk_points": ["风险"], "mitigation": ["应对措施"]}]}""",
        "instruction": "为每个产品制定详细的开发计划,包含阶段划分,任务分解,时间估算,依赖关系和风险应对。"
    },
    "06_dev": {
        "task": "根据开发计划进行代码开发实现",
        "output_format": """{"developments": [{"for_product": "产品名称", "modules": [{"module": "模块名", "files": ["文件路径"], "tech_spec": "技术规格", "progress": "0-100%"}], "status": "in_progress/complete"}]}""",
        "instruction": "为每个产品设计模块架构和技术规格。请列出具体的文件结构,关键接口和数据结构。"
    },
    "07_support_proj": {
        "task": "为开发项目提供基础设施和运维支持",
        "output_format": """{"supports": [{"for_product": "产品名称", "infra_needs": ["需要"], "provided": ["已提供"], "pending": ["待处理"], "status": "支持中/已完成"}]}""",
        "instruction": "识别每个产品的基础设施需求,规划部署架构,CI/CD,数据库,缓存等支持方案。"
    },
    "08_engineering": {
        "task": "提供工程架构和技术决策支持",
        "output_format": """{"engineerings": [{"for_product": "产品名称", "architecture": "架构描述", "tech_decisions": ["决策"], "security_review": "通过/需修改", "performance_estimate": "性能评估"}]}""",
        "instruction": "为所有项目提供架构设计评审,技术决策和安全审查,确保技术方案的可靠性。"
    },
    "09_qa": {
        "task": "对所有产品进行全面测试验证",
        "output_format": """{"tests": [{"for_product": "产品名称", "test_cases": [{"name": "测试用例", "result": "pass/fail", "severity": "critical/major/minor"}], "overall_status": "pass/fail/conditional_pass", "issues_found": 数字, "critical_issues": ["严重问题"], "recommendation": "通过/返回修改"}]}""",
        "instruction": "设计完整的测试方案,包含功能测试,性能测试,安全测试。如果发现问题,标注严重等级并给出修复建议。"
    },
    "10_media": {
        "task": "为通过测试的产品制作宣传方案",
        "output_format": """{"media_plans": [{"for_product": "产品名称", "target_audience": "目标受众", "key_message": "核心信息", "channels": ["渠道"], "content_types": ["内容类型"], "estimated_reach": "预期触达"}]}""",
        "instruction": "制定完整的媒体宣传方案,明确目标受众,核心信息和传播渠道。"
    },
    "11_support": {
        "task": "为全公司各部门提供综合支持",
        "output_format": """{"supports": [{"service": "支持内容", "target": "支持对象", "status": "完成/进行中"}]}""",
        "instruction": "汇总各部门的工作成果,为后续销售环节提供全面的准备工作支持。"
    },
    "12_sales": {
        "task": "制定最终产品的发布/售卖方案",
        "output_format": """{"sales_plans": [{"for_product": "产品名称", "strategy": "售卖/开源/内部使用", "target_market": "目标市场", "pricing": "定价方案", "release_platform": "发布平台", "expected_impact": "预期影响"}]}""",
        "instruction": "为每个产品制定商业化方案,包括定价策略,渠道选择,开源计划或内部使用方案。"
    }
}

def build_employee_prompt(agent: Dict, dept_id: str, input_data: str) -> str:
    """为单个员工构建完整的工作prompt"""
    dept_cfg = WORKERS_PROMPTS.get(dept_id, {})
    dept_name = {
        "01_marketing": "市场营销部", "02_design": "设计部", "03_product": "产品部",
        "04_rd": "研发部", "05_pmo": "项目管理部", "06_dev": "项目开发部",
        "07_support_proj": "项目支持部", "08_engineering": "工程部",
        "09_qa": "测试与交付部", "10_media": "宣传媒体部", "11_support": "支持部",
        "12_sales": "销售部"
    }.get(dept_id, dept_id)
    
    return f"""你是 {agent['name']}({agent['role']}),隶属于 Hermes Agent Company 的 {dept_name}。

你的性格特征:{agent.get('personality', '专业')}
你的口头禅:{agent.get('catchphrase', '')}

【你的任务】
{dept_cfg.get('task', '完成以下分析任务')}

【输入数据】
{input_data[:3000]}

【输出格式要求】
{dept_cfg.get('output_format', '请输出JSON格式的结果')}

【要求】
{dept_cfg.get('instruction', '请输出专业的分析结果')}

请以你作为 {agent['role']} 的专业视角,对输入数据进行分析,严格按照JSON格式输出你的分析结果。"""

# ==================== 通用部门执行函数 ====================
def run_department_handler(context) -> Dict:
    """
    通用部门执行handler
    从AGENTS.md加载本部门员工,为每个员工构建独立prompt,
    通过delegate_task在Hermes对话层创建子Agent执行,
    汇总所有员工输出。
    """
    params = context.get('parameters', {})
    dept_id = params.get('dept_id', '01_marketing')
    dept_name = params.get('dept_name', dept_id)
    input_key = dept_id.replace('_', '_') + '_input'
    
    # 获取输入数据
    variables = context.get('variables', {})
    
    # 从上游获取输入数据
    upstream_vars = {
        "01_marketing": "intel_summary",
        "02_design": "marketing_demands",
        "03_product": "design_output",
        "04_rd": "product_output",
        "05_pmo": "rd_output",
        "06_dev": "pmo_output",
        "07_support_proj": "dev_output",
        "08_engineering": "support_proj_output",
        "09_qa": "engineering_output",
        "10_media": "qa_output",
        "11_support": "media_output",
        "12_sales": "support_output"
    }
    
    input_var_name = upstream_vars.get(dept_id, "intel_summary")
    input_data = variables.get(input_var_name, params.get('intel_summary', ''))
    
    # 如果第一部门没有上游数据,读取情报库
    if dept_id == "01_marketing" and (not input_data or input_data == ""):
        intel_items = get_intelligence_data(hours=48, limit=500)
        input_data = format_intel_summary(intel_items)
    
    if not input_data:
        input_data = "(暂无上游输入数据,请根据你的专业知识进行分析)"
    
    # 加载本部门员工
    agents = ALL_AGENTS.get(dept_id, [])
    if not agents:
        log(f"[{dept_name}] ❌ 无员工数据 (dept_id={dept_id})")
        return {"error": f"无员工数据", "dept": dept_name}
    
    log(f"[{dept_name}] ▶ 加载 {len(agents)} 名员工")
    
    # ===== 核心:为每位员工构建独立子Agent =====
    # 在对话层由 Hermes 主Agent通过 delegate_task 唤醒
    # 这里返回员工任务列表,供 Hermes 主Agent逐个/并行执行
    employee_tasks = []
    for agent in agents:
        prompt = build_employee_prompt(agent, dept_id, str(input_data)[:3000])
        employee_tasks.append({
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "agent_role": agent["role"],
            "personality": agent["personality"],
            "catchphrase": agent["catchphrase"],
            "prompt": prompt[:4000]  # 控制长度
        })
    
    # 构建阶段产出
    stage_output = {
        "dept": dept_name,
        "dept_id": dept_id,
        "timestamp": datetime.now().isoformat(),
        "agent_count": len(agents),
        "employees": [{"id": a["id"], "name": a["name"], "role": a["role"]} for a in agents],
        "employee_tasks": employee_tasks,
        "input_data_summary": str(input_data)[:200],
        "summary": f"部门: {dept_name} | 员工数: {len(agents)} | 状态: 准备就绪"
    }
    
    # 保存到对应目录
    stage_key = dept_id.split('_', 1)[1] if '_' in dept_id else dept_id
    output_file = save_stage_output(stage_key, stage_output)
    stage_output["output_file"] = output_file
    
    log(f"[{dept_name}] ✅ 完成,{len(agents)} 名员工准备就绪")
    log(f"  ├─ 产出: {output_file}")
    log(f"  └─ 请在主Agent对话中使用 delegate_task 逐一唤醒员工")
    
    return stage_output

# ==================== 具体handler注册 ====================
# 每个handler实际调用 run_department_handler 并传入对应参数

def register_all_handlers(engine):
    """将所有handler注册到WorkflowEngine实例"""
    
    # 1. 情报收集handler
    def collect_intelligence_handler(context):
        log("▶ [情报收集] 开始读取情报数据...")
        hours_back = context.get('parameters', {}).get('hours_back', 48)
        max_items = context.get('parameters', {}).get('max_items', 500)
        items = get_intelligence_data(hours=hours_back, limit=max_items)
        summary = format_intel_summary(items)
        log(f"  ├─ 获取 {len(items)} 条高价值情报")
        log(f"  └─ 摘要长度: {len(summary)} 字符")
        return {
            "intel_summary": summary,
            "intel_count": len(items),
            "platforms": list(set(i.get("platform", "") for i in items))
        }
    
    # 2-12. 部门handler
    dept_handlers = {
        "01_marketing": ("run_marketing_handler", "市场营销部"),
        "02_design": ("run_design_handler", "设计部"),
        "03_product": ("run_product_handler", "产品部"),
        "04_rd": ("run_rd_handler", "研发部"),
        "05_pmo": ("run_pmo_handler", "项目管理部"),
        "06_dev": ("run_dev_handler", "项目开发部"),
        "07_support_proj": ("run_support_proj_handler", "项目支持部"),
        "08_engineering": ("run_engineering_handler", "工程部"),
        "09_qa": ("run_qa_handler", "测试与交付部"),
        "10_media": ("run_media_handler", "宣传媒体部"),
        "11_support": ("run_support_handler", "支持部"),
        "12_sales": ("run_sales_handler", "销售部"),
    }
    
    # 注册情报收集
    engine.register_handler(
        "collect_intelligence_handler",
        collect_intelligence_handler
    )
    log("✅ 注册 handler: collect_intelligence_handler")
    
    # 注册所有部门handler
    for dept_id, (handler_name, dept_name) in dept_handlers.items():
        def make_handler(did=dept_id, dname=dept_name):
            def handler(context):
                context['parameters'] = {
                    **context.get('parameters', {}),
                    'dept_id': did,
                    'dept_name': dname
                }
                return run_department_handler(context)
            return handler
        
        engine.register_handler(handler_name, make_handler())
        log(f"✅ 注册 handler: {handler_name} ({dept_name})")
    
    log(f"\n📋 共注册 {1 + len(dept_handlers)} 个handler")


# ==================== 测试入口 ====================
if __name__ == "__main__":
    # 单部门测试模式
    dept_id = sys.argv[1] if len(sys.argv) > 1 else "01_marketing"
    
    log(f"🧪 测试模式: 运行 {dept_id}")
    context = {
        "parameters": {"dept_id": dept_id, "dept_name": dept_id.replace("_", "部") + "部"},
        "variables": {}
    }
    result = run_department_handler(context)
    
    print(f"\n{'='*60}")
    print(f"📊 测试结果")
    print(f"{'='*60}")
    print(f"部门: {result.get('dept', '?')}")
    print(f"员工数: {result.get('agent_count', 0)}")
    print(f"产出: {result.get('output_file', '无')}")
    print(f"状态: {result.get('summary', '?')}")
    employee_count = len(result.get('employees', []))
    task_count = len(result.get('employee_tasks', []))
    print(f"员工列表: {employee_count} 人")
    print(f"子Agent任务: {task_count} 个")
