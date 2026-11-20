#!/bin/sh
# 由 ~/.xprofile 加载：让 GTK 程序把菜单导出到面板。
case ":$GTK_MODULES:" in
  *:appmenu-gtk-module:*) ;;
  *) GTK_MODULES="${GTK_MODULES:+$GTK_MODULES:}appmenu-gtk-module"; export GTK_MODULES ;;
esac
export UBUNTU_MENUPROXY=1
