"""
⚙️ 双规划器+见证者+三级纠偏任务引擎 V1.2 — 集成增强型语义漂移检测
================================================================
基于OI v4.0第二十章-第二十五章设计

V1.2 更新:
  - 见证者漂移检测集成EnhancedDriftDetector(英中文混合+同义词映射)
  - 注入semantic_engine_v2的增强型语义相似度计算
  - 修复GAP5: 同义词映射使JWT重构→RS256验证正确识别为轻度偏移(0.422)
"""

import json, os, sys, sqlite3, time, hashlib, uuid, threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum


HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)


# =================================================================
# 枚举与数据结构
# =================================================================

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"

    def __str__(self):
        return self.value


class DriftLevel(Enum):
    """漂移等级(对应三级纠偏)"""
    OK = "ok"              # 无漂移
    MILD = "mild"          # 轻度漂移 [0.3, 0.5)
    MODERATE = "moderate"  # 中度漂移 [0.5, 0.7)
    SEVERE = "severe"      # 重度漂移 ≥0.7

    def __str__(self):
        return self.value


class RiskLevel(Enum):
    """工具风险等级(对应KDN)"""
    LOW = "low"         # 不需要拦截
    MEDIUM = "medium"   # 需要单确认
    HIGH = "high"       # 需要双确认

    def __str__(self):
        return self.value


@dataclass
class Task:
    """
    任务数据结构 — 对应OI OITask struct
    
    Claude Code Task V2兼容:
      - 文件+SQLite双写
      - blockedBy/blocks依赖
      - owner归属Agent
    """
    task_id: str
    session_id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    parent_task_id: Optional[str] = None
    owner: Optional[str] = None
    priority: int = 0
    blocked_by: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None
    execution_metadata: dict = field(default_factory=dict)
    steps: List[str] = field(default_factory=list)
    current_step: int = 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "subject": self.subject,
            "description": self.description[:200],
            "status": str(self.status),
            "parent_task_id": self.parent_task_id,
            "owner": self.owner,
            "priority": self.priority,
            "blocked_by": self.blocked_by,
            "blocks": self.blocks,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "steps_total": len(self.steps),
            "current_step": self.current_step,
        }


@dataclass
class ExecutionPlan:
    """执行计划(双规划器输出)"""
    planner: str              # "A" 或 "B"
    steps: List[dict]         # 步骤序列
    confidence: float         # 置信度(0-1)
    rationale: str             # 推理依据
    estimated_rounds: int
    risk_assessment: str      # 风险评估


# =================================================================
# 任务存储 — 借鉴Claude Code Task V2
# =================================================================

