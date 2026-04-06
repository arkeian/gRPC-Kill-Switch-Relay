import os
import subprocess
import sys


def check_and_regenerate(project_root):
    proto_file = os.path.join(project_root, 'protos', 'killswitch.proto')
    pb2_file = os.path.join(project_root, 'generated', 'killswitch_pb2.py')
    grpc_file = os.path.join(project_root, 'generated', 'killswitch_pb2_grpc.py')

    needs_regen = False
    if not os.path.isfile(pb2_file) or not os.path.isfile(grpc_file):
        needs_regen = True
    elif os.path.getmtime(proto_file) > os.path.getmtime(pb2_file):
        needs_regen = True

    if not needs_regen:
        return

    print("[grus] Proto files are stale or missing. Regenerating...")

    out_dir = os.path.join(project_root, 'generated')
    os.makedirs(out_dir, exist_ok=True)

    proto_dir = os.path.join(project_root, 'protos')

    result = subprocess.run(
        [
            sys.executable, '-m', 'grpc_tools.protoc',
            f'--proto_path={proto_dir}',
            f'--python_out={out_dir}',
            f'--grpc_python_out={out_dir}',
            os.path.join(proto_dir, 'killswitch.proto'),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"[grus] Proto generation failed:\n{result.stderr}")
        sys.exit(1)

    _patch_grpc_imports(grpc_file)

    init_file = os.path.join(out_dir, '__init__.py')
    if not os.path.isfile(init_file):
        open(init_file, 'w').close()

    print("[grus] Proto generation complete.")


def _patch_grpc_imports(grpc_file):
    with open(grpc_file, 'r') as f:
        content = f.read()

    patched = content.replace(
        'import killswitch_pb2 as killswitch__pb2',
        'from generated import killswitch_pb2 as killswitch__pb2',
    )

    if patched != content:
        with open(grpc_file, 'w') as f:
            f.write(patched)
