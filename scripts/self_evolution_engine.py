#!/usr/bin/env python3
"""
Hermes 自进化引擎 (Self-Evolution Engine)
===========================================
基于 GenericAgent 理念 + SuperMemory 架构 + 自主skill生成

核心能力:
1. 从任务执行历史中自动提取可复用的skill
2. 记忆分层管理 (短期→工作→长期)
3. 模式识别: 发现重复任务模式并固化
4. 技能树生长: 从种子代码长成私有能力树
5. 主动优化建议: 基于使用模式推荐优化

架构:
```
任务执行 → 执行记录 → 模式检测 → skill提取 → skill注册 → 下次复用
                ↓
           记忆分层 (短期→工作→长期)
                ↓
           进化分析 → 优化建议 → 系统更新
```
"""

import os, sys, json, sqlite3, time, hashlib, logging, re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict, Counter

HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
SKILLS_DIR = HERMES / "skills"
MEMORY_DIR = HERMES / "memory"
LOG_DIR = HERMES / "logs"
AUTO_ENGINE = HERMES / "auto_engine"
EVOLUTION_DB = AUTO_ENGINE / "evolution.db"
AUTO_ENGINE.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EVOLVE] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"evolution_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("evolution")

C = {"OK": "\033[92m", "ERR": "\033[91m", "WRN": "\033[93m", "BOLD": "\033[1m", "END": "\033[0m"}

def p(msg, level="INFO"):
    prefix = {"INFO": f"{C['BOLD']}[EVOLVE]{C['END']}", "OK": f"{C['OK']}[✓]{C['END']}",
              "ERR": f"{C['ERR']}[✗]{C['END']}", "WRN": f"{C['WRN']}[!]{C['END']}"}
    print(f"{prefix.get(level, '[--]')} {datetime.now().strftime('%H:%M:%S')} {msg}")


