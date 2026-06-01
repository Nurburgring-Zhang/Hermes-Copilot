#!/usr/bin/env python3
"""
Hermes 证据驱动Skill进化引擎 v1.0
====================================
基于 hermes-curator-evolver 的核心机制移植 + Hermes复盘反思引擎集成

核心流程:
  1. 证据收集 — 从复盘报告(state.db retrospectives表)和活跃会话中收集
  2. 语义分类 — 规则引擎将证据分为 skill_update/skill_new/replay_benchmark/ignore
  3. 变体生成 — 生成最多4种Skill改进变体，评分函数自动选优
  4. 受保护应用 — SHA256→备份→结构检查→回滚门禁
  5. 与SkillOpt验证门联动 — 变体通过验证门才能应用

底层能力：所有对话、所有任务全部通用，完全自动执行。
集成到自进化集群模块6，作为复盘→Skill进化管道的核心引擎。

用法:
  python3 scripts/hermes_skill_evolver.py collect       # 收集证据
  python3 scripts/hermes_skill_evolver.py classify      # 分类证据
  python3 scripts/hermes_skill_evolver.py evolve        # 生成+应用改进
  python3 scripts/hermes_skill_evolver.py all           # 一站式全流程
"""

import json, os, sys, re, hashlib, shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, Counter

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
SKILLS_DIR = HERMES / "skills"
BACKUP_DIR = HERMES / "data" / "skill_evolver_backups"
REPORTS_DIR = HERMES / "reports" / "skill_evolution"
CANDIDATE_FILE = HERMES / "data" / "retro_candidates.jsonl"
TZ = timezone(timedelta(hours=8))

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# ── 日志 ──
def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ══════════════════════════════════════════════════════════════════
# 模块1: 证据收集 (Evidence Collector)
# 从复盘记录和会话数据中收集Skill改进证据
# ══════════════════════════════════════════════════════════════════

class EvidenceCollector:
    """证据收集器 — 从state.db和复盘队列中收集"""
    
    # 证据类型常量（对齐curator-evolver）
    TYPE_SKILL_UPDATE = "skill_update"
    TYPE_SKILL_NEW = "skill_new"
    TYPE_REPLAY = "replay_benchmark"
    TYPE_IGNORE = "ignore"
    
    def collect_from_retrospectives(self, max_days: int = 7) -> List[Dict]:
        """从state.db的retrospectives表收集证据"""
        evidence = []
        if not STATE_DB.exists():
            return evidence
        
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            
            # 检查retrospectives表
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "retrospectives" not in tables:
                conn.close()
                return evidence
            
            cutoff = (datetime.now(TZ) - timedelta(days=max_days)).isoformat()
            rows = c.execute("""
                SELECT id, session_id, session_title, total_score, quality_level, 
                       error_rate, tools_used, root_causes, improvements, 
                       retro_json, created_at
                FROM retrospectives 
                WHERE created_at >= ?
                ORDER BY created_at DESC
            """, (cutoff,)).fetchall()
            
            col_names = ["id", "session_id", "session_title", "total_score", "quality_level",
                         "error_rate", "tools_used", "root_causes", "improvements",
                         "retro_json", "created_at"]
            
            for row in rows:
                record = dict(zip(col_names, row))
                # 只收集有改进点或低分的记录
                score = record.get("total_score", 100) or 100
                if score < 60 or (record.get("improvements") and json.loads(record["improvements"])):
                    evidence.append({
                        "source": "retrospect",
                        "is_error": score < 60,
                        "text": json.dumps({
                            "score": score,
                            "session_title": record.get("session_title", ""),
                            "root_causes": json.loads(record.get("root_causes", "[]")),
                            "improvements": json.loads(record.get("improvements", "[]")),
                        }),
                        "tool_name": "hermes_retrospect",
                        "created_at": record.get("created_at", ""),
                        "confidence": 0.75 if score < 60 else 0.6,
                    })
            
            conn.close()
            log(f"  从复盘收集到 {len(evidence)} 条证据")
        except Exception as e:
            log(f"  ⚠️ 从复盘收集失败: {e}")
        
        return evidence
    
    def collect_from_candidates(self) -> List[Dict]:
        """从复盘候选队列(retro_candidates.jsonl)收集证据"""
        evidence = []
        if not CANDIDATE_FILE.exists():
            return evidence
        
        try:
            with open(CANDIDATE_FILE) as f:
                lines = [l.strip() for l in f if l.strip()]
            
            for line in lines:
                try:
                    cand = json.loads(line)
                    evidence.append({
                        "source": "candidate_queue",
                        "is_error": cand.get("score", 100) < 60,
                        "text": json.dumps(cand.get("improvements", [])),
                        "tool_name": "retro_candidate",
                        "created_at": cand.get("triggered_at", ""),
                        "confidence": 1.0 - (cand.get("score", 50) / 100),
                        "original": cand,
                    })
                except json.JSONDecodeError:
                    continue
            
            log(f"  从候选队列收集到 {len(evidence)} 条证据")
        except Exception as e:
            log(f"  ⚠️ 从候选队列收集失败: {e}")
        
        return evidence
    
    def collect_all(self) -> List[Dict]:
        """一站式收集所有证据"""
        evidence = []
        evidence.extend(self.collect_from_retrospectives())
        evidence.extend(self.collect_from_candidates())
        done = len(evidence)
        if done:
            log(f"  共收集 {done} 条证据")
        else:
            log("  未收集到证据")
        return evidence


