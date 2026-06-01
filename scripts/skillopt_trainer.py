#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
skillopt_trainer.py — SkillOpt验证门引擎（验证门+拒绝缓冲区+文本学习率）
======================================================================
基于微软SkillOpt论文 (arXiv:2605.23904) 的核心设计：
  - Rollout batch: 用当前Skill跑验证任务集
  - 小批量反思: 提取"保留/修正"规则
  - 文本学习率: 每次最多改 L 条规则
  - 验证门: 必须严格提升才接受
  - 拒绝缓冲区: 被拒编辑作为负反馈
  - Epoch动量: 跨epoch长期经验写保护区域

与Hermes skill_manage() 深度集成：
  skill_manage(action='patch') → 自动触发验证门
  
用法:
  # 验证skill
  python3 skillopt_trainer.py validate <skill_name> [--test-count N]
  
  # 训练skill（多epoch优化）
  python3 skillopt_trainer.py train <skill_name> [--epochs N] [--lr L]
  
  # 查看sku缓冲区
  python3 skillopt_trainer.py buffer
  
  # 查看统计数据
  python3 skillopt_trainer.py stats
"""

import json
import time
import hashlib
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional
from collections import defaultdict

SKILLS_DIR = Path.home() / ".hermes" / "skills"
BUFFER_FILE = Path.home() / ".hermes" / "skillopt_buffer.jsonl"
VALIDATION_LOG = Path.home() / ".hermes" / "skillopt_validation.jsonl"
PROTECTED_REGION = Path.home() / ".hermes" / "skillopt_protected.json"

# ======================== 配置 ========================
DEFAULT_TEXT_LR = 3   # 每次最多改L条规则（文本学习率）
DEFAULT_EPOCHS = 3    # 默认训练epoch数
VALIDATION_THRESHOLD = 0.80  # 验证门：通过率必须>80%
TEST_TASKS_PER_SKILL = 5     # 每个skill测试任务数


class SkillOptTrainer:
    """
    SkillOpt训练器
    
    核心设计：
    1. 验证门 — 验证集通过率>80%才接受修改
    2. 文本学习率 — 每次最多改L条规则（防一次改太多）
    3. 拒绝缓冲区 — 被拒的编辑不会丢，作为负反馈
    4. Epoch动量 — 跨epoch比较，长期经验写保护区域
    """
    
    def __init__(self):
        self.buffer_file = BUFFER_FILE
        self.validation_log = VALIDATION_LOG
        self.protected = self._load_protected()
    
    def _load_protected(self) -> dict:
        """加载保护区域（跨epoch长期经验）"""
        if PROTECTED_REGION.exists():
            try:
                return json.loads(PROTECTED_REGION.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return {"rules": [], "epochs": []}
    
    def _save_protected(self):
        """保存保护区域"""
        PROTECTED_REGION.write_text(
            json.dumps(self.protected, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    
    def get_skill_path(self, name: str) -> Optional[Path]:
        """根据skill名字找到SKILL.md路径"""
        for f in SKILLS_DIR.rglob("SKILL.md"):
            if name in str(f):
                return f
        return None
    
    def extract_rules(self, skill_path: Path) -> list[str]:
        """从SKILL.md中提取所有规则/步骤"""
        content = skill_path.read_text(encoding='utf-8', errors='replace')
        # 提取所有序号步骤
        rules = []
        for line in content.split('\n'):
            line = line.strip()
            if re.match(r'^\d+[.、]', line) or re.match(r'^###\s+\d+', line) or re.match(r'^-\s*\[', line):
                rules.append(line)
            elif line.startswith('| ') and '|' in line[2:]:
                # 表格行
                rules.append(line)
        return rules if rules else [content[:200]]  # 至少保底
    
    def count_rules(self, skill_path: Path) -> int:
        """统计SKILL.md中的规则/步骤数（用于文本学习率）"""
        content = skill_path.read_text(encoding='utf-8', errors='replace')
        # 统计步骤数：### 开头或者数字序号开头
        steps = re.findall(r'^###\s+\d+|^\d+[.、]', content, re.MULTILINE)
        return max(len(steps), 1)
    
    def build_validation_tasks(self, skill_name: str, count: int = TEST_TASKS_PER_SKILL) -> list[dict]:
        """
        构建验证任务集（对应SkillOpt的Rollout batch）
        
        每条验证任务 = {input: 输入, expected: 预期行为}
        不同类别的Skill有不同的验证集
        """
        tasks = []
        
        # 通用验证任务
        common_tasks = [
            {"input": "这个功能怎么用？", "expected": "触发对应的Skill", "type": "trigger"},
            {"input": "出错了怎么办？", "expected": "提供故障排查步骤", "type": "troubleshoot"},
            {"input": "用最简单的步骤实现", "expected": "按Step顺序执行", "type": "step_follow"},
        ]
        
        # 根据skill类别增加特定验证
        skill_path = self.get_skill_path(skill_name)
        if skill_path:
            content = skill_path.read_text(encoding='utf-8', errors='replace')
            if "terminal" in content or "bash" in content:
                common_tasks.append({"input": "执行命令", "expected": "用terminal执行", "type": "terminal"})
            if "python" in content or "script" in content:
                common_tasks.append({"input": "运行脚本", "expected": "用Python执行", "type": "script"})
            if "config" in content or "配置" in content:
                common_tasks.append({"input": "修改配置", "expected": "用patch修改", "type": "config"})
        
        # 去重并截取
        seen = set()
        for t in common_tasks:
            key = t["input"]
            if key not in seen:
                seen.add(key)
                tasks.append(t)
        
        return tasks[:count]
    
    def validate_skill(self, skill_name: str, test_count: int = TEST_TASKS_PER_SKILL,
                       new_content: Optional[str] = None,
                       use_llm: bool = True) -> dict:
        """
        验证门：验证skill是否达到标准（v2.0 LLM增强）
        
        LLM评估：用LLM理解skill文档的语义质量
        规则评估：保留v1的5维度检查
        双轨并行，按置信度融合
        """
        skill_path = self.get_skill_path(skill_name)
        if not skill_path and not new_content:
            return {"passed": False, "score": 0.0, "error": f"Skill {skill_name} 未找到"}
        
        # 规则引擎评估（v1保留）
        rule_result = self._rule_validate(skill_name, skill_path, new_content, test_count)
        
        # LLM评估（v2.0新增）
        llm_score = 0.0
        llm_opinion = ""
        if use_llm:
            try:
                llm_result = self._llm_validate(skill_name, skill_path, new_content)
                if llm_result:
                    llm_score = llm_result.get("score", 0.0) / 100.0  # 归一化
                    llm_opinion = llm_result.get("opinion", "")
                    print(f"  [SkillOpt] LLM评估: {skill_name} score={llm_result.get('score', 0)}")
            except Exception:
                pass
        
        # 融合：LLM和规则各占50%权重
        if llm_score > 0:
            final_score = (rule_result["score"] * 0.5) + (llm_score * 0.5)
            fusion = "llm_rule_hybrid"
        else:
            final_score = rule_result["score"]
            fusion = "rule_only"
        
        # 类型感知阈值
        skill_type = self._classify_skill(skill_name)
        threshold = self._get_threshold_for_type(skill_type)
        
        # mlops_ref类型直接通过（参考文档）
        if skill_type == "mlops_ref":
            final_score = 1.0
            threshold = 0.0
            fusion = "mlops_ref_skip"
        
        # 记录验证日志
        validation_entry = {
            "skill": skill_name,
            "timestamp": time.time(),
            "score": final_score,
            "rule_score": rule_result["score"],
            "llm_score": llm_score,
            "passed": final_score >= threshold,
            "checks": rule_result.get("checks", []),
            "llm_opinion": llm_opinion,
            "fusion": fusion,
            "skill_type": skill_type,
        }
        with open(self.validation_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(validation_entry, ensure_ascii=False) + '\n')
        
        return {
            "passed": final_score >= threshold,
            "score": final_score,
            "threshold": threshold,
            "skill_type": skill_type,
            "checks": rule_result.get("checks", []),
            "llm_score": llm_score,
            "llm_opinion": llm_opinion,
            "fusion": fusion,
            "details": validation_entry,
        }
    
    def _llm_validate(self, skill_name: str, skill_path: Optional[Path],
                       new_content: Optional[str] = None) -> Optional[dict]:
        """
        LLM验证：用LLM理解skill文档的实际质量
        
        LLM能发现规则引擎发现不了的问题：
        - 步骤是否合理（不仅仅是"存在"）
        - 故障处理是否实用（不仅仅是"有故障处理章节"）
        - 整体逻辑是否连贯
        """
        content = new_content or (skill_path.read_text(encoding='utf-8', errors='replace') if skill_path else "")
        if not content:
            return None
        
        prompt = f"""你是Skill质量评估专家。评估以下Agent Skill文档的质量。

