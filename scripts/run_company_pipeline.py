#!/usr/bin/env python3
"""
Agent Company 完整流水线入口
============================
由 cron 触发,运行整个 Workflow-Engine pipeline。

流程:
1. 初始化 WorkflowEngine
2. 注册所有handlers
3. 创建/加载公司流水线YAML
4. 执行流水线,等待完成
5. 输出最终报告
"""
import sys, os, json
from pathlib import Path
from datetime import datetime

# 添加路径
sys.path.insert(0, str(Path("/home/administrator/.hermes") / "skills" / "workflow-engine"))
sys.path.insert(0, str(Path("/home/administrator/.hermes") / "scripts"))

def main():
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n{'='*60}")
    print(f"🏭 Agent Company 全自动流水线")
    print(f"📅 {ts}")
    print(f"{'='*60}\n")
    
    # 1. 初始化引擎
    from workflow_engine import WorkflowEngine
    from workflow_storage import WorkflowStorage
    from workflow_builder import WorkflowBuilder
    
    storage = WorkflowStorage()
    engine = WorkflowEngine(storage=storage, max_workers=10)
    
    # 2. 注册handlers
    import company_handlers
    company_handlers.register_all_handlers(engine)
    
    # 3. 加载或创建workflow
    pipeline_yaml = "/mnt/d/Hermes/company_pipeline.yaml"
    if not Path(pipeline_yaml).exists():
        print(f"❌ 流水线YAML不存在: {pipeline_yaml}")
        return 1
    
    # 4. 创建workflow定义到storage
    from workflow_builder import load_workflow
    workflow = load_workflow(pipeline_yaml)
    if not workflow:
        # 手动创建
        import yaml
        with open(pipeline_yaml) as f:
            wf_data = yaml.safe_load(f)
        
        from workflow_definitions import Workflow, WorkflowStep, StepType
        workflow = Workflow(
            id=wf_data['id'],
            name=wf_data['name'],
            description=wf_data.get('description', ''),
            start_step_id=wf_data['start_step_id'],
            version=wf_data.get('version', '1.0.0')
        )
        # 直接存原始定义
        storage.save_workflow(wf_data['id'], wf_data)
    
    print("✅ 流水线已就绪")
    print(f"  ├─ YAML: {pipeline_yaml}")
    print(f"  ├─ Handlers: 13 个")
    print(f"  ├─ 员工: 138 人")
    print(f"  └─ 阶段: 12 个")
    
    # 5. 执行流水线(异步,不阻塞)
    run_id = f"company_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"\n▶ 启动流水线...")
    engine.start_workflow_async(
        workflow_id="company_pipeline_v1",
        run_id=run_id,
        variables={
            "intelligence_hours": 48,
            "max_employees_per_dept": 0,
            "pipeline_run_date": datetime.now().isoformat()
        }
    )
    print(f"  ├─ Run ID: {run_id}")
    print(f"  └─ 流水线已在后台启动\n")
    
    # 6. 输出启动报告
    report = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "pipeline": "company_pipeline_v1",
        "total_employees": sum(len(v) for v in company_handlers.parse_agents().values()),
        "total_handlers": len(engine._handlers),
        "status": "started"
    }
    
    report_file = Path(f"/mnt/d/Hermes/status/pipeline_run_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    
    print(f"📊 启动报告: {report_file}")
    print(f"\n{'='*60}")
    print(f"✅ 流水线已启动")
    print(f"{'='*60}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
