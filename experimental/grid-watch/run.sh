#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
if [ -x "$project_dir/.venv/bin/python" ]; then
  exec "$project_dir/.venv/bin/python" "$script_dir/server.py" "$@"
fi
exec python3 "$script_dir/server.py" "$@"
