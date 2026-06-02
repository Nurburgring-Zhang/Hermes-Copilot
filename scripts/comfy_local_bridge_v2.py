#!/usr/bin/env python3
"""
ComfyUI Local Bridge v2 — Hermes ↔ Windows ComfyUI 全功能桥接
用途：从微信控制本地 ComfyUI 的完整工作流

功能：
- 工作流加载、参数注入、运行
- 模型/插件列表查询
- 图片上传（img2img/inpaint）
- 结果下载 → 发送微信
- 本地存储组织

用法（Hermes 内部调用）：
    python3 comfy_local_bridge_v2.py run --workflow flux_dev --prompt "cat" --seed -1
    python3 comfy_local_bridge_v2.py list-models
    python3 comfy_local_bridge_v2.py health
"""

import json, sys, os, time, random, string, re
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

# ── 配置 ──────────────────────────────────────────────────────────
# WSL → Windows 的网关 IP（自动检测）
def detect_windows_host():
    """自动检测 WSL 中 Windows 主机的 IP"""
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "route"], capture_output=True, text=True, timeout=3
        )
        # 从 "default via X.X.X.X dev eth0" 提取
        for line in result.stdout.splitlines():
            if line.startswith("default"):
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]
    except:
        pass
    # 备选：从 resolv.conf 取 DNS（通常是 Windows）
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if "nameserver" in line:
                    ip = line.split()[1]
                    if ip != "127.0.0.53":
                        return ip
    except:
        pass
    return "172.31.32.1"  # 回退默认值

HOST = f"http://{detect_windows_host()}:8188"
CLIENT_ID = ''.join(random.choices(string.ascii_lowercase, k=8))

# 工作流目录跟 skill 的 workflows 打通
WORKFLOW_DIR = Path(os.path.expanduser(
    "~/.hermes/skills/creative/comfyui/workflows"
))
OUTPUT_DIR = Path(os.path.expanduser("~/.hermes/comfy_outputs"))

# ── 可用的工作流目录 ──────────────────────────────────────────────
AVAILABLE_WORKFLOWS = {
    "sd15": "sd15_txt2img.json",
    "sdxl": "sdxl_txt2img.json",
    "sdxl-img2img": "sdxl_img2img.json",
    "sdxl-inpaint": "sdxl_inpaint.json",
    "flux": "flux_dev_txt2img.json",
    "flux-dev": "flux_dev_txt2img.json",
    "upscale": "upscale_4x.json",
    "video": "wan_video_t2v.json",
    "wan": "wan_video_t2v.json",
    "animate": "animatediff_video.json",
}

# ── HTTP 工具 ──────────────────────────────────────────────────────
import urllib.request
import urllib.error

def http_get(path, timeout=10):
    url = f"{HOST}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}

def http_post_json(path, data, timeout=30):
    url = f"{HOST}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except:
            return e.code, {"error": body}
    except Exception as e:
        return 0, {"error": str(e)}

def http_post_file(path, file_path, extra_fields=None, timeout=120):
    """上传文件到ComfyUI（用于 img2img）"""
    import http.client
    import mimetypes
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders
    
    boundary = "----" + ''.join(random.choices(string.ascii_letters + string.digits, k=30))
    
    form_parts = []
    
    # 文件部分
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_data = f.read()
    
    form_parts.append(f"--{boundary}\r\n")
    form_parts.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n')
    form_parts.append("Content-Type: application/octet-stream\r\n\r\n".encode())
    form_parts.append(file_data)
    form_parts.append(b"\r\n")
    
    # 额外字段
    if extra_fields:
        for key, value in extra_fields.items():
            form_parts.append(f"--{boundary}\r\n".encode())
            form_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            form_parts.append(f"{value}\r\n".encode())
    
    form_parts.append(f"--{boundary}--\r\n".encode())
    
    body = b"".join(p if isinstance(p, bytes) else p.encode() for p in form_parts)
    
    url = f"{HOST}{path}"
    parsed = urllib.parse.urlparse(url)
    
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data
    except Exception as e:
        return 0, {"error": str(e)}
    finally:
        conn.close()

def download_file(path, file_params, save_path):
    """下载ComfyUI输出的文件"""
    url = f"{HOST}{path}?{urlencode(file_params)}"
    try:
        urllib.request.urlretrieve(url, save_path)
        return True
    except Exception as e:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(save_path, "wb") as f:
                    f.write(resp.read())
            return True
        except Exception as e2:
            return False

# ── 核心功能 ──────────────────────────────────────────────────────

def check_health():
    """检查 ComfyUI 在线状态"""
    status, data = http_get("/system_stats")
    return {
        "online": status == 200,
        "status_code": status,
        "data": data if status == 200 else None,
        "host": HOST,
    }

def list_models(folder="checkpoints"):
    """列出已安装模型"""
    status, data = http_get(f"/models/{folder}")
    if status == 200:
        return {"folder": folder, "models": data, "count": len(data) if isinstance(data, list) else "?" }
    return {"folder": folder, "error": data.get("error", str(data))}

