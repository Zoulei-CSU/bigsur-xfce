"""记录配方对机器所做更改的日志。

引擎中每个会改动内容的步骤都会在这里写入一行 JSON：创建或修改的文件、写入的
块、xfconf、gsettings 或 dconf 之前的值、安装的软件包。desfazer.py 倒序遍历该
日志，因此当同一内容被改动多次时，最后撤销的是最早的那次，恢复的是项目之前的
状态。

配方脚本不经过引擎：它通过引擎放在每个脚本开头、在任何改动之前的函数来记录，
这些函数调用本模块：

    d3_antes 路径...             文件或目录：存在则备份，否则记为 "criado"
    d3_gsettings 架构 键         保存当前值
    d3_dconf /路径/键            保存当前值（为空：原本是默认值）
    d3_xfconf 通道 /键 类型      保存当前值以及是否存在
    d3_processo 名称             保存启动前是否已在运行
    d3_criado 路径...            仅创建后才知道的内容（新的配置文件）
    d3_pacotes 名称...           脚本安装且之前不存在的软件包

模拟不会记录任何内容，撤销本身也不记录。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import caminhos, estado


def arquivo() -> Path:
    return caminhos.ESTADO_DIR / "diario.jsonl"


def anotar(tipo: str, **dados) -> None:
    caminhos.preparar()
    linha = {"quando": estado._agora(), "tipo": tipo, **dados}
    try:
        with arquivo().open("a", encoding="utf-8") as saida:
            saida.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError as erro:
        estado.registrar(f"无法写入更改日志：{erro}")


def ler() -> list[dict]:
    try:
        linhas = arquivo().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    itens = []
    for linha in linhas:
        try:
            item = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        # 更改日志位于用户目录中：相对路径或含 ".."（/usr/share/themes/../../etc）
        # 不会到达撤销流程
        if "caminho" in item and not caminho_limpo(item["caminho"]):
            continue
        if "criados" in item:
            item["criados"] = [c for c in item.get("criados") or [] if caminho_limpo(c)]
        itens.append(item)
    return itens


def caminho_limpo(bruto) -> bool:
    """绝对且已规范化（不含 ".."、"." 或重复斜杠）。"""
    return (isinstance(bruto, str) and bruto.startswith("/")
            and os.path.normpath(bruto) == bruto)


def existe() -> bool:
    return arquivo().is_file()


# ---- 当前值，在更改之前 -----------------------------------------------

def _saida(argumentos: list[str]) -> tuple[int, str]:
    try:
        # 用英文：撤销流程识别 xfconf-query 的 "Value is an array"
        proc = subprocess.run(argumentos, capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
    except OSError:
        return 127, ""
    return proc.returncode, proc.stdout


def _criado_pelo_projeto(caminho: Path) -> bool:
    """已记录为创建（它本身或其上级目录）：安装后的“应用”不能把项目自己放在
    那里的内容当作“之前的状态”保存。"""
    alvos = {str(caminho), *(str(p) for p in caminho.parents)}
    return any(i.get("tipo") == "criado" and i.get("caminho") in alvos for i in ler())


def antes_do_caminho(caminho: Path, receita: str = "") -> None:
    caminho = Path(caminho).expanduser()
    if _criado_pelo_projeto(caminho):
        return
    if caminho.exists() or caminho.is_symlink():
        estado.copia_de_seguranca(caminho)
        anotar("alterado", receita=receita, caminho=str(caminho))
    else:
        anotar("criado", receita=receita, caminho=str(caminho))


def antes_do_gsettings(esquema: str, chave: str, receita: str = "") -> None:
    if not shutil.which("gsettings"):
        return
    codigo, valor = _saida(["gsettings", "get", esquema, chave])
    if codigo != 0:
        return
    anotar("gsettings", receita=receita, esquema=esquema, chave=chave, valor=valor.strip(),
           padrao=not _gravado(esquema, chave))


def _gravado(esquema: str, chave: str) -> bool:
    """该键是否有用户写入的值（而不是架构默认值）？

    键从未写入时 gsettings get 会返回默认值，无法据此区分；只有 dconf 在架构路径
    中知道。可重定位架构以 ESQUEMA:/CAMINHO/ 形式出现（plank 的每个 dock 一个）。
    没有 dconf-cli 时，通过 python3-gi 询问 GSettings 本身；两者都没有时按已写入
    处理（撤销会写入之前的值，而不是清零）。
    """
    nome, _, base = esquema.partition(":")
    caminho = (base.rstrip("/") if base else "/" + nome.replace(".", "/")) + "/" + chave
    if shutil.which("dconf"):
        return _saida(["dconf", "read", caminho])[1].strip() != ""
    programa = ("import sys\n"
                "from gi.repository import Gio\n"
                "n, b, k = sys.argv[1:4]\n"
                "s = Gio.Settings.new_with_path(n, b) if b else Gio.Settings.new(n)\n"
                "sys.exit(10 if s.get_user_value(k) is None else 11)\n")
    try:
        r = subprocess.run([sys.executable, "-c", programa, nome, base, chave],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return True
    return r.returncode != 10


def antes_do_dconf(chave: str, receita: str = "") -> None:
    if not shutil.which("dconf"):
        return
    _, valor = _saida(["dconf", "read", chave])
    anotar("dconf", receita=receita, chave=chave, valor=valor.strip())


def antes_do_xfconf(canal: str, chave: str, tipo: str = "string", receita: str = "") -> None:
    if not shutil.which("xfconf-query"):
        return
    codigo, valor = _saida(["xfconf-query", "-c", canal, "-p", chave])
    # 通道还没有任何属性：撤销会删除留下的空文件
    _, lista = _saida(["xfconf-query", "-c", canal, "-l"])
    anotar("xfconf", receita=receita, canal=canal, chave=chave, existia=codigo == 0,
           valor=valor, tipo_valor=tipo, canal_existia=any(l.startswith("/") for l in lista.splitlines()))


def antes_do_processo(nome: str, receita: str = "") -> None:
    codigo, _ = _saida(["pgrep", "-x", nome])
    anotar("processo", receita=receita, nome=nome, rodava=codigo == 0)


def main(argumentos: list[str]) -> int:
    """由脚本的 d3_* 函数调用。绝不会因记录而让脚本失败。"""
    if os.environ.get("D3_SEM_DIARIO") or os.environ.get("CTX_SEM_DIARIO"):
        return 0
    receita = os.environ.get("D3_RECEITA") or os.environ.get("CTX_RECEITA", "")
    try:
        comando, *resto = argumentos
        if comando == "antes":
            for caminho in resto:
                antes_do_caminho(Path(caminho), receita)
        elif comando == "gsettings":
            antes_do_gsettings(resto[0], resto[1], receita)
        elif comando == "dconf":
            antes_do_dconf(resto[0], receita)
        elif comando == "xfconf":
            antes_do_xfconf(resto[0], resto[1], resto[2] if len(resto) > 2 else "string", receita)
        elif comando == "processo":
            antes_do_processo(resto[0], receita)
        elif comando == "pasta":
            for caminho in resto:
                pasta = Path(caminho).expanduser()
                if not pasta.exists():
                    anotar("pasta", receita=receita, caminho=str(pasta))
        elif comando == "criado":
            for caminho in resto:
                anotar("criado", receita=receita, caminho=str(Path(caminho).expanduser()))
        elif comando == "pacotes" and resto:
            anotar("pacotes", receita=receita, nomes=list(resto))
    except (ValueError, IndexError, OSError) as erro:
        estado.registrar(f"diario: 无法记录 {argumentos}：{erro}")
    return 0


# 以 root 在属于 root 的副本中运行：指向树外（绝对路径或过多 ..）的链接会
# 被移除，以免把指向用户目录的快捷方式带进系统
LINKS_PY = """import os, sys
raiz = os.path.realpath(sys.argv[1])
for pasta, dirs, arqs in os.walk(raiz):
    for nome in dirs + arqs:
        caminho = os.path.join(pasta, nome)
        if os.path.islink(caminho):
            alvo = os.path.realpath(caminho)
            if alvo != raiz and not alvo.startswith(raiz + os.sep):
                os.unlink(caminho)
