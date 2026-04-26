import os
import sys

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli


def load_config(env='dev', project_root=None):
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    config_file = os.path.join(project_root, 'config', f'{env}.toml')
    if not os.path.isfile(config_file):
        print(f"Error: config file not found: {config_file}")
        sys.exit(1)

    with open(config_file, 'rb') as f:
        cfg = tomli.load(f)

    cfg['_project_root'] = project_root
    cfg['_repo_root'] = os.path.dirname(project_root)
    cfg['_config_file'] = config_file
    cfg['_env'] = env

    policy_file = os.path.join(project_root, 'config', 'policy_rules.toml')
    if os.path.isfile(policy_file):
        cfg['_policy_config_file'] = policy_file

    return cfg


def get_service_addr(cfg, service_name):
    svc = cfg.get('services', {}).get(service_name, {})
    host = svc.get('host', 'localhost')
    port = svc.get('port', {'flag_store': 50051, 'policy_evaluator': 50052,
                             'broadcaster': 50053, 'audit_logger': 50054}[service_name])
    return f'{host}:{port}'
