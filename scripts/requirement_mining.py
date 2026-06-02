#!/usr/bin/env python3
"""
Hermes 需求挖掘系统
从情报数据中挖掘需求模式,趋势分析,需求预测
"""
import sqlite3, os, json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Dict, List

DB_PATH = os.path.expanduser("~/.hermes/intelligence.db")

TECH_DOMAINS = {
    "AI_LLM": ["AI","LLM","大模型","GPT","Claude","Gemini","OpenAI","Anthropic","Transformer","RAG","Agent"],
    "Frontend": ["React","Vue","Angular","TypeScript","Next.js","CSS","Tailwind","UI"],
    "Backend": ["Python","Go","Rust","Java","Node.js","FastAPI","Gin","Spring","Django","微服务"],
    "DevOps": ["Docker","Kubernetes","K8s","CI/CD","GitHub Actions","Terraform","监控"],
    "Data": ["大数据","Hadoop","Spark","Flink","Kafka","ETL","数据湖"],
    "Security": ["安全","漏洞","加密","零信任","渗透测试"],
    "Mobile": ["iOS","Android","Flutter","React Native","小程序"],
    "Cloud": ["AWS","Azure","GCP","阿里云","Serverless","云原生"],
}

REQUIREMENT_TYPES = {
    "技术研究": ["研究","调研","分析","评估"],
    "产品开发": ["开发","实现","构建","创建"],
    "集成对接": ["集成","对接","API","SDK"],
    "运维保障": ["部署","监控","运维"],
    "性能优化": ["优化","性能","提速"],
}

class RequirementMiner:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.conn = None
        
    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        
    def close(self):
        if self.conn: self.conn.close()
        
    def __enter__(self): self.connect(); return self
    def __exit__(self, *args): self.close()
    
    def detect_trends(self, days=7, min_score=15.0) -> List[Dict]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        c = self.conn.cursor()
        c.execute("""
            SELECT title, content, source, importance_score, category
            FROM cleaned_intelligence WHERE importance_score >= ? AND collected_at >= ?
            ORDER BY importance_score DESC LIMIT 200
        """, (min_score, cutoff))
        
        domain_counts = Counter()
        domain_scores = defaultdict(float)
        domain_items = defaultdict(list)
        
        for row in c.fetchall():
            text = ((row['title'] or "") + " " + (row['content'] or "")).upper()
            for domain, kws in TECH_DOMAINS.items():
                if any(kw.upper() in text for kw in kws):
                    domain_counts[domain] += 1
                    domain_scores[domain] += row['importance_score']
                    if len(domain_items[domain]) < 3:
                        domain_items[domain].append({'t': row['title'], 's': row['importance_score']})
        
        trends = []
        for d in domain_counts:
            avg = domain_scores[d]/domain_counts[d]
            strength = domain_counts[d] * avg
            trends.append({
                'domain': d, 'count': domain_counts[d],
                'avg_score': round(avg, 1),
                'strength': round(strength, 1),
                'level': '爆火' if strength > 500 else '活跃' if strength > 200 else '平稳',
                'items': domain_items[d]
            })
        trends.sort(key=lambda x: x['strength'], reverse=True)
        return trends
    
    def mine_patterns(self) -> Dict:
        c = self.conn.cursor()
        c.execute("SELECT title, content FROM cleaned_intelligence WHERE importance_score >= 15 LIMIT 300")
        type_dist = Counter()
        type_examples = defaultdict(list)
        for row in c.fetchall():
            text = (row['title'] or "") + " " + (row['content'] or "")
            for rtype, kws in REQUIREMENT_TYPES.items():
                if any(kw in text for kw in kws):
                    type_dist[rtype] += 1
                    if len(type_examples[rtype]) < 3:
                        type_examples[rtype].append(row['title'][:50])
        return {'types': [{'t':t,'c':c,'ex':type_examples[t]} for t,c in type_dist.most_common()]}
    
    def predict(self) -> List[Dict]:
        c = self.conn.cursor()
        c.execute("SELECT title, importance_score FROM cleaned_intelligence WHERE importance_score >= 35 ORDER BY importance_score DESC LIMIT 5")
        preds = []
        for r in c.fetchall():
            preds.append({'d': f"新技术: {r['title'][:40]}", 'conf': 0.8, 'ev': f"评分{r['importance_score']}"})
        return preds
    
    def generate_report(self) -> Dict:
        trends = self.detect_trends()
        patterns = self.mine_patterns()
        preds = self.predict()
        c = self.conn.cursor()
        c.execute("SELECT title, source, importance_score FROM cleaned_intelligence WHERE importance_score >= 30 AND is_ai_related = 1 ORDER BY importance_score DESC LIMIT 5")
        hv = [{'t':r['title'],'s':r['source'],'sc':r['importance_score']} for r in c.fetchall()]
        summary = f"最热:{trends[0]['domain'] if trends else 'N/A'} | 需求:{patterns['types'][0]['t'] if patterns['types'] else 'N/A'}"
        return {'at': datetime.now().isoformat(), 'trends': trends[:5], 'patterns': patterns, 'predictions': preds, 'high_value': hv, 'summary': summary}

def format_md(r):
    lines = [f"# 需求挖掘报告 | {r['at'][:10]}", "", "## 技术趋势", ""]
    for i, t in enumerate(r['trends'][:4], 1):
        lines.append(f"{i}. {t['domain']} {t['level']} (强度:{t['strength']})")
        for it in t['items'][:2]:
            lines.append(f"   - [{it['s']}分] {it['t'][:50]}")
    lines.extend(["", "## 高价值需求", ""])
    for h in r['high_value']:
        lines.append(f"- {h['sc']}分 [{h['s']}] {h['t'][:55]}")
    lines.extend(["", r['summary']])
    return "\n".join(lines)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=7)
    p.add_argument('--format', choices=['json','markdown'], default='markdown')
    args = p.parse_args()
    with RequirementMiner() as m:
        r = m.generate_report()
        print(json.dumps(r, ensure_ascii=False, indent=2) if args.format == 'json' else format_md(r))
