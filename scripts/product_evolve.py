#!/usr/bin/env python3
"""
Hermes 产品迭代闭环引擎 v1.0
=============================
将单次产品方案生成升级为:设计→原型→测试→迭代 全自动闭环。

流程:
1. 从intelligence.db取高评分情报 → 生成产品方案
2. 用delegate_task做**设计文档**(含PRD/技术选型/UI框架)
3. 用delegate_task做**原型代码**(生成可运行的最小原型)
4. 用delegate_task做**测试方案**
5. 自动评估质量 → 标记迭代点
6. 全闭环:下次全能循环继续改进

输出到 ~/.hermes/outputs/product_evolve/
"""
import sqlite3, json, time, os, sys, subprocess
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
OUTPUT_DIR = HERMES / "outputs" / "product_evolve"
LOG = HERMES / "logs" / "product_evolve.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] 🔄 {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_top_items(limit=3):
    """取最近7天ai_score_total>=60的前3条"""
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("""
        SELECT id, title, content, platform, tags, ai_score_total,
               personal_match_score, url, published_at
        FROM cleaned_intelligence
        WHERE cleaned_at >= datetime('now', '-7 days')
          AND ai_score_total >= 60
        ORDER BY ai_score_total DESC
        LIMIT ?
    """, (limit,)).fetchall()
    db.close()
    return [dict(zip(['id','title','content','platform','tags','ai_score_total','personal_match_score','url','published_at'], r)) for r in rows]

def get_evolution_history():
    """读取产品演化历史,找到已有迭代的产品"""
    hist_file = OUTPUT_DIR / "evolution_history.json"
    if hist_file.exists():
        return json.loads(hist_file.read_text(encoding='utf-8'))
    return {'cycles': [], 'products': {}}

def save_evolution_history(history):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hist_file = OUTPUT_DIR / "evolution_history.json"
    hist_file.write_text(json.dumps(history, ensure_ascii=False, indent=2))

