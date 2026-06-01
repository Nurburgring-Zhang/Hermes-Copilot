#!/usr/bin/env python3
"""
🔧 退化自动修复规则引擎 (Auto Healer) v1.0
============================================
功能:
  1. 读取 consistency_guard 的异常日志 (consistency_anomalies.log)
  2. 对重复出现的异常模式匹配预定义修复方案
  3. 执行修复并记录修复结果
  4. 连续3次修复失败推送到微信 status_reporter

可修复模式:
  Pattern 1: "context_index sections为空" → python3 context_index_system.py auto
  Pattern 2: "文件丢失" → 从 /mnt/d/Hermes/备份/ 恢复
  Pattern 3: "cron丢失" → 从上次配置重挂

接入: gear_enforcer.py 每轮循环调用 / crontab 每5分钟自动执行

格林主人最高指令(2026-06-01固化):
  所有可自动修复的退化必须自动修复，不允许人工介入。
  连续3次修复失败才推送到微信通知。
"""

import json, os, sys, re, subprocess, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

HERMES = Path(os.path.expanduser("~/.hermes"))
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)

# 日志文件
ANOMALY_LOG = HERMES / "reports" / "consistency_anomalies.log"
HEALER_LOG = HERMES / "reports" / "auto_healer.log"
HEALER_STATE = HERMES / "reports" / "auto_healer_state.json"
BACKUP_DIR = Path("/mnt/d/Hermes/备份/")


