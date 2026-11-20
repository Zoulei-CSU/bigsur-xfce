"""各处文件的位置。

遵循 XDG 规范，因此不会散落到用户主目录里。程序的资源（配方、页面、模板文件）
都来自包内部，可以直接从源码运行，也可以由 .deb 安装，无需任何改动。
"""

from __future__ import annotations

import os
from pathlib import Path

PACOTE = Path(__file__).resolve().parent
RECURSOS = PACOTE / "recursos"
RECEITAS = RECURSOS / "receitas"
WEB = RECURSOS / "web"
ARQUIVOS = RECURSOS / "arquivos"
CATALOGO = RECURSOS / "programas.json"


def _xdg(variavel: str, padrao: str) -> Path:
    bruto = os.environ.get(variavel, "").strip()
    base = Path(bruto) if bruto.startswith("/") else Path.home() / padrao
    return base


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "d3bian-init"
ESTADO_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "d3bian-init"
DADOS_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "d3bian-init"

CONFIG = CONFIG_DIR / "config.json"
REGISTRO = ESTADO_DIR / "registro.log"
APLICADO = ESTADO_DIR / "aplicado"
BACKUP = ESTADO_DIR / "backup"
FONTES = DADOS_DIR / "fontes"          # 克隆的仓库
CAPTURAS = DADOS_DIR / "capturas"      # 用户生成的预览

# 系统文件（/etc、/usr/share）的副本放在 root 的目录里：撤销时以 root 恢复，
# 而放在用户目录里的副本可能在恢复前被该用户的任意程序篡改。
BACKUP_SISTEMA = Path("/var/backups/d3bian-init-bigsur-xfce")


def preparar() -> None:
    """创建工作目录。开销很小，可以随时调用。"""
    for pasta in (CONFIG_DIR, ESTADO_DIR, APLICADO, BACKUP, DADOS_DIR, FONTES, CAPTURAS):
        pasta.mkdir(parents=True, exist_ok=True)
    # 日志和备份里可能有用户的路径和变量：只有本人可读
    for pasta in (ESTADO_DIR, BACKUP):
        os.chmod(pasta, 0o700)


def da_pessoa(caminho: Path) -> bool:
    """位于用户主目录内：用户本人无需 sudo 即可改动的内容。"""
    return Path(caminho).is_relative_to(Path.home())


def proteger_codigo() -> None:
    """去掉代码自身的组和其他用户写权限。部分代码以 sudo 运行；若别的账号能改动
    某个文件，就成了通往 root 的捷径。只改动属于本人的内容。"""
    uid = os.getuid()
    for raiz, pastas, arquivos in os.walk(PACOTE):
        for nome in [*pastas, *arquivos]:
            caminho = os.path.join(raiz, nome)
            try:
                info = os.lstat(caminho)
            except OSError:
                continue
            if info.st_uid == uid and info.st_mode & 0o022 and not os.path.islink(caminho):
                os.chmod(caminho, info.st_mode & ~0o022)


def escrever(destino: Path, texto: str, modo: int | None = None) -> None:
    """要么整个写入，要么不写：中途中断（断电、Ctrl+C）不会留下写了一半的文件。
    保留原有文件的权限。

    符号链接（指向 dotfiles 仓库的文件）会被跟随：写入真正的文件，链接仍然是
    链接。有多个名字的文件（硬链接）或属于其他所有者的文件就地重写，以免拆开
    名字或改变所有者。"""
    import tempfile
    destino = Path(destino)
    if destino.is_symlink():
        destino = Path(os.path.realpath(destino))
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        info = destino.stat()
    except OSError:
        info = None
    if info is not None and (info.st_nlink > 1 or info.st_uid != os.getuid()):
        with open(destino, "r+") as arquivo:
            arquivo.write(texto)
            arquivo.truncate()
            arquivo.flush()
            os.fsync(arquivo.fileno())
        if modo is not None:
            os.chmod(destino, modo)
        return
    if modo is None:
        if info is not None:
            modo = info.st_mode & 0o7777
        else:
            mascara = os.umask(0)
            os.umask(mascara)
            modo = 0o666 & ~mascara
    fd, temp = tempfile.mkstemp(dir=destino.parent, prefix=f".{destino.name}.")
    try:
        with os.fdopen(fd, "w") as arquivo:
            arquivo.write(texto)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.chmod(temp, modo)
        os.replace(temp, destino)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


class Ocupado(RuntimeError):
    """另一次运行（面板或命令行）已经在操作。"""


def livre() -> bool:
    """锁现在是空闲的吗？（以免保存一次会因命令行已在运行而被拒绝的执行的选项）"""
    try:
        with trava():
            return True
    except Ocupado:
        return False


class trava:
    """跨进程一次只允许一个执行：面板和命令行同时运行会争抢 apt 和相同的文件。"""

    def __enter__(self):
        import fcntl
        preparar()
        self._arquivo = open(ESTADO_DIR / "trava", "w")
        try:
            fcntl.flock(self._arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._arquivo.close()
            raise Ocupado("本项目的另一次执行已在运行") from None
        return self

    def __exit__(self, *_a) -> None:
        self._arquivo.close()


def captura(nome: str) -> Path:
    """一张预览：用户的预览优先于包内自带的。"""
    propria = CAPTURAS / f"{nome}.jpg"
    return propria if propria.is_file() else WEB / "capturas" / f"{nome}.jpg"