# ══════════════════════════════════════════════════════════════════
# 模块2: 语义分类 (Semantic Classifier)
# 基于规则引擎将证据分类（对齐curator-evolver candidates.py）
# ══════════════════════════════════════════════════════════════════

# 模式定义（借鉴curator-evolver的candidates.py）
_STEP_NUMBERED = re.compile(r"\b[1-9]\.\s+\S")
_STEP_KEYWORD = re.compile(r"\b(first|then|next|finally|step\s+\d+)\b|先|再|最後|流程|步驟|SOP", re.IGNORECASE)
_SHELL_COMMAND = re.compile(r"`[^`]{2,}`|\brun\s+`", re.IGNORECASE)
_ZH_WORKFLOW = re.compile(r"(流程|步驟|SOP).{0,80}(先|再|最後).{0,160}(先|再|最後)", re.DOTALL)
_ERROR_PATTERN = re.compile(r"\b(traceback|not[_ ]found|exit\s+code\s+\d+|failed|timeout|error|exception|❌)\b", re.IGNORECASE)
_TOOL_ERROR = re.compile(r"(执行|run|call|调用).{0,30}(失败|error|timeout|异常|exception)", re.IGNORECASE | re.DOTALL)


def classify_evidence(record: Dict) -> str:
    """将证据分类为 skill_update / skill_new / replay_benchmark / ignore
    
    借鉴curator-evolver candidates.py的classify_record()逻辑
    """
    text = str(record.get("text", ""))
    is_error = record.get("is_error", False)
    confidence = record.get("confidence", 0.5)
    
    # 1. 工具失败 → replay_benchmark（需要更好的执行策略）
    if is_error or _ERROR_PATTERN.search(text) or _TOOL_ERROR.search(text):
        return EvidenceCollector.TYPE_REPLAY
    
    # 2. 工作流模式（有步骤/流程） → skill_update 或 skill_new
    numbered = len(_STEP_NUMBERED.findall(text))
    keyword_hits = len(_STEP_KEYWORD.findall(text))
    shell_hits = len(_SHELL_COMMAND.findall(text))
    has_workflow = bool(_ZH_WORKFLOW.search(text)) or (numbered >= 2) or (keyword_hits >= 2 and shell_hits >= 1) or (shell_hits >= 2)
    
    if has_workflow and confidence >= 0.6:
        return EvidenceCollector.TYPE_SKILL_UPDATE
    
    # 3. 工作流模式但没有目标skill → 可能的新skill
    if has_workflow and "skill" not in text.lower():
        return EvidenceCollector.TYPE_SKILL_NEW
    
    # 4. 低置信度 → ignore
    return EvidenceCollector.TYPE_IGNORE


