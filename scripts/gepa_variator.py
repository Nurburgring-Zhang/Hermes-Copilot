#!/usr/bin/env python3
"""
GEPA遗传变异引擎 (P3-2) - Genetic Evolution with Probabilistic Adaptation
=============================================================================
功能：低分Skill(<60)每天做5种遗传变异
- 加点变异: 在Skill流程中插入新步骤
- 删点变异: 移除冗余步骤
- 替换变异: 用更优方案替换现有步骤
- 参数变异: 调整阈值参数(±5%)
- 交叉: 合并两个Skill

输出变异候选 + A/B测试队列

Usage:
  python3 gepa_variator.py --evolve <skill_name>
  python3 gepa_variator.py --daily-evolution
  python3 gepa_variator.py --ab-queue
"""

import json, sys, os, sqlite3, hashlib, random, copy, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
TZ = timezone(timedelta(hours=8))

random.seed(datetime.now().timestamp())

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ══════════════════════════════════════════════════════════════════
# Skill Definitions (sample skills for demonstration)
# ══════════════════════════════════════════════════════════════════

SAMPLE_SKILLS = {
    "retrospect": {
        "name": "复盘反思Skill",
        "score": 55,
        "steps": [
            {"id": "s1", "action": "load_session", "params": {"timeout": 30}},
            {"id": "s2", "action": "extract_steps", "params": {"max_steps": 200}},
            {"id": "s3", "action": "assess_quality", "params": {"dimensions": 5}},
            {"id": "s4", "action": "generate_report", "params": {"save_json": True}},
            {"id": "s5", "action": "save_to_db", "params": {}},
        ],
        "params": {
            "quality_threshold": 60,
            "error_rate_limit": 20,
            "max_retries": 3,
        },
    },
    "collector": {
        "name": "内容采集Skill",
        "score": 45,
        "steps": [
            {"id": "c1", "action": "check_source", "params": {"url": ""}},
            {"id": "c2", "action": "fetch_content", "params": {"timeout": 30}},
            {"id": "c3", "action": "parse_content", "params": {"format": "auto"}},
            {"id": "c4", "action": "extract_metadata", "params": {}},
            {"id": "c5", "action": "save_raw_item", "params": {"dedup": True}},
        ],
        "params": {
            "min_content_length": 80,
            "fetch_timeout": 30,
            "dedup_window_hours": 72,
        },
    },
    "pusher": {
        "name": "内容推送Skill",
        "score": 50,
        "steps": [
            {"id": "p1", "action": "filter_candidates", "params": {"min_score": 60}},
            {"id": "p2", "action": "dedup_check", "params": {"window_hours": 72}},
            {"id": "p3", "action": "format_content", "params": {"max_length": 2000}},
            {"id": "p4", "action": "push_to_target", "params": {"retry": 2}},
            {"id": "p5", "action": "record_push", "params": {}},
        ],
        "params": {
            "min_ai_score": 60,
            "max_age_days": 14,
            "push_frequency": 4,
        },
    },
}


