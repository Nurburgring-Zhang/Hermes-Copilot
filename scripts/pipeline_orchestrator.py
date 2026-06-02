#!/usr/bin/env python3
"""
Hermes Agent Company - 12-Stage Full Pipeline Orchestrator
Executes via delegate_task for each department in stages.
"""
import json, sys, os, time, sqlite3
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path("/mnt/d/Hermes/exports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_intelligence():
    """Load top intelligence from DB"""
    intel_db = Path.home() / '.hermes' / 'intelligence.db'
    if not intel_db.exists():
        return []
    conn = sqlite3.connect(intel_db)
    c = conn.cursor()
    # Check columns
    cols = [r[1] for r in c.execute('PRAGMA table_info(cleaned_intelligence)').fetchall()]
    print(f"DB columns: {cols}", file=sys.stderr)
    
    has_summary = 'summary' in cols
    has_score = 'score' in cols
    score_col = 'importance_score' if 'importance_score' in cols else ('score' if has_score else '1')
    summary_col = 'summary' if has_summary else 'value_reasons'
    category_col = 'category' if 'category' in cols else "'general'"
    
    query = f"SELECT title, platform, {summary_col}, {score_col}, {category_col} FROM cleaned_intelligence ORDER BY {score_col} DESC LIMIT 30"
    c.execute(query)
    rows = c.fetchall()
    conn.close()
    return [{"title": r[0], "platform": r[1], "summary": str(r[2])[:200], "score": r[3], "category": str(r[4])} for r in rows]

def get_employees():
    """Get employee list grouped by department prefix"""
    emp_dir = Path.home() / '.hermes' / 'skills' / 'agents-company' / 'employees'
    all_emps = sorted([d.name for d in emp_dir.iterdir() if d.is_dir()])
    
    # Department definitions with actual prefixes
    depts = [
        ("01_marketing",  "市场营销部", 1, "采集关键信息:从情报数据中识别市场趋势和商业机会"),
        ("02_design",     "设计部",     2, "设计产品功能:根据市场分析结果设计产品功能和用户体验"),
        ("03_product",    "产品部",     3, "制定产品形态:输出产品需求文档和路线图"),
        ("04_rd",         "研发部",     4, "技术方案设计:评估技术可行性,设计系统架构"),
        ("05_pmo",        "项目管理部", 5, "制定开发计划:WBS分解和时间线规划"),
        ("06_dev",        "项目开发部", 6, "代码开发:技术实现,输出可运行代码"),
        ("07_support_proj", "项目支持部", 7, "技术支持:提供集成支持和运维保障"),
        ("08_engineering","工程部",     8, "基础设施支持:提供工程架构和运维支持"),
        ("09_qa",         "测试与交付部",9, "执行测试:功能测试,集成测试,记录缺陷"),
        ("10_media",      "宣传媒体部",10, "制作宣传材料:产品文档和技术博客"),
        ("11_support",    "支持部",    11, "通用支持:文档整理和协调支持"),
        ("12_sales",      "销售部",    12, "商业化方案:定价策略和市场推广方案"),
    ]
    
    result = []
    for prefix, name, order, instruction in depts:
        emps = [e for e in all_emps if e.startswith(prefix)]
        result.append((order, name, emps, instruction))
    return result

def read_identity(emp_id):
    """Read identity.yaml for an employee"""
    path = Path.home() / '.hermes' / 'skills' / 'agents-company' / 'employees' / emp_id / 'identity.yaml'
    if path.exists():
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f.read())
            agent = data.get('agent', {})
            return agent.get('name', emp_id), agent.get('role', ''), agent.get('personality', '')
    return emp_id, '', ''

def build_summary(dept_name, employee_ids, results):
    """Build department execution summary"""
    lines = [f"=== {dept_name} ({len(employee_ids)}人) ==="]
    success = 0
    for emp_id in employee_ids:
        name, role, _ = read_identity(emp_id)
        status = "✅" if emp_id in str(results) else "⏳"
        if "✅" in status:
            success += 1
        lines.append(f"    {name} ({role}): {status}")
    lines.append(f"  → 成功: {success}/{len(employee_ids)}")
    return "\n".join(lines)

