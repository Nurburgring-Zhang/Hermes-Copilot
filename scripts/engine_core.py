#!/usr/bin/env python3
"""
Hermes 底层驱动引擎 — 让所有能力主动运行、自动决策
======================================================
核心设计: 把Hermes的"武器库"从被动调用改为主动调度。

当前问题:
  - 武器库(279脚本+188skill+130员工+390专家)不会主动用
  - 子Agent超时不会自动分段
  - 所有能力"等着被提醒"才用

解决方案: 三层主动驱动架构
  层1: 任务分析层 — 拿到任务先分析"需要哪些能力"
  层2: 调度执行层 — 自动调用武器库, 超时自动分段
  层3: 监控反馈层 — 每步检查结果, 不对自动换方案
"""

import os, sys, json, time, subprocess, hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

HERMES = Path(os.path.expanduser("~/.hermes"))

# ════════════════════════════════════════════════════════════
# 武器库注册中心 — 让Hermes知道"自己有什么能力"
# ════════════════════════════════════════════════════════════

class ArsenalRegistry:
    """武器库注册中心 — 扫描并索引所有可用能力"""
    
    def __init__(self):
        self.weapons = self._scan_all()
    
    def _scan_all(self) -> dict:
        """全量扫描武器库"""
        return {
            "scripts": self._scan_scripts(),
            "skills": self._scan_skills(),
            "agents": self._scan_agents(),
            "tools": self._scan_tools(),
            "modules": self._scan_modules(),
        }
    
    def _scan_scripts(self) -> list:
        """扫描所有可执行脚本"""
        scripts = []
        scripts_dir = HERMES / "scripts"
        if scripts_dir.exists():
            for f in sorted(scripts_dir.glob("*.py")):
                sz = f.stat().st_size
                # 跳过测试/备份/缓存
                if any(kw in f.name for kw in ["test_", "backup", "__pycache__", "init_"]):
                    continue
                # 识别脚本类型
                ftype = self._classify_script(f)
                scripts.append({
                    "name": f.stem,
                    "path": str(f.relative_to(HERMES)),
                    "size": sz,
                    "type": ftype,
                    "mtime": f.stat().st_mtime,
                })
        return scripts
    
    def _classify_script(self, path: Path) -> str:
        """分类脚本功能类型"""
        name = path.stem.lower()
        if any(kw in name for kw in ["collect", "crawl", "scrape", "feed"]):
            return "采集"
        if any(kw in name for kw in ["clean", "filter", "spam"]):
            return "清洗"
        if any(kw in name for kw in ["score", "rating", "rank"]):
            return "评分"
        if any(kw in name for kw in ["push", "send", "notify"]):
            return "推送"
        if any(kw in name for kw in ["memory", "recall", "store"]):
            return "记忆"
        if any(kw in name for kw in ["evolve", "learn", "train"]):
            return "进化"
        if any(kw in name for kw in ["guard", "check", "audit", "verify"]):
            return "质检"
        if any(kw in name for kw in ["context", "compress", "pack"]):
            return "上下文"
        if any(kw in name for kw in ["gear", "engine", "loop", "pipeline"]):
            return "引擎"
        if any(kw in name for kw in ["bridge", "api", "proxy"]):
            return "桥接"
        return "工具"
    
    def _scan_skills(self) -> list:
        """扫描所有skill"""
        skills = []
        skills_dir = HERMES / "skills"
        if skills_dir.exists():
            for cat_dir in skills_dir.iterdir():
                if not cat_dir.is_dir() or cat_dir.name.startswith("."):
                    continue
                for skill_dir in cat_dir.iterdir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        skills.append({
                            "name": skill_dir.name,
                            "category": cat_dir.name,
                            "path": str(skill_md.relative_to(HERMES)),
                            "size": skill_md.stat().st_size,
                        })
        return skills
    
    def _scan_agents(self) -> list:
        """扫描130员工+390专家"""
        agents = {"employees": 0, "experts": 0}
        emp_dir = HERMES / "agents_company" / "employees"
        exp_dir = HERMES / "agents_company" / "experts"
        if emp_dir.exists(): agents["employees"] = len(os.listdir(emp_dir))
        if exp_dir.exists(): agents["experts"] = len(os.listdir(exp_dir))
        return agents
    
    def _scan_tools(self) -> list:
        """扫描工具"""
        tools = []
        tools_dir = HERMES / "tools"
        if tools_dir.exists():
            for f in tools_dir.glob("*.py"):
                tools.append({"name": f.stem, "path": str(f.relative_to(HERMES))})
        return tools
    
    def _scan_modules(self) -> list:
        """扫描独立模块目录"""
        modules = []
        for d in ["production_loop", "auto_engine", "evolution_v3", "agent"]:
            mod_dir = HERMES / d
            if mod_dir.exists():
                files = [f.name for f in mod_dir.glob("*.py") if not f.name.startswith("_")]
                modules.append({"name": d, "files": files})
        return modules
    
    def summary(self) -> dict:
        """武器库总览"""
        return {
            "scripts": len(self.weapons["scripts"]),
            "skills": len(self.weapons["skills"]),
            "employees": self.weapons["agents"]["employees"],
            "experts": self.weapons["agents"]["experts"],
            "tools": len(self.weapons["tools"]),
            "modules": len(self.weapons["modules"]),
            "total": (len(self.weapons["scripts"]) + len(self.weapons["skills"]) +
                      self.weapons["agents"]["employees"] + self.weapons["agents"]["experts"] +
                      len(self.weapons["tools"])),
        }
    
    def query(self, task_type: str) -> dict:
        """根据任务类型查询需要什么武器"""
        type_map = {
            "采集": {"scripts": ["unified_collector_v5"], "skills": ["intelligence"]},
            "推送": {"scripts": ["hermes_v12_push", "guardian"], "skills": ["push"]},
            "开发": {"scripts": [], "skills": ["software-development"]},
            "修复": {"scripts": [], "skills": ["fix"]},
            "研究": {"scripts": [], "skills": ["research"]},
            "记忆": {"scripts": ["hy_memory_orchestrator"], "skills": ["memory"]},
            "安全": {"scripts": ["hermes_camel_guard"], "skills": ["security"]},
            "进化": {"scripts": ["hermes_self_evolve_cluster"], "skills": ["evolution"]},
        }
        return type_map.get(task_type, {"scripts": [], "skills": []})