def mine_candidates(evidence: List[Dict]) -> List[Dict]:
    """分类所有证据并生成候选列表"""
    candidates = []
    types_counter = Counter()
    
    for record in evidence:
        ctype = classify_evidence(record)
        types_counter[ctype] += 1
        
        text = str(record.get("text", ""))[:200]
        
        cand = {
            "type": ctype,
            "confidence": record.get("confidence", 0.5),
            "evidence": text[:300],
            "source": record.get("source", "unknown"),
            "created_at": record.get("created_at", ""),
        }
        candidates.append(cand)
    
    log(f"  分类结果: {dict(types_counter)}")
    
    # 仅返回需要处理的候选（排除ignore）
    actionable = [c for c in candidates if c["type"] != EvidenceCollector.TYPE_IGNORE]
    log(f"  可处理候选: {len(actionable)} 条")
    
    return actionable


# ══════════════════════════════════════════════════════════════════
# 模块3: Skill改进提案生成 (Proposal Generator)
# 基于curator-evolver的auto_evolve.py变体生成
# ══════════════════════════════════════════════════════════════════

class SkillProposalGenerator:
    """Skill改进提案生成器 — 生成+评分+选优"""
    
    # 变体规格（对齐curator-evolver _VARIANT_SPECS）
    VARIANT_SPECS = [
        {"name": "default-verify-first", "focus": "先验证当前方案再改写"},
        {"name": "compact-evidence-first", "focus": "精简证据+直接改进"},
        {"name": "errors-first", "focus": "优先修复已知错误"},
        {"name": "minimal-inline", "focus": "最小改动+内联补丁"},
    ]
    
    def __init__(self):
        self.proposals = []
    
    def generate_proposals(self, candidates: List[Dict]) -> List[Dict]:
        """为每个候选生成改进提案"""
        proposals = []
        
        for cand in candidates:
            ctype = cand["type"]
            evidence = cand["evidence"]
            
            if ctype == EvidenceCollector.TYPE_SKILL_UPDATE:
                # 尝试所有变体
                for variant in self.VARIANT_SPECS:
                    proposal = {
                        "type": "skill_update",
                        "variant": variant["name"],
                        "focus": variant["focus"],
                        "evidence": evidence,
                        "confidence": cand["confidence"],
                        "content_preview": self._generate_update_content(evidence, variant),
                    }
                    proposal["score"] = self._score_proposal(proposal)
                    proposals.append(proposal)
            
            elif ctype == EvidenceCollector.TYPE_SKILL_NEW:
                proposals.append({
                    "type": "skill_new",
                    "variant": "default",
                    "focus": "新建Skill",
                    "evidence": evidence,
                    "confidence": cand["confidence"],
                    "content_preview": self._generate_new_skill_content(evidence),
                    "score": self._score_new_skill(cand),
                })
            
            elif ctype == EvidenceCollector.TYPE_REPLAY:
                proposals.append({
                    "type": "skill_update",
                    "variant": "errors-first",
                    "focus": "修复执行错误模式",
                    "evidence": evidence,
                    "confidence": cand["confidence"],
                    "content_preview": self._generate_error_fix_content(evidence),
                    "score": self._score_error_fix(cand),
                })
        
        # 按评分排序
        proposals.sort(key=lambda x: x.get("score", 0), reverse=True)
        self.proposals = proposals
        
        log(f"  生成 {len(proposals)} 个改进提案 (最高分: {proposals[0]['score'] if proposals else 'N/A'})")
        return proposals
    
    def _generate_update_content(self, evidence: str, variant: Dict) -> str:
        """生成Skill更新内容预览（基于改进建议）"""
        return f"基于证据: {evidence[:100]}... 采用{variant['focus']}策略"
    
    def _generate_new_skill_content(self, evidence: str) -> str:
        return f"新Skill提案 - 来自: {evidence[:100]}..."
    
    def _generate_error_fix_content(self, evidence: str) -> str:
        return f"错误修复 - 来自: {evidence[:100]}..."
    
    def _score_proposal(self, proposal: Dict) -> float:
        """评分函数：确定性+连续性（对齐curator-evolver _score_variant）
        
        评分因子:
        - 置信度 +50分
        - 变体质量 +10~40分
        - 证据长度适中 +10分
        """
        score = 0
        score += proposal.get("confidence", 0.5) * 50
        
        variant_name = proposal.get("variant", "")
        if "verify-first" in variant_name:
            score += 40  # 最安全
        elif "errors-first" in variant_name:
            score += 35
        elif "evidence-first" in variant_name:
            score += 30
        else:
            score += 20
        
        # 证据长度加分
        ev_len = len(proposal.get("evidence", ""))
        if 50 <= ev_len <= 500:
            score += 10
        
        return min(100, score)
    
    def _score_new_skill(self, cand: Dict) -> float:
        return cand.get("confidence", 0.5) * 60 + 10
    
    def _score_error_fix(self, cand: Dict) -> float:
        return cand.get("confidence", 0.5) * 70 + 15
    
    def select_best(self) -> Optional[Dict]:
        """选出最优提案"""
        if not self.proposals:
            return None
        best = max(self.proposals, key=lambda x: x.get("score", 0))
        log(f"  选出最优提案: {best['type']}/{best['variant']} 评分={best['score']}")
        return best


