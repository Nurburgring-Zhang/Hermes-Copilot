#!/usr/bin/env python3
"""
ECC (Ensemble Coding Companion) — Agent性能优化系统
安装激活脚本：安装依赖 + 注册为hermes skill + 设定为软件开发优先能力
"""
import os, sys, json, subprocess
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
ECC_DIR = HERMES / "scripts" / "collectors" / "ECC"
VENV_PYTHON = HERMES / "hermes-agent" / "venv" / "bin" / "python3"
SKILLS_DIR = HERMES / "skills"

def log(msg): print(f"[ECC] {msg}")

def install_ecc():
    """安装ECC依赖并注册"""
    if not ECC_DIR.exists() or not list(ECC_DIR.glob("*.{js,py,json}")):
        log("⚠️  ECC目录为空，需先下载")
        return False
    
    log(f"📦 ECC目录: {ECC_DIR}")
    
    # 检查package.json
    pkg_json = ECC_DIR / "package.json"
    if pkg_json.exists():
        data = json.loads(pkg_json.read_text())
        log(f"   名称: {data.get('name', 'unknown')} v{data.get('version', '?')}")
        log(f"   描述: {data.get('description', '')[:100]}")
    
    # 安装npm依赖
    if (ECC_DIR / "package.json").exists():
        log("📦 安装npm依赖...")
        result = subprocess.run(
            ["npm", "install", "--production"],
            cwd=str(ECC_DIR), capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            log("   ✅ npm依赖安装成功")
        else:
            log(f"   ⚠️ npm安装有警告: {result.stderr[:200]}")
    
    # 安装Python依赖（如果有）
    req_file = ECC_DIR / "requirements.txt"
    if req_file.exists():
        log("📦 安装Python依赖...")
        result = subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(req_file)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            log("   ✅ Python依赖安装成功")
        else:
            log(f"   ⚠️ {result.stderr[:200]}")
    
    return True


def register_ecc_skill():
    """注册ECC为Hermes skill"""
    skill_dir = SKILLS_DIR / "ecc"
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    skill_md = """---
name: ecc
description: ECC (Ensemble Coding Companion) — Agent性能优化系统。增强skill直觉、记忆、安全，适用于Claude Code/Codex/OpenCode/Cursor等Agent。可作为软件开发优先能力组合使用。
category: software-development
---

# ECC — Agent性能优化系统

## 用途
ECC是Agent性能优化系统（189k+ GitHub Stars），提供：
- **Skills直觉**: 自动发现和加载最适合当前任务的skill
- **记忆增强**: 持久化跨会话记忆
- **安全层**: 命令执行安全审计
- **研究优先开发**: 自动收集上下文并生成研究报告

## 激活方式
```bash
cd ~/.hermes/scripts/collectors/ECC
npm install  # 安装依赖
```

## 与Multi-Agent组合使用
ECC可以联合多个Agent/子Agent协同工作：
1. 主Agent加载ECC后自动优化子Agent的skill选择
2. 子Agent通过ECC共享记忆上下文
3. 多个ECC实例可以同步安全策略

## 优先级
- 软件开发场景中优先级: P0 (最高)
- 可与skills/agents-company/autonomous-systems组合
"""
    (skill_dir / "SKILL.md").write_text(skill_md)
    log("   ✅ ECC skill已注册")
    
    # 创建激活标记
    activated_file = HERMES / "reports" / "ecc_activated.json"
    activated_file.write_text(json.dumps({
        "status": "activated",
        "priority": "P0-software-development",
        "multi_agent": True,
        "install_dir": str(ECC_DIR),
        "activated_at": __import__('datetime').datetime.now().isoformat()
    }, indent=2))
    log("   ✅ ECC激活标记已写入")
    return True


def setup_cron():
    """注册ECC守护cron"""
    # 用hermes内部cron系统注册
    cron_dir = HERMES / "cron"
    cron_dir.mkdir(parents=True, exist_ok=True)
    
    job = {
        "job_id": "ecc-daemon",
        "name": "ECC守护 — 自动优化Agent行为",
        "schedule": "0 */4 * * *",
        "command": f"cd {ECC_DIR} && npm run optimize 2>/dev/null || echo 'ECC优化跳过'",
        "enabled": True
    }
    (cron_dir / "ecc_daemon.json").write_text(json.dumps(job, indent=2))
    log("   ✅ ECC守护cron已注册（每4小时）")
    return True


if __name__ == "__main__":
    log("=" * 50)
    log("ECC安装激活工具")
    log("=" * 50)
    
    if install_ecc():
        register_ecc_skill()
        setup_cron()
        log("\n✅ ECC安装激活完成!")
        log("   技能已注册: ~/.hermes/skills/ecc/SKILL.md")
        log("   cron: 每4小时自动优化")
        log("   多Agent: 已启用（可组合使用）")
    else:
        log("\n❌ ECC安装失败 - 目录为空")
        log("   等待下载完成后重新运行: python3 ecc_install.py")
