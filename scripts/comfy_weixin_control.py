#!/usr/bin/env python3
"""
Hermes ComfyUI 微信控制层
Hermes 内部使用 — 解析微信指令 → 调桥接 → 推送结果到微信
"""

import sys, os, json, re
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from comfy_local_bridge_v2 import (
    check_health, list_models, list_available_workflows,
    run_workflow, OUTPUT_DIR, WORKFLOW_DIR
)

def parse_weixin_command(text):
    """
    解析微信发来的自然语言指令，返回结构化参数
    
    支持格式:
    "跑一下猫图 种子12345 30步" → {workflow, prompt, seed=12345, steps=30}
    "用flux画赛博朋克猫 负词:丑陋 步数40" → {workflow:flux, prompt:..., negative_prompt:..., steps:40}
    "sdxl img2img 图片路径 提示词" → ...
    "sd15 风景 种子-1" → ...
    "查看模型" → {action:"models"}
    "状态" → {action:"health"}
    "可用工作流" → {action:"list_workflows"}
    """
    text = text.strip()
    
    # 查看类指令
    if any(kw in text for kw in ["查看模型", "有什么模型", "模型列表"]):
        folder = "checkpoints"
        if "lora" in text: folder = "loras"
        if "vae" in text: folder = "vae"
        if "control" in text: folder = "controlnet"
        return {"action": "models", "folder": folder}
    
    if text in ["状态", "health", "检查", "在线吗", "在吗"]:
        return {"action": "health"}
    
    if any(kw in text for kw in ["工作流", "可用", "workflow"]):
        return {"action": "list_workflows"}
    
    # 生成类指令
    result = {"action": "generate"}
    
    # 识别工作流
    workflow_map = {
        "flux": "flux", "flux-dev": "flux", "flux dev": "flux",
        "sd15": "sd15", "1.5": "sd15",
        "sdxl": "sdxl", "xl": "sdxl",
        "img2img": "sdxl-img2img", "图生图": "sdxl-img2img",
        "inpaint": "sdxl-inpaint", "重绘": "sdxl-inpaint",
        "视频": "video", "video": "video", "wan": "video",
        "超分": "upscale", "放大": "upscale",
        "animate": "animate",
    }
    for kw, wf in workflow_map.items():
        if kw in text:
            result["workflow"] = wf
            break
    if "workflow" not in result:
        result["workflow"] = "flux"  # 默认
    
    # 提取种子
    seed_match = re.search(r'种子(\d+|－\d+)', text)
    if seed_match:
        result["seed"] = int(seed_match.group(1))
    
    # 提取步数
    steps_match = re.search(r'(\d+)步|步(\d+)', text)
    if steps_match:
        result["steps"] = int(steps_match.group(1) or steps_match.group(2))
    
    # 提取负向词
    neg_match = re.search(r'负词[：:](.*?)(?=\s|$)', text)
    if neg_match:
        result["negative_prompt"] = neg_match.group(1).strip()
    
    # 提取正向提示词（去掉所有已解析的关键词）
    clean = text
    for kw in list(workflow_map.keys()):
        clean = clean.replace(kw, "")
    clean = re.sub(r'种子[-\d]+', '', clean)
    clean = re.sub(r'\d+步|步\d+', '', clean)
    clean = re.sub(r'负词[：:][^\s]*', '', clean)
    clean = re.sub(r'跑一下|画|生成|做|帮我', '', clean).strip()
    
    if clean and not any(kw in text for kw in ["查看", "状态", "工作流"]):
        result["prompt"] = clean[:200]  # 防止太长
    
    return result

def format_health_report(data):
    if data.get("online"):
        info = data.get("data", {})
        device = info.get("device", {})
        parts = [f"✅ ComfyUI 在线"]
        parts.append(f"   GPU: {device.get('name', '?')}")
        parts.append(f"   VRAM: {device.get('vram_total', 0)/1e9:.1f} GB")
        parts.append(f"   节点: {info.get('comfyui_version', '?')}")
        return '\n'.join(parts)
    else:
        return f"❌ ComfyUI 未连接\n   {data.get('host', '?')}\n   请确保: ①ComfyUI已启动 ②加了--listen 0.0.0.0"

def format_models_report(data):
    models = data.get("models", [])
    folder = data.get("folder", "checkpoints")
    if not isinstance(models, list):
        models = list(models.keys())
    if not models:
        return f"📦 {folder}: (空)"
    
    # 分组显示
    lines = [f"📦 {folder} ({len(models)}个)"]
    for m in models[:20]:
        lines.append(f"   · {m}")
    if len(models) > 20:
        lines.append(f"   ... 还有 {len(models)-20} 个")
    return '\n'.join(lines)

def format_workflows_report(data):
    lines = ["📋 可用工作流:"]
    for name, info in data.items():
        mark = "✅" if info["exists"] else "❌"
        desc = info.get("description", "")
        lines.append(f"{mark} {name} — {desc}")
    return '\n'.join(lines)

def format_run_result(result):
    """格式化为微信消息"""
    if result["status"] == "success":
        parts = [f"🎨 生成完成 | ⏱ {result['elapsed']}s"]
        
        # 对每个输出文件
        media_paths = []
        for out in result.get("outputs", []):
            if out["saved"]:
                size = out.get("size_kb", 0)
                size_str = f"{size:.0f}KB" if size < 1024 else f"{size/1024:.1f}MB"
                parts.append(f"📎 [{out['type']}] {out['filename']} ({size_str})")
                media_paths.append(out["path"])
        
        parts.append(f"🆔 {result['prompt_id'][:12]}...")
        
        return {
            "text": '\n'.join(parts),
            "media": media_paths,  # 这些文件路径可以直接用 MEDIA: 发送
        }
    elif result["status"] == "timeout":
        return {
            "text": f"⏰ 超时 ({result['elapsed']}s)，生成还没完成\n可尝试: 更大的--timeout，或查看ComfyUI队列",
            "media": [],
        }
    else:
        return {
            "text": f"❌ 生成失败: {result.get('error', '未知错误')}",
            "media": [],
        }

if __name__ == "__main__":
    # 测试
    if len(sys.argv) > 1:
        cmd = parse_weixin_command(' '.join(sys.argv[1:]))
        print(json.dumps(cmd, ensure_ascii=False, indent=2))
