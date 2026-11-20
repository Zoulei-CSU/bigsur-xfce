#!/usr/bin/env python3
"""复制 xfwm4 主题，把边框加宽，便于抓取和调整大小。

我们使用的主题（WhiteSur、Orchis、Nordic、Gruvbox、Everforest）把侧边和
底部边框画成 1 到 2 像素，只能精准点中这条细线才能调整大小。xfwm4 只接受
点击 100% 不透明的像素，因此看不见的边框无效：新边框必须被绘制出来。它用
标题栏颜色绘制在主题轮廓与内容之间，窗口看起来只是多了一圈稍厚的边框。

    d3bian-bordas                 使用 xfwm4 当前主题
    d3bian-bordas TEMA [PIXELS]   默认多出 4 像素

创建 ~/.themes/TEMA-bordas/xfwm4，并在输出中写出其名称。由调用方决定是否
应用（xfconf-query -c xfwm4 -p /general/theme -s NOME）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

SUFIXO = "-bordas"
# xfwm4 查找覆盖 xpm 的图片的顺序
IMAGENS = ("svg", "png", "gif", "jpg", "bmp")
CHARS = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
         "0123456789#$%&*+-=@;:,<>?!~^_|/()[]{}")


def pasta_do_tema(nome: str) -> Path | None:
    dados = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    bases = [Path.home() / ".themes", Path.home() / ".local/share/themes"]
    bases += [Path(d) / "themes" for d in dados if d]
    for base in bases:
        if (base / nome / "xfwm4" / "themerc").is_file():
            return base / nome / "xfwm4"
    return None


# --------------------------------------------------------------------------
# 图像表示为数值网格：RGBA 元组（png）或颜色定义（xpm）
# --------------------------------------------------------------------------

class Grade:
    def __init__(self, linhas: list[list], opaco) -> None:
        self.linhas = linhas
        self.opaco = opaco

    @property
    def w(self) -> int:
        return len(self.linhas[0]) if self.linhas else 0

    @property
    def h(self) -> int:
        return len(self.linhas)

    def px(self, x: int, y: int):
        return self.linhas[y][x]

    def inserir_colunas(self, onde: int, n: int, valor) -> None:
        for y, linha in enumerate(self.linhas):
            linha[onde:onde] = [valor(y)] * n

    def inserir_linhas(self, onde: int, n: int, valor) -> None:
        novas = [[valor(x) for x in range(self.w)] for _ in range(n)]
        self.linhas[onde:onde] = novas


def ler_pixbuf(caminho: Path) -> Grade:
    pb = GdkPixbuf.Pixbuf.new_from_file(str(caminho))
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, passo = pb.get_width(), pb.get_height(), pb.get_rowstride()
    dados = pb.get_pixels()
    linhas = [[tuple(dados[y * passo + x * 4:y * passo + x * 4 + 4]) for x in range(w)]
              for y in range(h)]
    return Grade(linhas, lambda v: v[3] == 255)


def gravar_png(grade: Grade, caminho: Path) -> None:
    bruto = bytes(b for linha in grade.linhas for px in linha for b in px)
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bruto), GdkPixbuf.Colorspace.RGB,
                                         True, 8, grade.w, grade.h, grade.w * 4)
    pb.savev(str(caminho), "png", [], [])


def _normal(definicao: str) -> str:
    return " ".join(definicao.split())


def ler_xpm(caminho: Path) -> tuple[Grade, str]:
    texto = caminho.read_text(errors="replace")
    textos = re.findall(r'"((?:[^"\\]|\\.)*)"', texto)
    w, h, n, cpp = (int(x) for x in textos[0].split()[:4])
    cores = {}
    for linha in textos[1:1 + n]:
        cores[linha[:cpp]] = _normal(linha[cpp:])
    linhas = []
    for linha in textos[1 + n:1 + n + h]:
        linhas.append([cores[linha[i:i + cpp]] for i in range(0, w * cpp, cpp)])
    nome = re.search(r"char\s*\*\s*(\w+)", texto)
    return Grade(linhas, lambda v: "none" not in v.lower().split()), (nome.group(1) if nome else "xpm")


def gravar_xpm(grade: Grade, caminho: Path, nome: str) -> None:
    usadas = list(dict.fromkeys(v for linha in grade.linhas for v in linha))
    cpp = 1 if len(usadas) <= len(CHARS) else 2
    chaves = [CHARS[i] if cpp == 1 else CHARS[i // len(CHARS)] + CHARS[i % len(CHARS)]
              for i in range(len(usadas))]
    mapa = dict(zip(usadas, chaves))
    saida = ["/* XPM */", f"static char *{nome}[] = {{",
             f'"{grade.w} {grade.h} {len(usadas)} {cpp} ",']
    saida += [f'"{mapa[v]} {v}",' for v in usadas]
    saida += ['"' + "".join(mapa[v] for v in linha) + '",' for linha in grade.linhas]
    saida[-1] = saida[-1].rstrip(",")
    saida.append("};")
    caminho.write_text("\n".join(saida) + "\n")


# --------------------------------------------------------------------------
# 加宽
# --------------------------------------------------------------------------

def carregar(origem: Path, peca: str) -> dict[str, tuple[Grade, str]]:
    """某一部分的全部图像，按格式：xpm 以及其上层的格式。"""
    achadas: dict[str, tuple[Grade, str]] = {}
    xpm = origem / f"{peca}.xpm"
    if xpm.is_file():
        achadas["xpm"] = ler_xpm(xpm)
    for ext in IMAGENS:
        arquivo = origem / f"{peca}.{ext}"
        if arquivo.is_file():
            try:
                achadas[ext] = (ler_pixbuf(arquivo), "")
            except GLib.Error:
                continue
            break
    return achadas


def cor_do_titulo(origem: Path, estado: str) -> dict[str, object]:
    """标题栏中部的颜色，按各格式。"""
    cores: dict[str, object] = {}
    for peca in (f"title-3-{estado}", f"title-1-{estado}", f"top-left-{estado}"):
        for ext, (grade, _) in carregar(origem, peca).items():
            x = grade.w // 2 if peca.startswith("title") else grade.w - 1
            valor = grade.px(x, grade.h // 2)
            if grade.opaco(valor):
                cores.setdefault("xpm" if ext == "xpm" else "img", valor)
        if len(cores) == 2:
            break
    if "img" in cores and "xpm" not in cores:
        r, g, b, _ = cores["img"]
        cores["xpm"] = f"c #{r:02X}{g:02X}{b:02X}"
    if "xpm" in cores and "img" not in cores:
        cor = re.search(r"#([0-9A-Fa-f]{6})", str(cores["xpm"]))
        rgb = bytes.fromhex(cor.group(1)) if cor else b"\x80\x80\x80"
        cores["img"] = (*rgb, 255)
    return cores


def alargar(grade: Grade, peca: str, n: int, fundo, contorno: set) -> None:
    lado, _, _ = peca.rpartition("-")
    esquerda = lado != "bottom-right"

    # 新像素在内侧邻居是轮廓或落在拐角弧线之外时复制它；
    # 其余情况则变为标题栏颜色。透明且外侧有边框的部分原本在窗口
    # 背后，现在会显现出来
    def regra(x: int, y: int):
        ref = grade.px(x, y)
        if grade.opaco(ref):
            return ref if ref in contorno else fundo
        fora = range(x) if esquerda else range(x + 1, grade.w)
        return fundo if any(grade.opaco(grade.px(i, y)) for i in fora) else ref

    if lado in ("left", "bottom-left"):
        ref = min(1, grade.w - 1)
        col = [fundo if lado == "left" else regra(ref, y) for y in range(grade.h)]
        grade.inserir_colunas(1, n, lambda y: col[y])
    if lado in ("right", "bottom-right"):
        ref = max(grade.w - 2, 0)
        col = [fundo if lado == "right" else regra(ref, y) for y in range(grade.h)]
        grade.inserir_colunas(grade.w - 1, n, lambda y: col[y])
    if lado in ("bottom", "bottom-left", "bottom-right"):
        ref = max(grade.h - 2, 0)
        lin = [fundo if lado == "bottom" else regra(x, ref) for x in range(grade.w)]
        grade.inserir_linhas(grade.h - 1, n, lambda x: lin[x])


def contornos(origem: Path, estado: str) -> dict[str, set]:
    """侧边和底部边框的外侧像素，按各格式。"""
    saida: dict[str, set] = {"xpm": set(), "img": set()}
    for peca, onde in ((f"left-{estado}", lambda g: (0, g.h // 2)),
                       (f"right-{estado}", lambda g: (g.w - 1, g.h // 2)),
                       (f"bottom-{estado}", lambda g: (g.w // 2, g.h - 1))):
        for ext, (grade, _) in carregar(origem, peca).items():
            saida["xpm" if ext == "xpm" else "img"].add(grade.px(*onde(grade)))
    return saida


PECAS = ("left", "right", "bottom", "bottom-left", "bottom-right")


def gerar(tema: str, n: int) -> str:
    base = tema[:-len(SUFIXO)] if tema.endswith(SUFIXO) else tema
    origem = pasta_do_tema(base)
    if origem is None:
        raise SystemExit(f"找不到 xfwm4 主题 {base}")
    nome = base + SUFIXO
    destino = Path.home() / ".themes" / nome / "xfwm4"
    if destino.parent.exists():
        shutil.rmtree(destino.parent)
    shutil.copytree(origem, destino, symlinks=False)

    for estado in ("active", "inactive"):
        fundo = cor_do_titulo(origem, estado)
        if not fundo:
            continue
        linhas = contornos(origem, estado)
        for lado in PECAS:
            peca = f"{lado}-{estado}"
            for ext, (grade, rotulo) in carregar(origem, peca).items():
                chave = "xpm" if ext == "xpm" else "img"
                alargar(grade, peca, n, fundo[chave], linhas[chave])
                if ext == "xpm":
                    gravar_xpm(grade, destino / f"{peca}.xpm", rotulo)
                else:
                    # svg、gif 等会转为 png，xfwm4 读取效果相同
                    for outro in IMAGENS:
                        (destino / f"{peca}.{outro}").unlink(missing_ok=True)
                    gravar_png(grade, destino / f"{peca}.png")
    return nome


def tema_atual() -> str:
    try:
        return subprocess.run(["xfconf-query", "-c", "xfwm4", "-p", "/general/theme"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit("无法读取 xfwm4 当前主题")


def main(args: list[str]) -> int:
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    tema = args[0] if args else tema_atual()
    n = int(args[1]) if len(args) > 1 else 4
    if not 1 <= n <= 12:
        raise SystemExit("请使用 1 到 12 像素")
    print(gerar(tema, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
