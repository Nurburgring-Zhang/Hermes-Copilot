#!/usr/bin/env python3
"""
Orim — Hermes 全自动化 Multi-Agent 调度中枢
=============================================
核心功能:
1. 接收触发信号(cron 05:00 / 手动 / 事件驱动)
2. 按12阶段流水线唤醒各部门
3. 每个阶段唤醒对应专家系统提供专业支持
4. 跟踪每个环节的进度和交付物
5. 汇总最终交付到 /mnt/d/Hermes/

架构:
  调度Agent(主) → 部门调度(子) → 员工Agent(孙) + 专家Agent(并行)
  
三层Agent设计:
  Layer 1: Orim 主调度(我)— 负责任务分解/进度跟踪/异常处理
  Layer 2: 部门调度Agent — 每个部门一个,负责本部门内部协调
  Layer 3: 员工独立子Agent — 每人独立身份+独立工具,用delegate_task创建

工作流程:
  Trigger → [采集情报] → AgentExport分析 → [运营部挖需求] → [设计部做功能]
  → [产品部定义产品] → [研发部研发] → [PMO制定计划] → [开发部开发]
  → [支持部支持] → [工程部工程] → [QA测试] → [媒体部宣传] → [销售部售卖]
  → 交付到D:\\Hermes → 推送摘要到微信
"""

import json, sys, os, time, sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# ==================== 配置 ====================
HERMES_ROOT = Path("/mnt/d/Hermes")
DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"
SCRIPTS = Path("/home/administrator/.hermes") / "scripts"
AGENT_COMPANY_DIR = Path("/mnt/d/OpenClaw/agents_company")
EXPERTS_DIR = Path("/mnt/d/OpenClaw/experts")

# 确保目录存在
for d in ["demands","designs","products","rd","projects","dev","support",
          "engineering","qa","media","sales","exports","status","daily_report"]:
    (HERMES_ROOT / d).mkdir(parents=True, exist_ok=True)

# ==================== 12部门定义 ====================
DEPARTMENTS = {
    "marketing": {
        "name": "市场营销部",
        "code": "01_marketing",
        "upstream": "external",
        "downstream": "design",
        "trigger": "每日5点从情报流挖需求",
        "agent_count": 5
    },
    "design": {
        "name": "设计部",
        "code": "02_design",
        "upstream": "marketing",
        "downstream": "product",
        "trigger": "接到marketing需求",
        "agent_count": 8
    },
    "product": {
        "name": "产品部",
        "code": "03_product",
        "upstream": "design",
        "downstream": "rd",
        "trigger": "接到design设计稿",
        "agent_count": 4
    },
    "rd": {
        "name": "研发部",
        "code": "04_rd",
        "upstream": "product",
        "downstream": "pmo",
        "trigger": "接到product产品定义",
        "agent_count": 6
    },
    "pmo": {
        "name": "项目管理部",
        "code": "05_pmo",
        "upstream": "rd",
        "downstream": "dev",
        "trigger": "接到rd研发成果",
        "agent_count": 5
    },
    "dev": {
        "name": "项目开发部",
        "code": "06_dev",
        "upstream": "pmo",
        "downstream": "support_proj",
        "trigger": "接到pmo开发计划",
        "agent_count": 30
    },
    "support_proj": {
        "name": "项目支持部",
        "code": "07_support_proj",
        "upstream": "dev",
        "downstream": "engineering",
        "trigger": "接到dev开发成果",
        "agent_count": 20
    },
    "engineering": {
        "name": "工程部",
        "code": "08_engineering",
        "upstream": "support_proj",
        "downstream": "qa",
        "trigger": "接到support_proj支持成果",
        "agent_count": 23
    },
    "qa": {
        "name": "测试与交付部",
        "code": "09_qa",
        "upstream": "engineering",
        "downstream": "media",
        "trigger": "接到engineering工程成果",
        "agent_count": 8,
        "loopback": "pmo"  # 测试不通过返回PMO
    },
    "media": {
        "name": "宣传媒体部",
        "code": "10_media",
        "upstream": "qa",
        "downstream": "support",
        "trigger": "接到qa测试通过交付",
        "agent_count": 7
    },
    "support": {
        "name": "支持部",
        "code": "11_support",
        "upstream": "media",
        "downstream": "sales",
        "trigger": "接到media宣传材料",
        "agent_count": 6
    },
    "sales": {
        "name": "销售部",
        "code": "12_sales",
        "upstream": "support",
        "downstream": "交付",
        "trigger": "接到support支持成果",
        "agent_count": 8
    }
}