"""

# 由引擎放在每个配方脚本的开头
FUNCOES_SHELL = r'''
_d3_diario() { PYTHONPATH="$D3_DIARIO_PAI${PYTHONPATH:+:$PYTHONPATH}" "$D3_DIARIO_PYTHON" -m "$D3_DIARIO_PACOTE.diario" "$@" || true; }
d3_antes() { _d3_diario antes "$@"; }
d3_gsettings() { _d3_diario gsettings "$@"; }
d3_dconf() { _d3_diario dconf "$@"; }
d3_xfconf() { _d3_diario xfconf "$@"; }
d3_processo() { _d3_diario processo "$@"; }
d3_criado() { _d3_diario criado "$@"; }
# 尚不存在的公共目录（~/.themes、~/.icons……）：变空时撤销会将其删除
d3_pasta() { _d3_diario pasta "$@"; }
# 第三方安装器之前和之后：匹配模式（glob）且之前不存在的内容会作为“创建”记入日志
_D3_ANTES=""
d3_antes_de() {
  _D3_ANTES="$(for g in "$@"; do compgen -G "$g" || true; done)"
  local e
  while IFS= read -r e; do [ -n "$e" ] && d3_antes "$e"; done <<< "$_D3_ANTES"
  return 0
}
d3_depois_de() {
  local g e
  for g in "$@"; do
    while IFS= read -r e; do
      [ -n "$e" ] || continue
      grep -qxF -- "$e" <<< "$_D3_ANTES" || d3_criado "$e"
    done < <(compgen -G "$g" || true)
  done
  return 0
}
d3_pacotes() { _d3_diario pacotes "$@"; }
# ORIGEM（用户文件或目录）以 root:root 身份进入系统中的 DESTINO，组和其他用户
# 不可写，并可选设置 MODO（文件）。root 先复制到自己的新目录（sudo mktemp -d）
# 再从那里安装：源根部的符号链接会被拒绝，指向树外的链接会被移除。
# 调用此处的片段算作含 sudo 的片段（motor.py）：其中不放第三方代码。
d3_raiz_instalar() {
  local origem=$1 destino=$2 modo=${3:-} r
  if [ -L "$origem" ] || [ ! -e "$origem" ]; then
    echo "已拒绝（符号链接或不存在）：$origem" >&2; return 1
  fi
  r="$(sudo -n mktemp -d)" || return 1
  if ! sudo -n cp -R -P --no-preserve=all -- "$origem" "$r/c" || sudo -n test -L "$r/c"; then
    sudo -n rm -rf -- "$r"; echo "已拒绝：$origem" >&2; return 1
  fi
  sudo -n python3 -I -c "$D3_LINKS_PY" "$r/c"
  sudo -n chown -R root:root "$r/c"
  sudo -n chmod -R u+rwX,go+rX,go-w "$r/c"
  if [ -n "$modo" ]; then sudo -n chmod "$modo" "$r/c"; fi
  sudo -n install -d -m 755 -- "$(dirname "$destino")"
  sudo -n rm -rf -- "$destino"
  if ! sudo -n mv -T -- "$r/c" "$destino"; then
    sudo -n rm -rf -- "$r"; return 1
  fi
  sudo -n rm -rf -- "$r"
}
'''


def ambiente_shell(receita: str, anotar_ligado: bool) -> dict[str, str]:
    """FUNCOES_SHELL 用于找到本模块的变量。"""
    return {
        "D3_DIARIO_PAI": str(caminhos.PACOTE.parent),
        "D3_DIARIO_PACOTE": caminhos.PACOTE.name,
        "D3_DIARIO_PYTHON": sys.executable or "python3",
        "D3_RECEITA": receita,
        "D3_LINKS_PY": LINKS_PY,
        **({} if anotar_ligado else {"D3_SEM_DIARIO": "1"}),
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
