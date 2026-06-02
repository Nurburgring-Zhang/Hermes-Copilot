#!/usr/bin/env python3
"""
Initialize expert workspaces and memory databases
"""

import os
import sys
import sqlite3
from pathlib import Path

# Add hermes-agent to path
sys.path.insert(0, str(Path("/home/administrator/.hermes") / "hermes-agent"))

def init_workspaces():
    """Create workspace directories for all experts"""
    workspace_base = Path("/home/administrator/.hermes") / "workspace"
    memory_base = Path("/home/administrator/.hermes") / "memory"
    
    experts = ["main", "security-expert", "research-expert", "analyst-expert", "dev-expert"]
    
    for expert_id in experts:
        # Create workspace
        workspace_path = workspace_base / expert_id
        workspace_path.mkdir(parents=True, exist_ok=True)
        print(f"✓ Workspace created: {workspace_path}")
        
        # Create memory database
        memory_path = memory_base / f"{expert_id}.sqlite"
        if not memory_path.exists():
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            init_memory_db(memory_path, expert_id)
            print(f"✓ Memory database created: {memory_path}")
        else:
            print(f"• Memory database exists: {memory_path}")

def init_memory_db(db_path: Path, expert_id: str):
    """Initialize SQLite memory database with schema"""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Create memories table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL,
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            expert_id TEXT NOT NULL,
            messages TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create knowledge table for expert-specific knowledge
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create index for search
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_expert ON sessions(expert_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source)
    """)
    
    conn.commit()
    conn.close()

def verify_initialization():
    """Verify all workspaces and databases are initialized"""
    workspace_base = Path("/home/administrator/.hermes") / "workspace"
    memory_base = Path("/home/administrator/.hermes") / "memory"
    
    experts = ["main", "security-expert", "research-expert", "analyst-expert", "dev-expert"]
    
    all_ok = True
    for expert_id in experts:
        ws = workspace_base / expert_id
        mem = memory_base / f"{expert_id}.sqlite"
        
        if not ws.exists() or not ws.is_dir():
            print(f"✗ Missing workspace: {ws}")
            all_ok = False
        else:
            print(f"✓ Workspace OK: {ws}")
        
        if not mem.exists():
            print(f"✗ Missing memory db: {mem}")
            all_ok = False
        else:
            # Verify DB integrity
            try:
                conn = sqlite3.connect(str(mem))
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                if result[0] != "ok":
                    print(f"✗ Memory DB corruption: {mem}")
                    all_ok = False
                else:
                    print(f"✓ Memory DB OK: {mem}")
                conn.close()
            except Exception as e:
                print(f"✗ Memory DB error: {mem} - {e}")
                all_ok = False
    
    return all_ok

if __name__ == "__main__":
    print("Initializing Hermes Multi-Expert System...")
    print("=" * 50)
    init_workspaces()
    print("=" * 50)
    print("Verifying initialization...")
    if verify_initialization():
        print("=" * 50)
        print("✓ All experts initialized successfully!")
        sys.exit(0)
    else:
        print("=" * 50)
        print("✗ Some components failed to initialize")
        sys.exit(1)
