# Octopus Agent Dockerfile
# Base: ubuntu:24.04 with Python 3.12
# Install pre-built wheel to /octopus

FROM ubuntu:24.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Set timezone to Shanghai
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone

# Set locale to UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales && \
    locale-gen en_US.UTF-8 zh_CN.UTF-8 && \
    update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Install Python 3.12 (Ubuntu 24.04 includes Python 3.12 in default repos)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Install pip for Python 3.12
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Chinese fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    fontconfig \
    && fc-cache -f -v && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install system dependencies and common tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Version control
    git \
    git-lfs \
    # Development tools
    build-essential \
    pkg-config \
    libffi-dev \
    libssl-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    llvm \
    libncurses5-dev \
    libncursesw5-dev \
    # Shell tools
    zsh \
    tmux \
    screen \
    # Python ecosystem
    python3-pip \
    # Node.js (for MCP/npx)
    nodejs \
    npm \
    # Document processing
    pandoc \
    wkhtmltopdf \
    poppler-utils \
    # Media processing
    ffmpeg \
    imagemagick \
    # Network tools
    curl \
    wget \
    httpie \
    jq \
    openssh-client \
    rsync \
    # Archive tools
    zip \
    unzip \
    tar \
    gzip \
    bzip2 \
    xz-utils \
    # Other utilities
    tree \
    htop \
    vim \
    nano \
    sudo \
    ca-certificates \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install bubblewrap (sandbox security, project dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bubblewrap \
    libmariadb-dev \
    libpq-dev \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create installation directory
RUN mkdir -p /octopus

# Copy pre-built wheel file
COPY dist/*.whl /octopus/

# Install wheel to /octopus
RUN pip install --no-cache-dir --break-system-packages --target=/octopus /octopus/*.whl

# Set working directory
WORKDIR /workspace

# Expose port for Web UI (default port from README)
EXPOSE 8765

# Default command
CMD ["python", "/octopus/octopus.py", "--web"]
