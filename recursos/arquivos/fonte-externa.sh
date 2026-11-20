#!/usr/bin/env bash
# 启用一个非 Debian 的软件源。
#
#   fonte-externa.sh microsoft-vscode
#
# 每个源都在此文件内描述，而不来自外部，这样程序可能添加到 apt 的内容
# 都集中在一个可读的文件里。以 root 运行。
set -euo pipefail

fonte="${1:-}"

case "$fonte" in
  microsoft-vscode)
    url_chave="https://packages.microsoft.com/keys/microsoft.asc"
    chaveiro="/usr/share/keyrings/microsoft-vscode.gpg"
    lista="/etc/apt/sources.list.d/microsoft-vscode.list"
    linha="deb [arch=amd64,arm64,armhf signed-by=$chaveiro] https://packages.microsoft.com/repos/code stable main"
    # Microsoft 密钥的指纹；地址中若有其他密钥会被拒绝
    impressao="BC528686B50D79E339D3721CEB3E94ADBE1229CF"
    origem="packages.microsoft.com"
    pacotes="code"
    ;;
  docker)
    # 与 get.docker.com 配置的仓库相同，但不运行外部脚本
    url_chave="https://download.docker.com/linux/debian/gpg"
    chaveiro="/usr/share/keyrings/docker.gpg"
    lista="/etc/apt/sources.list.d/docker.list"
    versao="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    linha="deb [arch=$(dpkg --print-architecture) signed-by=$chaveiro] https://download.docker.com/linux/debian $versao stable"
    impressao="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
    origem="download.docker.com"
    pacotes="docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras"
    ;;
  *)
    echo "未知软件源：$fonte" >&2
    exit 2
    ;;
esac
# 外部仓库只提供它自己的软件包：其他任何包都不来自它
# （优先级 -1），只有本源的包（500，与 Debian 的相同）
preferencias="/etc/apt/preferences.d/$fonte"

# 没有 gpg 就无法验证密钥所有者：先安装它（来自 Debian）；
# 若仍不行，则什么都不加入 apt
if ! command -v gpg >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gpg >/dev/null 2>&1 || true
fi
command -v gpg >/dev/null || { echo "缺少 gpg：无法验证密钥；未添加任何内容" >&2; exit 1; }
tmp="$(mktemp)"
binaria="$(mktemp)"
gpg_casa="$(mktemp -d)"
trap 'rm -rf "$tmp" "$binaria" "$gpg_casa"' EXIT
# 校验密钥环：恰好一个公钥，且具有预期指纹
so_a_esperada() {
  local lista
  lista="$(GNUPGHOME="$gpg_casa" gpg --show-keys --with-colons "$1" 2>/dev/null || true)"
  [ "$(grep -c '^pub:' <<< "$lista" || true)" = 1 ] \
    && [ "$(awk -F: '/^fpr/{print $10; exit}' <<< "$lista")" = "$impressao" ]
}

if [ -f "$chaveiro" ] && [ -f "$lista" ]; then
  # 已有的密钥环也必须只有预期密钥，且密钥环中仅此一个
  if ! so_a_esperada "$chaveiro"; then
    echo "密钥环 $chaveiro 并非只含预期密钥（$impressao）；继续前请检查" >&2
    exit 1
  fi
  echo "软件源 $fonte 已配置"
else
  echo "正在下载来自 $url_chave 的密钥"
  curl -fsSL --max-time 40 "$url_chave" -o "$tmp"
  [ -s "$tmp" ] || { echo "密钥为空" >&2; exit 1; }
  # 只有具有预期指纹的密钥才进入 apt：同一文件中隐藏的第二个密钥
  # 也会开始为仓库签名
  GNUPGHOME="$gpg_casa" gpg --batch --quiet --import "$tmp" 2>/dev/null || true
  GNUPGHOME="$gpg_casa" gpg --batch --export "$impressao" > "$binaria" 2>/dev/null || true
  if ! [ -s "$binaria" ] || ! so_a_esperada "$binaria"; then
    echo "来自 $fonte 的密钥并非预期密钥（$impressao）；未向 apt 添加任何内容" >&2
    exit 1
  fi

  # 把密钥存入专属密钥环，并用 signed-by 将源绑定到它，
  # 使该密钥不会验证系统中的其他仓库
  install -m 0644 "$binaria" "$chaveiro"

  printf '%s\n' "$linha" > "$lista"
  chmod 0644 "$lista"
  echo "软件源已添加到 $lista"
fi

# 旧版本把仓库其余部分留为优先级 100：现在换掉
antiga="$(printf 'Package: *\nPin: origin %s\nPin-Priority: 100\n\nPackage: %s\nPin: origin %s\nPin-Priority: 500' "$origem" "$pacotes" "$origem")"
if [ ! -f "$preferencias" ] || [ "$(cat "$preferencias")" = "$antiga" ]; then
  {
    printf 'Package: *\nPin: origin %s\nPin-Priority: -1\n\n' "$origem"
    printf 'Package: %s\nPin: origin %s\nPin-Priority: 500\n' "$pacotes" "$origem"
  } > "$preferencias"
  chmod 0644 "$preferencias"
  echo "该源只提供：$pacotes（$preferencias）"
fi

echo "仅更新此源的索引"
apt-get update -o Dir::Etc::sourcelist="$lista" \
               -o Dir::Etc::sourceparts="-" \
               -o APT::Get::List-Cleanup="0"
echo "完成"
