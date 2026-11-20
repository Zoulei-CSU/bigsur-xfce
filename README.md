<div align="center">

<img src="docs/logo.svg" alt="d3bian-init bigsur-xfce" width="420">

**在 Debian 的 Xfce 上做出 macOS Big Sur 的外观：主题、图标、顶栏、Dock 和登录界面。**

[![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)](docs/desenvolvimento.md)
[![无依赖](https://img.shields.io/badge/depend%C3%AAncias-nenhuma-brightgreen)](docs/desenvolvimento.md)
[![Debian 13](https://img.shields.io/badge/Debian-13-A81D33?logo=debian&logoColor=white)](docs/uso.md)
[![Xfce](https://img.shields.io/badge/desktop-Xfce-2284F2?logo=xfce&logoColor=white)](docs/uso.md)
[![MIT 许可证](https://img.shields.io/badge/licen%C3%A7a-MIT-blue)](LICENSE)

</div>

> 一个在浏览器中打开的本地面板，用来准备并调整装有 Xfce 的 Debian，打造受
> macOS Big Sur 启发的视觉：边看边选、应用，想还原时随时恢复原状。
> 只用 Python 标准库——不需要 pip。

```sh
git clone https://github.com/diego-luz/bigsur-xfce.git d3bian_init_bigsur_xfce
python3 -m d3bian_init_bigsur_xfce        # 只询问一次密码，然后打开面板
```

<div align="center">
  <img src="docs/imagens/resultado-instalado.jpg" alt="使用默认选项刚安装后的样子" width="820">
  <br><sub>使用默认选项刚安装后的样子。</sub>
</div>

<details>
<summary><b>英文原文（已译为中文）</b></summary>

一个在浏览器中打开的本地控制面板，为 Debian 上的 Xfce 带来
**macOS Big Sur 的外观**：WhiteSur 主题、图标、光标和壁纸（GTK 和
Qt/Kvantum）、带全局菜单的顶栏、带缩放效果的 Dock（Plank Reloaded）、
Spotlight 风格的启动器（rofi）、桌面小组件、带阴影的圆角窗口、
窗口吸附与布局，以及配套的登录和锁屏界面。

- **来自 Debian 官方仓库的软件包**；Debian 未打包的 WhiteSur 来自其上游 Git
  仓库的固定提交，Plank Reloaded 则来自其官方发布版并校验 SHA-256。
- **可以放心尝试**：每一项改动都有备份和日志；*还原*会把桌面恢复到原来的样子。
- **只用 Python 标准库**：无需 pip，无需构建。

```sh
git clone https://github.com/diego-luz/bigsur-xfce.git d3bian_init_bigsur_xfce
python3 -m d3bian_init_bigsur_xfce        # 只询问一次密码，然后打开面板
```

界面和文档已译为简体中文（原文为巴西葡萄牙语）。

</details>

---

## 它做什么

- 窗口（GTK 和 Qt/Kvantum）上的 **WhiteSur 主题**，浅色或深色，可选强调色
- WhiteSur 的**图标、光标和壁纸**，带壁纸画廊可供挑选
- macOS 风格的**顶栏**，角落有标志，并带当前程序的**全局菜单**
- 带缩放的底部 **Dock**（Plank Reloaded）和 Spotlight 风格的**启动器**（rofi）
- 桌面**小组件**：时钟和进度条，或者圆环
- **窗口**：阴影和圆角、更宽的边框、Super+Z 下的吸附和布局
- 配套的**登录和锁屏界面**，带模糊背景；Firefox 也有主题
- 官方仓库中的**实用程序**，勾选后一次性安装
- 一键**还原到原来的样子**，包括移除已安装的内容

<!-- 图片：来自在 Debian 13 上的测试；重新生成，不要手动编辑 -->
## 截图

| 使用页面上的其他选项 | 另一组选项组合 |
|---|---|
| ![使用页面上的其他选项](docs/imagens/resultado-opcao.jpg) | ![另一组选项组合](docs/imagens/resultado-opcao2.jpg) |

| 首页 | 选项 | 实用程序 |
|---|---|---|
| ![首页](docs/imagens/painel-inicio.jpg) | ![选项](docs/imagens/painel-opcoes.jpg) | ![实用程序](docs/imagens/painel-programas.jpg) |

<details>
<summary><b>通过页面安装的整个过程，从开始到结果</b></summary>

![通过页面安装的整个过程，从开始到结果](docs/imagens/instalacao.gif)

</details>
<!-- fim imagens -->

## 文档

| | |
|---|---|
| 🚀 [使用](docs/uso.md) | 运行、通过面板安装、还原到原来的样子 |
| 🛠️ [开发](docs/desenvolvimento.md) | 配方、图像和缩略图如何生成 |

## d3bian-init 家族

全部使用同一引擎和同一种用法：一个本地面板、只用 Python 标准库，以及“还原到原来的样子”。

| | 项目 | 做什么 |
|---|---|---|
| 🪟 | **bigsur-xfce** · [bigsur-minimalista-xfce](https://github.com/diego-luz/bigsur-minimalista-xfce) | 在 Xfce 上做出 macOS Big Sur 的外观，完整或极简 |
| 🪟 | [minimal-xfce](https://github.com/diego-luz/minimal-xfce) · [paleta-xfce](https://github.com/diego-luz/paleta-xfce) | 精简的 Xfce，或只用一种配色（Nord、Gruvbox、Everforest） |
| 🪟 | [oasis-xfce](https://github.com/diego-luz/oasis-xfce) | 岛屿式 Xfce，带 picom 模糊、rofi 网格和沙丘，只用官方仓库 |

Xfce 主题（🪟）一次只能装一个：已安装另一个时，安装会被拒绝，而 `aplicar --trocar`（或面板上的按钮）会还原另一个并安装这个（[详情](docs/uso.md#一次只使用一个-xfce-主题)）。

## 致谢

d3bian-init-bigsur-xfce 不创建主题：它下载、安装并调整他人的成果。
一切视觉上的功劳都属于他们。

| 项目 | 项目 | 作者 | 许可证 |
|---|---|---|---|
| GTK 主题 | [WhiteSur-gtk-theme](https://github.com/vinceliuice/WhiteSur-gtk-theme) | vinceliuice | MIT |
| 图标 | [WhiteSur-icon-theme](https://github.com/vinceliuice/WhiteSur-icon-theme) | vinceliuice | GPL-3.0 |
| 光标 | [WhiteSur-cursors](https://github.com/vinceliuice/WhiteSur-cursors) | vinceliuice | GPL-3.0 |
| 壁纸 | [WhiteSur-wallpapers](https://github.com/vinceliuice/WhiteSur-wallpapers) | vinceliuice | MIT |
| Qt 主题（Kvantum） | [WhiteSur-kde](https://github.com/vinceliuice/WhiteSur-kde) | vinceliuice | GPL-3.0 |
| Firefox 主题 | [WhiteSur-firefox-theme](https://github.com/vinceliuice/WhiteSur-firefox-theme) | vinceliuice | MIT |
| 启动器主题 | [rofi](https://github.com/adi1090x/rofi) | adi1090x | GPL-3.0 |
| Dock | [plank-reloaded](https://github.com/zquestz/plank-reloaded) | zquestz | GPL-3.0 |
| Inter 字体 | Debian 的 `fonts-inter` 包 | Rasmus Andersson | OFL-1.1 |
| 圆环小组件 | [MX-CoreBlue](https://github.com/MX-Linux/mx-conky-data/tree/master/MX-CoreBlue)，基于 Clock Rings | MX Linux；londonali1010、despot77 和 Altin | GPL-3.0（此处的 `conky-aneis.lua` 和 `conky-aneis.conf` 文件同样如此） |
| 圆环小组件的构想 | [Xfce Big Sur setup](https://www.opencode.net/lsteam/xfce-big-sur-setup-file) | lsteam | |

`recursos/web/papeis` 中的缩略图和页面预览展示的是 WhiteSur-wallpapers 的壁纸。

XFCE、LightDM、light-locker、picom、Conky、Kvantum、全局菜单及其他
软件包都来自 Debian 官方仓库。

## 声明

独立项目，与 Apple、Debian 或 NBCUniversal 无关。
macOS 和 Big Sur 是 Apple Inc. 的商标。Debian 是
Software in the Public Interest, Inc. 的商标。Mr. Robot 和 fsociety 是
NBCUniversal 的商标。

---

<div align="center">
<sub>代码采用 <a href="LICENSE">MIT 许可证</a>，圆环小组件除外（GPL-3.0） · 为 Debian 13 打造</sub>
</div>