# ==================== 15专家类型定义 ====================
EXPERT_TYPES = {
    "Pm": "综合管理规划专家",
    "Collector": "信息采集与清洗专家",
    "Analyst": "信息分析与展示专家",
    "Intel": "咨询与情报分析专家",
    "Researcher": "深度科学研究专家",
    "Innovator": "创新与鬼点子专家",
    "Media": "新媒体运营专家",
    "AIGC": "媒体生产专家",
    "Artist": "创意设计专家",
    "Office": "办公自动化专家",
    "Architect": "架构设计与开发专家",
    "Coder": "代码编写软件生产专家",
    "Security": "系统安全与审计专家",
    "Acceptance": "系统验收与交付专家",
    "Companion": "AI数字人助手"
}

# ==================== 日志 ====================
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}] [ORIM] {msg}"
    print(line, flush=True)
    log_file = HERMES_ROOT / "status" / f"orim_{date.today().isoformat()}.log"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(line + "\n")

# ==================== 状态管理 ====================
class PipelineState:
    """全自动化流水线状态跟踪"""
    def __init__(self, pipeline_id: str = None):
        self.pipeline_id = pipeline_id or f"pipe-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.started_at = datetime.now().isoformat()
        self.stages: Dict[str, Dict] = {}
        self.current_stage: Optional[str] = None
        self.errors: List[str] = []
        self.deliveries: List[Dict] = []
        self._init_stages()
    
    def _init_stages(self):
        for dept_id, dept_info in DEPARTMENTS.items():
            self.stages[dept_id] = {
                "name": dept_info["name"],
                "status": "pending",  # pending | running | done | failed | loopback
                "started_at": None,
                "completed_at": None,
                "output_files": [],
                "summary": "",
                "error": None
            }
    
    def start_stage(self, dept_id: str):
        self.current_stage = dept_id
        self.stages[dept_id]["status"] = "running"
        self.stages[dept_id]["started_at"] = datetime.now().isoformat()
        log(f"阶段启动: [{dept_id}] {self.stages[dept_id]['name']}")
    
    def complete_stage(self, dept_id: str, summary: str, output_files: List[str] = None):
        self.stages[dept_id]["status"] = "done"
        self.stages[dept_id]["completed_at"] = datetime.now().isoformat()
        self.stages[dept_id]["summary"] = summary
        if output_files:
            self.stages[dept_id]["output_files"] = output_files
        log(f"阶段完成: [{dept_id}] {self.stages[dept_id]['name']} → {summary[:80]}")
    
    def fail_stage(self, dept_id: str, error: str):
        self.stages[dept_id]["status"] = "failed"
        self.stages[dept_id]["error"] = error
        self.errors.append(f"[{dept_id}] {error}")
        log(f"阶段失败: [{dept_id}] {error}", "ERROR")
    
    def loopback_stage(self, dept_id: str, target: str):
        """QA测试不通过,返回PMO重新规划"""
        self.stages[dept_id]["status"] = "loopback"
        log(f"回路触发: [{dept_id}] → 返回[{target}]重新规划")
    
    def add_delivery(self, item: Dict):
        self.deliveries.append(item)
    
    def get_report(self) -> Dict:
        elapsed = (datetime.fromisoformat(self.started_at) if 'T' in self.started_at 
                   else datetime.now())  # fallback
        now = datetime.now()
        try:
            start = datetime.fromisoformat(self.started_at)
            elapsed_seconds = (now - start).total_seconds()
        except:
            elapsed_seconds = 0
        
        done = sum(1 for s in self.stages.values() if s["status"] == "done")
        total = len(self.stages)
        
        return {
            "pipeline_id": self.pipeline_id,
            "started_at": self.started_at,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "progress": f"{done}/{total} stages completed",
            "stages": {k: {"name": v["name"], "status": v["status"], 
                          "summary": v["summary"][:100] if v["summary"] else ""}
                      for k, v in self.stages.items()},
            "deliveries": self.deliveries,
            "errors": self.errors,
            "status": "failed" if self.errors else "completed"
        }
    
    def save(self):
        report = self.get_report()
        report_file = HERMES_ROOT / "status" / f"pipeline_{date.today().isoformat()}.json"
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        log(f"流水线报告已保存: {report_file}")
        return report_file