def list_available_workflows():
    """列出可用的工作流"""
    result = {}
    for name, filename in AVAILABLE_WORKFLOWS.items():
        wf_path = WORKFLOW_DIR / filename
        result[name] = {
            "exists": wf_path.exists(),
            "path": str(wf_path),
            "description": {
                "sd15": "SD1.5文生图",
                "sdxl": "SDXL文生图",
                "sdxl-img2img": "SDXL图生图",
                "sdxl-inpaint": "SDXL局部重绘",
                "flux": "Flux Dev文生图",
                "flux-dev": "Flux Dev文生图",
                "upscale": "4倍超分",
                "video": "Wan视频生成",
                "wan": "Wan视频生成",
                "animate": "AnimateDiff视频生成",
            }.get(name, "")
        }
    return result

def run_workflow(workflow_name, params, timeout=300):
    """运行工作流 + 等待结果 + 下载输出"""
    
    # 1. 找到工作流文件
    filename = AVAILABLE_WORKFLOWS.get(workflow_name)
    if not filename:
        return {"status": "error", "error": f"未知工作流: {workflow_name}，可用: {list(AVAILABLE_WORKFLOWS.keys())}"}
    
    wf_path = WORKFLOW_DIR / filename
    if not wf_path.exists():
        return {"status": "error", "error": f"工作流文件不存在: {wf_path}"}
    
    # 2. 加载工作流 JSON
    with open(wf_path) as f:
        workflow = json.load(f)
    
    # 处理嵌套格式（有些工作流包在 {"prompt": {...}} 里）
    if "prompt" in workflow and isinstance(workflow["prompt"], dict):
        workflow = workflow["prompt"]
    
    # 3. 注入参数
    if "seed" in params and (params["seed"] == -1 or params["seed"] is None):
        params["seed"] = random.randint(0, 2**31 - 1)
    
    # 遍历工作流各节点，查找可注入的参数位置
    warnings = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        for key, value in params.items():
            # 尝试匹配节点输入名
            if key in inputs:
                # 不覆盖已有连接（如果是 [node, slot] 这种连接格式则跳过）
                if isinstance(inputs[key], list) and len(inputs[key]) == 2:
                    warnings.append(f"节点{node_id}.{key}是连接，跳过覆盖")
                    continue
                inputs[key] = value
    
    # 4. 提交
    payload = {"prompt": workflow, "client_id": CLIENT_ID}
    status, resp_data = http_post_json("/prompt", payload)
    
    if status != 200:
        errors = resp_data.get("node_errors", resp_data.get("error", resp_data))
        return {"status": "error", "error": f"提交失败 (HTTP {status})", "details": str(errors)[:500]}
    
    prompt_id = resp_data.get("prompt_id")
    if not prompt_id:
        return {"status": "error", "error": "未返回 prompt_id", "response": resp_data}
    
    # 5. 轮询等待
    start_time = time.time()
    deadline = start_time + timeout
    
    while time.time() < deadline:
        st, hist = http_get(f"/history/{prompt_id}")
        
        if st == 200:
            entry = hist.get(prompt_id, {})
            entry_status = entry.get("status", {})
            
            # 先检查错误
            if entry_status.get("status_str") == "error":
                return {
                    "status": "error",
                    "error": "执行出错",
                    "details": entry_status.get("messages", [])[-1] if entry_status.get("messages") else "",
                    "prompt_id": prompt_id,
                    "elapsed": round(time.time() - start_time, 1),
                }
            
            # 完成
            if entry_status.get("completed"):
                outputs = entry.get("outputs", {})
                elapsed = time.time() - start_time
                
                # 6. 下载输出文件
                output_dir = OUTPUT_DIR / prompt_id
                output_dir.mkdir(parents=True, exist_ok=True)
                
                downloaded_files = []
                for node_id, node_output in outputs.items():
                    for media_type in ("images", "gifs", "videos", "video", "audio"):
                        items = node_output.get(media_type, [])
                        if not isinstance(items, list):
                            items = [items]
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            fn = item.get("filename", "")
                            if not fn:
                                continue
                            sub = item.get("subfolder", "")
                            ftype = item.get("type", "output")
                            
                            save_path = output_dir / fn
                            ok = download_file("/view", {
                                "filename": fn, "subfolder": sub, "type": ftype
                            }, str(save_path))
                            
                            downloaded_files.append({
                                "filename": fn,
                                "type": media_type.rstrip("s"),  # images→image, videos→video
                                "path": str(save_path),
                                "saved": ok,
                                "size_kb": round(os.path.getsize(save_path) / 1024, 1) if ok and os.path.exists(save_path) else 0,
                            })
                
                return {
                    "status": "success",
                    "prompt_id": prompt_id,
                    "elapsed": round(elapsed, 1),
                    "warnings": warnings,
                    "outputs": downloaded_files,
                }
        
        time.sleep(1)
    
    return {"status": "timeout", "prompt_id": prompt_id, "elapsed": timeout}

