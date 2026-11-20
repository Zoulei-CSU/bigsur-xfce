"""d3bian-init-bigsur-xfce 的命令行。

不带任何参数时，它执行大多数人想要的操作：请求一次密码并打开浏览器中的面板。
子命令是给偏爱终端的人以及自动化使用的。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time

from . import VERSAO, caminhos, config, estado, receitas, servidor, sistema


# --------------------------------------------------------------------------
# 管理员凭据
# --------------------------------------------------------------------------

def garantir_sudo(obrigatorio: bool = False) -> bool:
    """请求一次密码，并在程序运行期间保持有效。

    密码在终端中输入，绝不在页面中输入。面板只复用这里已授权的凭据。
    """
    if sistema.sudo_liberado():
        # 已授权（sudo 缓存）：同样保持有效，否则它会在面板会话中途过期
        _manter_sudo()
        return True
    if not sys.stdin.isatty():
        if obrigatorio:
            print("  需要管理员权限，但没有可用于询问的终端")
        return False
    print("  有些步骤会改动软件包和 /etc。")
    print("  请在这里的终端中授权一次管理员权限。\n")
    try:
        if subprocess.run(["sudo", "-v"]).returncode != 0:
            return False
    except OSError:
        return False

    _manter_sudo()
    return True


_mantendo = threading.Event()


def _manter_sudo() -> None:
    """程序运行期间每 50 秒续期一次凭据（只启动一次）。"""
    if _mantendo.is_set():
        return
    _mantendo.set()

    def manter() -> None:
        while True:
            time.sleep(50)
            subprocess.run(["sudo", "-n", "true"], capture_output=True)

    threading.Thread(target=manter, daemon=True).start()


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_web(args) -> int:
    garantir_sudo()
    return servidor.subir(porta=args.porta, abrir=not args.sem_navegador)


def cmd_listar(_args) -> int:
    lista = receitas.carregar()
    print(f"  {'id':<5}{'步骤':<22}{'状态'}")
    for r in lista:
        situacao = f"于 {r.quando} 应用" if False else (
            f"已应用 {estado.quando(r.ident)}" if r.aplicada else "待处理")
        print(f"  {r.ident:<5}{r.nome:<22}{situacao}")
        if r.titulo:
            print(f"  {'':<5}{r.titulo}")
    print(f"\n  已准备：{'是' if receitas.instalado(lista) else '否'}")
    return 0


def cmd_aplicar(args) -> int:
    if not args.simular:
        # 已应用同族的另一个 Xfce 主题：在 sudo 之前拒绝；或者用 --trocar
        # 先恢复另一个；模拟时只给出提示并继续
        from . import familia
        recusa = familia.recusa()
        if recusa and not args.trocar:
            print(f"  {recusa}")
            return 1
        garantir_sudo()
        if recusa and familia.trocar(print, terminal=True) != 0:
            return 1
    falhas = receitas.executar(
        apenas=args.apenas.split(",") if args.apenas else None,
        pular=args.pular.split(",") if args.pular else None,
        refazer=args.refazer or bool(args.apenas),
        simular=args.simular,
    )
    if falhas:
        print(f"\n  {falhas} 个步骤有问题。详情见 {caminhos.REGISTRO}")
        return 1
    print("\n  全部已应用")
    return 0


def cmd_instalar(args) -> int:
    from . import familia
    recusa = familia.recusa()
    if recusa:
        print(f"  {recusa}")
        return 1
    impedem = sistema.impedimentos()
    if impedem and not args.mesmo_assim:
        print("  阻止安装的检查项：" + ", ".join(impedem))
        print("  使用 --mesmo-assim 按当前状态强行尝试")
        return 1
    garantir_sudo(obrigatorio=True)
    falhas = receitas.executar()
    print("\n  " + ("已安装" if not falhas else f"{falhas} 个步骤有问题"))
    print("  请注销并重新登录，让顶栏完整生效")
    return 1 if falhas else 0


def cmd_config(args) -> int:
    if not args.pares:
        atual = config.ler()
        for opcao in config.OPCOES:
            valores = "|".join(opcao.valores) if not opcao.livre else "自由文本"
            print(f"  {opcao.chave:<18}{atual[opcao.chave]:<12}({valores})")
            print(f"  {'':<18}{opcao.titulo}")
        return 0
    novos = {}
    for par in args.pares:
        chave, _, valor = par.partition("=")
        novos[chave.strip()] = valor.strip()
    validos = config.filtrar(novos)
    recusados = sorted(set(novos) - set(validos))
    if recusados:
        print("  已拒绝：" + ", ".join(recusados))
    mudou = config.gravar(validos)
    print("  已更改：" + (", ".join(mudou) if mudou else "无"))
    if mudou and not args.so_gravar:
        alvos = receitas.afetadas_por(mudou)
        if alvos:
            garantir_sudo()
            receitas.executar(apenas=alvos, refazer=True)
    return 0


def cmd_verificar(_args) -> int:
    lista = sistema.verificacoes()
    for c in lista:
        marca = "ok " if c["ok"] else ("!! " if c["critico"] else " ~ ")
        print(f"  {marca} {c['nome']:<28}{c['detalhe']}")
    impedem = sistema.impedimentos(lista)
    print("\n  " + ("可以安装" if not impedem
                    else "阻碍项：" + ", ".join(impedem)))
    return 1 if impedem else 0


def cmd_capturar(args) -> int:
    from . import capturas
    if args.login:
        return capturas.previa_login(print)
    if args.todas:
        garantir_sudo()
        return capturas.capturar_todas(print, args.espera)
    return capturas.capturar_atual(print, args.espera)


def cmd_restaurar(args) -> int:
    from . import desfazer
    if args.apagar:
        previa = desfazer.previa_remocao()
        print("  使用 --apagar 时，还会删除：")
        if previa["pacotes"]:
            print(f"    通过 apt 卸载的软件包：{', '.join(previa['pacotes'])}")
        for arquivo in previa.get("fontes_externas", []):
            print(f"    {arquivo}")
        for pasta in previa["pastas_do_projeto"]:
            print(f"    {pasta}")
        for item in previa["ficam"]:
            print(f"    保留：{item['nome']}（{item['motivo']}）")
        for item in previa.get("conferir", []):
            print(f"    请手动检查（之前可能已存在）：{item}")
    if not args.sim:
        print("  这会把机器恢复到之前的状态：撤销各配方声明的内容以及")
        print("  改动日志。" + ("" if args.apagar else " 已安装的软件包会保留（--apagar 会移除）。"))
        print("  用以下命令确认：d3bian-init-bigsur-xfce restaurar --sim" + (" --apagar" if args.apagar else ""))
        return 1
    garantir_sudo()
    falhas = desfazer.executar(lambda texto: print(texto), apagar=args.apagar)
    print("\n  完成；请注销并重新登录以完成" if not falhas
          else f"\n  {falhas} 个问题；请查看上面的行")
    return 1 if falhas else 0


# --------------------------------------------------------------------------

def construir() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="d3bian-init-bigsur-xfce",
        description="通过本地页面准备并调整装有 XFCE 的 Debian。")
    p.add_argument("--versao", action="version", version=f"d3bian-init-bigsur-xfce {VERSAO}")
    sub = p.add_subparsers(dest="comando")

    w = sub.add_parser("web", help="在浏览器中打开面板（默认）")
    w.add_argument("--porta", type=int, default=servidor.PORTA_PADRAO)
    w.add_argument("--sem-navegador", action="store_true")
    w.set_defaults(func=cmd_web)

    l = sub.add_parser("listar", help="显示各步骤及已应用的内容")
    l.set_defaults(func=cmd_listar)

    a = sub.add_parser("aplicar", help="运行步骤")
    a.add_argument("--apenas", help="用逗号分隔的 ID 或名称")
    a.add_argument("--pular", help="用逗号分隔的 ID 或名称")
    a.add_argument("--refazer", action="store_true", help="重做已应用的内容")
    a.add_argument("--simular", action="store_true", help="只显示，不做任何更改")
    a.add_argument("--trocar", action="store_true",
                   help="如果已安装同族的另一个 Xfce 主题，先恢复它（软件包保留）")
    a.set_defaults(func=cmd_aplicar)

    i = sub.add_parser("instalar", help="从零开始完整安装")
    i.add_argument("--mesmo-assim", action="store_true",
                   help="忽略预检查")
    i.set_defaults(func=cmd_instalar)

    c = sub.add_parser("config", help="读取或修改偏好")
    c.add_argument("pares", nargs="*", help="键=值")
    c.add_argument("--so-gravar", action="store_true", help="不重新应用任何内容")
    c.set_defaults(func=cmd_config)

    v = sub.add_parser("verificar", help="预检查")
    v.set_defaults(func=cmd_verificar)

    k = sub.add_parser("capturar", help="用你的屏幕更新预览")
    k.add_argument("--todas", action="store_true")
    k.add_argument("--login", action="store_true")
    k.add_argument("--espera", type=int, default=5)
    k.set_defaults(func=cmd_capturar)

    r = sub.add_parser("restaurar", help="把机器恢复到项目之前的状态")
    r.add_argument("--apagar", action="store_true",
                   help="同时移除项目安装的软件包和项目目录")
    r.add_argument("--sim", action="store_true", help="确认")
    r.set_defaults(func=cmd_restaurar)

    return p


def main(argv: list[str] | None = None) -> int:
    caminhos.preparar()
    caminhos.proteger_codigo()
    parser = construir()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["web", *(argv or [])])
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n  已中断")
        return 130
