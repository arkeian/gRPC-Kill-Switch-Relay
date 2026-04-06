import os
import sqlite3

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli


def needs_seeding(cfg):
    db_path = cfg.get('services', {}).get('flag_store', {}).get('db_path', 'data/flags.db')
    full_path = os.path.join(cfg['_project_root'], db_path)

    if not os.path.isfile(full_path):
        return True

    try:
        conn = sqlite3.connect(full_path)
        cursor = conn.execute('SELECT COUNT(*) FROM flags')
        count = cursor.fetchone()[0]
        conn.close()
        return count == 0
    except Exception:
        return True


def load_seed_flags(cfg):
    seed_cfg = cfg.get('seed_data', {})
    seed_file = seed_cfg.get('file', 'config/seed_flags.toml')
    full_path = os.path.join(cfg['_project_root'], seed_file)

    if not os.path.isfile(full_path):
        return []

    with open(full_path, 'rb') as f:
        data = tomli.load(f)

    return data.get('flags', [])


def prompt_and_seed(cfg, grpc_client):
    if not needs_seeding(cfg):
        return

    seed_cfg = cfg.get('seed_data', {})
    if not seed_cfg.get('auto_prompt', True):
        return

    flags = load_seed_flags(cfg)
    if not flags:
        return

    print("\n[grus] No existing flags found.")
    answer = input("[grus] Load default demo flags? (y/n): ").strip().lower()
    if answer != 'y':
        print("[grus] Skipping seed data.")
        return

    print(f"[grus] Seeding {len(flags)} demo flags...")
    for flag_data in flags:
        try:
            grpc_client.set_flag(
                name=flag_data['name'],
                enabled=flag_data.get('enabled', False),
                description=flag_data.get('description', ''),
                changed_by='grus-seed',
                reason='Initial seed from seed_flags.toml',
            )
            state = "enabled" if flag_data.get('enabled', False) else "disabled"
            print(f"  -> {flag_data['name']} ({state})")
        except Exception as e:
            print(f"  -> FAILED {flag_data['name']}: {e}")

    print("[grus] Seeding complete.")
