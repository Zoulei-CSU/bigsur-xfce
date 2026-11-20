"""把机器恢复到项目之前的状态。

共三个阶段，外加一个可选阶段：

- d1：各已应用配方的 [[desfazer]]，从最后一个到第一个。没有任何通用步骤知道
  如何撤销的内容都放在这里：chsh、gsettings、已启用的扩展、已启动的服务。
- d2：倒序遍历更改日志。创建的文件删除；原本已存在的文件从备份恢复；块从
  文件中移除，其余保留；xfconf、gsettings 和 dconf 恢复为之前的值；项目启动
  且之前未运行的进程停止。项目数据目录中的下载和克隆留给 d4，由它删除整个
  目录。
- d3：已应用阶段的标记，页面重新提供安装。
- d4（仅配合 apagar）：项目安装的软件包，以及项目目录（选项、日志、备份、
  下载）。会连带移除其他程序的软件包保留，提供登录 shell 的软件包也保留。

在更改日志出现之前安装的机器：d2 只恢复备份，软件包则来自 apt 历史记录。
"""

from __future__ import annotations

import getpass
import gzip
import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from . import caminhos, config, diario, estado, motor, programas, receitas, sistema

Diz = Callable[[str], None]

ETAPAS = [
    ("d1", "各配方要求撤销的内容"),
    ("d2", "文件、块和配置"),
    ("d3", "标记为已应用的阶段"),
]
ETAPA_APAGAR = ("d4", "移除已安装的内容")

# 因路径或日志错误而永不删除
PROTEGIDOS = {Path("/"), Path.home(), Path("/usr"), Path("/etc"), Path("/opt"), Path("/boot"),
              Path("/usr/share"), Path("/usr/local"), Path("/usr/local/bin"),
              Path.home() / ".config", Path.home() / ".local", Path.home() / ".local/share"}


def etapas(apagar: bool = False) -> list[tuple[str, str]]:
    return ETAPAS + ([ETAPA_APAGAR] if apagar else [])


def _rodar(argumentos: list[str], diz: Diz) -> int:
    estado.registrar("+ " + " ".join(argumentos))
    try:
        proc = subprocess.run(argumentos, capture_output=True, text=True)
    except OSError as erro:
        diz(f"  无法执行 {argumentos[0]}：{erro}")
        return 1
    if proc.returncode != 0:
        for linha in (proc.stderr or "").splitlines()[-4:]:
            diz("  " + linha)
    return proc.returncode


def _da_pessoa(caminho: Path) -> bool:
    return caminho == Path.home() or Path.home() in caminho.parents


# ---- d1：配方中声明的撤销 ----------------------------------------------

def _receitas(diz: Diz) -> int:
    ctx = motor.montar_contexto(config.ler())
    no_diario = {e.get("receita") for e in diario.ler()}
    falhas = 0
    for receita in reversed(receitas.carregar()):
        if not receita.desfazer or not (receita.aplicada or receita.ident in no_diario):
            continue
        diz(f"  {receita.ident} {receita.titulo}")
        try:
            motor.Motor(ctx, saida=diz, anotar=False).rodar(receita.desfazer)
        except motor.ErroDePasso as erro:
            diz(f"  ERRO 于 {receita.ident}：{erro}")
            falhas += 1
    return falhas


# ---- d2：倒序遍历更改日志 ----------------------------------------------

# 系统（和其他程序）即使为空也期望存在的目录
PASTAS_DO_SISTEMA = {Path.home() / p for p in (
    ".config", ".cache", ".local", ".local/bin", ".local/share", ".local/state",
    ".themes", ".icons", ".fonts", ".local/share/icons", ".local/share/themes",
    ".local/share/fonts", ".local/share/applications", ".local/share/backgrounds")}


def _limpar_vazias(pasta: Path, diz: Diz) -> None:
    """向上删除已变空的目录，避免留下项目的空壳。

    rmdir 只对空目录有效，因此不会碰任何含有他人或其他程序内容的目录。遇到系统
    期望存在的目录、项目数据目录以及主目录时停止。
    """
    casa = Path.home()
    guardadas = {getattr(caminhos, n, None) for n in ("DADOS_DIR", "ESTADO_DIR", "BACKUP")}
    while (pasta != casa and casa in pasta.parents
           and pasta not in PASTAS_DO_SISTEMA and pasta not in PROTEGIDOS
           and not any(g and (pasta == g or g in pasta.parents) for g in guardadas)):
        try:
            pasta.rmdir()
        except OSError:
            return
        diz(f"  空目录 {pasta} 已删除")
        pasta = pasta.parent