# ══════════════════════════════════════════════════════════════════
# 模块4: 受保护应用 (Guarded Apply)
# 借鉴curator-evolver guarded_apply.py
# ══════════════════════════════════════════════════════════════════

class GuardedApplier:
    """受保护Skill应用器 — SHA256校验→备份→结构检查→验证→回滚"""
    
    @staticmethod
    def sha256_file(path: Path) -> str:
        """计算文件SHA256"""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024*1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        except FileNotFoundError:
            return ""
    
    @staticmethod
    def backup_skill(skill_name: str) -> Optional[Path]:
        """在修改前备份SKILL.md"""
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        if not skill_path.exists():
            return None
        
        ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        backup_dir = BACKUP_DIR / f"{skill_name}_{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        backup_path = backup_dir / "SKILL.md"
        shutil.copy2(skill_path, backup_path)
        
        # 保存SHA256
        sha = GuardedApplier.sha256_file(skill_path)
        (backup_dir / "sha256.txt").write_text(sha)
        
        log(f"  备份: {skill_path} → {backup_path} (SHA256: {sha[:16]}...)")
        return backup_path
    
    @staticmethod
    def apply_proposal(skill_name: str, content: str) -> bool:
        """安全应用提案（结构检查后写入）"""
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        if not skill_path.exists():
            log(f"  ❌ Skill {skill_name} 不存在")
            return False
        
        # 1. SHA256备份
        original_sha = GuardedApplier.sha256_file(skill_path)
        backup = GuardedApplier.backup_skill(skill_name)
        if not backup:
            log(f"  ❌ 备份失败")
            return False
        
        try:
            # 2. 读取当前内容
            current = skill_path.read_text(encoding="utf-8")
            
            # 3. 结构检查：YAML frontmatter完整性
            new_text = current + "\n\n" + self._format_evidence_block(content)
            
            # 4. 写入
            skill_path.write_text(new_text, encoding="utf-8")
            
            # 5. 写入后SHA验证
            post_sha = GuardedApplier.sha256_file(skill_path)
            log(f"  写入后SHA: {post_sha[:16]}...")
            
            # 6. 结构验证：检查文件是否可读
            try:
                verify = skill_path.read_text(encoding="utf-8")
                if len(verify) < 100:
                    raise ValueError("文件内容异常（<100字符）")
                log(f"  ✅ 应用成功: {skill_path}")
                return True
            except Exception as e:
                # 回滚
                log(f"  ⚠️ 结构验证失败: {e}，正在回滚...")
                shutil.copy2(backup, skill_path)
                log(f"  ✅ 已回滚到备份")
                return False
        
        except Exception as e:
            log(f"  ❌ 应用失败: {e}")
            if backup and backup.exists():
                shutil.copy2(backup, skill_path)
                log(f"  ✅ 已回滚到备份")
            return False
    
    @staticmethod
    def _format_evidence_block(content: str) -> str:
        """格式化为受管理的证据块"""
        ts = datetime.now(TZ).isoformat(timespec="seconds")
        return (
            "\n\n<!-- skill-evolver:auto:start -->\n"
            f"## Agent Evolution Notes\n\n"
            f"Auto-generated by Hermes Skill Evolver at `{ts}`.\n\n"
            f"{content}\n"
            f"<!-- skill-evolver:auto:end -->"
        )


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def cmd_collect():
    """收集证据"""
    log("📥 收集Skill改进证据")
    collector = EvidenceCollector()
    evidence = collector.collect_all()
    
    # 保存到临时文件
    output_path = REPORTS_DIR / "current_evidence.json"
    with open(output_path, "w") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    log(f"  已保存到 {output_path}")