class GEPAVariator:
    """
    GEPA遗传变异引擎
    对低分Skill执行5种遗传变异操作
    """

    LOW_SCORE_THRESHOLD = 60
    MUTATION_TYPES = ["add", "remove", "replace", "param_tune", "crossover"]
    AB_TEST_DURATION_HOURS = 48

    def __init__(self):
        self.mutation_log = []
        self.ab_queue = []
        self.mutation_count = 0

    def load_skill(self, skill_name: str) -> Optional[Dict]:
        """加载Skill定义（先查数据库，没有则用示例）"""
        # Try loading from intelligence.db first
        try:
            conn = sqlite3.connect(str(HERMES / "intelligence.db"))
            c = conn.cursor()
            rows = c.execute(
                "SELECT content FROM skills WHERE name=? ORDER BY updated_at DESC LIMIT 1",
                (skill_name,)
            ).fetchall()
            conn.close()
            if rows:
                return json.loads(rows[0][0])
        except:
            pass
        
        # Fallback to sample skills
        skill = SAMPLE_SKILLS.get(skill_name)
        if skill:
            return copy.deepcopy(skill)
        
        return None

    def mutation_add(self, skill: Dict) -> Dict:
        """加点变异: 在Skill流程中插入新步骤"""
        log(f"    🔧 加点变异 — 插入新步骤")
        
        new_skill = copy.deepcopy(skill)
        steps = new_skill.get("steps", [])
        
        # 生成新步骤
        step_count = len(steps)
        new_step = {
            "id": f"m{self.mutation_count}_add",
            "action": "validation_check",
            "params": {"validate_before_next": True},
            "added_by": "gepa_add_mutation",
        }
        
        # 在中间或末尾插入
        insert_pos = random.randint(0, max(0, step_count))
        steps.insert(insert_pos, new_step)
        new_skill["steps"] = steps
        new_skill["mutation_type"] = "add"
        
        log(f"      插入位置: {insert_pos}/{len(steps)} | 步骤ID: {new_step['id']}")
        return new_skill

    def mutation_remove(self, skill: Dict) -> Dict:
        """删点变异: 移除冗余步骤"""
        log(f"    🔧 删点变异 — 移除冗余步骤")
        
        new_skill = copy.deepcopy(skill)
        steps = new_skill.get("steps", [])
        
        if len(steps) <= 2:
            log(f"      步骤太少({len(steps)})，跳过删点变异")
            return skill
        
        # 选择一个非关键步骤移除（跳过第一个和最后一个）
        removable = list(range(1, len(steps) - 1))
        if not removable:
            log(f"      无可删除步骤")
            return skill
        
        remove_idx = random.choice(removable)
        removed_step = steps.pop(remove_idx)
        new_skill["steps"] = steps
        new_skill["mutation_type"] = "remove"
        
        log(f"      移除位置: {remove_idx} | 步骤: {removed_step['action']}")
        return new_skill

    def mutation_replace(self, skill: Dict) -> Dict:
        """替换变异: 用更优方案替换现有步骤"""
        log(f"    🔧 替换变异 — 优化现有步骤")
        
        new_skill = copy.deepcopy(skill)
        steps = new_skill.get("steps", [])
        
        if not steps:
            return skill
        
        # 随机选一个步骤替换
        replace_idx = random.randint(0, len(steps) - 1)
        old_step = steps[replace_idx]
        
        # 生成替换方案
        replacement_actions = {
            "load_session": "load_session_with_cache",
            "extract_steps": "extract_steps_parallel",
            "assess_quality": "assess_quality_ml",
            "generate_report": "generate_report_streaming",
            "save_to_db": "save_to_db_batch",
            "check_source": "check_source_multi",
            "fetch_content": "fetch_content_parallel",
            "parse_content": "parse_content_ai",
            "filter_candidates": "filter_candidates_ml",
            "format_content": "format_content_template",
            "push_to_target": "push_to_target_fallback",
        }
        
        better_action = replacement_actions.get(old_step["action"], f"{old_step['action']}_v2")
        
        new_step = {
            "id": f"m{self.mutation_count}_replace",
            "action": better_action,
            "params": {**old_step.get("params", {}), "optimized": True},
            "replaces": old_step["id"],
            "added_by": "gepa_replace_mutation",
        }
        
        steps[replace_idx] = new_step
        new_skill["steps"] = steps
        new_skill["mutation_type"] = "replace"
        
        log(f"      替换位置: {replace_idx} | {old_step['action']} → {better_action}")
        return new_skill

    def mutation_param_tune(self, skill: Dict) -> Dict:
        """参数变异: 调整阈值参数(±5%)"""
        log(f"    🔧 参数变异 — 阈值参数微调(±5%)")
        
        new_skill = copy.deepcopy(skill)
        params = new_skill.get("params", {})
        
        if not params:
            log(f"      无参数可调")
            return skill
        
        tuned_params = {}
        for param_name, param_value in params.items():
            if isinstance(param_value, (int, float)) and not isinstance(param_value, bool):
                # ±5% 调整
                delta = param_value * 0.05 * random.choice([-1, 1])
                if isinstance(param_value, int):
                    new_val = int(round(param_value + delta))
                else:
                    new_val = round(param_value + delta, 2)
                tuned_params[param_name] = new_val
                log(f"      {param_name}: {param_value} → {new_val} ({'+' if delta >= 0 else ''}{delta:.2f})")
            else:
                tuned_params[param_name] = param_value
        
        new_skill["params"] = tuned_params
        new_skill["mutation_type"] = "param_tune"
        
        return new_skill

    def mutation_crossover(self, skill_a: Dict, skill_b: Dict) -> Tuple[Dict, Dict]:
        """交叉变异: 合并两个Skill的步骤"""
        log(f"    🔧 交叉变异 — 合并两个Skill")
        
        child_a = copy.deepcopy(skill_a)
        child_b = copy.deepcopy(skill_b)
        
        steps_a = child_a.get("steps", [])
        steps_b = child_b.get("steps", [])
        
        if not steps_a or not steps_b:
            log(f"      步骤不足，跳过交叉")
            return skill_a, skill_b
        
        # 选择交叉点
        cross_point_a = random.randint(1, max(1, len(steps_a) - 1))
        cross_point_b = random.randint(1, max(1, len(steps_b) - 1))
        
        # 交换后半部分
        new_steps_a = steps_a[:cross_point_a] + steps_b[cross_point_b:]
        new_steps_b = steps_b[:cross_point_b] + steps_a[cross_point_a:]
        
        child_a["steps"] = new_steps_a
        child_b["steps"] = new_steps_b
        child_a["mutation_type"] = "crossover"
        child_b["mutation_type"] = "crossover"
        child_a["parents"] = [skill_a.get("name", "unknown"), skill_b.get("name", "unknown")]
        child_b["parents"] = [skill_a.get("name", "unknown"), skill_b.get("name", "unknown")]
        
        log(f"      交叉点A: {cross_point_a}/{len(steps_a)} | 交叉点B: {cross_point_b}/{len(steps_b)}")
        log(f"      子代A: {len(new_steps_a)}步 | 子代B: {len(new_steps_b)}步")
        
        return child_a, child_b

    def evolve_skill(self, skill_name: str) -> List[Dict]:
        """对单个Skill执行5种变异"""
        skill = self.load_skill(skill_name)
        if not skill:
            log(f"❌ 未找到Skill: {skill_name}")
            return []
        
        score = skill.get("score", 100)
        log(f"\n📊 开始进化: {skill['name']} (当前评分: {score})")
        
        if score >= self.LOW_SCORE_THRESHOLD:
            log(f"  ✅ 评分 {score} >= {self.LOW_SCORE_THRESHOLD}，无需进化")
            return []
        
        candidates = []
        
        # 1. 加点变异
        cand_add = self.mutation_add(skill)
        candidates.append(("add", cand_add))
        
        # 2. 删点变异
        cand_remove = self.mutation_remove(skill)
        candidates.append(("remove", cand_remove))
        
        # 3. 替换变异
        cand_replace = self.mutation_replace(skill)
        candidates.append(("replace", cand_replace))
        
        # 4. 参数变异
        cand_param = self.mutation_param_tune(skill)
        candidates.append(("param_tune", cand_param))
        
        # 5. 交叉变异（需要另一个Skill）
        other_skills = [s for s in SAMPLE_SKILLS if s != skill_name]
        if other_skills:
            other_name = random.choice(other_skills)
            other_skill = self.load_skill(other_name)
            if other_skill:
                child_a, child_b = self.mutation_crossover(skill, other_skill)
                candidates.append(("crossover_a", child_a))
                candidates.append(("crossover_b", child_b))
        
        # 记录
        self.mutation_count += len(candidates)
        self.mutation_log.append({
            "skill_name": skill_name,
            "original_score": score,
            "mutations_generated": len(candidates),
            "candidates": [c[1].get("name", "unnamed") for c in candidates],
            "timestamp": datetime.now(TZ).isoformat(),
        })
        
        # 加入A/B测试队列
        for mut_type, candidate in candidates:
            ab_entry = {
                "id": str(uuid.uuid4())[:8],
                "skill_name": skill_name,
                "mutation_type": mut_type,
                "candidate": candidate,
                "status": "pending",
                "created_at": datetime.now(TZ).isoformat(),
                "test_duration_hours": self.AB_TEST_DURATION_HOURS,
            }
            self.ab_queue.append(ab_entry)
        
        log(f"\n  ✅ 进化完成 - 生成 {len(candidates)} 个变异候选")
        for mut_type, _ in candidates:
            log(f"    - {mut_type}")
        
        return candidates

    def daily_evolution(self):
        """每日批量进化"""
        log("\n" + "=" * 50)
        log("GEPA每日批量进化启动")
        log("=" * 50)
        
        all_candidates = []
        
        # 进化所有低分Skill
        for skill_name in SAMPLE_SKILLS:
            candidates = self.evolve_skill(skill_name)
            all_candidates.extend(candidates)
        
        # 保存A/B测试队列
        self._save_ab_queue()
        
        # 保存变异候选
        self._save_candidates(all_candidates)
        
        log(f"\n📊 每日进化汇总:")
        log(f"  处理Skill: {len(SAMPLE_SKILLS)} 个")
        log(f"  生成候选: {len(all_candidates)} 个")
        log(f"  A/B队列: {len(self.ab_queue)} 条")
        log("=" * 50)
        
        return all_candidates

    def _save_ab_queue(self):
        """保存A/B测试队列"""
        if not self.ab_queue:
            return
        
        queue_file = HERMES / "data" / "gepa_ab_queue.json"
        (HERMES / "data").mkdir(exist_ok=True)
        
        # 合并现有队列和新队列
        existing = []
        if queue_file.exists():
            with open(queue_file) as f:
                try:
                    existing = json.load(f)
                except:
                    existing = []
        
        all_entries = existing + self.ab_queue
        
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(all_entries, f, ensure_ascii=False, indent=2)
        
        log(f"  📝 A/B测试队列已保存: {queue_file} ({len(all_entries)} 条)")
    
    def _save_candidates(self, candidates: list):
        """保存变异候选到文件"""
        if not candidates:
            return
        
        date_str = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        filepath = HERMES / "reports" / f"gepa_candidates_{date_str}.json"
        (HERMES / "reports").mkdir(exist_ok=True)
        
        data = []
        for mut_type, candidate in candidates:
            data.append({
                "mutation_type": mut_type,
                "skill_name": candidate.get("name", "unknown"),
                "steps_count": len(candidate.get("steps", [])),
                "params": candidate.get("params", {}),
            })
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        log(f"  📄 变异候选已保存: {filepath}")

    def show_ab_queue(self):
        """显示A/B测试队列"""
        queue_file = HERMES / "data" / "gepa_ab_queue.json"
        if not queue_file.exists():
            log("📝 A/B测试队列为空")
            return
        
        with open(queue_file) as f:
            queue = json.load(f)
        
        log(f"\n📊 A/B测试队列 ({len(queue)} 条)")
        log("=" * 50)
        pending = [q for q in queue if q.get("status") == "pending"]
        running = [q for q in queue if q.get("status") == "running"]
        completed = [q for q in queue if q.get("status") == "completed"]
        
        log(f"  待测试: {len(pending)}")
        log(f"  进行中: {len(running)}")
        log(f"  已完成: {len(completed)}")
        
        if pending:
            log("\n  📋 待测试列表:")
            for p in pending[:10]:
                log(f"    [{p['id']}] {p['skill_name']} - {p['mutation_type']}")