# 在主目录之外，撤销（在那里以 root 运行）只删除以下这些：更改日志位于用户
# 目录中，不能自行决定 root 删什么。它们是配方创建的系统路径；谁新增了会创建
# 其他路径的配方，就在这里补充。
APAGAVEIS_FORA_DE_CASA = {
    *(f"/usr/share/themes/WhiteSur-{v}{'' if c == 'default' else '-' + c}"
      for v in ("Light", "Dark") for c in motor.DESTAQUE_EXTERNO.values()),
    "/usr/share/icons/WhiteSur", "/usr/share/icons/WhiteSur-dark",
    "/usr/share/icons/WhiteSur-light", "/usr/share/icons/WhiteSur-cursors",
    "/usr/share/backgrounds/d3bian-init", "/usr/share/themes/d3bian-login",
    "/etc/xdg/lightdm/lightdm-gtk-greeter.conf.d/90-d3bian.conf",
    "/etc/lightdm/lightdm.conf.d/90-d3bian.conf",
    # 程序页面中的第三方源（fonte-externa.sh）
    *programas.ARQUIVOS_DE_FONTE,
    str(caminhos.BACKUP_SISTEMA),
}


# root 可从其备份中恢复的路径：配方所改动的相同系统路径（备份目录本身除外）
RESTAURAVEIS_FORA_DE_CASA = APAGAVEIS_FORA_DE_CASA - {str(caminhos.BACKUP_SISTEMA)}


# 配方在主目录中直接创建的文件；撤销会删除它自己创建的内容（日志会说明），
# 主目录下不再多删
ARQUIVOS_DA_CASA = frozenset({".gtkrc-2.0", ".xprofile", ".xsessionrc"})


def _apagavel(caminho: Path) -> bool:
    bruto = str(caminho)
    # 已规范化且不含 ".." 的路径：列表位于用户目录中
    if not diario.caminho_limpo(bruto):
        return False
    casa = Path.home()
    if caminho.is_relative_to(casa):
        real = Path(os.path.realpath(caminho))
        # 绝不是整个主目录，也不是它正下方的目录（Documentos、.config……）
        if not real.is_relative_to(casa):
            return False
        partes = real.relative_to(casa).parts
        if len(partes) == 1:
            # 主目录正下方，只限配方写入的普通文件
            return (partes[0] in ARQUIVOS_DA_CASA and caminho.is_file()
                    and not caminho.is_symlink())
        return len(partes) >= 2
    return bruto in APAGAVEIS_FORA_DE_CASA


def _apagar(caminho: Path, diz: Diz) -> None:
    if caminho in PROTEGIDOS or len(caminho.parts) < 3:
        diz(f"  atencao: {caminho} 未删除（受保护的路径）")
        return
    if not caminho.exists() and not caminho.is_symlink():
        return
    if not _apagavel(caminho):
        diz(f"  atencao: 如果是项目内容，请手动检查并删除：{caminho}")
        return
    if _da_pessoa(caminho):
        if caminho.is_dir() and not caminho.is_symlink():
            shutil.rmtree(caminho, ignore_errors=True)
        else:
            caminho.unlink(missing_ok=True)
    elif _rodar(["sudo", "-n", "rm", "-rf", str(caminho)], diz) != 0:
        diz(f"  无法删除 {caminho}")
        return
    diz(f"  已删除 {caminho}")
    _limpar_vazias(caminho.parent, diz)