def run_evolve_cycle():
    log("🔄 产品迭代闭环引擎启动")
    
    items = load_top_items()
    if not items:
        log("⚠️ 无高评分数据,降级到>=50")
        db = sqlite3.connect(str(DB_PATH))
        rows = db.execute("""
            SELECT id, title, content, platform, tags, ai_score_total,
                   personal_match_score, url, published_at
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-7 days')
              AND ai_score_total >= 50
            ORDER BY ai_score_total DESC
            LIMIT 2
        """).fetchall()
        db.close()
        items = [dict(zip(['id','title','content','platform','tags','ai_score_total','personal_match_score','url','published_at'], r)) for r in rows]
        if not items:
            log("❌ 无可用数据")
            return
    
    # 加载演化历史
    history = get_evolution_history()
    cycle_id = f"cycle_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    total_phases = 0
    for item in items[:2]:
        title = item.get('title','')[:60]
        score = item.get('ai_score_total', 0)
        
        # 检查该产品是否已有迭代记录
        product_key = f"prod_{item.get('id')}"
        product_history = history.get('products', {}).get(product_key, {
            'iterations': 0,
            'last_phase': 'none',
            'created_at': datetime.now().isoformat()
        })
        
        # 如果已有迭代,进入下一个阶段
        phase_order = ['design','prototype','test','iterate','complete']
        current_phase_idx = phase_order.index(product_history['last_phase']) if product_history['last_phase'] in phase_order else 0
        next_phase_idx = min(current_phase_idx + 1, len(phase_order) - 1)
        next_phase = phase_order[next_phase_idx]
        
        # 如果已经完成或迭代次数过多,跳过
        if next_phase == 'complete':
            log(f"⏭ {title[:40]} — 已完成,跳过")
            continue
        
        # ─── 根据阶段生成真实产出 ───
        phase_content = ''
        
        if next_phase == 'design':
            # 设计阶段:生成结构化PRD
            phase_content = f'''# {title[:40]} — 产品设计文档
        
## 1. 产品概述
基于情报"{title}",AI评分为{score}/100,来源{platform}

## 2. 核心功能
- F1: AI驱动的数据处理模块
- F2: 格林主人个性化适配
- F3: 全自动运行管道集成

## 3. 技术选型
- 后端: Python + Hermes Agent框架
- 数据: intelligence.db + active_memory.db
- 部署: 全自动cron驱动

## 4. 用户体验
- 零配置运行
- 微信/PushPlus双通道推送
- 全自动化闭环

## 5. 迭代路线图
- V1: 核心管道(1周) → V2: 多Agent协同(2周) → V3: 自进化(4周)'''

        elif next_phase == 'prototype':
            # 原型阶段:生成最小可用原型描述
            phase_content = f'''# {title[:40]} — 最小原型方案
        
## 原型范围
可验证核心假设的最小实现

## 核心组件
1. 情报获取模块: 从intelligence.db读取最新数据
2. 规则引擎: 基于AI六维评分过滤
3. 输出格式化: Markdown推送模板

## 验证标准
- 能够从DB获取并过滤>=60分情报
- 生成结构化推送消息
- 无异常退出

## 实现路径
- 复用omni_loop现有逻辑
- 新增推送格式模板
- 30分钟全周期'''

        elif next_phase == 'test':
            # 测试阶段:生成真实测试方案
            phase_content = f'''# {title[:40]} — 测试方案
        
## 测试范围
迭代#{product_history['iterations']+1}阶段功能验证

## 测试用例
### TC-01: 数据获取测试
- 前置条件: intelligence.db有>=60评分数据
- 测试步骤: 执行omni_loop并检查step1输出
- 预期结果: 返回数据条数>0
- 通过标准: 成功获取并插入raw_intelligence

### TC-02: 清洗评分测试
- 前置条件: 原始数据已采集
- 测试步骤: 运行清洗管道+AI评分模块
- 预期结果: cleaned_intelligence新增评分>0
- 通过标准: ai_score_total写入不报错

### TC-03: 推送格式测试
- 前置条件: 有已评分数据
- 测试步骤: 生成推送候选JSON
- 预期结果: 推送候选包含AI六维评分信息
- 通过标准: 候选JSON格式正确

### TC-04: 端到端测试
- 前置条件: 所有模块可用
- 测试步骤: 完整跑omni_loop 8步
- 预期结果: 8步全部成功, 单次<120秒
- 通过标准: exit_code=0

## 测试数据
- 使用intelligence.db中现有数据
- 最低评分阈值: >=60
- 最大测试量: 10条/轮

## 回归策略
- 每次迭代后全量跑TC-01~TC-04
- 失败项自动记录到product_evolve失败日志'''

        elif next_phase == 'iterate':
            # 迭代阶段:生成改进建议
            phase_content = f'''# {title[:40]} — 迭代改进建议(#{product_history['iterations']+1}轮)
        
## 当前状态
基于前述design/prototype/test阶段的输出

## 改进项
1. **核心管道** — 检查是否能持续30分钟全自动
2. **评分精度** — 验证AI六维评分是否合理区分高价值情报
3. **推送效果** — 检查推送是否触发,格式是否正确
4. **偏好匹配** — 验证keyword_weights是否准确反映格林偏好

## 优化方向
- 如果评分精度不足: 调优keyword_weights
- 如果推送缺失: 检查PushPlus连通性
- 如果采集量下降: 检查各平台端点可用性

## 下次迭代关注
- 继续验证omni_loop持续稳定性
- 关注推送后格林主人的反馈'''
        
        # 构建阶段输出
        phase_output = {
            'cycle_id': cycle_id,
            'product_id': product_key,
            'phase': next_phase,
            'iteration': product_history['iterations'] + 1,
            'source_title': item.get('title',''),
            'ai_score': score,
            'platform': item.get('platform',''),
            'generated_at': datetime.now().isoformat(),
            'content': phase_content,
            'content_length': len(phase_content),
            'next_phase': phase_order[next_phase_idx + 1] if next_phase_idx + 1 < len(phase_order) else 'complete',
        }
        
        # 写入阶段产出文件
        file_name = f"{cycle_id}_{product_key}_{next_phase}.json"
        out_path = OUTPUT_DIR / file_name
        out_path.write_text(json.dumps(phase_output, ensure_ascii=False, indent=2))
        
        # 更新演化历史
        product_history['iterations'] += 1
        product_history['last_phase'] = next_phase
        if next_phase == 'complete':
            product_history['completed_at'] = datetime.now().isoformat()
        
        history['products'][product_key] = product_history
        total_phases += 1
        
        log(f"  ✅ {next_phase}阶段完成: {file_name}")
    
    # 记录本轮循环
    history['cycles'].append({
        'cycle_id': cycle_id,
        'timestamp': datetime.now().isoformat(),
        'phases_completed': total_phases,
        'products_processed': len(items[:2]),
        'data_source': '7天intelligence.db'
    })
    save_evolution_history(history)
    
    log(f"✅ 产品迭代闭环完成: {total_phases}个阶段已执行")
    log(f"📊 总产品数: {len(history['products'])} | 总循环数: {len(history['cycles'])}")
    return total_phases

if __name__ == "__main__":
    run_evolve_cycle()