# ==================== 情报系统接口 ====================
def get_intelligence_data(hours: int = 24, limit: int = 200) -> List[Dict]:
    """从cleaned_intelligence获取高价值情报"""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        c = db.execute(f"""
            SELECT c.title, c.content, c.url, c.platform, c.importance_score,
                   c.value_level, c.personal_match_score, c.is_ai_related,
                   c.language, c.category, c.source, c.collected_at, c.cleaned_at
            FROM cleaned_intelligence c
            WHERE c.cleaned_at >= datetime('now', '-{hours} hours')
              AND c.importance_score >= 0.5
            ORDER BY c.importance_score DESC, c.personal_match_score DESC
            LIMIT {limit}
        """)
        items = []
        for row in c.fetchall():
            items.append({
                "title": row[0],
                "content": (row[1] or "")[:500],
                "url": row[2],
                "platform": row[3],
                "importance": row[4],
                "value_level": row[5],
                "personal_match": row[6],
                "is_ai_related": row[7],
                "language": row[8],
                "category": row[9],
                "source": row[10] or row[3],
                "collected_at": row[11],
                "cleaned_at": row[12]
            })
        db.close()
        return items
    except Exception as e:
        log(f"读取情报失败: {e}", "ERROR")
        return []


# ==================== Multi-Agent 部门调用 ====================
def run_company_stage(dept_id: str, input_data: Dict, state: PipelineState) -> Dict:
    """
    运行一个部门的完整工作流。
    部门内部使用delegate_task创建员工子Agent集群并行处理。
    返回该阶段的产出物。
    """
    dept = DEPARTMENTS[dept_id]
    state.start_stage(dept_id)
    
    log(f"▶ [{dept['name']}] 开始工作,{dept['agent_count']}名员工待命...")
    
    # 这里实际的delegate_task调用由Orim在运行时完成
    # 本函数是调度协议,调用者使用delegate_task执行
    
    return {
        "dept_id": dept_id,
        "name": dept["name"],
        "input": input_data,
        "agent_count": dept["agent_count"],
    }


# ==================== 流水线入口 ====================
def run_full_pipeline(trigger: str = "cron_0500") -> Dict:
    """
    全自动化流水线入口
    trigger: 触发来源 (cron_0500 / manual / event)
    """
    pipeline_id = f"pipe-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    log(f"{'='*60}")
    log(f"🚀 全自动化流水线启动 | ID: {pipeline_id} | 触发: {trigger}")
    log(f"{'='*60}")
    
    state = PipelineState(pipeline_id)
    
    # ===== Phase 0: 情报采集 + Agent Export 分析 =====
    log("Phase 0: 获取情报数据...")
    intel_data = get_intelligence_data(hours=24, limit=200)
    log(f"获取到 {len(intel_data)} 条高价值情报")
    
    if not intel_data:
        log("无情报数据,流水线终止", "WARN")
        state.fail_stage("marketing", "无情报数据")
        state.save()
        return state.get_report()
    
    # 保存情报快照
    snapshot_file = HERMES_ROOT / "exports" / f"intel_snapshot_{date.today().isoformat()}.json"
    snapshot_file.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "pipeline_id": pipeline_id,
        "total": len(intel_data),
        "items": intel_data[:100]
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f"情报快照已保存: {snapshot_file}")
    
    # ===== Phase 1-12: 逐部门流水线 =====
    # 每个阶段接收上游产出,通过delegate_task调度
    # 详细实现在run_pipeline.py中
    
    return state.get_report()


# ==================== CLI入口 ====================
if __name__ == "__main__":
    trigger = sys.argv[1] if len(sys.argv) > 1 else "manual"
    report = run_full_pipeline(trigger)
    
    print("\n" + "="*60)
    print(f"流水线完成: {report['status']}")
    print(f"进度: {report['progress']}")
    print(f"耗时: {report['elapsed_seconds']}秒")
    if report['deliveries']:
        print(f"交付物: {len(report['deliveries'])}个")
    print("="*60)
