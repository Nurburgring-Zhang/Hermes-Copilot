#!/usr/bin/env python3
"""
OpenClaw 配置转换工具
将 openclaw.json 转换为 Hermes YAML 配置
"""

import json
import yaml
from pathlib import Path
import sys

base_path = Path("/mnt/c/Users/Administrator/.openclaw")
hermes_path = Path("/home/administrator/.hermes")

def convert_openclaw_config(openclaw_json_path, output_yaml_path):
    """转换 OpenClaw 配置到 Hermes 格式"""
    
    with open(openclaw_json_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # 构建 Hermes 配置
    hermes_config = {
        'version': '1.0',
        'meta': {
            'migrated_from': 'openclaw',
            'source_version': config.get('meta', {}).get('lastTouchedVersion', 'unknown'),
            'migration_date': config.get('meta', {}).get('lastTouchedAt', '')
        },
        'providers': {},
        'default_model': None,
        'fallback_models': [],
        'channels': {},
        'plugins': {},
        'agents': {
            'experts': []
        },
        'routing': {
            'smart_routing': True,
            'prefer_free': True,
            'max_cost_per_request': 1.0
        }
    }
    
    # 转换模型提供商
    if 'models' in config and 'providers' in config['models']:
        for provider_name, provider_config in config['models']['providers'].items():
            hermes_config['providers'][provider_name] = {
                'enabled': True,
                'base_url': provider_config.get('baseUrl'),
                'api_key_env': provider_config.get('apiKey', '').replace('${', '').replace('}', ''),
                'api_type': provider_config.get('api', 'openai-completions'),
                'models': []
            }
            
            for model in provider_config.get('models', []):
                hermes_config['providers'][provider_name]['models'].append({
                    'id': model['id'],
                    'name': model['name'],
                    'reasoning': model.get('reasoning', False),
                    'context_window': model.get('contextWindow', 8192),
                    'max_tokens': model.get('maxTokens', 4096),
                    'cost': model.get('cost', {}),
                    'capabilities': {
                        'text': 'text' in model.get('input', []),
                        'image': 'image' in model.get('input', [])
                    }
                })
    
    # 设置默认模型和回退
    if 'agents' in config and 'defaults' in config['agents']:
        defaults = config['agents']['defaults']
        hermes_config['default_model'] = defaults.get('model', {}).get('primary')
        hermes_config['fallback_models'] = defaults.get('model', {}).get('fallbacks', [])
        
        # 智能路由配置
        hermes_config['routing'].update({
            'prefer_free': True,
            'auto_upgrade': True,
            'satisfaction_threshold': 0.8
        })
    
    # 转换专家代理
    if 'agents' in config and 'list' in config['agents']:
        for agent in config['agents']['list']:
            hermes_config['agents']['experts'].append({
                'id': agent['id'],
                'description': f"OpenClaw {agent['id']} agent",
                'model': agent.get('model'),
                'workspace': agent.get('workspace', str(hermes_path / 'workspace' / agent['id'])),
                'tools': agent.get('tools', {}),
                'capabilities': []
            })
    
    # 转换渠道
    if 'channels' in config:
        for channel, channel_config in config['channels'].items():
            hermes_config['channels'][channel] = {
                'enabled': channel_config.get('enabled', False),
                'type': channel,
                'config': channel_config
            }
    
    # 转换插件
    if 'plugins' in config and 'entries' in config['plugins']:
        for plugin_id, plugin_config in config['plugins']['entries'].items():
            hermes_config['plugins'][plugin_id] = {
                'id': plugin_id,
                'enabled': plugin_config.get('enabled', False),
                'type': 'plugin'
            }
    
    # 保存转换后的配置
    output_path = Path(output_yaml_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(hermes_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    print(f"✅ 配置已转换并保存到: {output_path}")
    print(f"📊 统计:")
    print(f"   模型提供商: {len(hermes_config['providers'])}")
    print(f"   专家代理: {len(hermes_config['agents']['experts'])}")
    print(f"   渠道: {len(hermes_config['channels'])}")
    print(f"   插件: {len(hermes_config['plugins'])}")
    
    return hermes_config

if __name__ == "__main__":
    if len(sys.argv) == 3:
        input_path = sys.argv[1]
        output_path = sys.argv[2]
    else:
        # 默认路径
        input_path = str(base_path / "openclaw.json")
        output_path = str(hermes_path / "config" / "hermes.yaml")
    
    try:
        config = convert_openclaw_config(input_path, output_path)
        print("\n配置验证:")
        print(f"✅ 主模型: {config['default_model']}")
        print(f"✅ 回退模型数: {len(config['fallback_models'])}")
        print(f"✅ 智能路由: {'启用' if config['routing']['smart_routing'] else '禁用'}")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)