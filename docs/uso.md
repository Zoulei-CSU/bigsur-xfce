# 使用 d3bian-init-bigsur-xfce

[← 返回 README](../README.md)

## 运行

克隆时让文件夹名与 Python 包名一致（用 `_`），并在包含 `d3bian_init_bigsur_xfce`
的文件夹中将其作为模块运行：

```sh
git clone https://github.com/diego-luz/bigsur-xfce.git d3bian_init_bigsur_xfce
python3 -m d3bian_init_bigsur_xfce          # 在浏览器中打开面板
python3 -m d3bian_init_bigsur_xfce --help   # 终端子命令
```

面板会在 `http://127.0.0.1:8730` 打开。

## 通过面板安装

![通过页面安装的整个过程，从开始到结果](imagens/instalacao.gif)

1. `python3 -m d3bian_init_bigsur_xfce` 会在浏览器中打开页面（在终端中询问一次管理员密码）。
2. 在 **外观** 中挑选选项并点击 **全部安装**；每一步的进度会实时显示。
3. 之后更改某个选项并 **应用**，只会重新运行受影响的步骤。
4. **还原到原来的样子** 会撤销一切；勾选 **同时移除已安装的内容** 还会卸载软件包。

## 一次只使用一个 Xfce 主题

家族中的 Xfce 主题（bigsur-xfce、bigsur-minimalista-xfce、minimal-xfce、
paleta-xfce 和 oasis-xfce）使用相同的脚本（`d3bian-janelas`、
`d3bian-layouts`、`d3bian-bordas`、`d3bian-picom`）、相同的 `picom.conf`
以及相同的面板、xfwm4、快捷键和 GTK 调整。一个叠在另一个上会破坏第一个的“还原”，
所以只要另一个主题仍应用在本账户上，安装就会被拒绝（退出码 1）：

```
主题 oasis-xfce 已安装在本账户中；请先使用它的“还原”（python3 -m d3bian_init_oasis_xfce restaurar），或用 python3 -m d3bian_init_bigsur_xfce aplicar --trocar 直接切换
```

若主题在 `~/.local/state/<pasta>/aplicado/` 中留有步骤标记，或在 `diario.jsonl`
中有比该文件夹更新的记录，就算作已应用：仅模拟不算，完整的 `restaurar` 之后也不再算。
重新运行同一个项目（`aplicar --refazer`、`config`、`restaurar`）照常进行，
`aplicar --simular` 只做提示。

要一次完成切换：`python3 -m d3bian_init_bigsur_xfce aplicar --trocar`，或在面板中点击
**还原 … 并安装这个** 按钮（会请求确认）。切换会通过另一个主题自己的项目运行它的
`restaurar --sim`（它的软件包会保留），只有另一个主题无错误还原后才安装这个。
另一个项目会在与本项目相同的文件夹中（并排克隆）以及 Python 能找到的位置查找；
如果找不到，切换会停止并显示需要手动运行的命令。

## 还原到原来的样子

在“外观”中点击 **还原到原来的样子**，或在命令行运行 `restaurar --sim`。
每一步都会把改动记录到日志（`~/.local/state/<projeto>/diario.jsonl`），
撤销时从后往前遍历日志：新建的文件删除，原本存在的文件从备份恢复，
区块从文件中移除，xfconf、gsettings 和 dconf 恢复到之前的值，扩展恢复到此前的列表。
脚本用 `d3_antes`、`d3_xfconf`、`d3_gsettings`、
`d3_dconf`、`d3_criado` 和 `d3_pacotes` 在动手前做记录；连这些也覆盖不到的
（整个 XFCE 栏、GDM 登录界面）则放在配方自身的 `[[desfazer]]` 中。

使用 **同时移除已安装的内容**（`restaurar --sim --apagar`）时，
项目通过 apt 安装的内容和项目文件夹也会被删除；页面会事先显示列表。
早于日志的安装：只会恢复备份。
详情见模板的 `LEIAME.md`。
