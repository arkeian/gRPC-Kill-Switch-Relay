import os
import tomllib

_DEFAULT_TOML = '''\
[server]
host     = "localhost"
port     = 8080
log_file = "logs/surg.log"

[operator]
name = ""

[grus]
executable = "grus"

[grus.services]
flag_store       = "localhost:50051"
policy_evaluator = "localhost:50052"
broadcaster      = "localhost:50053"
audit_logger     = "localhost:50054"

[behavior]
idle_timeout_minutes     = 60
shutdown_warning_seconds = 60
'''


def load_config(surg_dir: str) -> tuple[dict, str]:
    config_path = os.path.join(surg_dir, 'surg.toml')
    if not os.path.isfile(config_path):
        with open(config_path, 'w') as f:
            f.write(_DEFAULT_TOML)
        print(f'[surg] Created default config at {config_path}')
    with open(config_path, 'rb') as f:
        cfg = tomllib.load(f)
    return cfg, config_path


def ensure_operator_name(cfg: dict, config_path: str) -> dict:
    name = cfg.get('operator', {}).get('name', '').strip()
    if name:
        return cfg
    print('[surg] First run: enter your operator name (recorded in all audit logs).')
    while not name:
        try:
            name = input('Operator name: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\n[surg] No operator name given — defaulting to "surg-operator".')
            name = 'surg-operator'
    _patch_operator_name(config_path, name)
    if 'operator' not in cfg:
        cfg['operator'] = {}
    cfg['operator']['name'] = name
    return cfg


def _patch_operator_name(config_path: str, name: str) -> None:
    with open(config_path, 'r') as f:
        content = f.read()
    content = content.replace('name = ""', f'name = "{name}"', 1)
    with open(config_path, 'w') as f:
        f.write(content)
