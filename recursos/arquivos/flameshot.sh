#!/usr/bin/env bash
# 让 Flameshot 成为默认截图工具：随会话启动，并占用 Print Screen。
#
# 以用户身份运行，在 apt 之后。这里不指向程序目录：安装来自 U 盘，
# 而会话读取的内容留在本机。
#
# Print Screen 调用 ~/.local/bin/d3bian-captura，而不是直接调用 flameshot。
# 如果从“程序”界面移除 Flameshot，按键会自动回退到 XFCE 的截图工具，
# 而不是去调用一个已不存在的程序。
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "请以普通用户身份运行，而不是 root" >&2
  exit 1
fi
if ! command -v flameshot >/dev/null; then
  echo "缺少 flameshot：apt 未安装它" >&2
  exit 1
fi

echo "正在创建截图快捷键"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/d3bian-captura" <<'FIM'
#!/bin/sh
# Print Screen：已安装时用 Flameshot，否则用 XFCE 的截图工具
if command -v flameshot >/dev/null 2>&1; then
  exec flameshot gui
fi
exec xfce4-screenshooter "$@"
FIM
chmod +x "$HOME/.local/bin/d3bian-captura"

echo "Print Screen 现在会打开 Flameshot"
xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/Print" \
  -n -t string -s "$HOME/.local/bin/d3bian-captura"

# 与 Flameshot 自身在勾选“随系统启动”时写入的名称和内容相同；
# 这样那边的勾选框仍然作用于本文件。若程序被移除，TryExec 会让会话跳过该条目。
echo "正在让 Flameshot 随会话启动"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/Flameshot.desktop" <<'FIM'
[Desktop Entry]
Name=flameshot
Icon=flameshot
Exec=flameshot
TryExec=flameshot
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
FIM

# startupLaunch 与上面的自启动项对应；自动启动时每次出现的
# “已在运行”提示只会添乱
ini="$HOME/.config/flameshot/flameshot.ini"
mkdir -p "$(dirname "$ini")"
[ -f "$ini" ] || printf '[General]\n' > "$ini"
grep -q '^\[General\]' "$ini" || printf '[General]\n' >> "$ini"
ini_chave() {
  if grep -q "^$1=" "$ini"; then
    sed -i "s|^$1=.*|$1=$2|" "$ini"
  else
    sed -i "/^\[General\]/a $1=$2" "$ini"
  fi
}
ini_chave startupLaunch true
ini_chave showStartupLaunchMessage false

# 就在本次会话中启动它，不必等下次登录
if [ -n "${DISPLAY:-}" ] && ! pgrep -u "$(id -u)" -x flameshot >/dev/null; then
  setsid -f flameshot >/dev/null 2>&1 </dev/null || true
fi

echo "Flameshot 已就绪：Print Screen 会打开区域选择"
