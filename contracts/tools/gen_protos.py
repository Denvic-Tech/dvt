import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PROTO_SRC = ROOT / "protos"
PY_OUT = ROOT / "src"

if not PROTO_SRC.exists():
    sys.exit(f"[ERROR] protos source folder not found: {PROTO_SRC}")

print(f"[contracts] Generating from {PROTO_SRC} → {PY_OUT}")

protos = sorted(PROTO_SRC.rglob("*.proto"))
if not protos:
    sys.exit("[ERROR] no .proto files found under protos/")

for folder in {p.parent for p in protos}:
    pkg_dir = PY_OUT / folder.relative_to(PROTO_SRC)
    pkg_dir.mkdir(parents=True, exist_ok=True)

    for sub in [pkg_dir] + list(pkg_dir.parents):
        if PY_OUT not in sub.parents and sub != PY_OUT:
            break
        init_file = sub / "__init__.py"
        if not init_file.exists():
            init_file.touch()

cmd = [
    sys.executable, "-m", "grpc_tools.protoc",
    "-I", str(PROTO_SRC),
    "--python_out", str(PY_OUT),
    "--grpc_python_out", str(PY_OUT),
    "--mypy_out", str(PY_OUT),
    *map(str, protos),
]
print("Running:", " ".join(cmd))
subprocess.check_call(cmd)
print("✅ Generation done!")
