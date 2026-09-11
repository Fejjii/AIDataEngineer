# Optional custom Cloud Agent image for AIDataEngineer (OPS003).
#
# Validated Cloud path: Cursor's default Ubuntu 24.04 image plus
# scripts/verify_environment.sh --bootstrap and --start. Nested Docker is
# not available in this Cloud VM, and the dashboard draft-build contract
# accepts only install/start/snapshot. This Dockerfile is therefore *not*
# referenced from environment.json until a later ops task can build-test it.
#
# It records the same system packages the bootstrap script installs so a later
# custom-image effort does not invent a different stack.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        build-essential \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        libpq-dev \
        postgresql-16 \
        postgresql-client-16 \
        postgresql-contrib \
        sudo \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

RUN id ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash ubuntu \
    && printf 'ubuntu ALL=(ALL) NOPASSWD:ALL\n' >/etc/sudoers.d/ubuntu \
    && chmod 0440 /etc/sudoers.d/ubuntu

USER ubuntu
WORKDIR /workspace
