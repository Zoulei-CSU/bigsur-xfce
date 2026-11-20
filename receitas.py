"""加载配方并执行所请求的配方。

每条配方是 recursos/receitas 中的一个 TOML 文件。它自我描述：顺序编号、标题、
依赖哪些其他配方以及哪些偏好会影响它。最后这个字段让网页能在用户更改选项时
自行决定重新执行什么，无需任何代码中的表。
"""

from __future__ import annotations

import shutil
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import caminhos, config, estado, familia, motor


@dataclass
class Receita:
    ident: str
    nome: str
    titulo: str
    passos: list[dict]
    requer: list[str] = field(default_factory=list)
    afetada_por: list[str] = field(default_factory=list)
    arquivo: Path | None = None
    # [[desfazer]]：desfazer.py 为日志未覆盖的内容运行的步骤
    desfazer: list[dict] = field(default_factory=list)

    @property
    def aplicada(self) -> bool:
        return estado.aplicado(self.ident)

    def como_dict(self) -> dict:
        return {"id": self.ident, "nome": self.nome, "titulo": self.titulo,
                "requer": self.requer, "afetada_por": self.afetada_por,
                "aplicada": self.aplicada, "quando": estado.quando(self.ident)}


def carregar() -> list[Receita]:
    """所有配方，按文件名中的编号排序。"""
    saida: list[Receita] = []
    for arquivo in sorted(caminhos.RECEITAS.glob("*.toml")):
        try:
            dados = tomllib.loads(arquivo.read_text())
        except (OSError, tomllib.TOMLDecodeError) as erro:
            estado.registrar(f"配方无效 {arquivo.name}：{erro}")
            continue
        cabecalho = dados.get("modulo", {})
        ident = str(cabecalho.get("id") or arquivo.stem.split("-")[0])
        saida.append(Receita(
            ident=ident,
            nome=cabecalho.get("nome", arquivo.stem),
            titulo=cabecalho.get("titulo", ""),
            passos=dados.get("passo", []),
            requer=[str(x) for x in cabecalho.get("requer", [])],
            afetada_por=[str(x) for x in cabecalho.get("afetada_por", [])],
            arquivo=arquivo,
            desfazer=dados.get("desfazer", []),
        ))
    return saida


def por_id() -> dict[str, Receita]:
    return {r.ident: r for r in carregar()}


NUCLEO = ("10", "30", "31")


def instalado(lista: list[Receita] | None = None) -> bool:
    """机器已经准备过了吗？只需核心已应用。"""
    feitas = {r.ident for r in (lista or carregar()) if r.aplicada}
    return all(n in feitas for n in NUCLEO)


def afetadas_por(chaves: list[str]) -> list[str]:
    """这些偏好改变时要重新执行哪些配方。"""
    alvos = {r.ident for r in carregar()
             if any(c in r.afetada_por for c in chaves)}
    return sorted(alvos, key=lambda x: (len(x), x))


def desatualizadas(lista: list[Receita] | None = None) -> set[str]:
    """从未应用过的配方，或应用后文件又发生变化的配方。

    否则，新写或重写的配方要等到有人改动影响它的选项时才会到达系统。
    """
    saida: set[str] = set()
    for r in lista or carregar():
        marca = estado.marca(r.ident)
        try:
            if not marca.is_file() or (
                    r.arquivo and r.arquivo.stat().st_mtime > marca.stat().st_mtime):
                saida.add(r.ident)
        except OSError:
            continue
    return saida


def selecionar(todas: list[Receita], apenas: list[str] | None,
               pular: list[str] | None) -> list[Receita]:
    escolhidas = todas
    if apenas:
        alvo = {x.strip() for x in apenas if x.strip()}
        escolhidas = [r for r in escolhidas if r.ident in alvo or r.nome in alvo]
    if pular:
        fora = {x.strip() for x in pular if x.strip()}
        escolhidas = [r for r in escolhidas if r.ident not in fora and r.nome not in fora]
    return escolhidas


def executar(apenas: list[str] | None = None, pular: list[str] | None = None,
             refazer: bool = False, simular: bool = False,
             saida: Callable[[str], None] | None = None,
             cfg: dict[str, str] | None = None) -> int:
    """运行选定的配方。返回失败数量。"""
    diz = saida or print
    # 本账户已应用同族的另一个 Xfce 主题：不运行任何内容（见 familia.py）
    recusa = familia.recusa()
    if recusa:
        if not simular:
            diz(f"  {recusa}")
            return 1
        diz(f"  atencao: {recusa}；模拟继续进行，实际安装会被拒绝")
    try:
        with caminhos.trava():
            # 仅本次执行使用的登录界面组装目录：新建、名称不可预测、
            # 0700（mkdtemp），结束时删除
            montagem = tempfile.mkdtemp(prefix="d3bian-init-login-")
            try:
                return _executar(apenas, pular, refazer, simular, diz, cfg, montagem)
            finally:
                shutil.rmtree(montagem, ignore_errors=True)
    except caminhos.Ocupado as erro:
        diz(f"{erro}；请等待完成")
        return 1


def _executar(apenas, pular, refazer, simular, diz, cfg, montagem: str = "") -> int:
    caminhos.preparar()
    cfg = cfg or config.ler()
    ctx = motor.montar_contexto(cfg)
    escolhidas = selecionar(carregar(), apenas, pular)
    if not escolhidas:
        diz("没有配方符合请求")
        return 0

    falhas = 0
    for receita in escolhidas:
        if receita.aplicada and not refazer:
            diz(f"  ja aplicado: {receita.ident} {receita.titulo}")
            continue
        faltando = [x for x in receita.requer if not estado.aplicado(x)]
        if faltando and not simular:
            diz(f"  pulando {receita.ident} {receita.titulo}: "
                f"依赖 {', '.join(faltando)}")
            falhas += 1
            continue

        diz(f"\n==> {receita.ident} {receita.titulo}")
        # 每条配方都重建上下文：壁纸和登录背景只有在壁纸配方下载图片后才存在
        ctx = motor.montar_contexto(cfg)
        ctx["login_dir"] = montagem
        maquina = motor.Motor(ctx, saida=diz, simular=simular, receita=receita.ident)
        try:
            maquina.rodar(receita.passos)
        except motor.ErroDePasso as erro:
            diz(f"  ERRO: {erro}")
            falhas += 1
            continue
        except Exception as erro:                      # 不影响其余内容
            diz(f"  ERRO 意外：{erro}")
            estado.registrar(f"{receita.ident} 出现意外错误：{erro!r}")
            falhas += 1
            continue
        if not simular:
            estado.marcar(receita.ident)
        diz(f"  concluido: {receita.titulo}")
    return falhas
