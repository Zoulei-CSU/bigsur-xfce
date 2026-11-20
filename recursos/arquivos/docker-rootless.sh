#!/usr/bin/env bash
# 为运行面板的用户配置 Docker 的 rootless 模式。
#
# 以该用户身份运行，而不是 root：rootless 守护进程属于他。少数系统步骤
# 使用 sudo -n，沿用面板已有的授权。
#
# 该用户不加入 docker 组。这个组会与 root 守护进程通信，等同于 root，
# 会抵消 rootless 的好处。
set -euo pipefail

usuario="$(id -un)"
if [ "$(id -u)" -eq 0 ]; then
  echo "请以普通用户身份运行，而不是 root" >&2
  exit 1
fi
if ! command -v dockerd-rootless-setuptool.sh >/dev/null; then
  echo "缺少 dockerd-rootless-setuptool.sh：未安装 docker-ce-rootless-extras" >&2
  exit 1
fi

# rootless 会把容器 id 映射到为用户预留的区间
if ! grep -q "^$usuario:" /etc/subuid || ! grep -q "^$usuario:" /etc/subgid; then
  echo "正在 /etc/subuid 和 /etc/subgid 中为 $usuario 预留 id"
  sudo -n usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$usuario"
fi

# root 守护进程开启时该工具会拒绝继续，而 rootless 也不需要它。
# 保留安装，只是关闭
echo "正在关闭 Docker 的 root 守护进程"
sudo -n systemctl disable --now docker.service docker.socket >/dev/null 2>&1 || true
sudo -n rm -f /var/run/docker.sock

echo "正在安装 rootless 守护进程"
dockerd-rootless-setuptool.sh install

systemctl --user enable --now docker
# 没有 linger 时，会话关闭后守护进程就会停止
sudo -n loginctl enable-linger "$usuario"

# setuptool 会创建 rootless 上下文；使用它就不必在 shell 中设置 DOCKER_HOST
docker context use rootless >/dev/null

if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then
  echo "已为 $usuario 启用 Docker rootless"
else
  echo "rootless 守护进程没有响应；请查看：systemctl --user status docker" >&2
  exit 1
fi
