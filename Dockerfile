# Dockerfile
# 继承 Dev Container 的基础镜像
ARG VARIANT="3.13"
FROM mcr.microsoft.com/devcontainers/python:${VARIANT}

# 设置非 root 用户
ARG USERNAME=vscode

# 运行命令手动安装系统依赖
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    ffmpeg \
    libturbojpeg0 \
    libpcap-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
    
# 切换回默认用户
USER ${USERNAME}