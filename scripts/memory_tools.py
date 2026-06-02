#!/usr/bin/env python3
"""
memory_tools.py — 记忆工具集
合并自: memory_index.py + memory_stats.py + memory_search_test.py
能力无损，接口兼容。

依赖: skills/rag-memory-enhanced 的 RAGIndexer
"""

import argparse, json, sys
from pathlib import Path

skill_path = Path.home() / ".hermes" / "skills" / "rag-memory-enhanced"
if skill_path.exists():
    sys.path.insert(0, str(skill_path))

try:
    from rag_core import RAGIndexer
except ImportError:
    RAGIndexer = None


def cmd_index(args):
    """索引文件"""
    if RAGIndexer is None:
        print("Error: RAGIndexer not available (skills/rag-memory-enhanced missing)")
        sys.exit(1)
    workspace = Path(args.workspace).expanduser()
    db = Path(args.db).expanduser()
    if not workspace.exists():
        print(f"Error: Workspace not found: {workspace}"); sys.exit(1)
    indexer = RAGIndexer(db_path=db, workspace_dir=workspace, auto_watch=not args.no_watch)
    if args.stats_only:
        stats = indexer.get_stats()
        print(json.dumps(stats, indent=2, default=str)); return
    extensions = [f".{e.strip()}" for e in args.extensions.split(",")] if args.extensions else None
    results = indexer.index_all(extensions=extensions)
    stats = indexer.get_stats()
    print(f"Indexed: {results['indexed_count']} files, {results['total_chunks']} chunks")
    print(f"Total: {stats['files']['total']} files, {stats['chunks']['total']} chunks")
    if not args.no_watch:
        try:
            import time
            while True: time.sleep(1)
        except KeyboardInterrupt: indexer.close()


def cmd_stats(args):
    """记忆统计"""
    if RAGIndexer is None:
        print("Error: RAGIndexer not available"); sys.exit(1)
    db = Path(args.db).expanduser(); ws = Path(args.workspace).expanduser()
    if not db.exists(): print(f"Error: DB not found: {db}"); sys.exit(1)
    indexer = RAGIndexer(db_path=db, workspace_dir=ws, auto_watch=False)
    stats = indexer.get_stats()
    if args.format == "json":
        print(json.dumps(stats, indent=2, default=str))
    else:
        print(f"DB: {stats['database']['size_mb']:.1f}MB | "
              f"Files: {stats['files']['total']} | "
              f"Chunks: {stats['chunks']['total']:,} | "
              f"Vectors: {stats['chunks']['vector_coverage_percent']:.1f}%")
    indexer.close()


def cmd_search(args):
    """搜索测试"""
    if RAGIndexer is None:
        print("Error: RAGIndexer not available"); sys.exit(1)
    db = Path(args.db).expanduser(); ws = Path(args.workspace).expanduser()
    if not db.exists(): print(f"Error: DB not found: {db}"); sys.exit(1)
    indexer = RAGIndexer(db_path=db, workspace_dir=ws, auto_watch=False)
    if args.query:
        results = indexer.search(args.query, limit=args.limit)
        if args.json:
            print(json.dumps({"query": args.query, "results": [{"id":r["id"],"file":r["path"],"score":r["score"],"text":r["text"][:200]} for r in results]}, indent=2))
        else:
            print(f"Query: '{args.query}' → {len(results)} results")
            for r in results[:5]:
                print(f"  [{r['score']:.3f}] {Path(r['path']).name}: {r['text'][:100]}")
    else:
        test_queries = ["authentication","configuration","database","error handling","API","security","function","class","async","import"]
        total = 0
        for q in test_queries:
            r = indexer.search(q, limit=args.limit)
            total += len(r)
            print(f"  '{q}': {len(r)} results")
        print(f"Average: {total/len(test_queries):.1f} results/query")
    indexer.close()


def main():
    parser = argparse.ArgumentParser(description="Memory Tools — 索引/统计/搜索")
    parser.set_defaults(func=lambda _: parser.print_help())

    sub = parser.add_subparsers(dest="command")
    
    p_idx = sub.add_parser("index", help="索引文件")
    p_idx.add_argument("--workspace", default="~/.hermes/workspace")
    p_idx.add_argument("--db", default="~/.hermes/memory/main.sqlite")
    p_idx.add_argument("--extensions")
    p_idx.add_argument("--force", action="store_true")
    p_idx.add_argument("--no-watch", action="store_true")
    p_idx.add_argument("--stats-only", action="store_true")
    p_idx.set_defaults(func=cmd_index)

    p_st = sub.add_parser("stats", help="记忆统计")
    p_st.add_argument("--db", default="~/.hermes/memory/main.sqlite")
    p_st.add_argument("--workspace", default="~/.hermes/workspace")
    p_st.add_argument("--format", choices=["text","json"], default="text")
    p_st.set_defaults(func=cmd_stats)

    p_sr = sub.add_parser("search", help="搜索测试")
    p_sr.add_argument("query", nargs="?")
    p_sr.add_argument("--limit", type=int, default=10)
    p_sr.add_argument("--db", default="~/.hermes/memory/main.sqlite")
    p_sr.add_argument("--workspace", default="~/.hermes/workspace")
    p_sr.add_argument("--json", action="store_true")
    p_sr.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