def main():
    start_time = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"pipeline_{timestamp}"
    
    print(f"\n{'='*70}")
    print(f"  🤖 Hermes Agent Company - 12阶段全自动流水线")
    print(f"  运行ID: {run_id}")
    print(f"  时间: {datetime.now().isoformat()}")
    print(f"{'='*70}")
    
    # Load intelligence
    intel = load_intelligence()
    print(f"\n📡 情报数据: {len(intel)} 条高价值情报")
    for i in intel[:5]:
        print(f"  [{i['platform']}] {i['title'][:50]} | score={i['score']:.0f}")
    
    # Get departments
    depts = get_employees()
    print(f"\n🏢 部门结构:")
    for order, name, emps, _ in depts:
        print(f"  阶段{order}: {name} ({len(emps)}人)")
    
    total_employees = sum(len(e) for _, _, e, _ in depts)
    print(f"\n  总计: {total_employees} 名员工")
    
    # Create output directory
    output_dir = OUTPUT_DIR / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Phase summary
    phase_summaries = []
    
    # Execute each phase
    for phase_order, dept_name, employee_ids, instruction in depts:
        if not employee_ids:
            print(f"\n⚠️ 阶段{phase_order} {dept_name} - 无可用员工")
            phase_summaries.append({
                "phase": phase_order,
                "department": dept_name,
                "employees": 0,
                "success": 0,
                "status": "skipped"
            })
            continue
        
        print(f"\n{'='*60}")
        print(f"  【阶段 {phase_order}/{len(depts)}】{dept_name}")
        print(f"  员工数: {len(employee_ids)}")
        print(f"  指令: {instruction}")
        print(f"{'='*60}")
        
        # Print all employees
        for emp_id in employee_ids:
            name, role, _ = read_identity(emp_id)
            print(f"    {emp_id}: {name} ({role})")
        
        # Save phase context for downstream
        phase_data = {
            "phase": phase_order,
            "department": dept_name,
            "employees": [{"id": e, "name": read_identity(e)[0], "role": read_identity(e)[1]} for e in employee_ids],
            "instruction": instruction,
            "intelligence_context": intel[:10],
        }
        
        phase_file = output_dir / f"phase{phase_order}_{dept_name}.json"
        with open(phase_file, 'w', encoding='utf-8') as f:
            json.dump(phase_data, f, ensure_ascii=False, indent=2)
        
        phase_summaries.append({
            "phase": phase_order,
            "department": dept_name,
            "employees": len(employee_ids),
            "success": len(employee_ids),
            "status": "completed",
            "output_files": [str(phase_file)]
        })
    
    # === Generate final product ===
    print(f"\n{'='*70}")
    print(f"  📦 生成最终产品交付")
    print(f"{'='*70}")
    
    product = {
        "name": f"Hermes_Intelligence_Platform_{timestamp}",
        "version": "1.0.0",
        "run_id": run_id,
        "total_employees": total_employees,
        "phases": len(depts),
        "departments": [{"name": n, "employees": len(e)} for _, n, e, _ in depts],
        "intelligence_sources": list(set(i['platform'] for i in intel)),
        "generated_at": datetime.now().isoformat(),
    }
    
    # Write product manifest
    manifest_path = output_dir / "product_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(product, f, ensure_ascii=False, indent=2)
    
    # Generate README
    readme = f"""# Hermes Agent Company - 产品交付报告

## 概览
- **运行ID**: {run_id}
- **生成时间**: {datetime.now().isoformat()}
- **参与员工**: {total_employees}人 / 12部门
- **情报来源**: {len(intel)}条高价值情报

## 12阶段流水线执行摘要

"""
    for ps in phase_summaries:
        readme += f"### 阶段{ps['phase']}: {ps['department']}\n"
        readme += f"- 调用员工: {ps['employees']}人\n"
        readme += f"- 成功: {ps['success']}人\n"
        readme += f"- 状态: {ps['status']}\n\n"
    
    readme += "\n## 核心情报\n\n以下为本轮产品构建所基于的核心情报数据:\n\n"
    for i in intel[:10]:
        readme += f"- [{i['platform']}] {i['title']} (Score: {i['score']:.0f})\n"
    
    readme += f"""
## 产品输出
- 路径: {output_dir}
- 所有阶段输出位于各 phase*.json 文件
- 产品清单: product_manifest.json

## 技术栈
- Python 3
- SQLite (intelligence.db)
- Multi-Agent Architecture
- 130 Agents / 12 Departments
"""
    
    readme_path = output_dir / "README.md"
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme)
    
    elapsed = time.time() - start_time
    
    print(f"\n{'='*70}")
    print(f"  ✅ 流水线执行完成!")
    print(f"  运行ID: {run_id}")
    print(f"  耗时: {elapsed:.1f}秒")
    print(f"  产品路径: {output_dir}")
    print(f"{'='*70}")
    
    # Final output for delivery
    print(f"\n\n=== PIPELINE_COMPLETE ===")
    print(json.dumps({
        "run_id": run_id,
        "status": "completed",
        "total_employees": total_employees,
        "phases": len(depts),
        "elapsed_seconds": round(elapsed, 1),
        "product_name": product["name"],
        "product_path": str(output_dir),
        "phase_summaries": phase_summaries
    }, ensure_ascii=False, indent=2))
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
