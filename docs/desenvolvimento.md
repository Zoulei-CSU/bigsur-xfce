# 开发

[← 返回 README](../README.md)

纯 Python 面板（只用标准库），HTML/JS 无依赖。
引擎、服务器和通用界面来自模板；
它们的细节和已知陷阱在模板的 `LEIAME.md` 中。

## 配方

| id | 名称 | 受影响于 |
|---|---|---|
| 00 | backup（备份当前已有的内容） | |
| 10 | Debian 仓库软件包 | |
| 20 | 界面和等宽字体 |  |
| 30 | WhiteSur 窗口主题 | `destaque` |
| 31 | WhiteSur 图标 | |
| 32 | WhiteSur 光标 | |
| 33 | Big Sur 壁纸 | |
| 34 | Qt 程序中的 WhiteSur 主题 | `tema` |
| 38 | macOS 风格的顶栏 | `tema`、`logo`、`menu_global`、`titulo_no_painel` |
| 40 | 主题、字体、按钮和壁纸 | `tema`、`destaque`、`papel_de_parede` |
| 42 | 终端的颜色和透明度 |  |
| 43 | 键盘快捷键 | |
| 44 | 吸附、边框和窗口快捷键 | `janelas`、`tema`、`destaque` |
| 50 | 当前程序的菜单栏 | `menu_global` |
| 60 | 底部 Dock | `dock` |
| 61 | 右键新建终端 | `dock` |
| 70 | Spotlight 风格的程序启动器 | |
| 80 | 桌面上的时钟和状态小组件 | `widget`、`destaque` |
| 90 | 阴影、圆角和透明度 | `efeitos` |
| 95 | Firefox 中的 WhiteSur 主题 | |
| 97 | 登录和锁屏界面 | `destaque`、`papel_de_parede`、`login_fundo`、`login_desfoque`、`login_usuarios` |
| 98 | 屏幕锁定 | `bloqueio` |

选项和接受的值在 `config.py` 中；配方使用的上下文在 `motor.py` 中组装。

## 图像

`docs/imagens` 中的图像来自在 Debian 13 上的测试，是重新生成而非手动编辑的
（README 中 `<!-- imagens -->` 和 `<!-- fim imagens -->` 之间的部分也是如此）。
页面预览（`recursos/web/capturas` 和 `recursos/web/exemplos`）是通用示例；
`capturar` 会用你自己屏幕的照片替换它们。

`recursos/web/papeis` 中的壁纸缩略图会在下载前显示。在从仓库下载新版本后要重新生成：

```sh
for f in ~/.local/share/backgrounds/WhiteSur/*; do
  convert "$f" -resize 320x -strip -quality 78 \
    "recursos/web/papeis/$(basename "${f%.*}").jpg"
done
```
