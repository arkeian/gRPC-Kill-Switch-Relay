#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROTO_DIR="$REPO_ROOT/protos"
OUT_DIR="$REPO_ROOT/generated"

echo "==> Installing gRPC dependencies..."
pip install grpcio grpcio-tools protobuf

echo "==> Generating Python stubs from killswitch.proto..."
mkdir -p "$OUT_DIR"
python -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "$PROTO_DIR/killswitch.proto"

echo "==> Patching generated imports for package-style usage..."
sed -i 's/^import killswitch_pb2 as killswitch__pb2$/from generated import killswitch_pb2 as killswitch__pb2/' "$OUT_DIR/killswitch_pb2_grpc.py"

echo "==> Creating __init__.py in generated/..."
touch "$OUT_DIR/__init__.py"

echo "==> Verifying output..."
EXPECTED_FILES=(
    "$OUT_DIR/killswitch_pb2.py"
    "$OUT_DIR/killswitch_pb2_grpc.py"
)

for f in "${EXPECTED_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        echo "    OK  $f"
    else
        echo "    MISSING  $f"
        exit 1
    fi
done

echo ""
echo "Proto generation complete."
