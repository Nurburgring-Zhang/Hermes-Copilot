#!/usr/bin/env python3
"""
配置验证脚本
"""

import sys
import yaml
from pathlib import Path

def validate_config():
    config_path = Path("~/.hermes/config/worldmonitor.yaml").expanduser()
    
    if not config_path.exists():
        print(f"✗ Config not found: {config_path}")
        return False
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        if not isinstance(config, dict):
            print("✗ Invalid config format")
            return False
        
        # 检查必要字段
        required = ['sources', 'pipelines', 'integrations']
        for field in required:
            if field not in config:
                print(f"⚠ Missing field: {field}")
        
        # 验证源配置
        sources = config.get('sources', {})
        for source_id, source in sources.items():
            if 'type' not in source:
                print(f"✗ Source {source_id} missing 'type'")
                return False
            
            source_type = source['type']
            if source_type == 'rss' and 'url' not in source:
                print(f"✗ RSS source {source_id} missing 'url'")
                return False
            
            if source_type == 'polling' and 'endpoint' not in source:
                print(f"✗ Polling source {source_id} missing 'endpoint'")
                return False
            
            if source_type == 'file_watcher' and 'paths' not in source:
                print(f"✗ File watcher source {source_id} missing 'paths'")
                return False
            
            if source_type == 'script' and 'script_path' not in source:
                print(f"✗ Script source {source_id} missing 'script_path'")
                return False
        
        print("✓ Configuration is valid!")
        print(f"  - {len(sources)} sources configured")
        print(f"  - {len(config.get('pipelines', {}))} pipelines")
        print(f"  - {len(config.get('integrations', {}))} integrations")
        return True
        
    except yaml.YAMLError as e:
        print(f"✗ YAML error: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == '__main__':
    success = validate_config()
    sys.exit(0 if success else 1)
