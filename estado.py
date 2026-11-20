"""已应用的内容、日志和备份。"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
from pathlib import Path

from . import caminhos


def _agora() -> str:
    return _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def registrar(texto: str) -> None:
    caminhos.preparar()
    try:
        with caminhos.REGISTRO.open("a", encoding="utf-8") as arq:
            arq.write(f"[{_agora()}] {texto}\n")
    except OSError:
        pass


def marca(ident: str) -> Path:
    return caminhos.APLICADO / ident


def aplicado(ident: str) -> bool:
    return marca(ident).is_file()


def quando(ident: str) -> str:
    try:
        return marca(ident).read_text().strip()
    except OSError:
        return ""


def marcar(ident: str) -> None:
    caminhos.preparar()
    try:
        caminhos.escrever(marca(ident), _agora() + "\n")
    except OSError:
        pass


def desmarcar(ident: str) -> None:
    marca(ident).unlink(missing_ok=True)


def limpar_marcas() -> None:
    for arquivo in caminhos.APLICADO.glob("*"):
        arquivo.unlink(missing_ok=True)
    # 目录保留撤销的时间：比它更旧的日志已被撤销，
    # 同族的其他主题不再看到本主题（familia.py）
    try:
        os.utime(caminhos.APLICADO)
    except OSError:
        pass


def copia_de_seguranca(alvo: Path) -> bool:
    """在改动前保存文件或目录，保留目录树。

    只保存第一个版本：目标是能回到 d3bian-init-bigsur-xfce 之前的状态，
    而不是保留每次执行的历史。
    """
    alvo = Path(alvo).expanduser()
    if not alvo.exists():
        return False
    if not caminhos.da_pessoa(alvo):
        return _copia_do_sistema(alvo)
    destino = caminhos.BACKUP / str(alvo).lstrip("/")
    if destino.exists():
        return True
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        if alvo.is_dir():
            shutil.copytree(alvo, destino, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(alvo, destino)
        registrar(f"备份：{alvo}")
        return True
    except (OSError, shutil.Error) as erro:
        registrar(f"备份 {alvo} 失败：{erro}")
        return False


def _copia_do_sistema(alvo: Path) -> bool:
    """系统文件：副本放在 caminhos.BACKUP_SISTEMA，属于 root 且封闭（0700），
    撤销也从那里恢复。"""
    raiz = str(caminhos.BACKUP_SISTEMA)
    bruto = str(alvo)
    # 含 ".." 的路径会离开备份目录
    if not bruto.startswith("/") or os.path.normpath(bruto) != bruto:
        registrar(f"（root）备份被拒绝，异常路径：{bruto}")
        return False
    destino = str(caminhos.BACKUP_SISTEMA / bruto.lstrip("/"))
    # 只保存第一个版本，如用户目录；备份目录必须是 root 的且不是链接，
    # 解析后的目标位于其中
    trecho = ('[ -e "$2" ] || [ -L "$2" ] && exit 0; '
              '[ -L "$1" ] && exit 1; '
              'install -d -m 0700 -o root -g root "$1" && [ "$(stat -c %u "$1")" = 0 ] '
              '&& mkdir -p "$(dirname "$2")" '
              '&& case "$(realpath -m -- "$2")" in "$1"/*) ;; *) exit 1;; esac '
              '&& cp -a "$3" "$2"')
    try:
        ok = subprocess.run(["sudo", "-n", "sh", "-c", trecho, "sh", raiz, destino, str(alvo)],
                            capture_output=True, stdin=subprocess.DEVNULL,
                            timeout=600).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    registrar(f"（root）备份：{alvo}" if ok else f"（root）备份 {alvo} 失败")
    return ok


def restaurar_tudo() -> list[str]:
    """把保存的文件放回原处。返回已恢复的内容。"""
    feitos: list[str] = []
    raiz = caminhos.BACKUP
    if not raiz.is_dir():
        return feitos
    for origem in sorted(raiz.rglob("*")):
        if origem.is_dir():
            continue
        relativo = origem.relative_to(raiz)
        # 只恢复来自根下存在的目录（如 home 或 etc）的内容；
        # 写在这里的旧记录（xfconf、软件包列表）会落到 /xfconf
        if len(relativo.parts) < 2 or not (Path("/") / relativo.parts[0]).is_dir():
            continue
        destino = Path("/") / relativo
        # 主目录之外，只恢复 root 目录中的内容（desfazer.py）
        if not caminhos.da_pessoa(destino):
            continue
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino)
            feitos.append(str(destino))
        except OSError as erro:
            registrar(f"无法恢复 {destino}：{erro}")
    return feitos
