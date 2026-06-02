#!/home/administrator/.hermes/hermes-agent/venv/bin/python3
"""
Hermes ALL-IN-ONE — 一键全能力激活部署脚本
"""
import subprocess, sys, os, time
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
VPY = str(HERMES / "hermes-agent/venv/bin/python3")
VPIP = str(HERMES / "hermes-agent/venv/bin/pip3")
LOG = HERMES / "logs" / "all_in_one_activate.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip()[-200:], r.stderr.strip()[-200:]
    except Exception as e:
        return False, "", str(e)

log("=" * 60)
log("HERMES ALL-IN-ONE ACTIVATION")
log("=" * 60)

# 1. 安装缺失库
log("\n[1/8] Installing missing Python libs...")
for lib in ["trafilatura", "newspaper3k", "jieba", "snownlp", "aiohttp"]:
    ok, out, err = run(f"{VPIP} install {lib} 2>&1 | tail -3", 180)
    if ok and ("Successfully" in out or "already satisfied" in out):
        log(f"  OK {lib}")
    else:
        log(f"  WARN {lib}: {out[:60]}")

# 2. 安装抖音采器
log("\n[2/8] Installing Douyin/TikTok collectors...")
ok, out, err = run(f"cd {HERMES}/scripts/collectors && git clone https://github.com/JoeanAmier/TikTokDownloader.git tiktok-downloader 2>&1 | head -3", 30)
log(f"  TikTokDownloader: {'OK' if ok else err[:60]}")
if ok:
    run(f"cd {HERMES}/scripts/collectors/tiktok-downloader && {VPIP} install -r requirements.txt 2>&1 | tail -3", 120)

ok, out, err = run(f"cd {HERMES}/scripts/collectors && git clone https://github.com/NanmiCoder/MediaCrawler.git media-crawler 2>&1 | head -3", 30)
log(f"  MediaCrawler: {'OK' if ok else err[:60]}")
if ok:
    run(f"cd {HERMES}/scripts/collectors/media-crawler && {VPIP} install -r requirements.txt 2>&1 | tail -3", 120)

# 3. 修复小红书skill相对引用
log("\n[3/8] Fixing xiaohongshu-skill relative imports...")
skill_dir = HERMES / "scripts/collectors/xiaohongshu-skill/scripts"
for fname in ["search.py", "feed.py", "user.py", "explore.py", "login.py", "comment.py", "interact.py", "strategy.py"]:
    fp = skill_dir / fname
    if fp.exists():
        content = fp.read_text()
        orig = content
        content = content.replace("from .client", "from client")
        content = content.replace("from . import client", "import client")
        content = content.replace("from . import ", "import ")
        content = content.replace("from .. import ", "import ")
        if content != orig:
            fp.write_text(content)
            log(f"  Fixed {fname}")

# 4. 运行capability_activator
log("\n[8/8] Final ability activation...")
ok, out, err = run(f"cd {HERMES} && {VPY} scripts/ability_activator.py 2>&1", 60)
log(f"  {out[:300]}")

log("\n" + "=" * 60)
log("ALL-IN-ONE COMPLETE")
log("=" * 60)