class AutoHealer:
    """退化自动修复规则引擎"""

    def __init__(self):
        self.state = self._load_state()
        self.fix_history = []

    def _load_state(self) -> dict:
        """加载修复状态"""
        if HEALER_STATE.exists():
            try:
                return json.loads(HEALER_STATE.read_text())
            except:
                pass
        return {
            "total_fixes": 0,
            "successful_fixes": 0,
            "failed_fixes": 0,
            "consecutive_failures": {},
            "last_run": None,
            "pattern_stats": {},
        }

    def _save_state(self):
        """保存修复状态"""
        self.state["last_run"] = now().isoformat()
        HEALER_STATE.parent.mkdir(parents=True, exist_ok=True)
        HEALER_STATE.write_text(json.dumps(self.state, indent=2, ensure_ascii=False))

    def _log(self, entry: str, level: str = "INFO"):
        """写入修复日志"""
        ts = now().isoformat()
        line = f"[{ts}] [{level}] {entry}"
        HEALER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(HEALER_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)

    def read_anomalies(self) -> List[Dict]:
        """读取一致性守卫的异常日志，返回按模式聚合的结果"""
        if not ANOMALY_LOG.exists():
            self._log("异常日志不存在，跳过", "DEBUG")
            return []

        try:
            content = ANOMALY_LOG.read_text(encoding="utf-8")
        except Exception as e:
            self._log(f"读取异常日志失败: {e}", "ERROR")
            return []

        # 解析每行: [timestamp] [CONSISTENCY] message
        patterns = []
        anomaly_pattern = re.compile(r'\[([^\]]+)\]\s*\[?CONSISTENCY\]?\s*(.*)')

        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            m = anomaly_pattern.search(line)
            if m:
                patterns.append({
                    "timestamp": m.group(1),
                    "message": m.group(2).strip(),
                })
            elif "CONSISTENCY" in line or "异常" in line or "❌" in line:
                # Fallback: extract timestamp and message
                parts = line.split("]", 2)
                if len(parts) >= 2:
                    ts = parts[0].lstrip("[")
                    msg = parts[-1].strip()
                    patterns.append({"timestamp": ts, "message": msg})

        # 按模式聚合: 统计每种异常出现的次数
        aggregated = {}
        for p in patterns:
            msg = p["message"]
            # 归类到预定义模式
            matched_pattern = self._classify(msg)
            if matched_pattern:
                key = matched_pattern["name"]
                if key not in aggregated:
                    aggregated[key] = {
                        "name": key,
                        "count": 0,
                        "examples": [],
                        "last_seen": None,
                        "fix_action": matched_pattern["fix_action"],
                        "fix_args": matched_pattern.get("fix_args", []),
                    }
                aggregated[key]["count"] += 1
                aggregated[key]["examples"].append(msg)
                if len(aggregated[key]["examples"]) > 3:
                    aggregated[key]["examples"] = aggregated[key]["examples"][-3:]
                aggregated[key]["last_seen"] = p["timestamp"]

        return list(aggregated.values())

    def _classify(self, message: str) -> Optional[Dict]:
        """将异常消息分类到预定义修复模式"""
        msg_lower = message.lower()

        # Pattern 1: context_index sections为空
        if "context_index" in msg_lower and ("空" in msg_lower or "sections为空" in msg_lower):
            return {
                "name": "context_index_empty",
                "description": "context_index sections为空",
                "fix_action": "rebuild_context_index",
                "fix_args": [],
            }

        # Pattern 1b: context_index.json 损坏
        if "context_index.json" in msg_lower and "损坏" in msg_lower:
            return {
                "name": "context_index_corrupt",
                "description": "context_index.json损坏",
                "fix_action": "rebuild_context_index",
                "fix_args": [],
            }

        # Pattern 2: 文件丢失
        if "文件丢失" in msg_lower or "file missing" in msg_lower or "文件缺失" in msg_lower:
            # 提取文件名
            fname = None
            fname_match = re.search(r'([\w/]+\.\w+)', message)
            if fname_match:
                fname = fname_match.group(1)
            return {
                "name": "file_missing",
                "description": f"文件丢失: {fname or '未知'}",
                "fix_action": "restore_from_backup",
                "fix_args": [fname] if fname else [],
            }

        # Pattern 2b: 文件异常小
        if "文件异常小" in msg_lower or "异常小" in msg_lower:
            fname = None
            fname_match = re.search(r'([\w/]+\.\w+)', message)
            if fname_match:
                fname = fname_match.group(1)
            return {
                "name": "file_truncated",
                "description": f"文件异常小: {fname or '未知'}",
                "fix_action": "restore_from_backup",
                "fix_args": [fname] if fname else [],
            }

        # Pattern 3: cron丢失
        if "cron丢失" in msg_lower or "cron" in msg_lower and ("丢失" in msg_lower or "missing" in msg_lower):
            cron_name = None
            cron_match = re.search(r'(?:cron丢失|cron missing)\s*[:：]?\s*([\w_]+)', message)
            if cron_match:
                cron_name = cron_match.group(1)
            return {
                "name": "cron_missing",
                "description": f"cron丢失: {cron_name or '未知'}",
                "fix_action": "restore_crons",
                "fix_args": [cron_name] if cron_name else [],
            }

        # Pattern 3b: cron异常少
        if "cron异常少" in msg_lower:
            return {
                "name": "cron_too_few",
                "description": "cron条目异常少",
                "fix_action": "restore_crons",
                "fix_args": [],
            }

        # Pattern: 齿轮不健康
        if "齿轮不健康" in msg_lower or "gear" in msg_lower and ("unhealthy" in msg_lower or "不健康" in msg_lower):
            return {
                "name": "gear_unhealthy",
                "description": "齿轮不健康",
                "fix_action": "restart_gear",
                "fix_args": [],
            }

        return None

    def fix(self, pattern: Dict) -> Dict:
        """执行修复操作"""
        action = pattern["fix_action"]
        args = pattern.get("fix_args", [])
        name = pattern["name"]

        self._log(f"🔧 开始修复: {name} ({pattern['description']})", "INFO")

        result = {"ok": False, "action": action, "name": name, "detail": ""}

        if action == "rebuild_context_index":
            result = self._fix_rebuild_context_index()
        elif action == "restore_from_backup":
            result = self._fix_restore_from_backup(args)
        elif action == "restore_crons":
            result = self._fix_restore_crons(args)
        elif action == "restart_gear":
            result = self._fix_restart_gear()
        else:
            result["detail"] = f"未知修复动作: {action}"
            self._log(f"  ❌ {result['detail']}", "ERROR")

        # 记录修复结果
        if result["ok"]:
            self.state["successful_fixes"] += 1
            self.state["consecutive_failures"][name] = 0
            self._log(f"  ✅ 修复成功: {result['detail']}", "INFO")
        else:
            self.state["failed_fixes"] += 1
            self.state["consecutive_failures"][name] = self.state["consecutive_failures"].get(name, 0) + 1
            n_fails = self.state["consecutive_failures"][name]
            self._log(f"  ❌ 修复失败(第{n_fails}次): {result['detail']}", "ERROR")

            # 连续3次失败 → 推送微信
            if n_fails >= 3:
                self._notify_wechat(name, pattern["description"], n_fails, result["detail"])

        # 更新统计
        self.state["total_fixes"] += 1
        pattern_name = name
        if pattern_name not in self.state["pattern_stats"]:
            self.state["pattern_stats"][pattern_name] = {"attempts": 0, "successes": 0}
        self.state["pattern_stats"][pattern_name]["attempts"] += 1
        if result["ok"]:
            self.state["pattern_stats"][pattern_name]["successes"] += 1

        self.fix_history.append({
            "ts": now().isoformat(),
            "name": name,
            "action": action,
            "ok": result["ok"],
            "detail": result["detail"],
        })
        # 保持历史不超过100条
        if len(self.fix_history) > 100:
            self.fix_history = self.fix_history[-100:]

        self._save_state()
        return result

    def _fix_rebuild_context_index(self) -> Dict:
        """修复: 重建context_index"""
        self._log("  执行: python3 scripts/context_index_system.py auto", "INFO")
        try:
            r = subprocess.run(
                [sys.executable, str(HERMES / "scripts" / "context_index_system.py"), "auto"],
                capture_output=True, timeout=60, text=True, cwd=str(HERMES),
            )
            if r.returncode == 0:
                return {"ok": True, "detail": "context_index重建成功"}
            else:
                return {"ok": False, "detail": f"重建失败: {r.stderr[:200]}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "重建超时(60s)"}
        except Exception as e:
            return {"ok": False, "detail": f"重建异常: {str(e)[:100]}"}

    def _fix_restore_from_backup(self, args: List[str]) -> Dict:
        """修复: 从备份恢复文件"""
        if not args or not args[0]:
            return {"ok": False, "detail": "未指定要恢复的文件名"}

        fname = args[0]
        self._log(f"  尝试从备份恢复: {fname}", "INFO")

        if not BACKUP_DIR.exists():
            return {"ok": False, "detail": f"备份目录不存在: {BACKUP_DIR}"}

        # 在备份目录中搜索匹配的文件
        candidates = list(BACKUP_DIR.rglob(fname))
        if not candidates:
            # 尝试搜索文件名部分
            basename = Path(fname).name
            candidates = list(BACKUP_DIR.rglob(f"*{basename}*"))

        if not candidates:
            return {"ok": False, "detail": f"备份中未找到: {fname}"}

        # 按修改时间排序，取最新的
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        latest_backup = candidates[0]

        # 目标路径
        target = HERMES / fname
        self._log(f"  备份文件: {latest_backup} → 目标: {target}", "INFO")

        try:
            # 先备份当前文件(如果存在)
            if target.exists():
                backup_name = f"{target}.bak.{int(time.time())}"
                target.rename(backup_name)
                self._log(f"  当前文件已备份到: {backup_name}", "INFO")

            # 确保目标目录存在
            target.parent.mkdir(parents=True, exist_ok=True)

            # 复制备份
            import shutil
            shutil.copy2(latest_backup, target)
            return {"ok": True, "detail": f"已恢复: {latest_backup.name} → {fname} ({latest_backup.stat().st_size}B)"}

        except Exception as e:
            return {"ok": False, "detail": f"恢复失败: {str(e)[:100]}"}

    def _fix_restore_crons(self, args: List[str]) -> Dict:
        """修复: 从上次保存的crontab配置重挂"""
        self._log("  执行: 从备份恢复crontab配置", "INFO")

        # 查找备份的crontab
        cron_backup = HERMES / "reports" / "cron_backup.txt"
        alt_backup = HERMES / "backups" / "crontab_backup.txt"

        backup_source = None
        if cron_backup.exists():
            backup_source = cron_backup
        elif alt_backup.exists():
            backup_source = alt_backup

        if not backup_source:
            return {"ok": False, "detail": "未找到crontab备份文件"}

        try:
            # 检查备份内容是否有效
            content = backup_source.read_text()
            if len(content.strip().split("\n")) < 5:
                return {"ok": False, "detail": f"备份内容异常(仅{len(content.strip().split(chr(10)))}行)"}

            # 保存当前crontab为额外备份
            try:
                current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
                if current.returncode == 0 and current.stdout.strip():
                    extra_backup = HERMES / "reports" / f"cron_backup_before_restore_{int(time.time())}.txt"
                    extra_backup.write_text(current.stdout)
            except:
                pass

            # 恢复备份
            r = subprocess.run(["crontab", str(backup_source)], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return {"ok": True, "detail": f"crontab已恢复(来自{backup_source.name})"}
            else:
                return {"ok": False, "detail": f"crontab恢复失败: {r.stderr[:200]}"}

        except Exception as e:
            return {"ok": False, "detail": f"crontab恢复异常: {str(e)[:100]}"}

    def _fix_restart_gear(self) -> Dict:
        """修复: 重启齿轮(重新运行gear_enforcer)"""
        self._log("  执行: 重新运行gear_enforcer", "INFO")
        try:
            r = subprocess.run(
                [sys.executable, str(HERMES / "scripts" / "gear_enforcer.py")],
                capture_output=True, timeout=120, text=True, cwd=str(HERMES),
            )
            if r.returncode == 0:
                return {"ok": True, "detail": "gear_enforcer重新运行成功"}
            else:
                return {"ok": False, "detail": f"gear_enforcer运行异常: {r.stderr[:200]}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "gear_enforcer运行超时"}
        except Exception as e:
            return {"ok": False, "detail": f"gear_enforcer异常: {str(e)[:100]}"}

    def _notify_wechat(self, name: str, description: str, n_fails: int, detail: str):
        """推送微信通知(连续3次修复失败)"""
        msg = (
            f"🔴 [AutoHealer] 连续{n_fails}次修复失败!\n"
            f"模式: {name}\n"
            f"描述: {description}\n"
            f"最后失败详情: {detail}\n"
            f"时间: {now().isoformat()}\n"
            f"⚠️ 需要格林主人介入"
        )
        self._log(f"  📱 推送微信通知: {msg[:100]}...", "WARN")

        # 尝试调用status_reporter推送
        try:
            reporter = HERMES / "scripts" / "status_reporter.py"
            if reporter.exists():
                r = subprocess.run(
                    [sys.executable, str(reporter), "push", "--title", "AutoHealer连续修复失败", "--content", msg],
                    capture_output=True, timeout=30, text=True, cwd=str(HERMES),
                )
                if r.returncode == 0:
                    self._log("  ✅ 微信推送成功", "INFO")
                else:
                    self._log(f"  ⚠️ 微信推送失败: {r.stderr[:100]}", "WARN")
            else:
                # 写入推送队列
                push_queue = HERMES / "reports" / "push_queue.json"
                queue = []
                if push_queue.exists():
                    try:
                        queue = json.loads(push_queue.read_text())
                    except:
                        queue = []
                queue.append({
                    "type": "urgent",
                    "title": "AutoHealer连续修复失败",
                    "content": msg,
                    "ts": now().isoformat(),
                })
                push_queue.write_text(json.dumps(queue, indent=2, ensure_ascii=False))
                self._log("  ⚠️ status_reporter不存在，消息已写入推送队列", "WARN")
        except Exception as e:
            self._log(f"  ❌ 微信推送异常: {str(e)[:100]}", "ERROR")

    def run(self) -> Dict:
        """主入口: 读取异常 → 执行修复 → 返回摘要"""
        self._log("=" * 60)
        self._log("🔧 AutoHealer 启动")
        self._log("=" * 60)

        # 步骤1: 读取异常日志
        patterns = self.read_anomalies()
        if not patterns:
            self._log("✅ 无待修复异常")
            return {"status": "ok", "fixed": 0, "total": 0, "details": "无异常"}

        self._log(f"📊 发现 {len(patterns)} 个异常模式:")
        for p in patterns:
            self._log(f"  - {p['name']}: {p['count']}次 | 最近: {p['last_seen']}")

        # 步骤2: 执行修复
        fix_results = []
        for pattern in patterns:
            # 跳过已经是连续失败>=3次的模式（已通知，等待人工）
            if self.state["consecutive_failures"].get(pattern["name"], 0) >= 3:
                self._log(f"  ⏭️ 跳过{pattern['name']}: 已连续失败3次，等待人工介入", "WARN")
                continue
            result = self.fix(pattern)
            fix_results.append(result)

        # 步骤3: 写入修复历史到文件
        history_file = HERMES / "reports" / "auto_healer_history.json"
        history = []
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text())
            except:
                history = []
        history.extend(self.fix_history)
        if len(history) > 500:
            history = history[-500:]
        history_file.write_text(json.dumps(history, indent=2, ensure_ascii=False))

        # 步骤4: 保存状态并返回
        self._save_state()

        success_count = sum(1 for r in fix_results if r.get("ok"))
        summary = {
            "status": "ok" if success_count == len(fix_results) else "partial",
            "total_patterns": len(patterns),
            "attempted": len(fix_results),
            "successful": success_count,
            "failed": len(fix_results) - success_count,
            "results": fix_results,
        }
        self._log(f"📋 摘要: 尝试{len(fix_results)}个, 成功{success_count}个, 失败{len(fix_results)-success_count}个")
        return summary


# ===== 独立运行入口 =====
if __name__ == "__main__":
    healer = AutoHealer()
    
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(json.dumps(healer.state, indent=2, ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "history":
        history_file = HERMES / "reports" / "auto_healer_history.json"
        if history_file.exists():
            print(history_file.read_text())
        else:
            print("[]")
    elif len(sys.argv) > 1 and sys.argv[1] == "force":
        # 强制修复某个模式: auto_healer.py force <pattern_name>
        if len(sys.argv) > 2:
            pattern_name = sys.argv[2]
            # 创建一个虚拟pattern
            patterns = healer.read_anomalies()
            target = [p for p in patterns if p["name"] == pattern_name]
            if target:
                result = healer.fix(target[0])
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                # 尝试直接从名称匹配
                action_map = {
                    "context_index_empty": "rebuild_context_index",
                    "context_index_corrupt": "rebuild_context_index",
                    "file_missing": "restore_from_backup",
                    "file_truncated": "restore_from_backup",
                    "cron_missing": "restore_crons",
                    "cron_too_few": "restore_crons",
                    "gear_unhealthy": "restart_gear",
                }
                action = action_map.get(pattern_name)
                if action:
                    result = healer.fix({"name": pattern_name, "description": f"强制修复: {pattern_name}", "fix_action": action, "fix_args": []})
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    print(json.dumps({"ok": False, "error": f"未知模式: {pattern_name}"}, ensure_ascii=False))
        else:
            print("用法: auto_healer.py force <pattern_name>")
    else:
        # 默认: 运行一次完整修复
        summary = healer.run()
        print(json.dumps(summary, indent=2, ensure_ascii=False))
