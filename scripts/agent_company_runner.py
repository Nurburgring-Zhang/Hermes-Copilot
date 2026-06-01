#!/usr/bin/env python3
"""
Agent Company 全自动化运行引擎
==============================
核心机制:每个员工使用 Hermes delegate_task 创建独立子Agent,
拥有独立身份,独立会话,独立工具集。

支持两种运行模式:
1. full_pipeline -- 12部门全链路(每天5点触发)
2. single_stage -- 指定某个部门单独运行(调试/手动触发)

每个部门内部:
  部门调度Agent → 并行唤醒所有员工子Agent
  → 每个子Agent用delegate_task获取独立上下文
  → 员工完成任务后汇总 → 部门调度汇总输出
"""

import json, sys, os, time, sqlite3, re, subprocess
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# ==================== 配置 ====================
HERMES_ROOT = Path("/mnt/d/Hermes")
DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"
SCRIPTS = Path("/home/administrator/.hermes") / "scripts"
AGENTS_DB = Path("/home/administrator/.hermes") / "intelligence.db"
COMPANY_AGENTS_FILE = Path("/home/administrator/.hermes") / "skills" / "agents-company" / "AGENTS.md"

# ==================== 130员工数据库(从AGENTS.md提取)====================
def parse_company_agents() -> Dict[str, List[Dict]]:
    """
    从AGENTS.md解析130名员工信息
    返回: { dept_code: [{ "id": "01_marketing_01", "name": "傅浩轩", "role": "市场总监", 
                           "personality": "连接者", "catchphrase": "等等,这个逻辑有问题。" }, ...] }
    """
    if not COMPANY_AGENTS_FILE.exists():
        # fallback: 从 skill 读取
        fallback = Path("/home/administrator/.hermes") / "skills" / "agents-company" / "SKILL.md"
        if fallback.exists():
            return _parse_agents_from_md(fallback.read_text(encoding='utf-8'))
        return {}
    
    return _parse_agents_from_md(COMPANY_AGENTS_FILE.read_text(encoding='utf-8'))

def _parse_agents_from_md(content: str) -> Dict[str, List[Dict]]:
    """从AGENTS.md的内容解析员工"""
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

