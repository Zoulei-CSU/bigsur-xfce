"""壁纸图库。

文件来自 WhiteSur 壁纸仓库，由配方 33 下载，存放在用户的背景图片目录中。
这里只负责列出、生成缩略图并决定使用哪张。

安装前目录尚不存在，因此包内为每张壁纸在 recursos/web/papeis 中带有缩略图。
选择按名称保存，上下文在每条配方中重建：外观运行到那里时，该名称的文件已被
下载。下载仓库新版本后要重建缩略图：

    for f in ~/.local/share/backgrounds/WhiteSur/*; do
      convert "$f" -resize 320x -strip -quality 78 \\
        "recursos/web/papeis/$(basename "${f%.*}").jpg"
    done
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import caminhos

PASTA = Path.home() / ".local/share/backgrounds/WhiteSur"
CATALOGO = caminhos.WEB / "papeis"
EXTENSOES = (".jpg", ".jpeg", ".png")
# 页面上为登录界面背景选择的图片
LOGIN_PROPRIA = caminhos.DADOS_DIR / "login-propria.jpg"
NOME_VALIDO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")

# 当用户让主题自行选择时，这是优先顺序。WhiteSur 的 "-dark" 变体是近乎黑色的灰色，
# 因此深色主题更偏好彩色版本，效果更好。
PREFERENCIA = {
    "escuro": ("WhiteSur", "WhiteSur-morning", "Monterey", "WhiteSur-dark"),
    "claro": ("WhiteSur-light", "WhiteSur-morning", "WhiteSur", "Monterey-light"),
}


def _listar(pasta: Path) -> list[dict]:
    if not pasta.is_dir():
        return []
    saida = []
    for arquivo in sorted(pasta.iterdir()):
        if arquivo.suffix.lower() not in EXTENSOES or not arquivo.is_file():
            continue
        if not NOME_VALIDO.fullmatch(arquivo.stem):
            continue
        saida.append({"nome": arquivo.stem, "arquivo": arquivo.name,
                      "escuro": "dark" in arquivo.stem.lower()})
    return saida


def baixados() -> bool:
    """壁纸已经到机器上了吗？"""
    return bool(_listar(PASTA))


def disponiveis() -> list[dict]:
    """按字母顺序排列的壁纸：已下载的，或在下载前来自包内目录的。"""
    return _listar(PASTA) or _listar(CATALOGO)


def caminho(nome: str) -> Path | None:
    """某张壁纸的文件，名称安全且存在时返回。"""
    if not nome or not NOME_VALIDO.fullmatch(nome):
        return None
    for ext in EXTENSOES:
        alvo = PASTA / f"{nome}{ext}"
        if alvo.is_file() and alvo.parent == PASTA:
            return alvo
    return None


def nome_escolhido(cfg: dict[str, str]) -> str | None:
    """按名称使用哪张壁纸；下载前同样有效。"""
    valor = cfg.get("papel_de_parede", "do-tema")
    if valor == "manter":
        return None
    todos = disponiveis()
    existentes = {p["nome"] for p in todos}
    # 已从仓库消失的名称回退到主题的偏好
    if valor != "do-tema" and valor in existentes:
        return valor
    for nome in PREFERENCIA.get(cfg.get("tema", "escuro"), ()):
        if nome in existentes:
            return nome
    return todos[0]["nome"] if todos else None


def escolhido(cfg: dict[str, str]) -> Path | None:
    """按偏好使用哪个文件。None 表示不修改，在图片尚未下载时也是如此。"""
    nome = nome_escolhido(cfg)
    return caminho(nome) if nome else None


def do_desktop() -> Path | None:
    """xfdesktop 当前显示的文件，包括来自图库之外的。"""
    try:
        saida = subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-lv"],
                               capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    # 含 workspace0 的键属于当前连接的显示器；其他通常是旧显示器的残留
    candidatos = []
    for linha in saida.splitlines():
        chave, _, valor = linha.partition(" ")
        if chave.endswith("/last-image"):
            candidatos.append((0 if "/workspace0/" in chave else 1, valor.strip()))
    for _, valor in sorted(candidatos):
        if valor and Path(valor).is_file():
            return Path(valor)
    return None


def fundo_login(cfg: dict[str, str]) -> Path | None:
    """登录界面背景的源图片。"""
    valor = cfg.get("login_fundo", "desktop")
    # 用户自己的图片；没有时（被删除、别的机器），使用与桌面相同的
    if valor == "propria" and LOGIN_PROPRIA.is_file():
        return LOGIN_PROPRIA
    if valor == "do-tema":
        return escolhido({**cfg, "papel_de_parede": "do-tema"})
    if valor != "desktop":
        direto = caminho(valor)
        if direto:
            return direto
    # "desktop"：外观将应用的那张，或在外观保留用户壁纸时，屏幕上已有的那张
    return escolhido(cfg) or do_desktop()


def miniatura(nome: str, largura: int = 320) -> Path | None:
    """图库壁纸的缓存缩略图；下载前使用包内的。"""
    origem = caminho(nome)
    if origem:
        return _miniatura(origem, nome, largura)
    if not NOME_VALIDO.fullmatch(nome or ""):
        return None
    pronta = CATALOGO / f"{nome}.jpg"
    return pronta if pronta.is_file() else None


def _miniatura(origem: Path, chave: str, largura: int) -> Path | None:
    """首次生成，之后只读取。"""
    destino = caminhos.DADOS_DIR / "miniaturas" / f"{chave}.jpg"
    if destino.is_file() and destino.stat().st_mtime >= origem.stat().st_mtime:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        pronto = subprocess.run(
            ["convert", str(origem), "-resize", f"{largura}x", "-quality", "80",
             str(destino)], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pronto = False
    if pronto and destino.is_file():
        return destino
    return origem          # 没有 ImageMagick，就使用整个文件