# ── CLI ───────────────────────────────────────────────────────────

def cmd_health():
    result = check_health()
    if result["online"]:
        info = result.get("data", {})
        print(f"✅ ComfyUI 在线 | {HOST}")
        if info:
            print(f"   版本: {info.get('comfyui_version', info.get('version', '?'))}")
            print(f"   GPU: {info.get('device', {}).get('name', '?')}")
            print(f"   VRAM: {info.get('device', {}).get('vram_total', 0) / 1e9:.1f} GB")
    else:
        print(f"❌ ComfyUI 不在线 | {HOST}")
        print(f"   请确保: ① ComfyUI 已启动 ② 加了 --listen 0.0.0.0")
        print(f"   检测IP: {detect_windows_host()}")
    return result

def cmd_list_models(args):
    folder = args[0] if args else "checkpoints"
    result = list_models(folder)
    print(f"📦 {result.get('folder', folder)} 模型 ({result.get('count', '?')})")
    models = result.get("models", [])
    if isinstance(models, list):
        for m in models:
            print(f"   - {m}")
    elif isinstance(models, dict):
        for k, v in list(models.items())[:20]:
            print(f"   - {k}")
    return result

def cmd_list_workflows():
    result = list_available_workflows()
    print("📋 可用工作流:")
    for name, info in result.items():
        mark = "✅" if info["exists"] else "❌"
        desc = info.get("description", "")
        print(f"   {mark} {name} — {desc} ({info['path']})")
    return result

def cmd_run(args):
    """run <workflow_name> [param=value ...] [--timeout N]"""
    if not args:
        print("❌ 用法: run <workflow_name> [prompt=...] [seed=-1] [steps=20] [--timeout 300]")
        return
    
    name = args[0]
    params = {}
    timeout = 300
    
    for arg in args[1:]:
        if arg.startswith("--timeout="):
            timeout = int(arg.split("=", 1)[1])
        elif "=" in arg:
            key, val = arg.split("=", 1)
            if val.isdigit():
                val = int(val)
            params[key] = val
    
    # 默认参数
    if "seed" not in params:
        params["seed"] = -1
    if "steps" not in params:
        params["steps"] = 20
    
    print(f"🚀 运行工作流: {name}")
    print(f"   参数: {json.dumps(params, ensure_ascii=False)}")
    print(f"   超时: {timeout}s")
    
    result = run_workflow(name, params, timeout=timeout)
    
    if result["status"] == "success":
        print(f"\n✅ 完成! 用时 {result['elapsed']}s")
        print(f"   prompt_id: {result['prompt_id']}")
        for out in result.get("outputs", []):
            mark = "✅" if out["saved"] else "❌"
            print(f"   {mark} [{out['type']}] {out['filename']} ({out.get('size_kb', 0)} KB)")
            print(f"      → {out['path']}")
        
        # 输出 JSON 让 Hermes 继续处理
        print("\n---JSON_OUTPUT---")
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"\n❌ {result['status']}: {result.get('error', '未知错误')}")
        if "details" in result:
            print(f"   详情: {result['details']}")

def cmd_upload(args):
    """上传本地图片到 ComfyUI（用于 img2img）"""
    if not args:
        print("❌ 用法: upload <image_path>")
        return
    
    path = args[0]
    if not os.path.exists(path):
        print(f"❌ 文件不存在: {path}")
        return
    
    print(f"📤 上传图片: {path}")
    status, data = http_post_file("/upload/image", path, {"type": "input", "overwrite": "true"})
    if status == 200:
        print(f"✅ 上传成功: {data}")
    else:
        print(f"❌ 上传失败: {data}")
    return data

def main():
    if len(sys.argv) < 2:
        print("""
ComfyUI Local Bridge v2

用法:
  health                        检查 ComfyUI 状态
  models [folder]               列出模型 (默认:checkpoints)
  workflows                     列出可用工作流
  run <name> [key=val ...]      运行工作流
  upload <path>                 上传图片

可用工作流名称:
  sd15, sdxl, sdxl-img2img, sdxl-inpaint, flux, upscale, video, wan, animate

示例:
  python3 comfy_local_bridge_v2.py health
  python3 comfy_local_bridge_v2.py models loras
  python3 comfy_local_bridge_v2.py workflows
  python3 comfy_local_bridge_v2.py run flux prompt="cat wearing hat" seed=12345 steps=30
  python3 comfy_local_bridge_v2.py run sd15 prompt="beautiful landscape" --timeout=600
  python3 comfy_local_bridge_v2.py upload /mnt/c/Users/xxx/photo.png
"""[1:])
        return
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    commands = {
    "health": lambda _: cmd_health(),
    "models": cmd_list_models,
    "workflows": lambda _: cmd_list_workflows(),
    "run": cmd_run,
    "upload": cmd_upload,
    }
    
    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"❌ 未知命令: {cmd}")
        print("可用: health, models, workflows, run, upload")

if __name__ == "__main__":
    main()
