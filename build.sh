#!/bin/bash
set -e

IMAGE_NAME="${IMAGE_NAME:-octopus-agent}"
VENV_DIR=".venv"
WHEEL_DIR="dist"

# Create venv if not exists
if [ ! -d "${VENV_DIR}" ]; then
    echo "=== Creating virtual environment ==="
    python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"

echo "=== Installing build tool ==="
pip install build

echo "=== Building wheel ==="
python -m build

deactivate

echo "=== Building Docker image ==="
docker build -t "${IMAGE_NAME}" .

echo "=== Done ==="
echo "Run with: docker run -d -p 8765:8765 ${IMAGE_NAME}"
