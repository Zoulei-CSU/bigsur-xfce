"""用户偏好。

单个 JSON 文件，值会对照选项表进行校验。该校验同时用于终端和网页：不在表中
的任何值都会在到达引擎之前被拒绝。
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import caminhos


class Opcao:
    """一项偏好：它接受什么、默认值以及用途。"""

    def __init__(self, chave: str, padrao: str, valores: tuple[str, ...],
                 titulo: str, ajuda: str = "", livre: str = "") -> None:
        self.chave = chave
        self.padrao = padrao
        self.valores = valores
        self.titulo = titulo
        self.ajuda = ajuda
        # 描述列表之外可接受值的表达式；为空表示只有列表有效
        self.livre = livre

    def valida(self, valor: Any) -> bool:
        if not isinstance(valor, str) or not valor:
            return False
        if valor in self.valores:
            return True
        return bool(self.livre) and bool(re.fullmatch(self.livre, valor))

    def como_dict(self) -> dict:
        return {"chave": self.chave, "padrao": self.padrao,
                "valores": list(self.valores), "titulo": self.titulo,
                "ajuda": self.ajuda, "livre": bool(self.livre)}


SIM_NAO = ("sim", "nao")

OPCOES: tuple[Opcao, ...] = (
    Opcao("tema", "escuro", ("claro", "escuro"),
          "主题", "窗口和顶栏的颜色"),
    Opcao("destaque", "padrao",
          ("padrao", "azul", "roxo", "rosa", "vermelho", "laranja", "amarelo", "verde", "cinza"),
          "强调色", "按钮和选中项的颜色"),
    Opcao("logo", "debian",
          ("debian", "debian-cor", "tux", "tux-cor"),
          "角落标志", "打开应用菜单的按钮"),
    Opcao("menu_global", "sim", SIM_NAO,
          "顶部菜单栏", "当前程序的菜单，如同 macOS"),
    Opcao("dock", "sim", SIM_NAO,
          "底部 Dock", "带缩放的快捷栏。中键（或 Ctrl + 单击）打开程序的另一个窗口；"
          "在终端中，右键有“新建窗口”和“新建标签页”"),
    # "sim" 是简单组件，保留该名称以免让已保存的配置失效；
    # "aneis" 来自 lsteam 的 Xfce Big Sur 设置
    Opcao("widget", "sim", ("sim", "aneis", "nao"),
          "桌面组件",
          "简单：时钟和进度条。圆环：模拟时钟、进程和网络"),
    Opcao("efeitos", "sim", SIM_NAO,
          "阴影和圆角", "会略微增加显卡负担"),
    Opcao("janelas", "sim", SIM_NAO,
          "窗口平铺", "更宽的边框、快捷键和 Super+Z 布局。"
          "Alt + 拖动移动窗口，Alt + 右键拖动调整大小"),
    Opcao("titulo_no_painel", "nao", SIM_NAO,
          "面板中的窗口标题", "最大化窗口会在栏中显示标题和按钮"),
    # 全新安装的机器没有需要保留的壁纸，因此默认跟随主题；
    # 已经选好壁纸的人改为“保留”
    # 除保留和跟随主题外，也接受图库中的文件名
    Opcao("papel_de_parede", "do-tema", ("do-tema", "manter"),
          "壁纸", "从图库中选择一张，或保留你现有的",
          livre=r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}"),
    # 登录界面：除桌面和跟随主题外，也接受图库中的名称
    Opcao("login_fundo", "desktop", ("desktop", "do-tema", "propria"),
          "登录界面背景", "与桌面相同、来自图库，或你自己的图片",
          livre=r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}"),
    Opcao("login_desfoque", "sim", SIM_NAO,
          "背景模糊", "输入框后的图片会变模糊，如同 macOS"),
    Opcao("login_escurecer", "10", ("0", "10", "20", "30", "40", "50", "60"),
          "背景变暗", "输入框后的背景变暗程度：0 显示原图"),
    Opcao("login_usuarios", "campos", ("campos", "lista"),
          "登录方式", "输入用户名和密码，或从列表中选择用户"),
    # 默认值与 Debian 用 light-locker 的现有行为一致：十分钟后熄屏并随即锁定
    Opcao("bloqueio", "10", ("nao", "5", "10", "15", "30"),
          "屏幕锁定", "闲置若干分钟及挂起后要求输入密码"),
)

POR_CHAVE = {o.chave: o for o in OPCOES}


def padroes() -> dict[str, str]:
    return {o.chave: o.padrao for o in OPCOES}


def ler() -> dict[str, str]:
    """在默认值之上叠加用户配置，忽略无效内容。"""
    valores = padroes()
    try:
        salvo = json.loads(caminhos.CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return valores
    if not isinstance(salvo, dict):
        return valores
    for chave, valor in salvo.items():
        opcao = POR_CHAVE.get(chave)
        if opcao and opcao.valida(valor):
            valores[chave] = valor
    return valores


def gravar(novos: dict[str, Any]) -> list[str]:
    """只保存有效且有变化的内容。返回被更改的键。"""
    atual = ler()
    mudou = []
    for chave, valor in novos.items():
        opcao = POR_CHAVE.get(chave)
        if opcao and opcao.valida(valor) and atual.get(chave) != valor:
            atual[chave] = valor
            mudou.append(chave)
    if mudou:
        caminhos.preparar()
        caminhos.escrever(caminhos.CONFIG, json.dumps(atual, ensure_ascii=False, indent=2) + "\n")
    return mudou


def filtrar(bruto: dict[str, Any]) -> dict[str, str]:
    """只保留已知且值可接受的键。"""
    return {c: v for c, v in bruto.items()
            if c in POR_CHAVE and POR_CHAVE[c].valida(v)}
