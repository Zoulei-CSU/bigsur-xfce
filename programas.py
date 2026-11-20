"""官方仓库的软件目录。

目录同时也是许可列表：程序只安装或移除这里的内容。这很重要，因为请求来自
网页，页面不应能要求安装任意内容。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from . import caminhos, diario, hardware, motor, sistema

LIMITE = 60          # 每次操作的软件包上限

# fonte-externa.sh 可在系统中创建的内容（各源的密钥、列表和偏好）；
# 配合 "apagar" 的撤销只会移除这些，且只限原本不存在的
ARQUIVOS_DE_FONTE = {
    f"{pasta}/{nome}{fim}"
    for nome in ("microsoft-vscode", "docker")
    for pasta, fim in (("/usr/share/keyrings", ".gpg"), ("/etc/apt/sources.list.d", ".list"),
                       ("/etc/apt/preferences.d", ""))
}


def catalogo() -> dict:
    try:
        return json.loads(caminhos.CATALOGO.read_text())
    except (OSError, json.JSONDecodeError):
        return {"aviso": "目录不可用", "categorias": []}


def itens() -> dict[str, dict]:
    """目录中的所有项，按软件包名称索引。"""
    return {
        item["pkg"]: item
        for categoria in catalogo().get("categorias", [])
        for item in categoria.get("itens", [])
        if isinstance(item.get("pkg"), str)
    }


def fontes_necessarias(pacotes: list[str]) -> list[dict]:
    """所选软件包中有哪些依赖第三方仓库。"""
    tabela = itens()
    saida = []
    for nome in pacotes:
        item = tabela.get(nome, {})
        if item.get("fonte"):
            saida.append({"pkg": nome, "nome": item.get("nome", nome),
                          "fonte": item["fonte"], "aviso": item.get("aviso", "")})
    return saida


def permitidos() -> set[str]:
    return {
        item["pkg"]
        for categoria in catalogo().get("categorias", [])
        for item in categoria.get("itens", [])
        if isinstance(item.get("pkg"), str)
    }


def com_estado() -> dict:
    """带可用和已安装标记的目录，供页面绘制。"""
    dados = catalogo()
    nomes = sorted(permitidos())
    estados = sistema.estado_pacotes(nomes)
    # 带 "hardware" 的项仅在机器有该硬件时才相关；
    # 页面在硬件卡片中显示它，而不在普通列表中
    maquina = hardware.detectar()
    for categoria in dados.get("categorias", []):
        for item in categoria.get("itens", []):
            item.update(estados.get(item.get("pkg", ""), {}))
            if item.get("hardware"):
                item["detectado"] = hardware.atende(item, maquina)
                usos = maquina["firmware"].get(item.get("pkg", ""))
                if usos:
                    item["motivo"] = "被以下使用：" + ", ".join(usos)
    dados["hardware"] = maquina
    return dados


class Recusado(Exception):
    pass


def conferir(pedidos) -> list[str]:
    """对照目录校验请求的列表。有不符项时抛出 Recusado。"""
    if not isinstance(pedidos, list) or not pedidos:
        raise Recusado("未提供任何程序")
    lista = permitidos()
    fora = [str(x) for x in pedidos if not isinstance(x, str) or x not in lista]
    if fora:
        raise Recusado("不在目录中：" + ", ".join(fora[:5]))
    if len(pedidos) > LIMITE:
        raise Recusado(f"每次最多 {LIMITE} 个程序")
    # 去重并保持顺序
    vistos: list[str] = []
    for nome in pedidos:
        if nome not in vistos:
            vistos.append(nome)
    return vistos


def arrastaria(pacotes: list[str]) -> list[str]:
    """模拟移除，并返回 apt 未请求也会一并移除的内容。"""
    try:
        simulacao = subprocess.run(["apt-get", "-s", "remove", *pacotes],
                                   capture_output=True, text=True, timeout=60,
                                   env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return []
    saindo = {
        linha.split()[1]
        for linha in simulacao.stdout.splitlines()
        if linha.startswith("Remv ") and len(linha.split()) > 1
    }
    return sorted(saindo - set(pacotes))


# apt 在输出中以 "dlstatus:" 和 "pmstatus:" 行写入进度；
# 页面据此绘制进度条和当前包，并从日志中隐藏这些行
PROGRESSO_APT = ["-o", "APT::Status-Fd=1"]


def comando_instalar(pacotes: list[str]) -> list[str]:
    # sudo 会清空环境：DEBIAN_FRONTEND 通过 env 内置传入
    return ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", *PROGRESSO_APT,
            *motor.APT_SEM_PERGUNTAS, "install", "-y",
            "--no-install-recommends", *pacotes]


def instalar(pacotes: list[str], diz: Callable[[str], None]) -> int:
    """启用第三方源、安装，并运行各项的脚本。

    某个项可以一并带上软件包（"junto"），并在 apt 之后请求配置脚本
    （"depois"），如 Docker rootless。
    """
    try:
        with caminhos.trava():
            return _instalar(pacotes, diz)
    except caminhos.Ocupado as erro:
        diz(f"{erro}；请等待完成")
        return 1


def remover(pacotes: list[str], diz: Callable[[str], None]) -> int:
    try:
        with caminhos.trava():
            comando = comando_remover(pacotes)
            diz("$ sudo " + " ".join(comando))
            return _correr(["sudo", "-n", *comando], diz)
    except caminhos.Ocupado as erro:
        diz(f"{erro}；请等待完成")
        return 1


def _instalar(pacotes: list[str], diz: Callable[[str], None]) -> int:
    for pedido in fontes_necessarias(pacotes):
        diz(f"habilitando a fonte de {pedido['nome']}: {pedido['fonte']}")
        roteiro = caminhos.ARQUIVOS / "fonte-externa.sh"
        antes = {c for c in ARQUIVOS_DE_FONTE if Path(c).exists()}
        codigo = _correr(["sudo", "-n", "bash", str(roteiro), pedido["fonte"]], diz)
        # 为配合 "apagar" 的撤销而记录：只记本步骤创建的内容
        criados = sorted(c for c in ARQUIVOS_DE_FONTE - antes if Path(c).exists())
        if criados:
            diario.anotar("fonte_externa", receita="programas", fonte=pedido["fonte"],
                          criados=criados)
        if codigo != 0:
            diz("无法启用源；未安装任何内容")
            return codigo

    tabela = itens()
    todos = list(pacotes)
    for nome in pacotes:
        todos += [p for p in tabela.get(nome, {}).get("junto", []) if p not in todos]
    diz("正在安装：" + ", ".join(todos))
    codigo = _correr(["sudo", "-n", *comando_instalar(todos)], diz)
    if codigo != 0:
        return codigo

    for nome in pacotes:
        roteiro = tabela.get(nome, {}).get("depois", "")
        # 只用 recursos/arquivos 的文件名，绝不是路径
        if not roteiro or Path(roteiro).name != roteiro:
            continue
        diz(f"正在配置 {tabela[nome].get('nome', nome)}")
        # 以用户身份运行：脚本配置的内容属于用户并由其使用，
        # 系统步骤中它会自行使用 sudo -n
        codigo = _correr(["bash", str(caminhos.ARQUIVOS / roteiro)], diz)
        if codigo != 0:
            return codigo
    return 0


def _correr(argumentos: list[str], diz: Callable[[str], None]) -> int:
    try:
        proc = subprocess.Popen(
            argumentos, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive", "TERM": "dumb"})
        assert proc.stdout is not None
        for linha in proc.stdout:
            diz(linha.rstrip("\n"))
        proc.wait()
        return proc.returncode
    except OSError as erro:
        diz(f"无法执行：{erro}")
        return 1


def comando_remover(pacotes: list[str]) -> list[str]:
    return ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", *PROGRESSO_APT, "remove", "-y",
            *pacotes]