def _voltar_copia(caminho: Path, diz: Diz) -> None:
    if not diario.caminho_limpo(str(caminho)):
        diz(f"  atencao: 更改日志中有异常路径，已忽略：{caminho}")
        return
    if not _da_pessoa(caminho):
        _voltar_copia_do_sistema(caminho, diz)
        return
    copia = caminhos.BACKUP / str(caminho).lstrip("/")
    if not copia.exists():
        diz(f"  atencao: {caminho} 没有备份；保持原样")
        return
    if caminho.is_dir() and not caminho.is_symlink():
        shutil.rmtree(caminho, ignore_errors=True)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if copia.is_dir():
        shutil.copytree(copia, caminho, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(copia, caminho)
    diz(f"  已恢复 {caminho}")


def _voltar_copia_do_sistema(caminho: Path, diz: Diz) -> None:
    """系统文件只从 root 的备份恢复（caminhos.BACKUP_SISTEMA）：
    用户目录中的备份可能已被其任意程序篡改。"""
    if str(caminho) not in RESTAURAVEIS_FORA_DE_CASA:
        diz(f"  atencao: root 不会恢复 {caminho}（不在列表中）；请手动检查")
        return
    copia = caminhos.BACKUP_SISTEMA / str(caminho).lstrip("/")
    if _rodar(["sudo", "-n", "test", "-e", str(copia)], diz) != 0:
        diz(f"  atencao: {caminho} 没有（root 的）备份；保持原样")
        return
    if _rodar(["sudo", "-n", "sh", "-c", DEVOLVER_ROOT, "sh", str(caminhos.BACKUP_SISTEMA),
               str(copia), str(caminho)], diz) != 0:
        diz(f"  无法恢复 {caminho}")
        return
    diz(f"  已恢复 {caminho}")


# 备份目录属于 root 且不是链接；解析后的副本（realpath -e）位于其中；
# 只有这样才能用副本替换目标
DEVOLVER_ROOT = (
    '[ -d "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u "$1")" = 0 ] || exit 3; '
    'raiz=$(realpath -e -- "$1") && c=$(realpath -e -- "$2") || exit 3; '
    'case "$c" in "$raiz"/*) ;; *) exit 4;; esac; '
    'rm -rf -- "$3" && cp -a -- "$c" "$3"')


def tirar_bloco(arquivo: Path, marca: str, comentario: str) -> bool:
    """用相同的标记移除引擎的块步骤写入的片段。"""
    if not arquivo.is_file():
        return False
    abre, fecha = (f"# {marca}", f"# fim {marca}") if comentario == "#" else (f"/* {marca} */", f"/* fim {marca} */")
    texto = arquivo.read_text()
    # 与 motor.passo_bloco 相同的独占行标记
    novo = re.sub(r"\n*^" + re.escape(abre) + r"$.*?^" + re.escape(fecha) + r"$\n?", "\n", texto,
                  flags=re.S | re.M)
    if novo == texto:
        return False
    caminhos.escrever(arquivo, novo.strip("\n") + "\n" if novo.strip() else "")
    return True


def _xfconf(item: dict, diz: Diz) -> None:
    if not shutil.which("xfconf-query"):
        return
    base = ["xfconf-query", "-c", item["canal"], "-p", item["chave"]]
    subprocess.run([*base, "-r"], capture_output=True)
    if not item.get("existia"):
        return
    valor = item.get("valor", "")
    tipo = item.get("tipo_valor", "string")
    if valor.startswith("Value is an array"):
        valores = [v for v in valor.split("\n\n", 1)[-1].splitlines() if v.strip()]
        tipo_item = "double" if tipo == "double-array" else "string"
    else:
        valores = [valor.rstrip("\n")]
        tipo_item = tipo
    argumentos = [*base, "-n"]
    for v in valores:
        argumentos += ["-t", tipo_item, "-s", v]
    _rodar(argumentos, diz)


def _canais_vazios(itens: list[dict], diz: Diz) -> None:
    """原本不存在且已无属性的 xfconf 通道：删除其文件。"""
    if not shutil.which("xfconf-query"):
        return
    pasta = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "xfce4/xfconf/xfce-perchannel-xml"
    for canal in sorted({i["canal"] for i in itens if i.get("tipo") == "xfconf" and i.get("canal_existia") is False}):
        lista = subprocess.run(["xfconf-query", "-c", canal, "-l"], capture_output=True, text=True,
                               env={**os.environ, "LC_ALL": "C"}).stdout
        arquivo = pasta / f"{canal}.xml"
        if not any(l.startswith("/") for l in lista.splitlines()) and arquivo.is_file() \
                and "<property" not in arquivo.read_text(errors="replace"):
            arquivo.unlink()
            diz(f"  已删除 {arquivo}，它仅因本项目而存在")


def _diario(diz: Diz) -> int:
    itens = diario.ler()
    if not itens:
        diz("  atencao: 本次安装早于更改日志；只能恢复备份文件")
        feitos = estado.restaurar_tudo()
        diz(f"  已恢复 {len(feitos)} 个文件")
        # GNOME 项目会保存之前的整个 dconf
        if getattr(estado, "restaurar_dconf", None) and estado.restaurar_dconf():
            diz("  已载入之前的 GNOME 配置")
        return 0
    falhas = 0
    guardados = 0
    for item in reversed(itens):
        try:
            tipo = item.get("tipo")
            if "caminho" in item and not diario.caminho_limpo(item["caminho"]):
                diz(f"  atencao: 更改日志中有异常路径，已忽略：{item['caminho']}")
                continue
            if tipo == "criado" and caminhos.DADOS_DIR in Path(item["caminho"]).parents:
                guardados += 1
            elif tipo == "criado":
                _apagar(Path(item["caminho"]), diz)
            elif tipo == "pasta":
                # 由项目创建：仅在变空时删除
                try:
                    Path(item["caminho"]).rmdir()
                    diz(f"  空目录 {item['caminho']} 已删除")
                except OSError:
                    pass
            elif tipo == "alterado":
                _voltar_copia(Path(item["caminho"]), diz)
            elif tipo == "bloco":
                caminho = Path(item["caminho"])
                if tirar_bloco(caminho, item["marca"], item.get("comentario", "")):
                    diz(f"  已从 {caminho} 移除块 '{item['marca']}'")
                if item.get("arquivo_novo") and caminho.is_file() and not caminho.read_text().strip():
                    caminho.unlink()
                    _limpar_vazias(caminho.parent, diz)
            elif tipo == "xfconf":
                _xfconf(item, diz)
            elif tipo == "gsettings" and shutil.which("gsettings"):
                # 原本为默认值的键恢复为默认值，而不是显式写入默认值
                if item.get("padrao"):
                    _rodar(["gsettings", "reset", item["esquema"], item["chave"]], diz)
                elif item.get("valor"):
                    _rodar(["gsettings", "set", item["esquema"], item["chave"], item["valor"]], diz)
            elif tipo == "dconf" and shutil.which("dconf"):
                if item.get("valor"):
                    _rodar(["dconf", "write", item["chave"], item["valor"]], diz)
                else:
                    _rodar(["dconf", "reset", item["chave"]], diz)
            elif tipo == "processo" and not item.get("rodava"):
                subprocess.run(["pkill", "-x", item["nome"]], capture_output=True)
        except (OSError, KeyError, shutil.Error) as erro:
            diz(f"  ERRO 撤销 {item.get('tipo')} {item.get('caminho', item.get('chave', ''))} 时：{erro}")
            falhas += 1
    _canais_vazios(itens, diz)
    if guardados:
        diz(f"  项目目录中有 {guardados} 个下载会保留；使用移除选项时删除")
    diz("  已遍历更改日志")
    return falhas


# ---- d4：移除已安装的内容 ----------------------------------------------

def _pacotes_das_receitas() -> set[str]:
    nomes = set()
    for receita in receitas.carregar():
        for passo in receita.passos:
            if passo.get("tipo") == "apt":
                nomes |= {n for n in passo.get("pacotes", []) if "@@" not in n}
    return nomes


def _historico_apt() -> list[str]:
    """没有更改日志时：自项目首次使用以来面板向 apt 请求的软件包。"""
    usuario = getpass.getuser()
    do_projeto = _pacotes_das_receitas()
    inicio = ""
    try:
        primeira = caminhos.REGISTRO.read_text(errors="replace").split("\n", 1)[0]
        inicio = primeira[1:11] if primeira.startswith("[") else ""
    except OSError:
        pass
    textos = []
    for arquivo in sorted(Path("/var/log/apt").glob("history.log*")):
        try:
            dados = arquivo.read_bytes()
            textos.append((gzip.decompress(dados) if arquivo.suffix == ".gz" else dados).decode(errors="replace"))
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
    achados = set()
    for bloco in "\n\n".join(textos).split("\n\n"):
        data = re.search(r"^Start-Date: (\S+)", bloco, re.M)
        pedido = re.search(r"^Commandline: apt-get (?:-o \S+ )*install -y --no-install-recommends (.+)$", bloco, re.M)
        por = re.search(r"^Requested-By: (\S+) ", bloco, re.M)
        if not (data and pedido and por) or por.group(1) != usuario:
            continue
        if inicio and data.group(1) < inicio:
            continue
        achados |= set(pedido.group(1).split()) & do_projeto
    return sorted(achados)


def _pacote_do_shell() -> str:
    """提供登录 shell 的软件包：移除会让人无法登录。"""
    shell = pwd.getpwnam(getpass.getuser()).pw_shell
    saida = subprocess.run(["dpkg", "-S", os.path.realpath(shell)], capture_output=True, text=True).stdout
    return saida.split(":", 1)[0].strip() if saida else ""


def previa_remocao() -> dict:
    """移除阶段会删除什么，不做任何改动。页面会先显示。"""
    itens = diario.ler()
    if itens:
        candidatos = sorted({n for e in itens if e.get("tipo") == "pacotes" for n in e.get("nomes", [])})
        origem = "diario"
    else:
        candidatos, origem = _historico_apt(), "historico"
    instalados = {n for n, i in sistema.estado_pacotes(candidatos).items() if i.get("instalado")}
    do_shell = _pacote_do_shell()
    pacotes, ficam = [], []
    for nome in (n for n in candidatos if n in instalados):
        if nome == do_shell:
            ficam.append({"nome": nome, "motivo": "提供登录 shell；请先换回原 shell"})
            continue
        pacotes.append(nome)
    # 依赖某软件包的东西只有在不一起移除时才会将其留下；循环重试，因为留下的
    # 软件包可能又留下另一个。apt 随项目软件包带来的依赖也会一起移除
    # （libglib2.0-bin 由项目以及随 appmenu 而来的
    # appmenu-gtk-module-common 请求）
    trazidas = {d.split(":")[0] for e in itens if e.get("tipo") == "pacotes" for d in e.get("dependencias", [])}
    mudou = True
    while mudou:
        mudou = False
        for nome in list(pacotes):
            simulado = subprocess.run(["apt-get", "-s", "remove", nome], capture_output=True, text=True,
                                      env={**os.environ, "LC_ALL": "C"}).stdout
            levaria = [x for x in re.findall(r"^Remv (\S+)", simulado, re.M)
                       if x != nome and x.split(":")[0] not in pacotes and x.split(":")[0] not in trazidas]
            if levaria:
                pacotes.remove(nome)
                ficam.append({"nome": nome, "motivo": "其他程序依赖它：" + ", ".join(levaria[:6])
                              + ("…" if len(levaria) > 6 else "")})
                mudou = True
    pastas = [str(p) for p in (caminhos.CONFIG_DIR, caminhos.DADOS_DIR, caminhos.ESTADO_DIR,
                               caminhos.BACKUP_SISTEMA) if p.exists()]
    # 只删除创建时日志记录且上面的列表允许的内容；其余内容出现以供手动检查
    # （可能在项目之前就已存在）
    conferir = sorted({e["caminho"] for e in itens if e.get("tipo") == "criado" and e.get("caminho")
                       and not _apagavel(Path(e["caminho"]))
                       and (Path(e["caminho"]).exists() or Path(e["caminho"]).is_symlink())})
    fontes = sorted({c for e in itens if e.get("tipo") == "fonte_externa" for c in e.get("criados", [])
                     if c in APAGAVEIS_FORA_DE_CASA and Path(c).exists()})
    # apt 一并带来的依赖；先移除软件包，再只移除无人使用的依赖
    dependencias = sorted({d for e in itens if e.get("tipo") == "pacotes" for d in e.get("dependencias", [])}
                          - set(pacotes) - {f["nome"] for f in ficam})
    return {"pacotes": pacotes, "ficam": ficam, "pastas_do_projeto": pastas, "origem": origem,
            "mudancas": len(itens), "dependencias": dependencias, "conferir": conferir,
            "fontes_externas": fontes}


def _orfas() -> set[str]:
    """apt autoremove 现在会移除的软件包。"""
    saida = subprocess.run(["apt-get", "-s", "autoremove"], capture_output=True, text=True,
                           env={**os.environ, "LC_ALL": "C"}).stdout
    return set(re.findall(r"^Remv (\S+)", saida, re.M))


def _dependencias_anotadas(nomes: list[str], diz: Diz) -> None:
    """随项目软件包而来、又被 autoremove 留下的依赖，因为它们只是建议项。"""
    sobram = [n for n, i in sistema.estado_pacotes(nomes).items() if i.get("instalado")]
    # 只移除不会连带移除列表之外的依赖；循环重试，因为留下的会留住另一个
    mudou = True
    while mudou and sobram:
        mudou = False
        for nome in list(sobram):
            simulado = subprocess.run(["apt-get", "-s", "remove", nome], capture_output=True, text=True,
                                      env={**os.environ, "LC_ALL": "C"}).stdout
            if any(x.split(":")[0] not in sobram for x in re.findall(r"^Remv (\S+)", simulado, re.M)):
                sobram.remove(nome)
                mudou = True
    if sobram:
        diz(f"  随它们而来的依赖：{', '.join(sobram)}")
        if _rodar(["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "remove", "-y", *sobram], diz) != 0:
            diz("  atencao: 无法移除这些依赖")


def _remover(diz: Diz) -> int:
    previa = previa_remocao()
    if previa["origem"] == "historico":
        diz("  atencao: 安装早于更改日志；软件包取自 apt 历史记录")
    for item in previa["ficam"]:
        diz(f"  atencao: {item['nome']} 保持安装：{item['motivo']}")
    if previa["pacotes"]:
        # 之前就已多余的包不属于项目，保留
        orfas_antes = _orfas()
        diz(f"  通过 apt 卸载：{', '.join(previa['pacotes'])}")
        if _rodar(["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "remove", "-y", *previa["pacotes"]], diz) != 0:
            diz("  ERRO: apt-get remove 失败；项目目录保留")
            return 1
        novas = sorted(_orfas() - orfas_antes)
        if novas:
            diz(f"  仅因项目而存在的依赖：{', '.join(novas)}")
            if _rodar(["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "remove", "-y", *novas], diz) != 0:
                diz("  atencao: 无法移除依赖；之后可用 sudo apt autoremove 清理")
        _dependencias_anotadas(previa.get("dependencias", []), diz)
    # 程序页面向 apt 添加的第三方源
    for arquivo in previa.get("fontes_externas", []):
        _apagar(Path(arquivo), diz)
    for item in previa.get("conferir", []):
        diz(f"  atencao: 如果是项目内容，请手动检查并删除：{item}")
    # 最后：前面阶段仍在使用的日志、更改记录和备份
    for pasta in previa["pastas_do_projeto"]:
        if Path(pasta) == caminhos.BACKUP_SISTEMA:
            _apagar(caminhos.BACKUP_SISTEMA, diz)
            continue
        shutil.rmtree(pasta, ignore_errors=True)
        diz(f"  已删除 {pasta}")
    return 0


# ---- 全部 -----------------------------------------------------------------

def executar(diz: Diz = print, apagar: bool = False) -> int:
    """逐步撤销全部内容。返回失败数量。"""
    try:
        with caminhos.trava():
            return _executar(diz, apagar)
    except caminhos.Ocupado as erro:
        diz(f"  {erro}；请等待完成")
        return 1


def _executar(diz: Diz, apagar: bool) -> int:
    caminhos.preparar()
    passos = {"d1": _receitas, "d2": _diario,
              "d3": lambda d: (estado.limpar_marcas(), d("  页面会重新显示完整安装"))[0] or 0,
              "d4": _remover}
    falhas = 0
    for ident, titulo in etapas(apagar):
        diz(f"\n==> {ident} {titulo}")
        try:
            erros = int(passos[ident](diz) or 0)
        except Exception as erro:                  # 一个阶段不阻碍其他阶段
            diz(f"  ERRO: {erro}")
            estado.registrar(f"撤销 {ident} 失败：{erro!r}")
            falhas += 1
            continue
        if erros:
            falhas += erros
            diz(f"  ERRO: 本阶段有 {erros} 项有问题")
            continue
        diz(f"  concluido: {titulo}")
    return falhas
