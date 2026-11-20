"""d3bian-init 系列的 Xfce 主题无法在同一账户中共存。

它们都使用相同的名称和调整项：~/.local/bin 中的 d3bian-janelas、d3bian-layouts、
d3bian-bordas 和 d3bian-picom 脚本，picom.conf 及其自启动，xfce4 面板，xfwm4 的
主题和边距，键盘快捷键以及 gtk。安装第二个主题会覆盖第一个，而第一个的“还原”
随后会删除第二个使用的脚本或在它下面恢复设置。因此在已应用同族另一主题时会
拒绝安装；本主题的重做、config 和还原仍可执行。

切换（aplicar --trocar，或面板按钮）通过另一个主题自己的项目运行其还原，该项目
知道配方、可删除内容列表和已保存的备份；它的软件包保留。只有另一个主题完整
还原后（退出码 0），才安装本主题。

相同的文件出现在全部五个项目中。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import caminhos

# 状态目录（在 ~/.local/state 中）->（主题名称、python 模块）
FAMILIA_XFCE = {
    "d3bian-init": ("bigsur-xfce", "d3bian_init_bigsur_xfce"),
    "d3bian-init-bigsur-minimalista": ("bigsur-minimalista-xfce", "d3bian_init_bigsur_minimalista_xfce"),
    "d3bian-init-minimal-xfce": ("minimal-xfce", "d3bian_init_minimal_xfce"),
    "d3bian-init-paleta-xfce": ("paleta-xfce", "d3bian_init_paleta_xfce"),
    "d3bian-init-oasis-xfce": ("oasis-xfce", "d3bian_init_oasis_xfce"),
}


def _mtime(caminho: Path) -> int:
    try:
        return caminho.stat().st_mtime_ns
    except OSError:
        return 0


def aplicado(pasta: Path) -> bool:
    """该状态目录对应的主题改动过账户且尚未撤销。

    以 aplicado/ 中的已应用配方标记计数，或以比 aplicado/ 目录更新的日志行为准：
    restaurar 会删除标记并让目录带上其时间，但保留日志（移除时仍会读取）。仅
    模拟只留下 registro.log，不算数。"""
    marcas = pasta / "aplicado"
    try:
        if any(m.is_file() for m in marcas.iterdir()):
            return True
    except OSError:
        pass
    diario = pasta / "diario.jsonl"
    if _mtime(diario) <= _mtime(marcas):
        return False
    try:
        with diario.open(encoding="utf-8", errors="replace") as arquivo:
            for linha in arquivo:
                try:
                    if isinstance(json.loads(linha), dict):
                        return True
                except ValueError:
                    continue
    except OSError:
        pass
    return False


def outro_aplicado() -> tuple[str, str] | None:
    """本账户中已应用的另一个同族主题的 (名称, 模块)，否则为 None。
    本主题已应用时无需拒绝：切换已经发生，重做、config 和还原需要继续。"""
    proprio = caminhos.ESTADO_DIR
    if aplicado(proprio):
        return None
    for nome_pasta, (nome, modulo) in FAMILIA_XFCE.items():
        if nome_pasta != proprio.name and aplicado(proprio.parent / nome_pasta):
            return nome, modulo
    return None


def recusa() -> str:
    """拒绝消息；可以安装时为空。"""
    outro = outro_aplicado()
    if not outro:
        return ""
    nome, modulo = outro
    return (f"主题 {nome} 已安装在本账户中；请先使用它的“还原” "
            f"(python3 -m {modulo} restaurar)，或用 "
            f"python3 -m {caminhos.PACOTE.name} aplicar --trocar 直接切换")


def localizar(modulo: str) -> Path | None:
    """另一个项目运行的目录（放入 PYTHONPATH 的那个）。

    先找与本项目相邻的（项目并排，如从 git 克隆时），再找 Python 自行找到的
    （安装在系统中）。状态目录不记录项目运行自何处。"""
    pai = caminhos.PACOTE.parent
    if (pai / modulo / "__main__.py").is_file() and (pai / modulo / "desfazer.py").is_file():
        return pai
    try:
        achado = importlib.util.find_spec(modulo)
    except (ImportError, ValueError):
        achado = None
    if achado and achado.origin:
        pasta = Path(achado.origin).parent
        if (pasta / "__main__.py").is_file() and (pasta / "desfazer.py").is_file():
            return pasta.parent
    return None


def para_pagina() -> dict | None:
    """已应用的另一个主题，供面板提供切换。"""
    outro = outro_aplicado()
    if not outro:
        return None
    nome, modulo = outro
    return {"nome": nome, "modulo": modulo, "achado": localizar(modulo) is not None,
            "comando": f"python3 -m {modulo} restaurar --sim"}


def trocar(diz: Callable[[str], None], terminal: bool = False) -> int:
    """通过另一个主题的还原将其恢复（软件包保留）。
    没有另一个主题或它完整还原时返回 0；其他任何情况都会停止，
    账户保持其还原后的状态。"""
    outro = outro_aplicado()
    if not outro:
        return 0
    nome, modulo = outro
    pai = localizar(modulo)
    if pai is None:
        diz(f"  找不到项目 {modulo} 来恢复主题 {nome}；请手动运行，然后重新安装本主题："
            f"python3 -m {modulo} restaurar --sim")
        return 1
    diz(f"\n==> 正在恢复主题 {nome} ({pai / modulo})")
    comando = [sys.executable or "python3", "-m", modulo, "restaurar", "--sim"]
    ambiente = {**os.environ,
                "PYTHONPATH": str(pai) + (os.pathsep + os.environ["PYTHONPATH"]
                                          if os.environ.get("PYTHONPATH") else "")}
    try:
        if terminal:
            # 在终端中输出直接透传，sudo 可以询问密码
            codigo = subprocess.run(comando, cwd=pai, env=ambiente).returncode
        else:
            proc = subprocess.Popen(comando, cwd=pai, env=ambiente, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for linha in proc.stdout:
                diz(linha.rstrip("\n"))
            codigo = proc.wait()
    except OSError as erro:
        diz(f"  无法运行主题 {nome} 的还原：{erro}")
        return 1
    if codigo != 0:
        diz(f"  主题 {nome} 的还原出错结束（代码 {codigo}）；已在此停止，"
            "本主题未安装任何内容")
        return 1
    if outro_aplicado() == outro:
        diz(f"  主题 {nome} 仍显示为已安装；已在此停止，本主题未安装任何内容")
        return 1
    diz(f"  主题 {nome} 已恢复；现在安装本主题")
    return 0
