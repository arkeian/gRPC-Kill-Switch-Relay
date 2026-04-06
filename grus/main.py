import argparse
import logging
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        prog='grus',
        description='GRUS - Kill Switch Relay Control Center',
    )
    parser.add_argument(
        '--env',
        default='dev',
        choices=['dev', 'demo', 'prod'],
        help='Environment config to use (default: dev)',
    )
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from grus.config import load_config
    from grus.proto_check import check_and_regenerate
    from grus.process_manager import ProcessManager
    from grus.grpc_client import GrpcClient
    from grus.seed import prompt_and_seed

    cfg = load_config(env=args.env, project_root=project_root)

    log_dir = os.path.join(project_root, cfg.get('logging', {}).get('directory', 'logs'))
    os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, cfg.get('logging', {}).get('level', 'INFO')),
        format='%(asctime)s [grus] %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'grus.log')),
        ],
    )

    print("=" * 60)
    print("  GRUS - Kill Switch Relay Control Center")
    print(f"  Environment: {args.env}")
    print("=" * 60)

    print("\n[grus] Checking protobuf files...")
    check_and_regenerate(project_root)

    print("[grus] Starting services...")
    pm = ProcessManager(cfg)
    pm.start_all()
    print("[grus] All services running.\n")

    client = GrpcClient(cfg)

    prompt_and_seed(cfg, client)

    print("\n[grus] Launching TUI...")

    try:
        from grus.app import GrusApp
        app = GrusApp(cfg=cfg, grpc_client=client, process_manager=pm)
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[grus] Shutting down services...")
        client.close()
        pm.stop_all()
        print("[grus] Goodbye.")


if __name__ == '__main__':
    main()