def init_db():
    """初始化进化数据库"""
    conn = sqlite3.connect(str(EVOLUTION_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_hash TEXT,
            task_description TEXT,
            tools_used TEXT,
            steps_count INTEGER,
            duration_seconds REAL,
            success INTEGER,
            skills_created TEXT,
            executed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_hash TEXT UNIQUE,
            task_pattern TEXT,
            frequency INTEGER DEFAULT 1,
            first_seen TEXT,
            last_seen TEXT,
            suggested_name TEXT,
            status TEXT DEFAULT 'candidate'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evolution_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT,
            description TEXT,
            skill_name TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    return conn


def analyze_skill_usage():
    """分析现有技能的访问模式"""
    p("分析技能使用模式...")
    
    # 从skills目录统计
    skill_count = 0
    skill_with_code = 0
    for d in SKILLS_DIR.iterdir():
        if d.is_dir():
            skill_count += 1
            has_code = False
            for f in d.rglob("*.py"):
                has_code = True
                break
            if has_code:
                skill_with_code += 1
    
    p(f"总skills: {skill_count}, 含代码: {skill_with_code}", "OK")
    
    # 检测最近修改的skill
    recent = []
    for d in sorted(SKILLS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
        if d.is_dir():
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
            recent.append((d.name, mtime))
            if mtime > datetime.now() - timedelta(days=7):
                p(f"  最近更新: {d.name} ({mtime.strftime('%m-%d %H:%M')})")
    
    return {"total": skill_count, "with_code": skill_with_code, "recent": recent}


def mine_patterns_from_state():
    """从state.db会话历史中挖掘重复模式"""
    p("挖掘任务执行模式...")
    
    try:
        state_db = HERMES / "state.db"
        if not state_db.exists():
            p("state.db不存在", "WRN")
            return []
        
        conn = sqlite3.connect(str(state_db))
        
        # 分析最近会话的主题分布
        sessions = conn.execute("""
            SELECT id, title, source, started_at 
            FROM sessions 
            WHERE source = 'cli'
            ORDER BY started_at DESC 
            LIMIT 50
        """).fetchall()
        
        # 提取关键词模式
        patterns = Counter()
        for s in sessions:
            title = s[1] or ''
            # 提取常见的任务动词
            verbs = ['采集', '清洗', '推送', '修复', '更新', '检查', '创建', '分析', 
                     '调试', '安装', '配置', '部署', '优化', '搜索', '查询']
            for v in verbs:
                if v in title:
                    patterns[v] += 1
        
        top_patterns = patterns.most_common(5)
        if top_patterns:
            p("高频任务模式:")
            for pattern, count in top_patterns:
                p(f"  {pattern}: {count}次")
        
        conn.close()
        return top_patterns
    
    except Exception as e:
        p(f"模式挖掘失败: {e}", "WRN")
        return []


def scan_for_skill_opportunities():
    """扫描系统,发现可以固化为skill的机会"""
    p("扫描skill生成机会...")
    
    opportunities = []
    
    # 检查是否有高频重复的手动操作
    # 从scripts目录看哪些是独立工具但没有对应skill
    script_files = list(SCRIPTS.glob("*.py"))
    existing_skills = {d.name for d in SKILLS_DIR.iterdir() if d.is_dir()}
    
    for script in script_files:
        name = script.stem
        # 跳过内部模块和测试文件
        if name.startswith('_') or name.startswith('test_') or name.startswith('debug_'):
            continue
        if name.startswith('check_'):
            continue
        
        # 如果有脚本但无对应skill,标记为机会
        skill_name = name.replace('_', '-')
        if skill_name not in existing_skills and name not in existing_skills:
            # 进一步筛选:只建议有完整功能的脚本
            content = script.read_text()
            if 'def main()' in content or 'if __name__' in content:
                opportunities.append({
                    'script': name,
                    'path': str(script),
                    'lines': len(content.split('\n')),
                    'has_main': 'def main()' in content
                })
    
    if opportunities:
        p(f"发现 {len(opportunities)} 个可生成skill的脚本机会:")
        for opp in sorted(opportunities, key=lambda x: -x['lines'])[:10]:
            p(f"  {opp['script']}.py ({opp['lines']}行) → skill/{opp['script']}")
    
    return opportunities


def auto_generate_skill(name: str, script_path: str, description: str = None):
    """从已有脚本自动生成skill"""
    skill_dir = SKILLS_DIR / name
    if skill_dir.exists():
        p(f"skill已存在: {name}", "WRN")
        return False
    
    skill_dir.mkdir(parents=True)
    
    # 读取原始脚本
    source = Path(script_path).read_text()
    
    # 生成skill元数据
    lines = source.split('\n')
    docstring = ""
    in_doc = False
    for line in lines[:10]:
        if '"""' in line or "'''" in line:
            in_doc = not in_doc
            continue
        if in_doc:
            docstring += line.strip() + " "
    
    desc = description or docstring[:100] or f"从 {name}.py 自动生成的skill"
    
    # 写SKILL.md
    skill_md = f"""---
name: {name}
description: {desc}
category: auto-generated
tags: [auto-generated, {name}]
---

# {name}

由Hermes自进化引擎于 {datetime.now().strftime('%Y-%m-%d %H:%M')} 自动生成。

## 源文件
`{script_path}`

## 使用方法
加载此skill后可直接使用其功能。

## 自动生成说明
此skill是从系统中已有的脚本自动提取而来。
"""
    (skill_dir / "SKILL.md").write_text(skill_md)
    
    # 复制脚本
    dest = skill_dir / f"{name}.py"
    dest.write_text(source)
    
    # 记录进化历史
    conn = init_db()
    conn.execute("""
        INSERT INTO evolution_history (action_type, description, skill_name, created_at)
        VALUES (?, ?, ?, datetime('now'))
    """, ('skill_auto_generated', f'从 {script_path} 自动生成skill', name))
    conn.commit()
    conn.close()
    
    p(f"✅ 自动生成skill: {name}", "OK")
    return True


def run_evolution_cycle():
    """执行完整的自进化循环"""
    p("=" * 60)
    p("  🔄 Hermes 自进化引擎 — 完整循环")
    p("=" * 60)
    
    results = {}
    
    # Step 1: 初始化DB
    conn = init_db()
    
    # Step 2: 分析技能使用
    results['usage'] = analyze_skill_usage()
    
    # Step 3: 挖掘任务模式
    results['patterns'] = mine_patterns_from_state()
    
    # Step 4: 扫描skill机会
    results['opportunities'] = scan_for_skill_opportunities()
    
    # Step 5: 自动生成skill (只对高质量且未覆盖的)
    auto_generated = 0
    for opp in results['opportunities'][:5]:  # 每次最多生成5个
        name = opp['script']
        # 检查是否已有同名skill
        skill_name = name.replace('_', '-')
        if not (SKILLS_DIR / skill_name).exists() and not (SKILLS_DIR / name).exists():
            try:
                auto_generate_skill(skill_name if '_' in name else name, opp['path'])
                auto_generated += 1
            except Exception as e:
                p(f"  生成失败 {name}: {e}", "ERR")
    
    results['auto_generated'] = auto_generated
    
    # Step 6: 生成优化建议
    suggestions = []
    
    total_skills = results['usage'].get('total', 0)
    code_skills = results['usage'].get('with_code', 0)
    
    if code_skills < total_skills * 0.3:
        suggestions.append("含代码的skill比例偏低,建议为纯文档skill补充实现")
    if results['opportunities']:
        suggestions.append(f"有 {len(results['opportunities'])} 个脚本可生成skill: {'/'.join(o['script'] for o in results['opportunities'][:5])}")
    
    results['suggestions'] = suggestions
    
    # 汇总
    p("\n" + "=" * 60)
    p("  📊 进化循环完成")
    p("=" * 60)
    p(f"  skills: {results['usage'].get('total', 0)} (+{auto_generated} 新)")
    p(f"  可生成: {len(results.get('opportunities', []))} 个机会")
    for s in suggestions:
        p(f"  建议: {s}")
    p("=" * 60)
    
    conn.close()
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 自进化引擎")
    parser.add_argument("--full", action="store_true", help="完整进化循环")
    parser.add_argument("--analyze", action="store_true", help="仅分析模式")
    parser.add_argument("--generate", type=str, nargs=2, metavar=("NAME", "SCRIPT"), help="从脚本生成skill")
    
    args = parser.parse_args()
    
    if args.generate:
        name, script = args.generate
        auto_generate_skill(name, script)
    elif args.analyze:
        analyze_skill_usage()
        mine_patterns_from_state()
        scan_for_skill_opportunities()
    else:
        run_evolution_cycle()


if __name__ == "__main__":
    main()
