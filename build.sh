#!/bin/bash
set -e

IMAGE_NAME="${IMAGE_NAME:-octopus-agent}"
DOCKER_REPO="${DOCKER_REPO:-}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
VENV_DIR=".venv"
WHEEL_DIR="dist"

# Create venv if not exists
if [ ! -d "${VENV_DIR}" ]; then
    echo "=== Creating virtual environment ==="
    python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"

echo "=== Installing build tool ==="
pip install build --quiet

echo "=== Building wheel ==="
python -m build

deactivate

if [ -n "${DOCKER_REPO}" ]; then
    # Multi-arch build + push to Docker Hub
    echo "=== Multi-arch build (${PLATFORMS}) ==="
    echo "=== Target: ${DOCKER_REPO} ==="

    if ! docker buildx version &>/dev/null; then
        echo "Error: docker buildx not available. Install Docker 19.03+ or use IMAGE_NAME for local build."
        exit 1
    fi

    # Ensure QEMU binfmt handlers are installed for cross-arch emulation
    docker run --privileged --rm tonistiigi/binfmt --install all &>/dev/null || true

    # Create or reuse multiarch builder
    if ! docker buildx inspect multiarch &>/dev/null; then
        docker buildx create --use --name multiarch --driver docker-container
    else
        docker buildx use multiarch
    fi

    TAG_DATE=$(date +%Y%m%d)
    docker buildx build \
        --platform "${PLATFORMS}" \
        -t "${DOCKER_REPO}:latest" \
        -t "${DOCKER_REPO}:${TAG_DATE}" \
        --push \
        .

    echo "=== Pushed to ${DOCKER_REPO}:latest / ${DOCKER_REPO}:${TAG_DATE} ==="
    echo "Pull with: docker pull ${DOCKER_REPO}:latest"
else
    # Local single-arch build (compatible with old usage)
    echo "=== Building Docker image (local, single-arch) ==="
    docker build -t "${IMAGE_NAME}" .

    echo "=== Done ==="
    echo "Run with: docker run -d -p 8765:8765 ${IMAGE_NAME}"
fi
