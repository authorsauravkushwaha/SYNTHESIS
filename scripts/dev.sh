#!/usr/bin/env bash
# Run the SYNTHESIS MVP locally.
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -r requirements.txt
exec uvicorn server.main:app --host 0.0.0.0 --port 8000