# ==================== 各部门的具体Agent提示工程 ====================
DEPARTMENT_PROMPTS = {
    "01_marketing": {
        "name": "市场营销部",
        "task": "从情报数据中挖掘用户需求和市场机会",
        "output_format": "每个员工输出3个需求建议(格式:需求名称+目标用户+痛点+市场规模估计+优先级 1-5)",
        "workers_prompt_template": """你叫{name},是市场营销部的{role}。
你的性格:{personality}
你的口头禅:{catchphrase}

你的任务:从以下情报数据中,挖掘出真实的市场需求和产品机会。

情报数据(共{total}条):
{data}

要求:
1. 基于真实数据分析,不要编造
2. 每个需求必须明确:目标用户是谁,解决什么问题,为什么是现在
3. 优先级1-5:1=明天不做就晚了,5=可以等等
4. 输出格式严格为以下JSON:
{{"demands": [{{"name": "需求名称", "target_user": "目标用户", "pain_point": "痛点", "market_size": "市场估计", "priority": 1-5, "evidence": "支撑数据/情报来源"}}]}}

请输出你的分析结果(只输出JSON):"""
    },
    "02_design": {
        "name": "设计部",
        "task": "根据需求设计产品功能",
        "workers_prompt_template": """你叫{name},是设计部的{role}。
你的性格:{personality}
你的口头禅:{catchphrase}

上游传递来的需求:
{demands}

你的任务:为这些需求设计具体的产品功能。

要求:
1. 每个功能必须有明确的使用场景
2. 考虑用户体验,交互流程,视觉风格
3. 输出格式为JSON:
{{"features": [{{"name": "功能名称", "for_demand": "对应需求", "scenario": "使用场景", "ux_flow": "交互流程", "priority": 1-3}}]}}"""
    },
    "03_product": {
        "name": "产品部",
        "task": "将功能设计转化为具体产品定义",
        "workers_prompt_template": """你叫{name},是产品部的{role}。
你的性格:{personality}
你的口头禅:{catchphrase}

上游传递来的功能设计:
{designs}

你的任务:将功能组合成具体产品,定义产品形态。

输出JSON格式:
{{"products": [{{"name": "产品名称", "features": ["功能1","功能2","功能3"], "target_user": "目标用户", "business_model": "商业模式", "tech_stack": "技术栈建议", "estimated_effort": "人天估计"}}]}}"""
    },
    "04_rd": {
        "name": "研发部",
        "task": "对产品定义进行技术可行性研究",
        "workers_prompt_template": """你叫{name},是研发部的{role}。
你的性格:{personality}
你的口头禅:{catchphrase}

上游传递来的产品定义:
{products}

你的任务:分析每个产品的技术可行性,给出研发方案。

输出JSON:
{{"research": [{{"for_product": "产品名称", "feasibility": "high/medium/low", "tech_challenges": ["挑战1","挑战2"], "solutions": ["方案1","方案2"], "recommended_approach": "推荐方案", "estimated_rd_days": 天数}}]}}"""
    },
    "05_pmo": {
        "name": "项目管理部",
        "task": "制定项目开发计划",
        "workers_prompt_template": """你叫{name},是项目管理部的{role}。
你的性格:{personality}
你的口头禅:{catchphrase}

上游传递来的研发方案:
{rd_results}

你的任务:为每个产品制定详细的项目开发计划。

输出JSON:
{{"plans": [{{"for_product": "产品名称", "phases": [{{"phase": "阶段名", "tasks": ["任务1","任务2"], "duration_days": 天数, "dependencies": ["前置条件"]}}], "total_days": 总天数, "risk_points": ["风险1","风险2"], "mitigation": ["应对1","应对2"]}}]}}"""
    },
    "06_dev": {
        "name": "项目开发部",
        "task": "根据开发计划进行代码开发",
        "workers_prompt_template": """你叫{name},是项目开发部的{role}({personality})。
你的口头禅:{catchphrase}

上游传递来的开发计划:
{plans}

你的任务:根据计划开始具体开发工作。

输出JSON:
{{"developments": [{{"for_product": "产品名称", "modules": [{{"module": "模块名", "files": ["文件路径"], "tech_spec": "技术规格", "progress": "0-100%"}}], "status": "in_progress/complete"}}]}}"""
    },
    "07_support_proj": {
        "name": "项目支持部",
        "task": "为开发提供基础设施和支持",
        "workers_prompt_template": """你叫{name},是项目支持部的{role}({personality})。
你的口头禅:{catchphrase}

上游传递来的开发成果:
{developments}

你的任务:为每个开发项目提供基础设施,运维,数据库等支持。

输出JSON:
{{"supports": [{{"for_product": "产品名称", "infra_needs": ["需要1","需要2"], "provided": ["已提供1","已提供2"], "pending": ["待处理1"], "status": "支持中/已完成"}}]}}"""
    },
    "08_engineering": {
        "name": "工程部",
        "task": "提供工程架构和技术支持",
        "workers_prompt_template": """你叫{name},是工程部的{role}({personality})。
你的口头禅:{catchphrase}

上游传递来的支持需求:
{supports}

你的任务:为所有项目提供架构设计,技术决策,工程支持。

输出JSON:
{{"engineerings": [{{"for_product": "产品名称", "architecture": "架构描述", "tech_decisions": ["决策1","决策2"], "security_review": "通过/需修改", "performance_estimate": "性能评估"}}]}}"""
    },
    "09_qa": {
        "name": "测试与交付部",
        "task": "对所有产品进行测试验证",
        "workers_prompt_template": """你叫{name},是测试与交付部的{role}({personality})。
你的口头禅:{catchphrase}

上游传递来的工程成果:
{engineerings}

你的任务:对每个产品进行完整测试。

输出JSON:
{{"tests": [{{"for_product": "产品名称", "test_cases": [{{"name": "测试用例", "result": "pass/fail", "severity": "critical/major/minor"}}], "overall_status": "pass/fail/conditional_pass", "issues_found": 数字, "critical_issues": ["严重问题1"], "recommendation": "通过/返回修改/需重新测试"}}]}}"""
    },
    "10_media": {
        "name": "宣传媒体部",
        "task": "为通过测试的产品制作宣传内容",
        "workers_prompt_template": """你叫{name},是宣传媒体部的{role}({personality})。
你的口头禅:{catchphrase}

上游传递来的测试通过产品:
{deliveries}

你的任务:为每个产品制作媒体宣传方案。

输出JSON:
{{"media_plans": [{{"for_product": "产品名称", "target_audience": "目标受众", "key_message": "核心信息", "channels": ["渠道1","渠道2"], "content_types": ["内容类型1","内容类型2"], "estimated_reach": "预期触达"}}]}}"""
    },
    "11_support": {
        "name": "支持部",
        "task": "为全公司提供通用支持",
        "workers_prompt_template": """你叫{name},是支持部的{role}({personality})。
你的口头禅:{catchphrase}

当前各部门已完成的工作:
{company_status}

你的任务:为所有部门提供通用支持,确保后续销售环节顺利。

输出JSON:
{{"supports": [{{"service": "支持内容", "target": "支持对象", "status": "完成/进行中"}}]}}"""
    },
    "12_sales": {
        "name": "销售部",
        "task": "将产品售卖或开源发布",
        "workers_prompt_template": """你叫{name},是销售部的{role}({personality})。
你的口头禅:{catchphrase}

最终交付的产品:
{final_products}

你的任务:制定销售策略或开源发布方案。

输出JSON:
{{"sales_plans": [{{"for_product": "产品名称", "strategy": "售卖/开源", "target_market": "目标市场", "pricing": "定价方案(如售卖)", "release_platform": "GitHub/其他", "expected_impact": "预期影响"}}]}}"""
    }
}