def auto():
    """--auto入口: 每日自动进化低分Skill，供cron调用"""
    variator = GEPAVariator()
    return variator.daily_evolution()

def install_cron():
    """安装crontab每天凌晨4:00自动执行"""
    cron_line = "0 4 * * * cd ~/.hermes && python3 scripts/gepa_variator.py --auto >> logs/gepa_cron.log 2>&1"
    try:
        import subprocess
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
        if "gepa_variator.py" in existing or "gepa" in existing.lower():
            log("  ⏰ crontab条目已存在，跳过安装")
            return False
        # 写入
        new_cron = existing.strip() + "\n" + cron_line + "\n" if existing.strip() else cron_line + "\n"
        subprocess.run(["crontab", "-"], input=new_cron, text=True, timeout=10)
        log("  ✅ crontab已安装: 每天4:00 gepa_variator.py --auto")
        return True
    except Exception as e:
        log(f"  ⚠️ 安装crontab失败: {e}")
        log(f"  请手动添加: {cron_line}")
        return False

def main():
    if "--evolve" in sys.argv:
        idx = sys.argv.index("--evolve")
        skill_name = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if skill_name:
            variator = GEPAVariator()
            variator.evolve_skill(skill_name)
        else:
            log("用法: --evolve <skill_name>")
    elif "--daily-evolution" in sys.argv or "--auto" in sys.argv:
        variator = GEPAVariator()
        variator.daily_evolution()
    elif "--install-cron" in sys.argv:
        install_cron()
    elif "--ab-queue" in sys.argv:
        variator = GEPAVariator()
        variator.show_ab_queue()
    else:
        print("""GEPA遗传变异引擎 (P3-2)
Usage:
  python3 gepa_variator.py --evolve <skill_name>   进化单个Skill
  python3 gepa_variator.py --daily-evolution       每日批量进化
  python3 gepa_variator.py --auto                  每日自动进化(供cron)
  python3 gepa_variator.py --install-cron          安装crontab(每天4:00)
  python3 gepa_variator.py --ab-queue              查看A/B测试队列
""")


if __name__ == "__main__":
    main()
