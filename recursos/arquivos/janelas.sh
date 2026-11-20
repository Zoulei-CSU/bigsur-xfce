#!/usr/bin/env bash
# 将活动窗口定位到屏幕的若干比例区域。
#
# xfwm4 本身已能完成半屏和四分之一屏，快捷键用的就是它。本脚本
# 补上它做不到的：居中以及三等分。
#
#   bigsur-janelas centro          居中，占屏幕 72%
#   bigsur-janelas quase-cheia     占 92%，四周留出间隙
#   bigsur-janelas 2-3-esquerda    靠左三分之二
#   bigsur-janelas 1-3-direita     靠右三分之一
#   bigsur-janelas 2-3-direita     靠右三分之二
#   bigsur-janelas 1-3-esquerda    靠左三分之一
set -u

comando="${1:-}"
[ -z "$comando" ] && { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

for exigido in wmctrl xprop; do
  command -v "$exigido" >/dev/null || { echo "缺少 $exigido：sudo apt install wmctrl x11-utils"; exit 1; }
done

# 可用区域：屏幕减去面板和 dock。以 x、y、宽度、高度表示。
leia_area(){
  local bruto
  bruto="$(xprop -root -notype _NET_WORKAREA 2>/dev/null | sed 's/.*= //;s/,//g')"
  # shellcheck disable=SC2086
  set -- $bruto
  AX="${1:-0}"; AY="${2:-0}"; AW="${3:-0}"; AH="${4:-0}"
  [ "${AW:-0}" -gt 0 ] || { echo "无法读取屏幕可用区域"; exit 1; }
}

# 窗口边框要计入，否则会越出边缘。
leia_moldura(){
  local bruto
  bruto="$(xprop -id "$(xdotool getactivewindow 2>/dev/null)" -notype _NET_FRAME_EXTENTS 2>/dev/null | sed 's/.*= //;s/,//g')"
  # shellcheck disable=SC2086
  set -- $bruto
  ME="${1:-0}"; MD="${2:-0}"; MC="${3:-0}"; MB="${4:-0}"
  case "$ME$MD$MC$MB" in *[!0-9]*|"") ME=0; MD=0; MC=0; MB=0 ;; esac
}

posicionar(){ # posicionar <x> <y> <largura> <altura>
  local x="$1" y="$2" w="$3" h="$4"
  wmctrl -r :ACTIVE: -b remove,maximized_vert,maximized_horz 2>/dev/null
  sleep 0.08
  leia_moldura
  # wmctrl 测量的是内容而非边框；减去边框
  w=$(( w - ME - MD )); h=$(( h - MC - MB ))
  [ "$w" -lt 200 ] && w=200
  [ "$h" -lt 150 ] && h=150
  wmctrl -r :ACTIVE: -e "0,$x,$y,$w,$h"
}

leia_area

case "$comando" in
  centro)
    w=$(( AW * 72 / 100 )); h=$(( AH * 78 / 100 ))
    posicionar $(( AX + (AW - w) / 2 )) $(( AY + (AH - h) / 2 )) "$w" "$h" ;;
  quase-cheia)
    w=$(( AW * 92 / 100 )); h=$(( AH * 92 / 100 ))
    posicionar $(( AX + (AW - w) / 2 )) $(( AY + (AH - h) / 2 )) "$w" "$h" ;;
  2-3-esquerda) posicionar "$AX" "$AY" $(( AW * 2 / 3 )) "$AH" ;;
  1-3-direita)  posicionar $(( AX + AW * 2 / 3 )) "$AY" $(( AW / 3 )) "$AH" ;;
  2-3-direita)  posicionar $(( AX + AW / 3 )) "$AY" $(( AW * 2 / 3 )) "$AH" ;;
  1-3-esquerda) posicionar "$AX" "$AY" $(( AW / 3 )) "$AH" ;;
  *) echo "未知命令：$comando"; sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