# ==================== 工具函数 ====================
def get_intelligence_data(hours: int = 48, limit: int = 100) -> List[Dict]:
    """读取最新情报数据"""
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
        print(f"[ERROR] 读取情报: {e}")
        return []

def format_intel_for_prompt(items: List[Dict]) -> str:
    """将情报数据格式化为提示词可读格式"""
    lines = []
    for i, item in enumerate(items[:50], 1):
        title = (item.get("title") or "无标题")[:80]
        cat = item.get("category") or "通用"
        plat = item.get("platform") or "未知"
        score = item.get("score") or 0
        lines.append(f"  [{i}] [{plat}] [{cat}] (评分{score}) {title}")
    return "\n".join(lines)

def get_last_stage_output(stage_name: str) -> Optional[str]:
    """获取上游阶段的最新产出文件内容"""
    stages_dir = {
        "marketing": "demands", "design": "designs", "product": "products",
        "rd": "rd", "pmo": "projects", "dev": "dev", 
        "support_proj": "support", "engineering": "engineering",
        "qa": "qa", "media": "media", "support": "support", "sales": "sales"
    }
    dir_name = stages_dir.get(stage_name, stage_name)
    stage_dir = HERMES_ROOT / dir_name
    if not stage_dir.exists():
        return None
    files = sorted(stage_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        files = sorted(stage_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        content = files[0].read_text(encoding='utf-8')
        return content[:3000]  # 截断避免过长
    except:
        return None

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}] [COMPANY] {msg}"
    print(line, flush=True)
    log_file = HERMES_ROOT / "status" / f"company_{date.today().isoformat()}.log"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(line + "\n")

def save_stage_output(stage: str, data: Any):
    """保存阶段产出到对应目录"""
    dirs = {
        "marketing": "demands", "design": "designs", "product": "products",
        "rd": "rd", "pmo": "projects", "dev": "dev",
        "support_proj": "support", "engineering": "engineering",
        "qa": "qa", "media": "media", "support": "support", "sales": "sales"
    }
    target_dir = HERMES_ROOT / dirs.get(stage, stage)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    ts = datetime.now().strftime('%H%M%S')
    fname = target_dir / f"{stage}_{date.today().isoformat()}_{ts}.json"
    fname.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f"阶段产出已保存: {fname}")
    return str(fname)