# ════════════════════════════════════════════════════════════
# 智能调度器 — 自动拆任务、调武器、分段执行
# ════════════════════════════════════════════════════════════

class SmartScheduler:
    """
    智能调度器 — 拿到任务后自动:
    1. 分析任务需要什么能力
    2. 自动并行调用相关武器
    3. 结果汇总
    4. 超时自动分段
    """
    
    def __init__(self):
        self.arsenal = ArsenalRegistry()
        self.running_tasks = {}
    
    def analyze_task(self, task: str) -> dict:
        """分析任务, 返回需要的能力清单"""
        task_lower = task.lower()
        
        # 识别任务类型 — 支持多类型匹配
        task_types = []
        if any(kw in task_lower for kw in ["推送", "push", "发送", "通知"]):
            task_types.append("推送")
        if any(kw in task_lower for kw in ["采集", "收集", "crawl", "scrape", "抓取", "爬"]):
            task_types.append("采集")
        if any(kw in task_lower for kw in ["修复", "修", "fix", "bug", "错误", "故障"]):
            task_types.append("修复")
        if any(kw in task_lower for kw in ["开发", "写", "code", "implement", "实现", "创建"]):
            task_types.append("开发")
        if any(kw in task_lower for kw in ["研究", "调查", "research", "分析", "搜索"]):
            task_types.append("研究")
        if any(kw in task_lower for kw in ["记忆", "remember", "memory"]):
            task_types.append("记忆")
        if any(kw in task_lower for kw in ["安全", "security", "审计"]):
            task_types.append("安全")
        if any(kw in task_lower for kw in ["进化", "优化", "evolve", "enhance", "升级"]):
            task_types.append("进化")
        if any(kw in task_lower for kw in ["清洗", "clean", "filter", "评分", "score"]):
            task_types.append("清洗")
        if any(kw in task_lower for kw in ["部署", "deploy", "配置", "安装"]):
            task_types.append("部署")
        
        # 如果没有匹配到任何类型, 调整为通用
        if not task_types:
            task_types = ["通用"]
        
        # 主类型 = 第一个匹配的
        primary_type = task_types[0]
        
        # 查询武器库 — 合并所有匹配类型
        all_scripts = []
        all_skills = []
        seen_scripts = set()
        seen_skills = set()
        for tt in task_types:
            needed = self.arsenal.query(tt)
            for s in needed.get("scripts", []):
                if s not in seen_scripts:
                    all_scripts.append(s)
                    seen_scripts.add(s)
            for sk in needed.get("skills", []):
                if sk not in seen_skills:
                    all_skills.append(sk)
                    seen_skills.add(sk)
        
        # 估算复杂度: 决定是否分段
        complexity = "简单"
        if len(task) > 200:
            complexity = "复杂"
        elif len(task_types) > 2:
            complexity = "复杂"
        elif any(kw in task_lower for kw in ["多个", "所有", "全部", "批量", "大量", "大规模"]):
            complexity = "复杂"
        elif any(kw in task_lower for kw in ["同时", "并行", "然后", "接着", "再"]):
            complexity = "复杂"
        
        # 建议分段数
        segments = 1
        if complexity == "复杂":
            segments = max(len(task_types), 3)  # 至少拆3段
        
        return {
            "task_type": primary_type,
            "task_types": task_types,  # 新增: 完整类型列表
            "complexity": complexity,
            "suggested_segments": segments,
            "needs_scripts": all_scripts,
            "needs_skills": all_skills,
            "available_weapons": self.arsenal.summary(),
        }
    
    def should_segment(self, task: str, timeout_min: int = 5) -> bool:
        """判断是否需要分段执行"""
        # 超时自动分段
        task_lower = task.lower()
        
        # 场景1: 任务涉及多个独立步骤
        multi_step_markers = ["然后", "接着", "之后", "再", "并且", "同时", "and", "then"]
        marker_count = sum(1 for m in multi_step_markers if m in task_lower)
        if marker_count >= 3:
            return True
        
        # 场景2: 涉及大量数据或批量操作
        if any(kw in task_lower for kw in ["所有", "全部", "每个", "批量", "all", "every"]):
            return True
        
        # 场景3: 涉及多个工具或子Agent
        if any(kw in task_lower for kw in ["同时", "并行", "多个agent", "multi"]):
            return True
        
        # 场景4: 任务描述很长(>200字)
        if len(task) > 200:
            return True
        
        return False
    
    def segment_task(self, task: str, n_segments: int = 3) -> list:
        """将任务拆成多个子任务"""
        if n_segments <= 1:
            return [{"id": 1, "description": task, "depends_on": []}]
        
        # 按自然段落或关键标记拆解
        import re
        segments = []
        
        # 尝试按"然后/接着/再"拆
        parts = re.split(r'(?:然后|接着|之后|再|并且|下一步)', task)
        if len(parts) >= n_segments:
            for i, part in enumerate(parts):
                if part.strip():
                    segments.append({
                        "id": i + 1,
                        "description": part.strip(),
                        "depends_on": [i] if i > 0 else [],
                    })
        
        # 如果自然拆不够, 平均分
        if len(segments) < n_segments:
            words = task.split()
            seg_size = max(len(words) // n_segments, 10)
            segments = []
            for i in range(0, len(words), seg_size):
                chunk = " ".join(words[i:i+seg_size])
                if chunk.strip():
                    segments.append({
                        "id": len(segments) + 1,
                        "description": chunk.strip(),
                        "depends_on": [len(segments)] if segments else [],
                    })
        
        return segments
    
    def get_relevant_weapons(self, task: str) -> list:
        """获取与当前任务相关的武器"""
        analysis = self.analyze_task(task)
        weapons = []
        
        # 从所有script中找相关的
        task_lower = task.lower()
        task_words = set(w for w in task_lower.split() if len(w) > 1)
        for s in self.arsenal.weapons["scripts"]:
            name = s["name"].lower().replace("_", " ")
            # 检查任务关键词是否出现在脚本名中, 或脚本类型匹配任务类型
            if any(w in name for w in task_words) or s["type"] in task_lower:
                weapons.append({
                    "name": s["name"],
                    "path": s["path"],
                    "type": s["type"],
                    "relevance": "匹配",
                })
        
        return weapons


# ════════════════════════════════════════════════════════════
# 武器强制调用协议 — 让LLM不能不调用武器
# ════════════════════════════════════════════════════════════

class ForcedWeaponProtocol:
    """
    武器强制调用协议 v1.0
    ======================
    不是"告诉LLM有什么武器"——那是建议, 不是强制。
    
    核心设计:
      每次任务到达时, 生成三段式强制指令:
      [武器匹配] 必须输出 — 不输出=违规
      [武器调用] 必须调用至少2个 — 未调用=违规  
      [武器结果] 必须汇报 — 未汇报=违规
    
    输出格式是面向LLM的system prompt块, 包含:
      1. 任务分析结果
      2. 推荐武器清单(至少3个)
      3. 调用方案(并行/串行/分段)
      4. 强制规则: "不执行这些步骤直接回答=违规"
    """
    
    def __init__(self, task: str = ""):
        self.arsenal = ArsenalRegistry()
        self.scheduler = SmartScheduler()
        self.task = task
        self.task_analysis = self.scheduler.analyze_task(task) if task else None
        self.weapons = self.scheduler.get_relevant_weapons(task) if task else []
    
    def generate_mandate(self, task: str) -> str:
        """生成强制武器调用指令块 — 这是LLM必须执行的指令, 不是参考信息"""
        analysis = self.scheduler.analyze_task(task)
        weapons = self.scheduler.get_relevant_weapons(task)
        needs_scripts = analysis["needs_scripts"]
        needs_skills = analysis["needs_skills"]
        task_types = analysis.get("task_types", [analysis["task_type"]])
        
        # 如果武器库匹配出0个脚本, 改用全武器库按类型推荐
        if not needs_scripts and not needs_skills:
            # 根据所有匹配的任务类型推全类别武器
            for tt in task_types:
                type_weapons = self._recommend_by_type(tt)
                for s in type_weapons.get("scripts", []):
                    if s not in needs_scripts:
                        needs_scripts.append(s)
                for sk in type_weapons.get("skills", []):
                    if sk not in needs_skills:
                        needs_skills.append(sk)
        
        # 强制构建: 至少3个推荐
        recommended = []
        for s in needs_scripts[:5]:
            recommended.append(f"├─ scripts/{s}.py — {self._get_script_desc(s)}")
        for sk in needs_skills[:5]:
            recommended.append(f"├─ skill: {sk} — {self._get_skill_desc(sk)}")
        
        # 如果还不够3个, 从武器库补
        if len(recommended) < 3:
            for w in weapons:
                w_name = w["name"]
                w_path = w["path"]
                if f"{w_name}" not in " ".join(recommended):
                    recommended.append(f"├─ {w_path} — 任务关键词匹配")
                    if len(recommended) >= 5:
                        break
        
        # 如果还不够, 补通用
        if len(recommended) < 3:
            recommended.append("├─ tools/progress_tool.py — 进度追踪与反馈")
            recommended.append("├─ scripts/hermes_retrospect.py — 任务复盘引擎")
            recommended.append("├─ scripts/consistency_guard.py — 执行一致性守卫")
        
        summary = self.arsenal.summary()
        
        # ── 判断：这个任务需要分解吗？ ──
        needs_decomposition = (
            analysis["complexity"] == "复杂" 
            or len(task_types) > 1 
            or len(task) > 200
            or any(kw in task.lower() for kw in ["然后", "接着", "再", "同时", "并行", "and then", "multiple", "多个"])
        )
        
        # ── 分解方案 ──
        decomposition = ""
        if needs_decomposition:
            segments_needed = analysis["suggested_segments"]
            # 生成分段方案
            seg_schema = ""
            for i, tt in enumerate(task_types):
                seg_schema += f"   段{i+1}: 【{tt}】→ 使用{tt}类武器 → 完成后保存检查点\n"
            seg_schema += "   最终段: 【合并】→ 综合所有段的结果 → 输出结论\n"
            
            decomposition = f"""
【步骤0: 任务分解】(🔴必须执行, 不可跳过)
此任务涉及多个步骤({', '.join(task_types)}), 不可一次性完成。
你必须先分解为至少{segments_needed}个独立段, 逐段执行。

  分解规则:
    1. 分析任务 → 识别所有独立子任务
    2. 拆分 → 至少{segments_needed}段
    3. 每段只做一件事
    4. 标记依赖关系(哪些段必须在前、哪些可并行)
    5. 保存断点 → 每段完成后必须执行:
       python3 ~/.hermes/scripts/checkpoint_recorder.py save "{analysis['task_type']}_seg_X" "段进度描述"
    6. 中断恢复 → 被截断后恢复时, 从上一个检查点继续, 不从头开始

  分段方案:
{seg_schema}
  执行顺序:
    - 互不依赖的段: 用 delegate_task 并行运行(最多3个并行)
    - 有依赖的段: A完成后才能开始B

  ⚠️ 每段开始前: 重新执行本协议, 重新匹配武器(因为每段任务类型不同)

  违规(立即纠正):
    ❌ 不分解就直接执行 → 必然被截断、丢失进度
    ❌ 分解后只做第一段就停下来 → 任务未完成
    ❌ 不保存检查点 → 中断后所有工作白做
    ❌ 段间不重新匹配武器 → 本段武器不适合下段任务

  正确行为:
    ✅ 拿到任务先输出分段方案(段1/段2/段3...)
    ✅ 每段: 匹配武器→调用武器→执行→保存断点→汇报完成
    ✅ 最后段: 合并所有段结果, 输出最终答案
"""
        
        # ── 反模拟铁律(独立于其他规则, 最高优先级) ──
        anti_fake = """
🔴🔴🔴🔴🔴 最高级别禁令: 严禁任何形式的精简/示意/模拟/占位/假装实现

这是最高优先级的铁律, 凌驾于所有其他规则之上。任何时候都不能违反。

禁止的行为(包括但不限于):
  · 用"示例代码"代替完整实现 → 必须写出完整可运行的代码
  · 用"示意"或"演示"代替真实执行 → 必须实际调用工具完成任务
  · 用"占位符"或"TODO"代替实际内容 → 不允许留下任何未完成的标记
  · 用"简化版本"或"核心功能"偷工减料 → 必须是端到端完整实现
  · 用"只展示关键部分"逃避写完整内容 → 必须输出全部内容
  · 用"以此类推"跳过重复工作 → 每项工作都必须逐一完成
  · 输出"示例输出"代替真实工具调用结果 → 必须实际运行工具获取真实结果
  · 说"我已经完成了X"但没有留下任何可验证的产出物 → 必须有可读的文件/配置/代码
  
  正确的做法:
  ✅ 任务太大 → 分解段落, 逐段完成, 每段都完整实现
  ✅ 代码太多 → 逐文件编写, 每个文件完整可运行
  ✅ 重复操作 → 用脚本批量处理, 不是"以此类推"
  ✅ 没有结果 → 实际调用工具, 展示真实输出
  ✅ 不知道怎么做 → 直接说不知道, 不能假装知道

  这条规则由齿轮G1每轮扫描你的输出, 发现"示例/示意/简化/占位/演示/TODO/FIXME"等词→自动标记违规。
"""

        segments_info = decomposition
        
        mandate = f"""
🔴🔴🔴 强制武器调用协议 + 任务分解协议 + 反模拟铁律 — 三重强制, 不可降级

{anti_fake}

你面对的任务: 「{task}」
武器库总量: {summary['total']}件 (scripts {summary['scripts']} / skills {summary['skills']} / 员工 {summary['employees']} / 专家 {summary['experts']})

你必须按以下步骤执行, 不得跳过:

{segments_info}
【步骤1: 武器匹配】(必须输出)
任务类型: {analysis['task_type']} | 复杂度: {analysis['complexity']}
推荐武器(至少选3个):
"""
        for r in recommended:
            mandate += f"  {r}\n"
        
        # 判断并行
        needs_parallel = needs_decomposition or len(recommended) >= 2
        
        if needs_parallel and (len(task_types) > 1 or analysis["complexity"] == "复杂"):
            mandate += f"""
【步骤2: 武器调用】(必须执行, 至少调用2个)
  ✅ 可并行: 使用 delegate_task 同时调用互不依赖的武器
  ✅ 或串行: 按依赖顺序依次调用
  你必须明确输出: 「[武器调用] 使用: weapon_A + weapon_B」
  然后通过 tool_call 实际执行它们。
  禁止不调用武器就直接回答!
  
【步骤3: 结果融合】(必须输出)
  合并各武器的执行结果。
  格式:
  [武器结果]
    weapon_A: 完成, 输出XXX
    weapon_B: 完成, 输出YYY
    → 综合结论: ZZZ

【步骤4: 验证】(必须做)
  答案是基于武器执行结果得出的, 不是自己编的。
  确认: 每个结论都有对应的武器调用作为证据。

❌ 违规行为(立即纠正):
  · 不调用武器直接回答
  · 只调用1个武器就停下来
  · 假装调用(写了调用但实际上没执行tool_call)
  · 调用武器但不输出使用了什么
  · 选择性忽略推荐的武器

✅ 正确行为:
  · 至少2个武器并行/串行调用
  · 每个武器的输出都明确记录
  · 最终答案基于武器结果综合得出
"""
        else:
            mandate += f"""
【步骤2: 武器调用】(必须执行, 至少调用2个)
  按序调用: 先用分析型武器了解情况, 再用执行型武器解决问题。
  你必须明确输出: 「[武器调用] 使用: weapon_A → weapon_B」
  然后通过 tool_call 实际执行它们。
  禁止不调用武器就直接回答!

【步骤3: 结果汇报】(必须输出)
  每个武器的输出关键信息。

【步骤4: 验证】
  确认答案基于武器执行结果, 不是自己编的。

❌ 违规: 不调用武器直接回答 / 只调用1个 / 假装调用
"""
        
        return mandate
    
    def _get_script_desc(self, name: str) -> str:
        """根据脚本名快速描述功能"""
        descs = {
            "unified_collector_v5": "全平台采集引擎(微博/头条/微信/RSS)",
            "hermes_v12_push": "v12推送引擎(AI六维评分+方向标签)",
            "guardian": "3模式调度(cycle/heal/push)+cron驱动",
            "hy_memory_orchestrator": "Hy-Memory全链路编排(L1→L2→L3)",
            "hermes_camel_guard": "CaMeL安全护栏(注入检测/工具防护)",
            "hermes_self_evolve_cluster": "自进化集群(技能进化+记忆压缩)",
            "dialogue_context_init": "对话层压缩+武器库注入+全链路恢复",
            "gear_enforcer": "G1齿轮(中断检测+AI评分+wake_guide)",
            "engine_core": "武器库注册中心+智能调度器(本模块)",
        }
        return descs.get(name, f"{name}相关脚本")
    
    def _get_skill_desc(self, name: str) -> str:
        """快速获取skill描述"""
        descs = {
            "intelligence": "情报系统(48个注册采集器)",
            "push": "微信推送系统(全链路)",
            "software-development": "软件开发(调试/测试/代码审查)",
            "research": "研究与采集(学术/博客/信息检索)",
            "memory": "记忆系统(Hy-Memory完整管道)",
            "security": "安全护栏(CaMeL注入防护)",
            "evolution": "自进化(技能/记忆/对话/能力)",
        }
        return descs.get(name, f"{name}相关skill")
    
    def _recommend_by_type(self, task_type: str) -> dict:
        """按任务类型推荐全部可用武器"""
        type_map = {
            "采集": {
                "scripts": [
                    "unified_collector_v5", "toutiao_enhanced", 
                    "wechat_collector_v9", "xiaohongshu_collector",
                    "browser_multi_platform_collector", "wechat_bing_collector",
                    "wechat_browser_collector_v3", "ultimate_collector"
                ],
                "skills": ["intelligence", "hermes-intelligence-v5-debug", 
                          "platform-collection-debugging-playbook", "unified-collection-pipeline"]
            },
            "推送": {
                "scripts": [
                    "hermes_v12_push", "guardian",
                    "v8_final_push", "pushplus_wechat"
                ],
                "skills": ["hermes-push-v3", "hermes-ai-push-manager", 
                          "push-preference-matching-tags", "pushplus-rate-limit-handler"]
            },
            "开发": {
                "scripts": [
                    "production_loop_cron", "engine_core"
                ],
                "skills": ["software-development", "test-driven-development",
                          "requesting-code-review", "systematic-debugging",
                          "deep-code-architecture-analysis", "six-page-plan",
                          "extreme-code-audit-triple-agent"]
            },
            "修复": {
                "scripts": [
                    "engine_core", "consistency_guard", "auto_healer"
                ],
                "skills": ["systematic-debugging", "diagnose",
                          "deep-code-architecture-analysis"]
            },
            "研究": {
                "scripts": [],
                "skills": ["research", "arxiv", "blogwatcher", "hv-analysis"]
            },
            "记忆": {
                "scripts": [
                    "hy_memory_orchestrator", "l1_extractor",
                    "task_boundary", "episodic_injector",
                    "l2_scene_scheduler", "l3_persona_scheduler"
                ],
                "skills": ["hy-memory-p0-integration", "memory-evolution-v2",
                          "rag-memory-enhanced", "parallel-memory-orchestrator"]
            },
            "安全": {
                "scripts": ["hermes_camel_guard", "consistency_guard"],
                "skills": ["security", "hermes-camel-guard",
                          "security-permissions-system"]
            },
            "进化": {
                "scripts": [
                    "hermes_self_evolve_cluster", "experience_extractor",
                    "gepa_variator", "auto_cleaner"
                ],
                "skills": ["self-evolution-executor", "hermes-skill-evolver",
                          "evolution-fix-actions", "self-evolution-agent-cycle"]
            },
            "通用": {
                "scripts": [
                    "engine_core", "gear_enforcer", "dialogue_context_init",
                    "consistency_guard", "context_failsafe"
                ],
                "skills": ["task-retrospect", "production-reliability-engine",
                          "long-task-guardian", "task-auto-resume"]
            },
            "清洗": {
                "scripts": [
                    "unified_cleaning_pipeline", "hermes_cleaning_pipeline_v2",
                    "lowscore_cleaning_workflow"
                ],
                "skills": ["intelligence", "unified-cleaning-pipeline",
                          "collection-quality-prescreen"]
            },
            "部署": {
                "scripts": ["deploy", "production_loop_cron", "engine_core"],
                "skills": ["devops", "hermes-upgrade-workflow",
                          "system-code-consolidation"]
            },
        }
        return type_map.get(task_type, type_map["通用"])


# ════════════════════════════════════════════════════════════
# 武器调用验证器 — 检测LLM是否真的调用了武器
# ════════════════════════════════════════════════════════════

class WeaponCallValidator:
    """
    武器调用验证器 — 在G1齿轮中运行, 检测LLM是否真的调用了推荐的武器。
    
    检测方式:
    1. 读取最近的对话session log中的tool_call记录
    2. 检查是否有调用了推荐列表中的scripts/skills
    3. 如果没有 -> 标记违规 -> 写入wake_guide
    """
    
    def __init__(self):
        self.hermes = HERMES
    
    def check_recent_calls(self, recommended_weapons: list) -> dict:
        """
        检查最近的tool_call是否包含推荐的武器调用。
        
        返回:
        {
            "called": ["weapon_A", "weapon_B"],
            "missed": ["weapon_C"],  # 推荐了但没调用的
            "total_calls": 5,        # 总共调用了几个工具
            "weapon_calls": 2,       # 其中武器调用几个
            "compliant": True,       # 是否合规(至少调用了2个武器)
        }
        """
        result = {
            "called": [],
            "missed": [],
            "total_calls": 0,
            "weapon_calls": 0,
            "compliant": False,
        }
        
        # 方法1: 检查最近的session log
        log_dir = self.hermes / "logs"
        if log_dir.exists():
            recent_logs = sorted(log_dir.glob("session_*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
            if recent_logs:
                latest = recent_logs[0]
                try:
                    content = latest.read_text()
                    # 提取所有的tool_call关键字
                    import re
                    tool_calls = re.findall(r'(?:tool_call|tool_use|tool_call_id|terminal|read_file|search_files|delegate_task)', content)
                    result["total_calls"] = len(tool_calls)
                    
                    # 检查推荐武器是否在日志中
                    for weapon in recommended_weapons:
                        w_name = weapon if isinstance(weapon, str) else weapon.get("name", str(weapon))
                        if w_name in content:
                            result["called"].append(w_name)
                            result["weapon_calls"] += 1
                        else:
                            result["missed"].append(w_name)
                except:
                    pass
        
        # 方法2: 检查wake_guide中的tool_call记录
        wg_path = self.hermes / "reports" / "wake_guide.json"
        if wg_path.exists():
            try:
                wg = json.loads(wg_path.read_text())
                recent_tools = wg.get("recent_tool_calls", [])
                result["total_calls"] = max(result["total_calls"], len(recent_tools))
                for w in recommended_weapons:
                    w_name = w if isinstance(w, str) else w.get("name", str(w))
                    if any(w_name in tc for tc in recent_tools):
                        if w_name not in result["called"]:
                            result["called"].append(w_name)
                            result["weapon_calls"] += 1
                            if w_name in result["missed"]:
                                result["missed"].remove(w_name)
            except:
                pass
        
        # 判定合规: 至少调用了2个武器
        result["compliant"] = result["weapon_calls"] >= 2
        return result
    
    def generate_violation_report(self, task: str, check_result: dict) -> str:
        """生成违规报告"""
        report = []
        report.append(f"⚠️ [武器调用违规检测] 任务: {task[:50]}...")
        report.append(f"  调用状态: {'✅ 合规' if check_result['compliant'] else '❌ 违规'}")
        report.append(f"  总tool_call: {check_result['total_calls']}次")
        report.append(f"  武器调用: {check_result['weapon_calls']}次")
        if check_result["called"]:
            report.append(f"  已调用武器: {', '.join(check_result['called'])}")
        if check_result["missed"]:
            report.append(f"  未调用武器: {', '.join(check_result['missed'])}")
        report.append(f"  要求: 至少调用2个武器, 不允许不调用直接回答")
        return "\n".join(report)


# ════════════════════════════════════════════════════════════
# 底层注入 — 修改gear_enforcer使其在每轮循环中调用调度器
# ════════════════════════════════════════════════════════════

class EngineCore:
    """引擎核心 — 在齿轮每1分钟循环中自动运行"""
    
    def __init__(self):
        self.arsenal = ArsenalRegistry()
        self.scheduler = SmartScheduler()
        self.last_report = 0
    
    def tick(self):
        """每轮tick — 自动检查+调度"""
        now = time.time()
        report = []
        
        # 1. 武器库自检
        summary = self.arsenal.summary()
        report.append(f"武器库: {summary['total']}件可用")
        
        # 2. 检查wake_guide中的当前任务
        wg_path = HERMES / "reports" / "wake_guide.json"
        if wg_path.exists():
            try:
                with open(wg_path) as f:
                    wg = json.load(f)
                interrupted = wg.get("interrupted_task", "")
                if interrupted:
                    # 分析是否需要分段
                    task_str = str(interrupted)
                    if self.scheduler.should_segment(task_str):
                        segs = self.scheduler.segment_task(task_str)
                        report.append(f"当前任务需拆{len(segs)}段执行")
            except:
                pass
        
        # 3. 每小时输出一次武器库总览
        if now - self.last_report > 3600:
            report.append(f"可用: {summary}")
            self.last_report = now
        
        return report


# ════════════════════════════════════════════════════════════
# 独立运行入口
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    
    if cmd == "scan":
        registry = ArsenalRegistry()
        summary = registry.summary()
        print("=" * 60)
        print("Hermes 武器库全量扫描")
        print("=" * 60)
        print(f"  scripts:  {summary['scripts']}个")
        print(f"  skills:   {summary['skills']}个")
        print(f"  员工Agent: {summary['employees']}人")
        print(f"  专家Agent: {summary['experts']}人")
        print(f"  tools:    {summary['tools']}个")
        print(f"  modules:  {summary['modules']}个")
        print(f"  ─────────────────────")
        print(f"  总计: {summary['total']}件武器")
        print()
        
        # 按类型分类
        types = {}
        for s in registry.weapons["scripts"]:
            t = s["type"]
            if t not in types: types[t] = 0
            types[t] += 1
        print("  武器类型分布:")
        for t, c in sorted(types.items(), key=lambda x: -x[1]):
            print(f"    {t}: {c}个")
    
    elif cmd == "analyze":
        task = sys.argv[2] if len(sys.argv) > 2 else "修复推送系统"
        scheduler = SmartScheduler()
        analysis = scheduler.analyze_task(task)
        print(f"任务: {task}")
        print(f"类型: {analysis['task_type']}")
        print(f"复杂度: {analysis['complexity']}")
        print(f"建议分段: {analysis['suggested_segments']}段")
        print(f"需要scripts: {analysis['needs_scripts']}")
        print(f"需要skills: {analysis['needs_skills']}")
        print(f"武器库规模: {analysis['available_weapons']['total']}件")
        
        if scheduler.should_segment(task):
            segs = scheduler.segment_task(task)
            print(f"\n自动拆分为{len(segs)}段:")
            for s in segs:
                dep = f"(依赖段{s['depends_on']})" if s['depends_on'] else "(独立)"
                print(f"  段{s['id']}: {s['description'][:80]} {dep}")
    
    elif cmd == "tick":
        engine = EngineCore()
        reports = engine.tick()
        for r in reports:
            print(f"  {r}")
    
    elif cmd == "weapons":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        scheduler = SmartScheduler()
        if task:
            weapons = scheduler.get_relevant_weapons(task)
            print(f"与「{task}」相关的武器:")
            for w in weapons[:10]:
                print(f"  [{w['type']}] {w['name']} ({w['path']})")
        else:
            registry = ArsenalRegistry()
            summary = registry.summary()
            print(f"武器库: {summary['total']}件")
    
    elif cmd == "mandate":
        task = sys.argv[2] if len(sys.argv) > 2 else "通用任务"
        protocol = ForcedWeaponProtocol()
        mandate = protocol.generate_mandate(task)
        print(mandate)
    
    elif cmd == "validate":
        task = sys.argv[2] if len(sys.argv) > 2 else "通用任务"
        protocol = ForcedWeaponProtocol(task)
        validator = WeaponCallValidator()
        # 从mandate中提取推荐的武器名
        mandate = protocol.generate_mandate(task)
        import re
        rec_weapons = re.findall(r'scripts/(\w+)\.py', mandate)
        rec_skills = re.findall(r'skill: ([\w-]+)', mandate)
        all_recs = rec_weapons + rec_skills
        result = validator.check_recent_calls(all_recs)
        print(validator.generate_violation_report(task, result))
