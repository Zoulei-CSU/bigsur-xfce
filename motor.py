"""执行配方的步骤。

每个步骤都是一个带 `tipo` 字段的字典。引擎能执行少数几种明确定义的类型，
`script` 作为逃生通道，用于不值得用数据描述的内容。

所有文本都会经过上下文替换，因此配方写 `WhiteSur-@@gtk_variante@@`，引擎会
解析它。
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable

from . import caminhos, diario, estado, papeis, sistema

Saida = Callable[[str], None]


# --------------------------------------------------------------------------
# 上下文：配方可以插值的值
# --------------------------------------------------------------------------

# 偏好使用葡萄牙语名称，但第三方安装器期望英文名称。翻译放在这里而不是配方里，
# 以免把这种转换分散到各处。
DESTAQUE_EXTERNO = {
    "padrao": "default", "azul": "blue", "roxo": "purple", "rosa": "pink",
    "vermelho": "red", "laranja": "orange", "amarelo": "yellow",
    "verde": "green", "cinza": "grey",
}

# 与页面示意图相同的颜色；圆环组件用它们绘制
DESTAQUE_COR = {
    "padrao": "0860f2", "azul": "2e7cf7", "roxo": "9a57a3", "rosa": "e55e9c",
    "vermelho": "ed5f5d", "laranja": "e9873a", "amarelo": "f3ba4b",
    "verde": "79b757", "cinza": "8c8c8c",
}


# 从 GitHub 下载固定版本的 Dock，并在 apt 以 root 安装前用 SHA-256 校验：
# 被替换或损坏的 release 无法进入系统。更新时更换版本和哈希
# （GitHub 会显示 release 各文件的 sha256；或下载后运行 sha256sum）。
PLANK_VERSAO = "0.11.174"
PLANK_SHA256 = {
    "amd64": "4bbed4110e170789d22c5d11b7bf9970b8274436a9b8fb765dcc2c42210f3ab4",
    "arm64": "e564a7299f99b1b2a070a6772a381f01170bd2db82a85d40edf914a37b2f6533",
}
ARQUITETURAS = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

# 中国大陆访问 GitHub 常被阻断。设置 D3_GITHUB_MIRROR（或 GITHUB_MIRROR）为
# 前缀型镜像地址后，所有 GitHub 下载都会经过它；未设置时仍用 github.com。
GITHUB = "https://github.com"


def _github_base() -> str:
    """GitHub 前缀，后面直接接 /owner/repo 或 /owner/repo/releases/...。

    镜像按前缀使用（如 https://ghfast.top/https://github.com）；未设置时返回
    原始地址。也接受不带协议的写法，会自动补上 https://。
    """
    bruto = (os.environ.get("D3_GITHUB_MIRROR")
             or os.environ.get("GITHUB_MIRROR") or "").strip()
    if not bruto:
        return GITHUB
    if not re.match(r"https?://", bruto):
        bruto = "https://" + bruto
    return bruto.rstrip("/") + "/" + GITHUB


def montar_contexto(cfg: dict[str, str]) -> dict[str, str]:
    escuro = cfg.get("tema") == "escuro"
    logo = cfg.get("logo", "debian")

    # 标志图与背景相反：深色面板需要浅色图案
    if logo.endswith("-cor"):
        arquivo_logo = f"{logo[:-4]}-cor.svg"
    else:
        arquivo_logo = f"{logo}-{'claro' if escuro else 'escuro'}.svg"

    # WhiteSur 在主题名末尾加上颜色，如 WhiteSur-Dark-red，只有默认颜色不带后缀。
    # 否则用所选颜色编译的主题虽在磁盘上存在，却永远不会被使用。
    destaque = DESTAQUE_EXTERNO.get(cfg.get("destaque", "padrao"), "default")
    sufixo = "" if destaque == "default" else f"-{destaque}"
    variante = "Dark" if escuro else "Light"

    # 登录界面始终使用深色变体：输入框是照片上的浅色玻璃，顶部菜单需要白色文字。
    temas = Path("/usr/share/themes")
    login_tema = temas / f"WhiteSur-Dark{sufixo}" / "gtk-3.0/gtk.css"
    if not login_tema.is_file():
        login_tema = temas / "WhiteSur-Dark" / "gtk-3.0/gtk.css"

    # lightdm 不读取用户主目录（在 Debian 中是封闭的）；安装时照片会放到
    # /usr/share
    face = Path.home() / ".face"
    avatar = face if face.is_file() else caminhos.ARQUIVOS / "logos" / "debian-claro.svg"

    minutos = cfg.get("bloqueio", "10")

    # 虚拟机中视频通常由处理器模拟，使用 glx 和 vsync 的 picom 会停止重绘窗口：
    # 终端能收到输入，但文字只在焦点变化时出现。xrender 更简单，在这些情况下
    # 可用。
    try:
        virtual = " hypervisor" in Path("/proc/cpuinfo").read_text()
    except OSError:
        virtual = False

    ctx: dict[str, str] = dict(cfg)
    ctx.update({
        "HOME": str(Path.home()),
        "USUARIO": os.environ.get("USER", ""),
        "gtk_variante": variante,
        "gtk_tema": f"WhiteSur-{variante}{sufixo}",
        "gtk_tema_base": f"WhiteSur-{variante}",
        "gtk_sufixo": sufixo,
        "gtk_escuro": "true" if escuro else "false",
        # 这是 libadwaita 应用和门户选择颜色时查询的值
        "gtk_esquema": "prefer-dark" if escuro else "default",
        # 浅色 WhiteSur 的操作图标是深灰色，在深色主题的栏中会消失，
        # 因此变体跟随主题
        "icones": "WhiteSur-dark" if escuro else "WhiteSur",
        "cursores": "WhiteSur-cursors",
        # 两个变体位于同一个 Kvantum/WhiteSur 目录
        "kvantum_tema": "WhiteSurDark" if escuro else "WhiteSur",
        # 面板每次会话都会读取图标；指向包内部在从 U 盘运行时失效，
        # 因此配方把标志从 logo_origem 复制到本机上的 logo_arquivo
        "logo_origem": str(caminhos.ARQUIVOS / "logos" / arquivo_logo),
        "logo_arquivo": str(Path.home() / ".local/share/icons/d3bian-init" / arquivo_logo),
        "painel_fundo": "0.11 0.11 0.13 0.55" if escuro else "0.97 0.97 0.99 0.72",
        "painel_texto": "#f2f2f7" if escuro else "#1d1d1f",
        # 小米 MiSans（配方 21）；Inter 仍随配方 10 安装，作为回退
        "fonte_ui": "MiSans",
        "fonte_mono": "Fira Code",
        "destaque_externo": destaque,
        "widget_cor": DESTAQUE_COR.get(cfg.get("destaque", "padrao"), DESTAQUE_COR["padrao"]),
        "papel_arquivo": str(papeis.escolhido(cfg) or ""),
        # login_dir 是组装文件的位置：每次执行都新建并封闭
        # （0700、tempfile.mkdtemp），由 receitas.py 创建和删除
        # （/tmp 中的固定名称可能先被其他账户创建）；
        # 这里为空时，登录配方拒绝运行。login_raiz 是 greeter 看到它们的位置。
        # 预览会替换两者并关闭 login_instalar
        "login_dir": "",
        "login_raiz": "/usr/share/backgrounds/d3bian-init",
        "login_instalar": "sim",
        "login_tema_base": str(login_tema),
        "login_fundo_arquivo": str(papeis.fundo_login(cfg) or ""),
        "login_avatar_arquivo": str(avatar),
        "login_esconder_usuarios": "false" if cfg.get("login_usuarios") == "lista" else "true",
        "bloqueio_segundos": str(int(minutos) * 60) if minutos.isdigit() else "0",
        "picom_backend": "xrender" if virtual else "glx",
        "picom_vsync": "false" if virtual else "true",
        "plank_versao": PLANK_VERSAO,
        "plank_arquitetura": ARQUITETURAS.get(platform.machine().lower(), ""),
        "plank_sha256": PLANK_SHA256.get(ARQUITETURAS.get(platform.machine().lower(), ""), ""),
        "fontes": str(caminhos.FONTES),
        "arquivos": str(caminhos.ARQUIVOS),
        "github": _github_base(),
        # 供查询的记录放在这里，备份目录之外
        "estado_dir": str(caminhos.ESTADO_DIR),
    })
    return ctx


# 用 @@chave@@ 而不是 {chave}：大括号会与模板中出现的 conky、CSS 和 shell 语法冲突
_CHAVE = re.compile(r"@@([a-zA-Z_][a-zA-Z0-9_]*)@@")


def resolver(valor, ctx: dict[str, str]):
    """在文本和列表中把 @@chave@@ 替换为上下文的值。"""
    if isinstance(valor, str):
        return _CHAVE.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), valor)
    if isinstance(valor, list):
        return [resolver(x, ctx) for x in valor]
    if isinstance(valor, dict):
        return {c: resolver(v, ctx) for c, v in valor.items()}
    return valor


def condicao_atende(expressao: str, ctx: dict[str, str]) -> bool:
    """计算 `chave == valor` 或 `chave != valor`。刻意不支持更多。"""
    for operador, esperado in ((" != ", False), (" == ", True)):
        if operador in expressao:
            chave, _, alvo = expressao.partition(operador)
            igual = ctx.get(chave.strip(), "") == alvo.strip().strip('"\'')
            return igual is esperado
    return bool(ctx.get(expressao.strip()))


# --------------------------------------------------------------------------
# motor
# --------------------------------------------------------------------------

# 用户改动过的配置文件：保留其版本，不询问
APT_SEM_PERGUNTAS = ["-o", "Dpkg::Options::=--force-confdef",
                     "-o", "Dpkg::Options::=--force-confold"]


# 以 root 将用户目录（$1）复制到系统（$2）：经过 root 的新目录，拒绝根部的
# 符号链接，移除指向树外的链接，最终为 root:root 且组和其他用户不可写
COPIA_ROOT = r'''
set -eu
r=$(mktemp -d)
trap 'rm -rf "$r"' EXIT
[ ! -L "$1" ] && [ -e "$1" ] || { echo "已拒绝：$1" >&2; exit 1; }
cp -R -P --no-preserve=all -- "$1" "$r/c"
[ ! -L "$r/c" ] || { echo "已拒绝：$1" >&2; exit 1; }
python3 -I -c "$3" "$r/c"
chown -R root:root "$r/c"
chmod -R u+rwX,go+rX,go-w "$r/c"
mkdir -p -- "$(dirname "$2")"
rm -rf -- "$2"
mv -T -- "$r/c" "$2"
'''


class ErroDePasso(Exception):
    pass


class Motor:
    def __init__(self, ctx: dict[str, str], saida: Saida | None = None,
                 simular: bool = False, receita: str = "", anotar: bool = True) -> None:
        self.ctx = ctx
        self.simular = simular
        self._saida = saida or (lambda t: None)
        # 更改日志（diario.py）记录改动供撤销使用；模拟和撤销本身不记录
        self.receita = receita
        self.anotar = anotar and not simular

    def _anotar(self, tipo: str, **dados) -> None:
        if self.anotar:
            diario.anotar(tipo, receita=self.receita, **dados)

    # ---- 工具 ------------------------------------------------------
    def diz(self, texto: str) -> None:
        self._saida(texto)
        estado.registrar(texto)

    def _executa(self, argumentos: list[str], root: bool = False,
                 entrada: str | None = None) -> int:
        if root:
            # sudo 会清空环境：DEBIAN_FRONTEND 必须内置传入，
            # 否则会提问的包（debconf）会一直等待
            argumentos = ["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", *argumentos]
        if self.simular:
            self.diz("  [模拟] " + " ".join(shlex.quote(a) for a in argumentos))
            return 0
        estado.registrar("+ " + " ".join(shlex.quote(a) for a in argumentos))
        try:
            proc = subprocess.run(
                argumentos, input=entrada, capture_output=True, text=True,
                # 无输入时，不能让任何程序一直等待键盘
                stdin=subprocess.DEVNULL if entrada is None else None,
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive", "TERM": "dumb"},
            )
        except OSError as erro:
            raise ErroDePasso(f"无法执行 {argumentos[0]}：{erro}") from erro
        for linha in (proc.stdout or "").splitlines():
            estado.registrar("  " + linha)
        if proc.returncode != 0:
            for linha in (proc.stderr or "").splitlines()[-8:]:
                self.diz("  " + linha)
        return proc.returncode

    def _caminho(self, bruto: str) -> Path:
        return Path(resolver(bruto, self.ctx)).expanduser()

    # ---- 步骤 ----------------------------------------------------------
    def passo_apt(self, p: dict) -> None:
        pedidos = [x for x in resolver(p.get("pacotes", []), self.ctx) if x]
        faltam, inexistentes = [], []
        estados = sistema.estado_pacotes(pedidos)
        for nome in pedidos:
            info = estados.get(nome, {})
            if info.get("instalado"):
                continue
            (faltam if info.get("disponivel") else inexistentes).append(nome)
        if inexistentes:
            self.diz(f"  仓库中不存在，已忽略：{', '.join(inexistentes)}")
        if not faltam:
            self.diz("  软件包已存在")
            return
        self.diz(f"  正在安装：{', '.join(faltam)}")
        antes = sistema.pacotes_instalados()
        codigo = self._executa(["apt-get", *APT_SEM_PERGUNTAS, "install", "-y",
                                "--no-install-recommends", *faltam], root=True)
        if codigo != 0:
            raise ErroDePasso(f"apt-get 安装 {', '.join(faltam)} 失败")
        # 只记录原本缺少的：机器上已存在的从不进入移除列表。
        # 一并带来的依赖也会记录：Debian 的 autoremove 会保留被其他包仅作为建议的
        # 依赖，它们会残留下来
        vieram = sorted(sistema.pacotes_instalados() - antes - set(faltam)) if antes else []
        self._anotar("pacotes", nomes=faltam, dependencias=vieram)

    def passo_xfconf(self, p: dict) -> None:
        canal = resolver(p["canal"], self.ctx)
        chave = resolver(p["chave"], self.ctx)
        # "tipo" 已是步骤类型；xfconf 值的类型放在 "tipo_valor"，
        # 否则会互相覆盖
        tipo = p.get("tipo_valor", "string")
        valor = resolver(p["valor"], self.ctx)
        if self.anotar:
            diario.antes_do_xfconf(canal, chave, tipo, self.receita)
        valores = valor.split() if tipo == "double-array" else [str(valor)]
        tipos = ["double"] * len(valores) if tipo == "double-array" else [tipo]
        args = ["xfconf-query", "-c", canal, "-p", chave]
        for t in tipos:
            args += ["-t", t]
        for v in valores:
            args += ["-s", v]
        if self._executa([*args, "-n"]) != 0 and self._executa(args) != 0:
            # 属性可能以其他类型存在；重新创建
            self._executa(["xfconf-query", "-c", canal, "-p", chave, "-r"])
            if self._executa([*args, "-n"]) != 0:
                self.diz(f"  无法设置 {canal}{chave}")

    def passo_arquivo(self, p: dict) -> None:
        destino = self._caminho(p["destino"])
        if p.get("modelo"):
            origem = caminhos.ARQUIVOS / resolver(p["modelo"], self.ctx)
            try:
                conteudo = origem.read_text()
            except OSError as erro:
                raise ErroDePasso(f"模板缺失：{origem}") from erro
        else:
            conteudo = p.get("conteudo", "")
        conteudo = resolver(conteudo, self.ctx)
        if self.simular:
            self.diz(f"  [模拟] 将写入 {destino}")
            return
        existia = destino.exists()
        estado.copia_de_seguranca(destino)
        caminhos.escrever(destino, conteudo, int(str(p["modo"]), 8) if p.get("modo") else None)
        self._anotar("alterado" if existia else "criado", caminho=str(destino))
        self.diz(f"  已写入 {destino}")

    def passo_bloco(self, p: dict) -> None:
        """在现有文件中插入或替换一段带标记的片段。"""
        destino = self._caminho(p["destino"])
        marca = resolver(p.get("marca", "d3bian-init"), self.ctx)
        conteudo = resolver(p.get("conteudo", ""), self.ctx)
        abre, fecha = f"/* {marca} */", f"/* fim {marca} */"
        if p.get("comentario") == "#":
            abre, fecha = f"# {marca}", f"# fim {marca}"
        if self.simular:
            self.diz(f"  [模拟] 在 {destino} 中的块 '{marca}'")
            return
        existia = destino.exists()
        estado.copia_de_seguranca(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        texto = destino.read_text() if existia else ""
        # 只用独占行的标记：用户文本在行中间引用标记不会成为块的开头
        texto = re.sub(r"^" + re.escape(abre) + r"$.*?^" + re.escape(fecha) + r"$", "", texto,
                       flags=re.S | re.M)
        texto = texto.rstrip() + f"\n\n{abre}\n{conteudo.strip()}\n{fecha}\n"
        caminhos.escrever(destino, texto)
        # 撤销时只移除该块；用户此后在文件中写的内容保留
        self._anotar("bloco", caminho=str(destino), marca=marca,
                     comentario=p.get("comentario", ""), arquivo_novo=not existia)
        self.diz(f"  块 '{marca}' 已写入 {destino}")

    def passo_git(self, p: dict) -> None:
        """将仓库克隆或更新到经过校验的精确提交（40 位十六进制）。

        只使用固定提交：分支（main、master、HEAD）会在项目下方发生变化。git
        运行时禁用克隆的钩子（它们位于用户目录），结果必须恰好是请求的提交且
        工作树干净；否则步骤失败，而不是沿用原有内容。"""
        destino = self._caminho(p["destino"])
        url = resolver(p["url"], self.ctx)
        ref = resolver(p.get("ref", ""), self.ctx)
        if not re.fullmatch(r"[0-9a-f]{40}", ref):
            raise ErroDePasso(f"仓库没有固定提交（ref = {ref or '空'}）：{url}")
        if self.simular:
            self.diz(f"  [模拟] 将获取 {url} 的提交 {ref[:12]} 到 {destino}")
            return
        git = ["git", "-c", "core.hooksPath=/dev/null", "-C", str(destino)]
        if (destino / ".git").is_dir():
            self.diz(f"  正在更新 {destino.name}")
            self._executa([*git, "remote", "set-url", "origin", url])
        else:
            self.diz(f"  正在克隆 {destino.name}")
            nova = not destino.exists()
            destino.mkdir(parents=True, exist_ok=True)
            if (self._executa([*git, "init", "-q"]) != 0
                    or self._executa([*git, "remote", "add", "origin", url]) != 0):
                if nova:
                    shutil.rmtree(destino, ignore_errors=True)
                raise ErroDePasso(f"无法克隆 {url}")
            self._anotar("criado", caminho=str(destino))
        if self._executa([*git, "fetch", "-q", "--depth", "1", "origin", ref]) != 0:
            raise ErroDePasso(f"无法获取 {url} 的提交 {ref[:12]}")
        if self._executa([*git, "checkout", "-q", "-f", "--detach", "FETCH_HEAD"]) != 0:
            raise ErroDePasso(f"无法使用 {url} 的提交 {ref[:12]}")
        self._executa([*git, "clean", "-q", "-ffdx"])
        atual = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        sujo = subprocess.run([*git, "status", "--porcelain", "--ignored"], capture_output=True,
                              text=True).stdout.strip()
        if atual != ref or sujo:
            raise ErroDePasso(f"{destino.name} 未停留在提交 {ref[:12]} 且工作树不干净")

    def passo_comando(self, p: dict) -> None:
        argumentos = [str(x) for x in resolver(p["argumentos"], self.ctx)]
        codigo = self._executa(argumentos, root=bool(p.get("root")))
        if codigo != 0 and not p.get("tolera_falha"):
            raise ErroDePasso(f"命令失败（{codigo}）：{' '.join(argumentos)}")

    def passo_script(self, p: dict) -> None:
        """shell 片段。用于用数据描述比直接写更费劲的地方。"""
        corpo = resolver(p["corpo"], self.ctx)
        if self.simular:
            self.diz("  [模拟] 将运行一段 shell 片段")
            return
        # 没有 TERM 时，操作终端的安装器（setterm、tput）会出错退出；
        # 从菜单打开面板、不在终端中时就会这样
        ambiente = {**os.environ, "DEBIAN_FRONTEND": "noninteractive",
                    "TERM": os.environ.get("TERM") or "dumb"}
        for chave, valor in self.ctx.items():
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", chave):
                ambiente[f"D3_{chave.upper()}"] = str(valor)
        # 写入更改日志的 d3_antes、d3_xfconf…… 函数（见 diario.py）
        ambiente.update(diario.ambiente_shell(self.receita, self.anotar))
        # 只有自身调用 sudo 的片段才使用已确认的密码（它仅对本终端有效）；
        # 其他片段在新会话中于其外运行，因此自行尝试 "sudo" 的第三方安装器会失败
        # （日志的 d3_raiz_* 函数也会调用 sudo）。所以第三方代码（install.sh）
        # 绝不与 sudo 放在同一片段中
        usa_sudo = re.search(r"\bsudo\b|\bd3_raiz_", corpo) is not None
        if not usa_sudo:
            ambiente["SUDO_ASKPASS"] = "/bin/false"
        estado.registrar("+ shell:\n" + corpo)
        proc = subprocess.run(["bash", "-euo", "pipefail", "-c", diario.FUNCOES_SHELL + corpo],
                              capture_output=True, text=True, env=ambiente,
                              stdin=subprocess.DEVNULL, start_new_session=not usa_sudo)
        for linha in (proc.stdout or "").splitlines():
            self.diz("  " + linha)
        if proc.returncode != 0:
            for linha in (proc.stderr or "").splitlines()[-10:]:
                self.diz("  " + linha)
            if not p.get("tolera_falha"):
                raise ErroDePasso(f"shell 片段失败（{proc.returncode}）")

    def passo_copiar(self, p: dict) -> None:
        origem = self._caminho(p["origem"])
        destino = self._caminho(p["destino"])
        if not origem.exists():
            # 模拟时 git 步骤不会克隆，因此源可能只是尚不存在
            if self.simular:
                self.diz(f"  [模拟] 将把 {origem} 复制到 {destino}（源尚不存在）")
                return
            if p.get("tolera_falha"):
                self.diz(f"  源缺失，已忽略：{origem}")
                return
            raise ErroDePasso(f"源不存在：{origem}")
        if self.simular:
            self.diz(f"  [模拟] 将把 {origem} 复制到 {destino}")
            return
        # 复制会先删除目标；没有这次备份，原本在那里的内容就会丢失
        existia = destino.exists()
        if existia:
            estado.copia_de_seguranca(destino)
        if p.get("root"):
            # 源属于用户：root 先复制到自己的新目录（不跟随链接、不继承所有者），
            # 只从那里安装
            if self._executa(["sh", "-c", COPIA_ROOT, "sh", str(origem), str(destino),
                              diario.LINKS_PY], root=True) != 0:
                raise ErroDePasso(f"无法复制到 {destino}")
        else:
            destino.parent.mkdir(parents=True, exist_ok=True)
            if destino.exists() and destino.is_dir():
                shutil.rmtree(destino, ignore_errors=True)
            if origem.is_dir():
                shutil.copytree(origem, destino, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(origem, destino)
        self._anotar("alterado" if existia else "criado", caminho=str(destino))
        self.diz(f"  已复制到 {destino}")

    def passo_autostart(self, p: dict) -> None:
        ident = resolver(p["id"], self.ctx)
        arquivo = Path.home() / ".config/autostart" / f"{ident}.desktop"
        if p.get("remover"):
            if not self.simular and arquivo.exists():
                estado.copia_de_seguranca(arquivo)
                arquivo.unlink()
                self._anotar("alterado", caminho=str(arquivo))
            self.diz(f"  已移除自启动：{ident}")
            return
        conteudo = (
            "[Desktop Entry]\nType=Application\n"
            f"Name={resolver(p.get('nome', ident), self.ctx)}\n"
            f"Exec={resolver(p['comando'], self.ctx)}\n"
            "Terminal=false\nX-GNOME-Autostart-enabled=true\n"
            f"X-GNOME-Autostart-Delay={p.get('atraso', 3)}\n"
        )
        if self.simular:
            self.diz(f"  [模拟] 自启动：{ident}")
            return
        existia = arquivo.exists()
        estado.copia_de_seguranca(arquivo)
        caminhos.escrever(arquivo, conteudo)
        self._anotar("alterado" if existia else "criado", caminho=str(arquivo))
        self.diz(f"  自启动：{ident}")

    def passo_processo(self, p: dict) -> None:
        """停止、启动或重启一个图形会话中的程序。"""
        nome = resolver(p["nome"], self.ctx)
        acao = p.get("acao", "reiniciar")
        if self.simular:
            self.diz(f"  [模拟] {acao} {nome}")
            return
        if self.anotar:
            diario.antes_do_processo(nome, self.receita)
        if acao in ("parar", "reiniciar"):
            subprocess.run(["pkill", "-x", nome], capture_output=True)
            # 等待旧的退出：在此之前启动的 plank（以及其他单实例程序）
            # 拿不到 D-Bus 名称而退出，旧的随后也结束，最终一个都不剩
            for _ in range(50):
                if subprocess.run(["pgrep", "-x", "-u", str(os.getuid()), nome],
                                  capture_output=True).returncode != 0:
                    break
                time.sleep(0.1)
        if acao in ("iniciar", "reiniciar"):
            argumentos = [str(x) for x in resolver(p.get("argumentos", [nome]), self.ctx)]
            try:
                subprocess.Popen(["setsid", "--fork", *argumentos],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
            except OSError as erro:
                self.diz(f"  无法启动 {nome}：{erro}")
                return
        self.diz(f"  {acao}：{nome}")

    def passo_backup(self, p: dict) -> None:
        for bruto in resolver(p.get("caminhos", []), self.ctx):
            if self.simular:
                self.diz(f"  [模拟] 将保存 {bruto}")
                continue
            if estado.copia_de_seguranca(Path(bruto).expanduser()):
                self.diz(f"  已保存：{bruto}")

    # ---- 分发 --------------------------------------------------------
    TIPOS = {
        "apt": passo_apt, "xfconf": passo_xfconf, "arquivo": passo_arquivo,
        "bloco": passo_bloco, "git": passo_git, "comando": passo_comando,
        "script": passo_script, "copiar": passo_copiar,
        "autostart": passo_autostart, "processo": passo_processo,
        "backup": passo_backup,
    }

    def rodar(self, passos: Iterable[dict]) -> None:
        for passo in passos:
            tipo = passo.get("tipo")
            funcao = self.TIPOS.get(tipo)
            if funcao is None:
                raise ErroDePasso(f"未知的步骤类型：{tipo}")
            condicao = passo.get("se")
            if condicao and not condicao_atende(str(condicao), self.ctx):
                continue
            if passo.get("dizer"):
                self.diz(resolver(passo["dizer"], self.ctx))
            funcao(self, passo)