class TaskStore:
    """
    任务存储 — 文件+SQLite双写
    
    文件名: ~/.hermes/tasks/{task_id}.json
    SQLite: ~/.hermes/data/tasks.db
    """

    def __init__(self):
        self._tasks_dir = HERMES / "tasks"
        self._tasks_dir.mkdir(exist_ok=True)
        self._db_path = HERMES / "data" / "tasks.db"
        self._db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                parent_task_id TEXT,
                owner TEXT,
                priority INTEGER DEFAULT 0,
                blocked_by TEXT DEFAULT '[]',
                blocks TEXT DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                execution_metadata TEXT DEFAULT '{}',
                steps TEXT DEFAULT '[]',
                current_step INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def create(self, task: Task) -> Task:
        """创建任务(文件+SQLite双写)"""
        if not task.created_at:
            task.created_at = NOW().isoformat()
        if not task.updated_at:
            task.updated_at = task.created_at
        if not task.task_id:
            task.task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        if not task.session_id:
            task.session_id = f"session_{int(time.time())}"
        
        # 写入文件
        file_path = self._tasks_dir / f"{task.task_id}.json"
        file_path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        
        # 写入SQLite
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            INSERT OR REPLACE INTO tasks 
            (task_id, session_id, subject, description, status, parent_task_id,
             owner, priority, blocked_by, blocks, created_at, updated_at,
             completed_at, execution_metadata, steps, current_step)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task.task_id, task.session_id, task.subject, task.description,
            str(task.status), task.parent_task_id, task.owner, task.priority,
            json.dumps(task.blocked_by), json.dumps(task.blocks),
            task.created_at, task.updated_at, task.completed_at,
            json.dumps(task.execution_metadata),
            json.dumps(task.steps), task.current_step,
        ))
        conn.commit()
        conn.close()
        
        return task

    def get(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        return self._row_to_task(row)

    def _row_to_task(self, row) -> Task:
        """数据库行转Task对象"""
        return Task(
            task_id=row[0], session_id=row[1], subject=row[2],
            description=row[3] or "",
            status=TaskStatus(row[4]) if row[4] else TaskStatus.PENDING,
            parent_task_id=row[5], owner=row[6], priority=row[7] or 0,
            blocked_by=json.loads(row[8] or "[]"),
            blocks=json.loads(row[9] or "[]"),
            created_at=row[10] or "", updated_at=row[11] or "",
            completed_at=row[12],
            execution_metadata=json.loads(row[13] or "{}"),
            steps=json.loads(row[14] or "[]"),
            current_step=row[15] or 0,
        )

    def update(self, task: Task) -> bool:
        """更新任务"""
        task.updated_at = NOW().isoformat()
        
        if task.status == TaskStatus.COMPLETED and not task.completed_at:
            task.completed_at = task.updated_at
        
        # 写文件
        file_path = self._tasks_dir / f"{task.task_id}.json"
        file_path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        
        # 写SQLite
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            UPDATE tasks SET
                status=?, owner=?, priority=?, blocked_by=?, blocks=?,
                updated_at=?, completed_at=?, execution_metadata=?,
                steps=?, current_step=?, description=?
            WHERE task_id=?
        """, (
            str(task.status), task.owner, task.priority,
            json.dumps(task.blocked_by), json.dumps(task.blocks),
            task.updated_at, task.completed_at,
            json.dumps(task.execution_metadata),
            json.dumps(task.steps), task.current_step,
            task.description, task.task_id,
        ))
        conn.commit()
        affected = conn.total_changes
        conn.close()
        
        return affected > 0

    def list_tasks(self, status_filter: Optional[str] = None) -> List[Task]:
        """列出任务"""
        conn = sqlite3.connect(str(self._db_path))
        if status_filter:
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at DESC",
                (status_filter,)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM tasks ORDER BY priority DESC, created_at DESC"
            )
        tasks = [self._row_to_task(row) for row in cursor.fetchall()]
        conn.close()
        return tasks

    def claim(self, task_id: str, owner: str) -> bool:
        """原子抢占任务"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.execute(
            "SELECT status, owner FROM tasks WHERE task_id = ?", (task_id,)
        )
        row = cursor.fetchone()
        if not row or row[0] != "pending":
            conn.close()
            return False
        
        conn.execute(
            "UPDATE tasks SET status=?, owner=?, updated_at=? WHERE task_id=? AND status='pending'",
            ("in_progress", owner, NOW().isoformat(), task_id)
        )
        conn.commit()
        affected = conn.total_changes
        conn.close()
        
        # 同步写文件
        task = self.get(task_id)
        if task:
            file_path = self._tasks_dir / f"{task.task_id}.json"
            file_path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        
        return affected > 0

    def clear_dependency(self, completed_task_id: str):
        """
        清理依赖 — 当某任务完成时,
        从所有依赖它的任务的blocked_by列表中移除
        """
        conn = sqlite3.connect(str(self._db_path))
        tasks = conn.execute(
            "SELECT task_id, blocked_by FROM tasks WHERE blocked_by LIKE ?",
            (f'%{completed_task_id}%',)
        ).fetchall()
        
        for row in tasks:
            task_id = row[0]
            blocked_by = json.loads(row[1] or "[]")
            if completed_task_id in blocked_by:
                blocked_by.remove(completed_task_id)
                conn.execute(
                    "UPDATE tasks SET blocked_by=? WHERE task_id=?",
                    (json.dumps(blocked_by), task_id)
                )
        
        conn.commit()
        conn.close()