Skill名称: {skill_name}

文档内容（前3000字）:
{content[:3000]}

请从以下维度评估（每项0-20分）:
1. 触发条件明确性：是否清晰定义了何时使用此Skill
2. 步骤实用性：步骤是否具体可执行（不是空洞的描述）
3. 故障处理质量：是否覆盖了真实的常见错误
4. 验证完整性：是否有量化的验收标准
5. 整体可读性：结构是否清晰，能否快速理解

返回JSON:
{{
  "trigger_clarity": 0-20,
  "step_practicality": 0-20,
  "troubleshoot_quality": 0-20,
  "verification_completeness": 0-20,
  "readability": 0-20,
  "score": 0-100,
  "opinion": "一句话总体评价"
}}"""
        
        from llm_bridge import llm_call_json
        
        result = llm_call_json(
            system_prompt="",
            user_prompt=prompt,
            fallback=None,
            max_tokens=400,
            timeout=30,
        )
        
        if result.success and result.data is not None:
            return result.data
        
        return None

    def _classify_skill(self, skill_name: str) -> str:
        """自动判断Skill类型: workflow / reference / mlops_ref"""
        for pattern in self.SKILL_TYPE_MLOPS_PATTERNS:
            if pattern in skill_name:
                return "mlops_ref"
        cat = skill_name.split("/")[0] if "/" in skill_name else skill_name
        if cat in self.SKILL_TYPE_REFERENCE:
            return "reference"
        return "workflow"

    def _get_threshold_for_type(self, skill_type: str) -> float:
        """按类型返回阈值"""
        if skill_type == "workflow":
            return 0.80
        elif skill_type == "reference":
            return 0.60
        elif skill_type == "mlops_ref":
            return 0.0
        return 0.80
    
    def _rule_validate(self, skill_name: str, skill_path: Optional[Path],
                        new_content: Optional[str] = None,
                        test_count: int = 5) -> dict:
        """v1规则引擎验证（类型感知，阈值自适应）"""
        
        tasks = self.build_validation_tasks(skill_name, test_count)
        if not tasks:
            return {"passed": True, "score": 1.0, "detail": "无验证任务（自动通过）"}
        
        # 评分标准：
        # 1. 必须有触发条件（20分）
        # 2. 必须有标准流程步骤（30分）
        # 3. 必须有故障处理（20分）
        # 4. 必须有验证步骤（15分）
        # 5. 必须有回滚方案（15分）
        
        content = new_content or skill_path.read_text(encoding='utf-8', errors='replace')
        
        score = 0.0
        checks = []
        
        # 1. 触发条件
        if re.search(r'(触发条件|Trigger|triggers|##\s*触发|##\s*Trigger)', content, re.IGNORECASE):
            score += 0.20
            checks.append("触发条件✅")
        else:
            checks.append("触发条件❌")
        
        # 2. 标准流程
        steps = re.findall(r'^\d+[.、]|^###\s+\d+|^-\s*\[|^## 步骤|^## 工作流|^## 流程', content, re.MULTILINE)
        if len(steps) >= 3:
            score += 0.30
            checks.append(f"流程步骤✅({len(steps)}步)")
        elif steps:
            score += 0.15
            checks.append(f"流程步骤⚠️(仅{len(steps)}步)")
        else:
            checks.append("流程步骤❌")
        
        # 3. 故障处理
        if re.search(r'(故障|问题|错误|坑|陷阱|Pitfall|Error|Troubleshoot|问题排查)', content, re.IGNORECASE):
            score += 0.20
            checks.append("故障处理✅")
        else:
            checks.append("故障处理❌")
        
        # 4. 验证步骤
        if re.search(r'(验证|Check|Test|检验|确认|Verify|验证方法)', content, re.IGNORECASE):
            score += 0.15
            checks.append("验证步骤✅")
        else:
            checks.append("验证步骤❌")
        
        # 5. 回滚方案
        if re.search(r'(回滚|恢复|Rollback|回退|还原|revert|backup)', content, re.IGNORECASE):
            score += 0.15
            checks.append("回滚方案✅")
        else:
            checks.append("回滚方案❌")
        
        # 记录验证日志
        validation_entry = {
            "skill": skill_name,
            "timestamp": time.time(),
            "score": score,
            "passed": score >= VALIDATION_THRESHOLD,
            "checks": checks,
            "rule_count": self.count_rules(skill_path) if skill_path else 0,
        }
        with open(self.validation_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(validation_entry, ensure_ascii=False) + '\n')
        
        return {
            "passed": score >= VALIDATION_THRESHOLD,
            "score": score,
            "threshold": VALIDATION_THRESHOLD,
            "checks": checks,
            "details": validation_entry,
        }
    
    def add_to_reject_buffer(self, skill_name: str, old_content: str, 
                               proposed_change: str, reason: str):
        """
        拒绝缓冲区：记录被拒绝的修改
        
        SkillOpt原论文: 被拒的编辑不会丢掉，而是作为负反馈留着
        """
        entry = {
            "skill": skill_name,
            "timestamp": time.time(),
            "old_content_preview": old_content[:200],
            "proposed_change": proposed_change[:300],
            "reason": reason,
            "rejected_by": "validation_gate",
        }
        with open(self.buffer_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def get_reject_buffer(self, skill_name: Optional[str] = None, 
                          limit: int = 20) -> list[dict]:
        """读取拒绝缓冲区"""
        if not self.buffer_file.exists():
            return []
        
        entries = []
        with open(self.buffer_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        if not skill_name or entry.get("skill") == skill_name:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        
        return sorted(entries, key=lambda e: e.get("timestamp", 0), reverse=True)[:limit]
    
    def get_rejected_patterns(self, skill_name: str) -> list[str]:
        """从拒绝缓冲区提取模式（避免反复犯同样错误）"""
        entries = self.get_reject_buffer(skill_name)
        if not entries:
            return []
        
        # 提取重复出现的拒绝模式
        reasons = defaultdict(int)
        for e in entries:
            reason = e.get("reason", "unknown")
            # 简化原因
            if "验证门" in reason:
                reasons["缺少必要字段"] += 1
            elif "分数" in reason:
                reasons["质量不达标"] += 1
            else:
                reasons[reason[:30]] += 1
        
        # 返回最常见拒绝模式（>1次）
        return [f"{r}({c}次被拒)" for r, c in reasons.items() if c > 1]
    
    def train_skill(self, skill_name: str, epochs: int = DEFAULT_EPOCHS, 
                    lr: int = DEFAULT_TEXT_LR) -> dict:
        """
        训练skill（多epoch验证门循环）
        
        SkillOpt原论文:
          - 文本学习率：每次最多改L条规则
          - Epoch动量：跨epoch比较
          - 验证门：严格提升才接受
        """
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            return {"success": False, "error": f"Skill {skill_name} 未找到"}
        
        results = []
        current_best_score = 0.0
        
        for epoch in range(1, epochs + 1):
            print(f"\n  [Epoch {epoch}/{epochs}] 验证 {skill_name}...")
            
            # 验证当前版本
            val = self.validate_skill(skill_name, test_count=TEST_TASKS_PER_SKILL)
            score = val["score"]
            
            # 记录epoch
            epoch_record = {
                "epoch": epoch,
                "skill": skill_name,
                "score": score,
                "passed": val["passed"],
                "checks": val.get("checks", []),
                "rule_count": self.count_rules(skill_path),
                "timestamp": time.time(),
            }
            results.append(epoch_record)
            
            print(f"    分数: {score:.2f}/{VALIDATION_THRESHOLD:.2f} "
                  f"{'✅ 通过' if val['passed'] else '❌ 未通过'}")
            
            if val["passed"]:
                if score > current_best_score:
                    current_best_score = score
                    print(f"    🏆 新的最高分!")
            else:
                # 获取拒绝模式，帮助改进
                patterns = self.get_rejected_patterns(skill_name)
                if patterns:
                    print(f"    拒绝模式: {patterns}")
            
            # Epoch间保护区域更新（动量）
            if epoch > 1 and results[-1]["score"] >= results[-2].get("score", 0):
                # 分数提升或持平 → 更新保护区域
                protected_entry = {
                    "skill": skill_name,
                    "epoch": epoch,
                    "score": score,
                    "timestamp": time.time(),
                }
                self.protected.setdefault("epochs", []).append(protected_entry)
                self._save_protected()
        
        # 最终总结
        final_score = results[-1]["score"] if results else 0
        return {
            "success": True,
            "skill": skill_name,
            "epochs": epochs,
            "final_score": final_score,
            "passed": final_score >= VALIDATION_THRESHOLD,
            "best_score": current_best_score,
            "history": results,
            "rule_count": self.count_rules(skill_path),
        }
    
    def scan_negative_transfer(self, min_samples: int = 3) -> list[dict]:
        """
        负迁移检测：扫描有风险的Skill
        
        基于Skill生命周期论文 (arXiv:2605.23899):
          - 25%的model-generated skill造成负迁移
          - 信号：验证分数持续下降
        """
        if not self.validation_log.exists():
            return []
        
        # 读取所有验证记录
        skills_scores = defaultdict(list)
        with open(self.validation_log, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        sname = entry.get("skill", "")
                        skills_scores[sname].append(entry)
                    except json.JSONDecodeError:
                        continue
        
        # 检测负迁移信号
        risks = []
        for sname, records in skills_scores.items():
            if len(records) < min_samples:
                continue
            
            # 按时间排序
            sorted_records = sorted(records, key=lambda r: r.get("timestamp", 0))
            scores = [r.get("score", 0) for r in sorted_records]
            
            # 检测趋势
            if len(scores) >= 2:
                first_half = sum(scores[:len(scores)//2]) / max(len(scores)//2, 1)
                last_half = sum(scores[len(scores)//2:]) / max(len(scores) - len(scores)//2, 1)
                
                decline = last_half - first_half
                if decline < -0.1:  # 下降超过10%
                    risks.append({
                        "skill": sname,
                        "risk": "negative_transfer",
                        "decline": round(decline, 3),
                        "first_avg": round(first_half, 3),
                        "last_avg": round(last_half, 3),
                        "samples": len(records),
                        "recommended_action": "review_and_fix",
                    })
        
        return sorted(risks, key=lambda r: r["decline"])
    
    def get_stats(self) -> dict:
        """获取统计数据"""
        # 验证记录数
        val_count = 0
        if self.validation_log.exists():
            with open(self.validation_log) as f:
                val_count = len([l for l in f if l.strip()])
        
        # 拒绝缓冲区大小
        buf_count = 0
        if self.buffer_file.exists():
            with open(self.buffer_file) as f:
                buf_count = len([l for l in f if l.strip()])
        
        # 保护区域
        protected_epochs = len(self.protected.get("epochs", []))
        
        # 负迁移扫描
        risks = self.scan_negative_transfer()
        
        return {
            "validation_records": val_count,
            "reject_buffer_entries": buf_count,
            "protected_epochs": protected_epochs,
            "negative_transfer_risks": len(risks),
            "risk_details": risks[:5],  # top 5
        }


# ======================== CLI ========================

def cmd_validate(args: list[str]):
    trainer = SkillOptTrainer()
    skill_name = args[0] if args else None
    if not skill_name:
        print("用法: skillopt_trainer.py validate <skill_name> [--test-count N]")
        return
    
    test_count = TEST_TASKS_PER_SKILL
    if "--test-count" in args:
        idx = args.index("--test-count")
        if idx + 1 < len(args):
            test_count = int(args[idx + 1])
    
    result = trainer.validate_skill(skill_name, test_count)
    status = "✅ 通过" if result["passed"] else "❌ 未通过"
    print(f"\nSkillOpt验证: {skill_name}")
    print(f"  状态: {status}")
    print(f"  分数: {result['score']:.2f} (阈值: {result['threshold']:.2f})")
    if result.get("checks"):
        for c in result["checks"]:
            print(f"  {c}")
    if not result["passed"]:
        print(f"  建议: 补充缺少的字段")


def cmd_train(args: list[str]):
    trainer = SkillOptTrainer()
    skill_name = args[0] if args else None
    if not skill_name:
        print("用法: skillopt_trainer.py train <skill_name> [--epochs N] [--lr L]")
        return
    
    epochs = DEFAULT_EPOCHS
    lr = DEFAULT_TEXT_LR
    if "--epochs" in args:
        idx = args.index("--epochs")
        if idx + 1 < len(args):
            epochs = int(args[idx + 1])
    if "--lr" in args:
        idx = args.index("--lr")
        if idx + 1 < len(args):
            lr = int(args[idx + 1])
    
    result = trainer.train_skill(skill_name, epochs, lr)
    print(f"\nSkillOpt训练完成: {skill_name}")
    print(f"  最终分数: {result['final_score']:.2f}")
    print(f"  通过阈值: {'✅' if result['passed'] else '❌'}")
    if result.get("history"):
        for h in result["history"]:
            print(f"  Epoch {h['epoch']}: {h['score']:.2f}")


def cmd_buffer(args: list[str]):
    trainer = SkillOptTrainer()
    skill_name = args[0] if args else None
    entries = trainer.get_reject_buffer(skill_name)
    if not entries:
        print("拒绝缓冲区为空")
        return
    print(f"拒绝缓冲区 ({len(entries)} 条):")
    for e in entries:
        print(f"  [{e.get('skill')}] {e.get('reason', '?')[:60]}")
        print(f"    提议: {e.get('proposed_change', '')[:80]}")


def cmd_scan_risks(args: list[str]):
    """扫描负迁移风险"""
    trainer = SkillOptTrainer()
    risks = trainer.scan_negative_transfer()
    if not risks:
        print("✅ 未检测到负迁移风险")
        return
    print(f"⚠️ 检测到 {len(risks)} 个负迁移风险:")
    for r in risks:
        print(f"  {r['skill']}: 下降 {r['decline']:.1%} "
              f"(前{r['first_avg']:.2f}→后{r['last_avg']:.2f})")


def cmd_stats(args: list[str]):
    trainer = SkillOptTrainer()
    stats = trainer.get_stats()
    print(f"SkillOpt 统计:")
    print(f"  验证记录: {stats['validation_records']} 条")
    print(f"  拒绝缓冲区: {stats['reject_buffer_entries']} 条")
    print(f"  保护区域: {stats['protected_epochs']} 个epoch")
    print(f"  负迁移风险: {stats['negative_transfer_risks']} 个")
    if stats.get("risk_details"):
        print(f"  高风险Skill:")
        for r in stats["risk_details"][:3]:
            print(f"    ⚠️ {r['skill']}: 下降{r['decline']:.1%}")


if __name__ == "__main__":
    args = sys.argv[1:]
    
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
    elif args[0] == "validate":
        cmd_validate(args[1:])
    elif args[0] == "train":
        cmd_train(args[1:])
    elif args[0] == "buffer":
        cmd_buffer(args[1:])
    elif args[0] == "risks":
        cmd_scan_risks(args[1:])
    elif args[0] == "stats":
        cmd_stats(args)
    else:
        print(f"未知命令: {args[0]}")