# ==================== 核心运行逻辑 ====================
def _execute_employee(agent: Dict, prompt_text: str, dept_id: str, 
                       timeout: int = 120) -> Dict:
    """
    通过 hermes chat -q 为单个员工创建独立子Agent执行任务
    模拟 delegate_task 效果:独立身份 + 独立会话 + 独立上下文
    """
    agent_id = agent["id"]
    agent_name = agent["name"]
    worker_dir = HERMES_ROOT / dept_id
    worker_dir.mkdir(parents=True, exist_ok=True)
    
    # 构建带身份上下文的完整提示
    full_prompt = f"""[系统指令]
你是 {agent_name}({agent['role']}),隶属于 Hermes Agent Company 的 {DEPARTMENT_PROMPTS.get(dept_id, {}).get('name', dept_id)}。
你的性格特征:{agent.get('personality', '专业')}
你的口头禅:{agent.get('catchphrase', '')}

[任务开始]
{prompt_text}

[任务要求]
请根据你作为 {agent['role']} 的专业视角,输出真实的分析结果。
必须严格按照指定的JSON格式输出,不要包含其他文字。
如果无法严格按JSON格式,请用 ```json ... ``` 包裹你的输出。
[任务结束]"""

    # 写入独立任务文件(作为持久化记录)
    task_file = worker_dir / f"task_{agent_id}_{datetime.now().strftime('%H%M%S')}.txt"
    task_file.write_text(full_prompt, encoding='utf-8')
    
    result_file = worker_dir / f"result_{agent_id}_{datetime.now().strftime('%H%M%S')}.json"
    
    ts_start = time.time()
    log(f"  👤 启动员工 [{agent_name}] ({agent['role']})...")
    
    try:
        # 通过子进程调用 hermes chat,每个员工独立运行
        proc = subprocess.run(
            [sys.executable, "-m", "hermes_cli.main", "chat", "-q", full_prompt, "--quiet"],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "HERMES_SKILLS": "agents-company",
                 "HERMES_SESSION_TAG": f"employee_{agent_id}"}
        )
        # fallback: 直接调用 hermes 命令
        if proc.returncode != 0:
            proc = subprocess.run(
                ["hermes", "chat", "-q", full_prompt, "--quiet"],
                capture_output=True, text=True, timeout=timeout
            )
        
        elapsed = time.time() - ts_start
        output = proc.stdout.strip() if proc.returncode == 0 else proc.stderr.strip()
        
        # 尝试从输出中提取JSON
        result_data = _extract_json_from_output(output)
        
        employee_result = {
            "id": agent_id,
            "name": agent_name,
            "role": agent["role"],
            "personality": agent.get("personality", ""),
            "status": "success" if proc.returncode == 0 else "error",
            "elapsed_seconds": round(elapsed, 2),
            "raw_output": output[:500],
            "parsed_result": result_data
        }
        
        log(f"  ✅ 员工 [{agent_name}] 完成 ({elapsed:.1f}s)")
        
        # 保存结果
        result_file.write_text(json.dumps(employee_result, ensure_ascii=False, indent=2), encoding='utf-8')
        
    except subprocess.TimeoutExpired:
        elapsed = time.time() - ts_start
        log(f"  ⚠️ 员工 [{agent_name}] 超时 ({timeout}s)", "WARN")
        employee_result = {
            "id": agent_id,
            "name": agent_name,
            "role": agent["role"],
            "status": "timeout",
            "elapsed_seconds": round(elapsed, 2),
            "raw_output": "",
            "parsed_result": None
        }
        result_file.write_text(json.dumps(employee_result, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        elapsed = time.time() - ts_start
        log(f"  ❌ 员工 [{agent_name}] 异常: {e}", "ERROR")
        employee_result = {
            "id": agent_id,
            "name": agent_name,
            "role": agent["role"],
            "status": "exception",
            "error": str(e),
            "elapsed_seconds": round(elapsed, 2),
            "raw_output": "",
            "parsed_result": None
        }
    
    return employee_result


def _extract_json_from_output(output: str) -> Optional[Any]:
    """从模型输出中提取JSON(支持 ```json ... ``` 包裹或裸JSON)"""
    if not output:
        return None
    # 尝试提取 ```json ... ``` 块
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', output, re.DOTALL)
    if json_match:
        candidate = json_match.group(1).strip()
    else:
        candidate = output.strip()
    # 尝试解析
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # 尝试找 { ... } 或 [ ... ] 顶层结构
    for brace in ('{', '['):
        start = output.find(brace)
        if start >= 0:
            try:
                end_brace = '}' if brace == '{' else ']'
                # 简单的括号匹配
                depth = 0
                for i in range(start, len(output)):
                    if output[i] == brace: depth += 1
                    elif output[i] == end_brace:
                        depth -= 1
                        if depth == 0:
                            candidate = output[start:i+1]
                            return json.loads(candidate)
            except:
                continue
    return None


def run_department(dept_id: str, input_data: str, dept_info: Dict, 
                   agents: List[Dict]) -> Dict:
    """
    运行一个部门:为每个员工创建独立子Agent执行任务
    通过 hermes chat -q 模拟 delegate_task 机制
    每个员工获得:独立身份 + 独立会话 + 独立上下文 + 独立输出
    """
    dept_prompt = DEPARTMENT_PROMPTS.get(dept_id, {})
    dept_name = dept_prompt.get("name", dept_info.get("name", dept_id))
    template = dept_prompt.get("workers_prompt_template", "")
    
    log(f"▶ [{dept_name}] 唤醒 {len(agents)} 名员工...")
    log(f"  📦 输入数据: {len(input_data or '')} chars")
    
    # 并行执行所有员工(用线程池)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = min(len(agents), 5)  # 最多5个并行,避免过载
    
    employee_results = []
    completed_count = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        
        for agent in agents:
            # 构造每个人的独立prompt
            try:
                prompt_text = template.format(
                    name=agent["name"],
                    role=agent["role"],
                    personality=agent["personality"],
                    catchphrase=agent["catchphrase"],
                    demands=input_data if input_data else "无",
                    data=input_data if input_data else "无",
                    total=0,
                    designs=input_data if input_data else "无",
                    products=input_data if input_data else "无",
                    rd_results=input_data if input_data else "无",
                    plans=input_data if input_data else "无",
                    developments=input_data if input_data else "无",
                    supports=input_data if input_data else "无",
                    engineerings=input_data if input_data else "无",
                    deliveries=input_data if input_data else "无",
                    company_status=input_data if input_data else "无",
                    final_products=input_data if input_data else "无"
                )
            except KeyError as e:
                log(f"  ⚠️ 提示词模板key缺失 {e},使用默认模板", "WARN")
                prompt_text = f"作为{agent['role']} {agent['name']},分析以下数据并输出结果:\n{input_data}"
            
            future = executor.submit(
                _execute_employee, agent, prompt_text, dept_id
            )
            future_map[future] = agent
        
        # 收集结果
        for future in as_completed(future_map):
            agent = future_map[future]
            try:
                result = future.result()
                employee_results.append(result)
                if result.get("status") == "success":
                    completed_count += 1
            except Exception as e:
                log(f"  ❌ 员工 [{agent['name']}] 收集异常: {e}", "ERROR")
                employee_results.append({
                    "id": agent["id"],
                    "name": agent["name"],
                    "role": agent["role"],
                    "status": "exception",
                    "error": str(e)
                })
    
    # 汇总本部门所有员工产出
    all_parsed = [r.get("parsed_result") for r in employee_results if r.get("parsed_result")]
    
    # 合并所有员工的JSON输出为一个汇总
    merged_output = _merge_employee_outputs(all_parsed)
    
    log(f"✅ [{dept_name}] {completed_count}/{len(agents)} 员工完成")
    
    return {
        "dept_id": dept_id,
        "name": dept_name,
        "agents": agents,
        "agent_count": len(agents),
        "completed_count": completed_count,
        "status": "completed" if completed_count > 0 else "failed",
        "employees": employee_results,
        "merged_output": merged_output,
        "input_data": input_data[:200] if input_data else ""
    }


def _merge_employee_outputs(parsed_results: List[Any]) -> Dict:
    """合并多个员工的JSON输出为统一格式"""
    merged = {
        "total_employees": len(parsed_results),
        "contributions": []
    }
    for r in parsed_results:
        if isinstance(r, dict):
            merged["contributions"].append(r)
        elif isinstance(r, list):
            merged["contributions"].extend(r)
    merged["contribution_count"] = len(merged["contributions"])
    return merged

def run_pipeline_phase(dept_id: str, input_data: Any = None) -> Dict:
    """
    运行流水线的单个阶段
    通过 run_department 为每个员工创建独立子Agent(通过 hermes chat -q)
    返回该阶段的产出物
    """
    dept_prompt = DEPARTMENT_PROMPTS.get(dept_id)
    if not dept_prompt:
        return {"error": f"未知部门: {dept_id}"}
    
    dept_name = dept_prompt["name"]
    agents = parse_company_agents().get(dept_id, [])
    
    if not agents:
        log(f"[{dept_name}] 无员工数据", "WARN")
        return {"error": "无员工数据", "dept_id": dept_id}
    
    log(f"[{dept_name}] {len(agents)}名员工开始工作")
    
    # 构建输入数据
    if input_data is None:
        input_data = get_last_stage_output(dept_id)
    if input_data is None:
        input_data = "(无上游输入,请基于你的专业知识进行分析)"
    
    # === 真正唤醒所有员工子Agent执行任务 ===
    dept_info = {"name": dept_name}
    dept_result = run_department(dept_id, str(input_data), dept_info, agents)
    
    # 构建阶段产出
    result = {
        "dept": dept_name,
        "dept_id": dept_id,
        "timestamp": datetime.now().isoformat(),
        "agent_count": len(agents),
        "completed_count": dept_result.get("completed_count", 0),
        "status": dept_result.get("status", "unknown"),
        "agents": dept_result.get("employees", []),
        "merged_output": dept_result.get("merged_output", {}),
        "summary": _generate_stage_summary(dept_id, dept_result)
    }
    
    # 保存产出
    output_file = save_stage_output(dept_id, result)
    result["output_file"] = output_file
    
    log(f"✅ [{dept_name}] 完成,{result['completed_count']}/{len(agents)} 员工产生实际输出")
    
    return result


def _generate_stage_summary(dept_id: str, dept_result: Dict) -> str:
    """为阶段产出生成摘要文本"""
    merged = dept_result.get("merged_output", {})
    contribs = merged.get("contributions", [])
    employees = dept_result.get("employees", [])
    
    parts = [f"部门: {dept_result.get('name', dept_id)}"]
    parts.append(f"员工: {dept_result.get('completed_count', 0)}/{dept_result.get('agent_count', 0)} 完成")
    parts.append(f"产出: {len(contribs)} 条贡献")
    
    # 添加每个员工的简短摘要
    for emp in employees[:10]:  # 前10人摘要
        name = emp.get("name", "?")
        role = emp.get("role", "?")
        status = emp.get("status", "?")
        elapsed = emp.get("elapsed_seconds", 0)
        result_preview = ""
        parsed = emp.get("parsed_result")
        if parsed:
            if isinstance(parsed, dict):
                # 提取关键字段预览
                keys = list(parsed.keys())
                counts = [f"{k}:{len(v) if isinstance(v, list) else '?'}" for k in keys if k in parsed]
                result_preview = f" [{', '.join(counts[:3])}]"
            elif isinstance(parsed, list):
                result_preview = f" [{len(parsed)} items]"
        parts.append(f"  {name}({role}): {status}{result_preview} ({elapsed:.1f}s)")
    
    if len(employees) > 10:
        parts.append(f"  ... 还有 {len(employees) - 10} 名员工")
    
    return "\n".join(parts)


# ==================== 全流水线 ====================
DEPARTMENT_ORDER = [
    "01_marketing", "02_design", "03_product", "04_rd", "05_pmo",
    "06_dev", "07_support_proj", "08_engineering", "09_qa",
    "10_media", "11_support", "12_sales"
]

def run_full_pipeline():
    """全自动化流水线"""
    log("="*60)
    log("🚀 Agent Company 全自动化流水线启动")
    log("="*60)
    
    # Phase 0: 读取情报
    log("Phase 0: 读取最新情报数据...")
    intel_items = get_intelligence_data(hours=24, limit=100)
    log(f"获取到 {len(intel_items)} 条高价值情报")
    
    if not intel_items:
        log("无情报数据,流水线终止", "WARN")
        return
    
    # 保存情报摘要
    intel_summary = format_intel_for_prompt(intel_items)
    
    pipeline_results = {}
    current_input = intel_summary
    
    for dept_id in DEPARTMENT_ORDER:
        dept_name = DEPARTMENT_PROMPTS.get(dept_id, {}).get("name", dept_id)
        agents = parse_company_agents().get(dept_id, [])
        
        log(f"\n▶ Phase: [{dept_name}] ({len(agents)}人)")
        
        # 运行当前阶段(实际由orim调度)
        result = run_pipeline_phase(dept_id, current_input)
        pipeline_results[dept_id] = result
        
        # 准备作为下一阶段的输入
        if "output_file" in result:
            current_input = f"上一阶段 [{dept_name}] 产出: {result['output_file']}"
        
        # 进度汇报
        log(f"📋 [{dept_name}] 完成 → {result.get('output_file', '无')}")
    
    # 生成最终报告
    report = {
        "pipeline_id": f"pipe-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "timestamp": datetime.now().isoformat(),
        "total_stages": len(DEPARTMENT_ORDER),
        "results": {k: {"name": DEPARTMENT_PROMPTS.get(k,{}).get("name",k), 
                       "agent_count": len(parse_company_agents().get(k,[])),
                       "output": v.get("output_file","")} 
                   for k, v in pipeline_results.items()},
        "status": "completed"
    }
    
    report_file = HERMES_ROOT / "status" / f"pipeline_{date.today().isoformat()}.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    log("="*60)
    log(f"✅ 全流水线完成!报告: {report_file}")
    log("="*60)
    
    return report


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--phase":
        dept_id = sys.argv[2] if len(sys.argv) > 2 else "01_marketing"
        run_pipeline_phase(dept_id)
    else:
        run_full_pipeline()