# =================================================================
# 规划器 & 见证者 — 双规划器+见证者(DPW)架构
# =================================================================

class Planner:
    """
    规划器基类
    对应OI Planner trait
    """

    def __init__(self, name: str, style: str):
        self.name = name
        self.style = style  # "systematic" or "intuitive"
        self.plan_count = 0
        self.success_count = 0

    def plan(self, goal: str, context: Optional[dict] = None) -> ExecutionPlan:
        """生成执行计划"""
        raise NotImplementedError

    def reflect(self, feedback: str) -> dict:
        """从反馈中学习"""
        raise NotImplementedError


class SystematicPlanner(Planner):
    """
    规划器A — 系统性规划器(Tree-of-Thoughts风格)
    
    特点:
      - 生成完整执行路径树
      - 每个分支评估可行性与预期效果
      - 保守倾向(倾向于经充分验证的路径)
      - 利用历史经验
    """

    def __init__(self):
        super().__init__("Planner-A", "systematic")

    def plan(self, goal: str, context: Optional[dict] = None) -> ExecutionPlan:
        """系统化生成执行计划"""
        self.plan_count += 1
        
        context = context or {}
        
        # 基于目标复杂度的步骤预估
        goal_length = len(goal)
        estimated_rounds = max(3, min(10, goal_length // 20))
        
        # 系统化分解 — Tree-of-Thoughts风格的路径树
        steps = [
            {"id": f"A.{i+1}", "action": self._generate_step(goal, i, estimated_rounds),
             "rationale": "", "expected_outcome": ""}
            for i in range(estimated_rounds)
        ]
        
        plan = ExecutionPlan(
            planner="A",
            steps=steps,
            confidence=0.75,  # 保守
            rationale=f"系统化分解为{estimated_rounds}步,TOT风格完整路径评估",
            estimated_rounds=estimated_rounds,
            risk_assessment="low",
        )
        
        return plan

    def _generate_step(self, goal: str, step_index: int, total: int) -> str:
        """生成步骤描述"""
        phases = [
            "分析目标与需求",
            "制定技术方案",
            "搭建基础架构",
            "实现核心功能",
            "集成与测试",
            "性能优化",
            "文档与验证",
        ]
        
        if step_index < len(phases):
            return f"{phases[step_index]} - {goal[:30]}"
        else:
            return f"迭代优化 #{step_index + 1} - {goal[:20]}"

    def reflect(self, feedback: str) -> dict:
        """从反馈中学习"""
        return {
            "planner": "A",
            "learned": f"从反馈中分析: {feedback[:100]}",
            "weight_adjustment": 0.0,
        }


class IntuitivePlanner(Planner):
    """
    规划器B — 直觉性规划器(ReAct风格)
    
    特点:
      - 不预生成完整计划
      - 根据执行反馈动态调整
      - 激进倾向(尝试新的执行路径)
      - 善于利用历史经验
    """

    def __init__(self):
        super().__init__("Planner-B", "intuitive")

    def plan(self, goal: str, context: Optional[dict] = None) -> ExecutionPlan:
        """直觉式生成执行计划"""
        self.plan_count += 1
        
        context = context or {}
        goal_length = len(goal)
        estimated_rounds = max(2, min(8, goal_length // 30))
        
        # 直觉式—更直接、更少步骤
        steps = [
            {"id": f"B.{i+1}", "action": self._generate_step(goal, i),
             "rationale": "直觉推断", "expected_outcome": ""}
            for i in range(estimated_rounds)
        ]
        
        plan = ExecutionPlan(
            planner="B",
            steps=steps,
            confidence=0.85,  # 偏向自信
            rationale=f"直觉式分解为{estimated_rounds}步,ReAct风格动态调整",
            estimated_rounds=estimated_rounds,
            risk_assessment="medium",  # 激进倾向
        )
        
        return plan

    def _generate_step(self, goal: str, step_index: int) -> str:
        """生成直觉式步骤"""
        actions = [
            "快速原型",
            "核心实现",
            "关键验证",
            "迭代完善",
            "最终交付",
        ]
        if step_index < len(actions):
            return f"{actions[step_index]}: {goal[:40]}"
        else:
            return f"快速迭代 #{step_index + 1}"

    def reflect(self, feedback: str) -> dict:
        """从反馈中学习"""
        return {
            "planner": "B",
            "learned": f"直觉式自省: {feedback[:100]}",
            "weight_adjustment": 0.0,
        }


class Witness:
    """
    见证者 — 独立裁决者
    
    职责:
      1. 比较A/B规划方案的一致性
      2. 检测任务执行漂移
      3. 触发三级纠偏
      4. 记录监督日志
    
    对应OI: 见证者+KDN审计器
    """

    def __init__(self):
        self.total_comparisons = 0
        self.consistent_count = 0
        self.drift_count = 0
        self.correction_count = {DriftLevel.MILD: 0, DriftLevel.MODERATE: 0, DriftLevel.SEVERE: 0}
        
        # 纠偏经验库(借鉴Hermes学习循环)
        self.correction_library = []
        self._load_correction_library()

    def _load_correction_library(self):
        """加载纠偏经验库"""
        path = HERMES / "reports" / "correction_library.json"
        if path.exists():
            try:
                self.correction_library = json.loads(path.read_text())
            except Exception:
                pass

    def _save_correction_library(self):
        """保存纠偏经验库"""
        path = HERMES / "reports" / "correction_library.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.correction_library[-100:], ensure_ascii=False, indent=2))

    def compare_plans(self, plan_a: ExecutionPlan, plan_b: ExecutionPlan) -> dict:
        """
        比较A和B规划方案
        
        返回: {consistent, similarity, analysis}
        """
        self.total_comparisons += 1
        
        # 比较步骤数和内容
        steps_a = [s["action"] for s in plan_a.steps]
        steps_b = [s["action"] for s in plan_b.steps]
        
        # 文本相似度
        text_a = " ".join(steps_a)
        text_b = " ".join(steps_b)
        
        # 简单相似度计算(基于共同子串)
        shared = len(set(text_a.split()) & set(text_b.split()))
        total = len(set(text_a.split()) | set(text_b.split()))
        similarity = shared / max(total, 1)
        
        consistent = similarity > 0.3
        
        if consistent:
            self.consistent_count += 1
        
        analysis = {
            "consistent": consistent,
            "similarity": round(similarity, 3),
            "plan_a_steps": len(steps_a),
            "plan_b_steps": len(steps_b),
            "analysis": "方案一致" if consistent else "方案分歧",
        }
        
        if not consistent:
            analysis["divergence_reason"] = (
                f"A计划{len(steps_a)}步 vs B计划{len(steps_b)}步, "
                f"文本相似度{similarity:.1%}"
            )
        
        return analysis

    def detect_drift(self, goal: str, current_context: str, 
                     current_step: int, total_steps: int) -> dict:
        """
        检测任务漂移
        
        使用EnhancedDriftDetector进行三重检测:
          1. 同义词增强的关键词重叠(支持英中文混合)
          2. 语义嵌入相似度(如可用)
          3. 进度偏离度
        
        返回: {drift_level, score, action}
        """
        # 尝试使用增强型漂移检测器
        try:
            import importlib.util
            evo_path = Path(__file__).parent.parent / "evolution_v3"
            spec = importlib.util.spec_from_file_location(
                "semantic_engine_v2", 
                str(evo_path / "semantic_engine_v2.py")
            )
            if spec and spec.loader:
                sem_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sem_mod)
                detector = sem_mod.EnhancedDriftDetector()
                result = detector.detect_drift(goal, current_context, current_step, total_steps)
                return result
        except Exception:
            pass
        
        # 回退: 使用原有的中文trigram检测
        def _extract_trigrams(text: str) -> set:
            import re
            stops = {'的','了','是','在','和','与','有','不','也'}
            chars = re.findall(r'[\u4e00-\u9fff]', text)
            trigrams = set()
            for i in range(len(chars)-2):
                tg = chars[i] + chars[i+1] + chars[i+2]
                non_stop = sum(1 for c in tg if c not in stops)
                if non_stop >= 2:
                    trigrams.add(tg)
            return trigrams
        
        goal_trigrams = _extract_trigrams(goal)
        context_trigrams = _extract_trigrams(current_context)
        
        # 如果没有上下文,认为无漂移
        if not context_trigrams:
            return {"drift_level": DriftLevel.OK, "score": 0.0, "action": "上下文不足,跳过"}
        
        if not goal_trigrams:
            return {"drift_level": DriftLevel.OK, "score": 0.0, "action": "无目标"} 
        
        # 重叠度计算
        overlap = len(goal_trigrams & context_trigrams)
        semantic_distance = 1.0 - (overlap / max(len(goal_trigrams), 1))
        
        # 检测因子2: 进度偏离度
        if total_steps > 0:
            progress_ratio = current_step / total_steps
            progress_deviation = abs(progress_ratio - 0.5) * 0.5  # 简单估算
        else:
            progress_deviation = 0.0
        
        # 综合漂移分数
        # 语义距离权重0.4, 进度偏差0.3, 额外加一个"完成度"因子0.3
        drift_score = semantic_distance * 0.4 + progress_deviation * 0.3
        
        # 如果接近完成(>80%),降低漂移警告
        if total_steps > 0 and current_step / total_steps > 0.8:
            drift_score *= 0.7
        
        drift_score = min(1.0, max(0.0, drift_score))
        
        # 阈值设置 — 中文trigram检测偏保守
        if drift_score < 0.25:
            drift_level = DriftLevel.OK
            action = "正常执行"
        elif drift_score < 0.5:
            drift_level = DriftLevel.MILD
            action = "需注意:语义轻微偏移"
        elif drift_score < 0.7:
            drift_level = DriftLevel.MODERATE
            action = "警告:中度漂移,需干预"
        else:
            drift_level = DriftLevel.SEVERE
            action = "严重:完全偏离目标"
        
        if drift_level != DriftLevel.OK:
            self.drift_count += 1
            self.correction_count[drift_level] = self.correction_count.get(drift_level, 0) + 1
        
        return {
            "drift_level": drift_level,
            "score": round(drift_score, 4),
            "semantic_distance": round(semantic_distance, 4),
            "progress_deviation": round(progress_deviation, 4),
            "action": action,
        }

    def apply_correction(self, drift_result: dict, task: Task,
                         correction_history: list) -> dict:
        """
        应用三级纠偏
        
        Level 1 轻度: 上下文注入引导提示
        Level 2 中度: 自动回退3-5步
        Level 3 重度: 完全重置+复盘
        """
        level = drift_result["drift_level"]
        # 支持字符串和Enum
        if isinstance(level, str):
            try:
                level_enum = DriftLevel(level)
            except ValueError:
                level_enum = DriftLevel.OK
        else:
            level_enum = level
        
        correction = {
            "ts": NOW().isoformat(),
            "task_id": task.task_id,
            "drift_score": drift_result["score"],
            "level": str(level_enum),
            "action": "",
            "message": "",
            "history_count": len(correction_history),
        }
        
        if level_enum == DriftLevel.MILD:
            # 轻度: 注入引导提示
            mild_count = sum(1 for c in correction_history 
                           if c.get("level") == "mild")
            
            if mild_count >= 3:
                correction["action"] = "escalate_to_moderate"
                correction["message"] = "轻度纠偏已尝试3次,升级为中度"
                correction["level"] = "moderate"
            else:
                correction["action"] = "inject_guidance"
                correction["message"] = (
                    f"注入引导提示: 当前任务'{task.subject}'的目标是"
                    f"'{task.description[:100]}',请注意保持目标一致性"
                )
        
        elif level_enum == DriftLevel.MODERATE:
            # 中度: 回退3-5步
            moderate_count = sum(1 for c in correction_history 
                               for lvl in ["moderate", "mild->moderate"]
                               if c.get("level") in [lvl, "mild->moderate"])
            
            if moderate_count >= 2:
                correction["action"] = "escalate_to_severe"
                correction["message"] = "中度纠偏已尝试2次,升级为重度"
                correction["level"] = "severe"
            else:
                fallback_steps = min(5, task.current_step)
                task.current_step = max(0, task.current_step - fallback_steps)
                correction["action"] = f"rollback_{fallback_steps}_steps"
                correction["message"] = f"自动回退{fallback_steps}步到步骤{task.current_step}"
        
        elif level_enum == DriftLevel.SEVERE:
            # 重度: 完全重置
            correction["action"] = "full_reset_with_review"
            correction["message"] = (
                f"完全重置任务'{task.subject}': "
                f"记录失败案例到经验库,注入复盘报告,等待用户确认"
            )
            
            # 记录失败案例
            failure_case = {
                "ts": NOW().isoformat(),
                "task_id": task.task_id,
                "subject": task.subject,
                "drift_score": drift_result["score"],
                "current_step": task.current_step,
                "total_steps": len(task.steps),
            }
            self.correction_library.append(failure_case)
            self._save_correction_library()
        
        return correction

    def health(self) -> dict:
        """见证者健康报告"""
        return {
            "total_comparisons": self.total_comparisons,
            "consistent_rate": round(
                self.consistent_count / max(self.total_comparisons, 1) * 100, 1
            ),
            "drift_total": self.drift_count,
            "corrections_by_level": {
                str(k): v for k, v in self.correction_count.items()
            },
            "correction_library_size": len(self.correction_library),
        }


# =================================================================
# 任务引擎 — 主入口
# =================================================================

class TaskEngine:
    """
    任务引擎 — 整合规划器+见证者+存储
    
    七大工具(Task API):
      TaskCreate, TaskList, TaskGet, TaskUpdate,
      TaskStop, TaskClaim, TaskOutput
    """

    def __init__(self):
        self.store = TaskStore()
        self.planner_a = SystematicPlanner()
        self.planner_b = IntuitivePlanner()
        self.witness = Witness()
        
        # 活跃任务的纠偏历史
        self.correction_histories: Dict[str, list] = {}

    # ===== 七大工具 =====

    def task_create(self, subject: str, description: str,
                    parent_id: Optional[str] = None,
                    steps: Optional[List[str]] = None,
                    blocked_by: Optional[List[str]] = None) -> Task:
        """TaskCreate工具 — 创建任务"""
        task = Task(
            task_id=f"task_{int(time.time())}_{uuid.uuid4().hex[:6]}",
            session_id=f"session_{int(time.time())}",
            subject=subject,
            description=description,
            parent_task_id=parent_id,
            steps=steps or [
                f"分析-{subject[:20]}",
                f"计划-{subject[:20]}",
                f"执行-{subject[:20]}",
                f"验证-{subject[:20]}",
                f"交付-{subject[:20]}",
            ],
            blocked_by=blocked_by or [],
        )
        task = self.store.create(task)
        self.correction_histories[task.task_id] = []
        return task

    def task_list(self, status_filter: Optional[str] = None) -> List[dict]:
        """TaskList工具 — 列出任务"""
        tasks = self.store.list_tasks(status_filter)
        return [t.to_dict() for t in tasks]

    def task_get(self, task_id: str) -> Optional[dict]:
        """TaskGet工具 — 获取任务详情"""
        task = self.store.get(task_id)
        return task.to_dict() if task else None

    def task_update(self, task_id: str, **kwargs) -> Optional[Task]:
        """TaskUpdate工具 — 更新任务"""
        task = self.store.get(task_id)
        if not task:
            return None
        
        for key, value in kwargs.items():
            if hasattr(task, key) and key not in ("task_id", "session_id", "created_at"):
                setattr(task, key, value)
        
        self.store.update(task)
        
        # 如果完成,清理依赖
        if task.status == TaskStatus.COMPLETED:
            self.store.clear_dependency(task_id)
        
        return task

    def task_stop(self, task_id: str, reason: str = "") -> Optional[Task]:
        """TaskStop工具 — 终止任务"""
        task = self.store.get(task_id)
        if not task:
            return None
        
        task.status = TaskStatus.KILLED
        task.execution_metadata["stop_reason"] = reason
        self.store.update(task)
        return task

    def task_claim(self, task_id: str, owner: str) -> bool:
        """TaskClaim工具 — 原子抢占任务"""
        return self.store.claim(task_id, owner)

    def task_output(self, task_id: str) -> Optional[dict]:
        """TaskOutput工具 — 读取任务执行输出"""
        task = self.store.get(task_id)
        if not task:
            return None
        return task.execution_metadata

    # ===== 高级功能 =====

    def execute_plan(self, task_id: str) -> dict:
        """
        执行任务 — DPW双规划器+见证者循环
        
        每步执行:
          1. A/B独立规划
          2. 见证者比较
          3. 执行步骤
          4. 漂移检测
          5. 必要纠偏
        """
        task = self.store.get(task_id)
        if not task:
            return {"ok": False, "error": f"任务不存在: {task_id}"}
        
        task.status = TaskStatus.IN_PROGRESS
        self.store.update(task)
        
        goal = f"{task.subject}: {task.description[:100]}"
        
        # 步骤0: 新任务激活 → 自动检索相关历史经验注入上下文
        try:
            sys.path.insert(0, str(HERMES / "evolution_v3"))
            from experience_engine import get_experience_engine
            exp = get_experience_engine()
            related = exp.retrieve_relevant_experiences(goal, max_results=3)
            if related:
                task.execution_metadata["related_experiences"] = related
                self.store.update(task)
        except Exception as e:
            # 经验检索失败不影响主流程
            task.execution_metadata["experience_retrieval_error"] = str(e)[:100]
        
        # 执行循环
        execution_log = []
        
        while task.current_step < len(task.steps):
            current_step = task.steps[task.current_step]
            
            # 步骤1: 双规划
            plan_a = self.planner_a.plan(goal)
            plan_b = self.planner_b.plan(goal)
            
            # 步骤2: 见证者比较
            comparison = self.witness.compare_plans(plan_a, plan_b)
            
            # 步骤3: 漂移检测 (使用完整上下文,不只是步骤名)
            drift_context = f"{goal} 当前步骤: {current_step}"
            drift = self.witness.detect_drift(
                goal, drift_context,
                task.current_step, len(task.steps)
            )
            
            # 步骤4: 必要时纠偏
            correction = None
            if drift["drift_level"] != DriftLevel.OK:
                correction = self.witness.apply_correction(
                    drift, task,
                    self.correction_histories.get(task_id, [])
                )
                self.correction_histories.setdefault(task_id, []).append(correction)
                
                if correction.get("level") == "severe" or correction.get("action") == "full_reset_with_review":
                    break  # 重度纠偏终止循环
            
            # 步骤5: 记录执行日志
            step_log = {
                "step_index": task.current_step,
                "step_name": current_step,
                "comparison": comparison,
                "drift": {"score": drift["score"], "level": str(drift["drift_level"])},
                "correction": correction,
                "result": "ok" if drift["drift_level"] in (DriftLevel.OK, DriftLevel.MILD) else "warning",
                "ts": NOW().isoformat(),
            }
            execution_log.append(step_log)
            
            # 步骤6: 从该步提取经验(自动注入记忆通道)
            try:
                # 确保drift_level是字符串
                step_log_copy = dict(step_log)
                dl = step_log_copy.get("drift", {}).get("level")
                if dl is not None and hasattr(dl, 'value'):
                    step_log_copy["drift"] = dict(step_log_copy.get("drift", {}))
                    step_log_copy["drift"]["level"] = dl.value
                
                sys.path.insert(0, str(HERMES / "evolution_v3"))
                from experience_engine import get_experience_engine
                exp = get_experience_engine()
                exp.extract_step_experience(step_log_copy)
            except Exception as e:
                # 经验提取失败不应阻断任务执行
                task.execution_metadata.setdefault("experience_errors", []).append(str(e)[:80])
            
            # 前进
            task.current_step += 1
        
        # 完成
        if task.current_step >= len(task.steps):
            task.status = TaskStatus.COMPLETED
        elif task.status != TaskStatus.KILLED:
            task.status = TaskStatus.FAILED
        
        task.execution_metadata["execution_log"] = execution_log
        self.store.update(task)
        
        # 任务级经验总结: 自动触发经验引擎
        try:
            sys.path.insert(0, str(HERMES / "evolution_v3"))
            from experience_engine import get_experience_engine
            exp = get_experience_engine()
            exp.summarize_task(task.to_dict())
        except Exception as e:
            task.execution_metadata["task_summary_error"] = str(e)[:100]
            self.store.update(task)
        
        return {
            "ok": True,
            "task": task.to_dict(),
            "total_steps": len(task.steps),
            "completed_steps": task.current_step,
            "status": str(task.status),
            "drift_detected": len(execution_log) > 0,
        }

    def health(self) -> dict:
        """任务引擎健康报告"""
        return {
            "planner_a": {"plan_count": self.planner_a.plan_count},
            "planner_b": {"plan_count": self.planner_b.plan_count},
            "witness": self.witness.health(),
            "total_tasks": len(self.store.list_tasks()),
        }


# =================================================================
# 全局单例
# =================================================================

_engine_instance: Optional[TaskEngine] = None


def get_engine() -> TaskEngine:
    """获取任务引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = TaskEngine()
    return _engine_instance


if __name__ == "__main__":
    import sys
    
    engine = get_engine()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "create":
            subject = sys.argv[2] if len(sys.argv) > 2 else "默认任务"
            desc = sys.argv[3] if len(sys.argv) > 3 else "默认描述"
            task = engine.task_create(subject, desc)
            print(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        
        elif cmd == "list":
            sf = sys.argv[2] if len(sys.argv) > 2 else None
            tasks = engine.task_list(sf)
            print(json.dumps(tasks, ensure_ascii=False, indent=2))
        
        elif cmd == "get":
            task = engine.task_get(sys.argv[2])
            print(json.dumps(task, ensure_ascii=False, indent=2) if task else "null")
        
        elif cmd == "execute":
            result = engine.execute_plan(sys.argv[2])
            print(json.dumps(result, ensure_ascii=False, indent=2))
        
        elif cmd == "update":
            task = engine.task_update(sys.argv[2], status=TaskStatus(sys.argv[3]))
            print(json.dumps(task.to_dict() if task else {"error": "not found"}, ensure_ascii=False, indent=2))
        
        elif cmd == "health":
            print(json.dumps(engine.health(), ensure_ascii=False, indent=2))
        
        else:
            print(f"未知命令: {cmd}")
    else:
        print("用法: python3 task_engine.py [create|list|get|execute|update|health] [args]")