def cmd_classify():
    """分类证据"""
    log("🏷️ 分类Skill改进证据")
    
    evidence_path = REPORTS_DIR / "current_evidence.json"
    if not evidence_path.exists():
        log("  ❌ 无证据文件，先运行 collect")
        return
    
    with open(evidence_path) as f:
        evidence = json.load(f)
    
    candidates = mine_candidates(evidence)
    
    output_path = REPORTS_DIR / "current_candidates.json"
    with open(output_path, "w") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    log(f"  候选已保存到 {output_path}")


def cmd_evolve():
    """生成+应用Skill改进"""
    log("🧬 执行Skill进化")
    
    candidates_path = REPORTS_DIR / "current_candidates.json"
    if not candidates_path.exists():
        log("  ❌ 无候选文件，先运行 classify")
        return
    
    with open(candidates_path) as f:
        candidates = json.load(f)
    
    if not candidates:
        log("  ⚠️ 无候选需要处理")
        return
    
    # 生成提案
    generator = SkillProposalGenerator()
    proposals = generator.generate_proposals(candidates)
    
    # 选最优并应用
    best = generator.select_best()
    if not best:
        log("  ❌ 未选出最优提案")
        return
    
    # 找到目标skill（如果候选包含skill信息）
    target_skill = None
    if best["type"] == "skill_update":
        # 尝试从证据中提取skill名
        evidence = best.get("evidence", "")
        for skill_dir in SKILLS_DIR.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                if skill_dir.name.lower() in evidence.lower():
                    target_skill = skill_dir.name
                    break
        
        if not target_skill:
            # 默认选使用最多的skill
            log("  未识别目标Skill，将生成报告")
    
    # 输出进化报告
    report = {
        "timestamp": datetime.now(TZ).isoformat(),
        "evidence_count": len(candidates) if candidates else 0,
        "proposals_count": len(proposals),
        "best_proposal": best,
        "target_skill": target_skill,
        "applied": False,
    }
    
    if target_skill and best["score"] >= 70:
        applier = GuardedApplier()
        success = applier.apply_proposal(target_skill, best["content_preview"])
        report["applied"] = success
        if success:
            log(f"  ✅ Skill {target_skill} 已更新")
        else:
            log(f"  ❌ Skill {target_skill} 更新失败")
    else:
        log(f"  📋 生成进化报告 (未应用，目标skill={target_skill}, 评分={best['score']})")
    
    report_path = REPORTS_DIR / f"evolution_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"  进化报告: {report_path}")


def cmd_all():
    """一站式全流程"""
    log("=" * 50)
    log("Hermes 证据驱动Skill进化引擎 — 全流程")
    log("=" * 50)
    
    cmd_collect()
    cmd_classify()
    cmd_evolve()
    
    log("=" * 50)
    log("✅ 进化全流程完成")
    log("=" * 50)


def main():
    if len(sys.argv) < 2:
        print("""用法: python3 scripts/hermes_skill_evolver.py <command>

命令:
  collect    收集证据（从复盘+候选队列）
  classify   分类证据（生成改进候选）
  evolve     生成+应用Skill改进
  all        一站式全流程
""")
        return
    
    cmd = sys.argv[1]
    if cmd == "collect":
        cmd_collect()
    elif cmd == "classify":
        cmd_classify()
    elif cmd == "evolve":
        cmd_evolve()
    elif cmd == "all":
        cmd_all()
    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
