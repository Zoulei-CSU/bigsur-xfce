"""本地网页面板。

只监听 127.0.0.1。它会执行机器上的操作，因此不应通过网络访问。
想从其他电脑使用的可以建立 SSH 隧道。
"""

from __future__ import annotations

import base64
import hmac
import html
import json
import os
import secrets
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import (caminhos, capturas, config, estado, familia, papeis, programas,
               receitas, sistema)
from .tarefa import Tarefa

PORTA_PADRAO = 8730

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".woff2": "font/woff2",
}

NOME = "d3bian-init-bigsur-xfce"

tarefa = Tarefa()
parar = threading.Event()

# 访问：只有通过终端链接打开的页面能与 API 通信。链接携带一次性代码（ENTRADA），
# 它会变成一个秘密 cookie（CHAVE）；没有它，浏览器中任意打开的网站（或机器上的
# 其他用户）都无法让面板安装、撤销或删除任何内容。
CHAVE = secrets.token_urlsafe(32)
_entrada = {"codigo": secrets.token_urlsafe(32)}
_trava_entrada = threading.Lock()


def link_de_entrada(porta: int) -> str:
    return f"http://127.0.0.1:{porta}/entrar?k={_entrada['codigo']}"


def _arquivo_de_entrada(porta: int) -> Path:
    """链接写入仅用户可读的文件，而不是命令行：
    进程列表（/proc/*/cmdline）对机器上的其他账户可见。"""
    base = os.environ.get("XDG_RUNTIME_DIR") or str(caminhos.ESTADO_DIR)
    alvo = Path(base) / f"{NOME}-entrar.html"
    link = html.escape(link_de_entrada(porta))
    caminhos.escrever(alvo, f"<!doctype html><meta charset=utf-8>"
                            f"<meta http-equiv=refresh content='0;url={link}'>"
                            f"<a href='{link}'>打开面板</a>\n", 0o600)
    return alvo


def _uid_da_conexao(porta_cliente: int, porta_servidor: int) -> int | None:
    """通过内核表获取连接的所有者；无法得知时为 None。"""
    try:
        linhas = Path("/proc/net/tcp").read_text().splitlines()[1:]
    except OSError:
        return None
    for linha in linhas:
        campos = linha.split()
        try:
            local, remoto, uid = campos[1], campos[2], int(campos[7])
        except (IndexError, ValueError):
            continue
        if (int(local.split(":")[1], 16) == porta_cliente
                and int(remoto.split(":")[1], 16) == porta_servidor):
            return uid
    return -1  # 未出现的连接：拒绝


def _no_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


NO_WSL = _no_wsl()


def _nome_cookie(porta: int) -> str:
    # cookie 不区分端口：每个面板使用自己的名称
    return f"painel_{porta}"


ACESSO_HTML = ("<!doctype html><meta charset=utf-8><title>" + html.escape(NOME) + "</title>"
               "<body style='font-family:sans-serif;max-width:36em;margin:4em auto;line-height:1.5'>"
               "<h1>通过终端中的链接打开</h1><p>出于安全考虑，本面板只接受通过其运行终端中"
               "显示的链接打开的窗口（链接仅可使用一次；"
               "使用后，终端会显示新的链接）。</p>").encode()


class Painel(BaseHTTPRequestHandler):
    server_version = NOME

    def log_message(self, *_a) -> None:
        pass

    # ---- 访问 ----------------------------------------------------------
    def _porta(self) -> int:
        return self.server.server_address[1]

    def _host_ok(self) -> bool:
        # 防止 DNS 重绑定：把自己的域名指向 127.0.0.1 的网站
        # 会带着自己的 Host 来到这里
        porta = self._porta()
        return self.headers.get("Host", "") in (f"127.0.0.1:{porta}", f"localhost:{porta}")

    def _sessao_ok(self) -> bool:
        # 手动读取头：127.0.0.1 上其他程序的畸形 cookie
        # （cookie 不区分端口）不能卡住面板
        nome = _nome_cookie(self._porta()) + "="
        for parte in self.headers.get("Cookie", "").split(";"):
            parte = parte.strip()
            if parte.startswith(nome) and hmac.compare_digest(parte[len(nome):], CHAVE):
                return True
        return False

    def _mesmo_usuario(self) -> bool:
        """只有打开面板的账户能与它通信：机器上的其他账户也能访问 127.0.0.1，
        因此通过所有者检查连接。"""
        uid = _uid_da_conexao(self.client_address[1], self._porta())
        if uid in (os.getuid(), None):
            return True
        # 在 WSL 中浏览器运行于 Windows，连接经 WSL 转发而来：
        # 来自 root 或 Linux 侧无端点。此时由一次性链接和 cookie 把关；
        # 其他 Linux 账户仍被拒绝
        return NO_WSL and uid in (0, -1)

    def _post_ok(self) -> bool:
        porta = self._porta()
        origem = self.headers.get("Origin")
        if origem is not None and origem not in (f"http://127.0.0.1:{porta}", f"http://localhost:{porta}"):
            return False
        # JSON 强制浏览器先询问（预检），我们不响应预检
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return False
        return self._sessao_ok()

    def _negado(self) -> None:
        self.json({"motivo": "acesso", "detalhe": "请通过终端中显示的链接打开面板"}, 403)

    def _entrar(self) -> None:
        recebido = self.path.split("k=", 1)[1].split("&")[0] if "k=" in self.path else ""
        porta = self._porta()
        with _trava_entrada:
            valido = bool(recebido) and hmac.compare_digest(recebido, _entrada["codigo"])
            if valido:
                # 一次性使用：链接可能留在历史记录或进程列表中；
                # 终端会为另一个窗口显示新的链接
                _entrada["codigo"] = secrets.token_urlsafe(32)
                print(f"  一个窗口进入了面板（{time.strftime('%H:%M:%S')}）")
                print(f"  要在另一个窗口打开：{link_de_entrada(porta)}")
        if not valido:
            self._envia(403, ACESSO_HTML, "text/html; charset=utf-8")
            return
        # 窗口通过 xdg-open 打开的本地文件来到这里，浏览器把该导航视为来自其他
        # 网站：Strict cookie 不会随重定向到 "/" 发送，页面会再次索要链接。
        # 从这里前往 "/" 已属于面板本身，cookie 会一并发送
        corpo = ("<!doctype html><meta charset=utf-8>"
                 "<meta http-equiv=refresh content='0;url=/'>"
                 "<script>location.replace('/')</script>"
                 "<a href='/'>打开面板</a>\n").encode()
        self.send_response(200)
        self.send_header("Set-Cookie", f"{_nome_cookie(porta)}={CHAVE}; HttpOnly; SameSite=Strict; Path=/")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    # ---- 响应 -------------------------------------------------------
    def _envia(self, codigo: int, corpo: bytes, tipo: str) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(corpo)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, dados: dict, codigo: int = 200) -> None:
        self._envia(codigo, json.dumps(dados, ensure_ascii=False).encode(),
                    "application/json; charset=utf-8")

    def corpo(self, limite: int = 64_000) -> dict:
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if tamanho <= 0 or tamanho > limite:
            return {}
        try:
            dados = json.loads(self.rfile.read(tamanho))
        except (json.JSONDecodeError, OSError):
            return {}
        return dados if isinstance(dados, dict) else {}

    def arquivo(self, alvo: Path) -> None:
        if not alvo.is_file():
            self._envia(404, "未找到".encode(), "text/plain; charset=utf-8")
            return
        self._envia(200, alvo.read_bytes(),
                    TIPOS.get(alvo.suffix.lower(), "application/octet-stream"))

    # ---- GET -------------------------------------------------------------
    def do_GET(self) -> None:
        if not self._mesmo_usuario():
            self._envia(403, "其他账户".encode(), "text/plain; charset=utf-8")
            return
        if not self._host_ok():
            self._envia(403, "不允许的主机".encode(), "text/plain; charset=utf-8")
            return
        rota = self.path.split("?")[0]
        if rota == "/entrar":
            self._entrar()
            return
        if rota == "/":
            rota = "/index.html"
        if rota.startswith("/api/") and not self._sessao_ok():
            self._negado()
            return
        # 预览和壁纸是本机的照片（缩略图还会运行 ImageMagick）：仅限有会话时。
        # css、js 和包内标志保持公开
        if rota.startswith(("/capturas/", "/papeis/")) and not self._sessao_ok():
            self._envia(403, "请通过终端中的链接打开面板".encode(), "text/plain; charset=utf-8")
            return
        if rota.endswith(".html") and not self._sessao_ok():
            # 没有会话的页面毫无用处：说明该怎么做
            self._envia(403, ACESSO_HTML, "text/html; charset=utf-8")
            return

        if rota == "/api/estado":
            lista = receitas.carregar()
            self.json({
                "config": config.ler(),
                "opcoes": [o.como_dict() for o in config.OPCOES],
                "receitas": [r.como_dict() for r in lista],
                "instalado": receitas.instalado(lista),
                "outro_tema": familia.para_pagina(),
                "previa": capturas.nome_do_momento(),
                # 本机拍摄的照片；其余是包内示例
                "proprias": sorted(p.stem for p in caminhos.CAPTURAS.glob("*.jpg")),
            })
            return

        if rota == "/api/verificacoes":
            lista = sistema.verificacoes()
            self.json({"verificacoes": lista, "impedimentos": sistema.impedimentos(lista)})
            return

        if rota == "/api/desfazer/previa":
            from . import desfazer
            self.json(desfazer.previa_remocao())
            return

        if rota == "/api/progresso":
            try:
                desde = int(self.path.split("desde=")[1].split("&")[0])
            except (IndexError, ValueError):
                desde = 0
            self.json(tarefa.instantaneo(desde))
            return

        if rota == "/api/programas":
            self.json(programas.com_estado())
            return

        if rota == "/api/papeis":
            # 按名称：下载前图库显示包内缩略图
            atual = papeis.nome_escolhido(config.ler())
            # 页面示意图需要知道“跟随主题”会选择什么
            do_tema = {t: papeis.nome_escolhido({"tema": t, "papel_de_parede": "do-tema"}) or ""
                       for t in ("escuro", "claro")}
            self.json({"papeis": papeis.disponiveis(), "doTema": do_tema,
                       "baixados": papeis.baixados(), "emUso": atual or ""})
            return


        # 登录自有图片的缩略图，它位于 web 目录之外
        if rota == "/api/login-propria.jpg":
            origem = papeis.LOGIN_PROPRIA
            alvo = papeis._miniatura(origem, "login-propria", 320) if origem.is_file() else None
            if alvo is None:
                self._envia(404, "没有图片".encode(), "text/plain")
                return
            self._envia(200, alvo.read_bytes(), "image/jpeg")
            return

        if rota.startswith("/papeis/"):
            alvo = papeis.miniatura(Path(rota).stem)
            if alvo is None:
                self._envia(404, "未找到".encode(), "text/plain")
                return
            self.arquivo(alvo)
            return

        # 预览：用户的截图优先于包内的
        if rota.startswith("/capturas/"):
            nome = Path(rota).stem
            if "/" in nome or ".." in nome:
                self._envia(404, "未找到".encode(), "text/plain")
                return
            self.arquivo(caminhos.captura(nome))
            return

        # 标志与模板放在一起，不在 web 目录中
        if rota.startswith("/logos/"):
            nome = Path(rota).name
            if "/" in nome or ".." in nome or not nome.endswith(".svg"):
                self._envia(404, "未找到".encode(), "text/plain")
                return
            self.arquivo(caminhos.ARQUIVOS / "logos" / nome)
            return

        alvo = (caminhos.WEB / rota.lstrip("/")).resolve()
        # "/index.html/" 会解析到页面：规则按文件而非文本判断
        if alvo.suffix == ".html" and not self._sessao_ok():
            self._envia(403, ACESSO_HTML, "text/html; charset=utf-8")
            return
        if not alvo.is_relative_to(caminhos.WEB.resolve()):
            self._envia(404, "未找到".encode(), "text/plain; charset=utf-8")
            return
        self.arquivo(alvo)

    # ---- POST ------------------------------------------------------------
    def do_POST(self) -> None:
        # 所有 POST 路由都经过这里：操作仅在会话中、以 JSON 且来自页面本身
        if not (self._mesmo_usuario() and self._host_ok() and self._post_ok()):
            self._negado()
            return
        rota = self.path.split("?")[0]
        # 登录图片完整放在 JSON 中（页面已缩小）
        corpo = self.corpo(8_000_000 if rota == "/api/login-imagem" else 64_000)

        if rota == "/api/sair":
            # 在 apt 中途退出会让 dpkg 半途而废
            if tarefa.ocupada():
                self.json({"tchau": False, "motivo": "ocupado", "detalhe": tarefa.rotulo}, 409)
                return
            self.json({"tchau": True})
            threading.Timer(0.4, parar.set).start()
            return

        if tarefa.ocupada() and rota != "/api/progresso":
            self.json({"iniciado": False, "motivo": "ocupado",
                       "detalhe": tarefa.rotulo}, 409)
            return

        if rota == "/api/aplicar":
            self._aplicar(corpo)
            return
        if rota == "/api/login-imagem":
            self._login_imagem(corpo)
            return
        if rota == "/api/instalar":
            self._instalar_tudo(corpo)
            return
        if rota == "/api/trocar":
            self._trocar(corpo)
            return
        if rota == "/api/desfazer":
            from . import desfazer
            apagar = bool(corpo.get("apagar"))
            iniciado = tarefa.funcao("正在撤销" + ("并删除" if apagar else ""),
                                     lambda diz: desfazer.executar(diz, apagar))
            self.json({"iniciado": iniciado, "motivo": "" if iniciado else "ocupado",
                       "etapas": [{"id": i, "nome": n} for i, n in desfazer.etapas(apagar)]},
                      200 if iniciado else 409)
            return
        if rota == "/api/programas/instalar":
            self._programas(corpo, remover=False)
            return
        if rota == "/api/programas/remover":
            self._programas(corpo, remover=True)
            return
        if rota == "/api/capturar":
            self._capturar(corpo)
            return
        if rota == "/api/reiniciar-login":
            self._reiniciar_login(corpo)
            return
        if rota == "/api/previa-login":
            # 预览使用页面上选中的选项，即使在应用之前
            pedido = config.filtrar(corpo)
            iniciado = tarefa.funcao("正在生成登录界面预览",
                                     lambda diz: capturas.previa_login(diz, pedido))
            self.json({"iniciado": iniciado}, 200 if iniciado else 409)
            return

        self._envia(404, "未找到".encode(), "text/plain; charset=utf-8")

    # ---- 操作 -----------------------------------------------------------
    def _recusa_da_familia(self) -> bool:
        """已应用同族的另一个 Xfce 主题：回应原因，页面会像其他错误一样显示
        （见 familia.py）。"""
        recusa = familia.recusa()
        if recusa:
            self.json({"iniciado": False, "motivo": "outro tema", "erro": recusa}, 409)
        return bool(recusa)

    def _trocar(self, corpo: dict) -> None:
        """恢复同族的另一个 Xfce 主题（它的还原，软件包保留），
        并用页面选项安装本主题。"""
        outro = familia.para_pagina()
        if not outro:
            self.json({"iniciado": False, "motivo": "nada a trocar",
                       "erro": "本账户中未安装同族的其他 Xfce 主题"}, 409)
            return
        if not outro["achado"]:
            self.json({"iniciado": False, "motivo": "outro tema",
                       "erro": f"找不到项目 {outro['modulo']}；请在终端中恢复主题 {outro['nome']}："
                               f"{outro['comando']}"}, 409)
            return
        impedem = sistema.impedimentos(sistema.verificacoes(usar_cache=False))
        if impedem:
            self.json({"iniciado": False, "motivo": "verificacoes",
                       "impedimentos": impedem}, 412)
            return
        pedido = config.filtrar(corpo)
        if not caminhos.livre():
            self.json({"iniciado": False, "motivo": "ocupado",
                       "detalhe": "命令行正在运行"}, 409)
            return

        def trocar_e_instalar(diz) -> int:
            if familia.trocar(diz) != 0:
                return 1
            return receitas.executar(saida=diz, cfg={**config.ler(), **pedido})

        # 标签以安装的标签开头：重新加载的页面同样能跟上
        iniciado = tarefa.funcao(f"完整安装，正在切换主题 {outro['nome']}",
                                 trocar_e_instalar)
        if not iniciado:
            self.json({"iniciado": False, "motivo": "ocupado"}, 409)
            return
        if pedido:
            config.gravar(pedido)
        self.json({"iniciado": True, "outro": outro["nome"]})

    def _aplicar(self, corpo: dict) -> None:
        if self._recusa_da_familia():
            return
        pedido = config.filtrar(corpo)
        if not pedido:
            self.json({"iniciado": False, "motivo": "nada valido"}, 400)
            return
        atual = config.ler()
        mudou = [c for c, v in pedido.items() if atual.get(c) != v]
        # 没有差异时重新应用整套：按钮总能做点什么
        chaves = mudou or list(pedido)
        # 应用后发生变化的配方即使选项未变也会加入，
        # 否则新的登录界面永远不会离开代码
        pendentes = set(receitas.afetadas_por(list(pedido))) & receitas.desatualizadas()
        alvos = sorted(set(receitas.afetadas_por(chaves)) | pendentes,
                       key=lambda x: (len(x), x))
        if not alvos:
            self.json({"iniciado": False, "motivo": "nada a fazer"})
            return

        if not caminhos.livre():
            self.json({"iniciado": False, "motivo": "ocupado",
                       "detalhe": "命令行正在运行"}, 409)
            return
        novidade = bool(mudou or pendentes)
        rotulo = ("正在应用" if novidade else "正在重新应用") + "： " + ", ".join(alvos)
        iniciado = tarefa.funcao(
            rotulo,
            lambda diz: receitas.executar(apenas=alvos, refazer=True, saida=diz,
                                          cfg={**atual, **pedido}),
        )
        if not iniciado:
            self.json({"iniciado": False, "motivo": "ocupado"}, 409)
            return
        # 只在执行开始后保存，否则配置会声称已应用某些实际未应用的内容
        config.gravar(pedido)
        self.json({"iniciado": True, "receitas": alvos, "mudou": mudou,
                   "reaplicou": not novidade})

    def _login_imagem(self, corpo: dict) -> None:
        """保存页面上为登录背景选择的图片。页面发送已缩小的 JPEG；
        这里校验后由 ImageMagick 仅以 JPEG 形式重写到 papeis.fundo_login
        查找的位置。"""
        try:
            dados = base64.b64decode(str(corpo.get("imagem", "")), validate=True)
        except (ValueError, TypeError):
            dados = b""
        if not dados.startswith(b"\xff\xd8\xff") or len(dados) > 6_000_000:
            self.json({"ok": False, "erro": "图片未以 JPEG 形式送达（或超过 6 MB）"}, 400)
            return
        destino = papeis.LOGIN_PROPRIA
        destino.parent.mkdir(parents=True, exist_ok=True)
        temp = destino.with_name(".login-propria-envio.jpg")
        try:
            temp.write_bytes(dados)
            subprocess.run(["convert", f"jpeg:{temp}[0]", "-auto-orient", "-resize", "2560x1600>",
                            "-strip", "-quality", "90", f"jpeg:{destino}"],
                           capture_output=True, timeout=60, check=True)
        except (OSError, subprocess.SubprocessError):
            self.json({"ok": False, "erro": "无法读取该图片"}, 400)
            return
        finally:
            temp.unlink(missing_ok=True)
        self.json({"ok": True})

    def _reiniciar_login(self, corpo: dict) -> None:
        """重启 LightDM，这会结束图形会话。绝不在未确认时进行。"""
        if corpo.get("confirmar") is not True:
            self.json({"iniciado": False, "motivo": "sem_confirmacao"}, 400)
            return
        try:
            instalada = "lightdm-gtk-greeter" in Path(
                "/etc/lightdm/lightdm.conf.d/90-d3bian.conf").read_text()
        except OSError:
            instalada = False
        if not instalada:
            # 在应用前重启只会关闭会话并显示旧界面
            self.json({"iniciado": False, "motivo": "login_nao_aplicado"}, 412)
            return
        if not sistema.sudo_liberado():
            self.json({"iniciado": False, "motivo": "sem_permissao"}, 412)
            return
        self.json({"iniciado": True})
        estado.registrar("应页面请求重启 lightdm")
        # 响应先发出，因为会话和浏览器会一起关闭。不用
        # setsid：sudo 按终端保存凭据，systemctl 只将重启排队，即使本进程结束
        # 也会继续
        threading.Timer(1.5, lambda: subprocess.Popen(
            ["sudo", "-n", "systemctl", "restart", "lightdm"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)).start()

    def _instalar_tudo(self, corpo: dict) -> None:
        if self._recusa_da_familia():
            return
        impedem = sistema.impedimentos(sistema.verificacoes(usar_cache=False))
        if impedem:
            self.json({"iniciado": False, "motivo": "verificacoes",
                       "impedimentos": impedem}, 412)
            return
        pedido = config.filtrar(corpo)
        if not caminhos.livre():
            self.json({"iniciado": False, "motivo": "ocupado",
                       "detalhe": "命令行正在运行"}, 409)
            return
        iniciado = tarefa.funcao(
            "完整安装，可能需要 15 到 25 分钟",
            lambda diz: receitas.executar(saida=diz, cfg={**config.ler(), **pedido}),
        )
        if not iniciado:
            self.json({"iniciado": False, "motivo": "ocupado"}, 409)
            return
        if pedido:
            config.gravar(pedido)
        self.json({"iniciado": True})

    def _programas(self, corpo: dict, remover: bool) -> None:
        try:
            escolhidos = programas.conferir(corpo.get("pacotes"))
        except programas.Recusado as erro:
            self.json({"iniciado": False, "erro": str(erro)}, 400)
            return
        externas = [] if remover else programas.fontes_necessarias(escolhidos)
        if externas and not corpo.get("confirmar_externo"):
            # 在用户看到将向系统添加什么之前不安装任何内容；
            # 这个问题与移除确认相互独立
            self.json({"iniciado": False, "motivo": "fonte_externa",
                       "externas": externas})
            return

        if not caminhos.livre():
            self.json({"iniciado": False, "motivo": "ocupado",
                       "detalhe": "命令行正在运行"}, 409)
            return
        if remover:
            extras = programas.arrastaria(escolhidos)
            if extras and not corpo.get("confirmar"):
                self.json({"iniciado": False, "motivo": "arrasta_outros",
                           "extras": extras})
                return
            rotulo = "正在移除： " + ", ".join(escolhidos)
            iniciado = tarefa.funcao(
                rotulo, lambda diz: programas.remover(escolhidos, diz))
        else:
            rotulo = "正在安装： " + ", ".join(escolhidos)
            iniciado = tarefa.funcao(
                rotulo, lambda diz: programas.instalar(escolhidos, diz))
        self.json({"iniciado": iniciado, "pacotes": escolhidos,
                   "externas": [e["pkg"] for e in externas]})

    def _capturar(self, corpo: dict) -> None:
        modo = corpo.get("modo")
        espera = corpo.get("espera")
        espera = espera if isinstance(espera, int) and 0 <= espera <= 30 else 5
        if modo == "atual":
            alvo = lambda diz: capturas.capturar_atual(diz, espera)
        elif modo == "todas":
            alvo = lambda diz: capturas.capturar_todas(diz, espera)
        else:
            self.json({"iniciado": False, "erro": "无效模式"}, 400)
            return
        self.json({"iniciado": tarefa.funcao(f"正在截图预览（{modo}）", alvo)})


def subir(porta: int = PORTA_PADRAO, abrir: bool = True) -> int:
    caminhos.preparar()
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", porta), Painel)
    except OSError as erro:
        print(f"  无法打开端口 {porta}：{erro}")
        return 1
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    endereco = link_de_entrada(porta)
    print(f"\n  {NOME} 已打开：{endereco}")
    print("  （链接仅可使用一次；请用页面上的按钮关闭，或在此按 Ctrl+C）\n")
    if abrir:
        try:
            subprocess.Popen(["xdg-open", _arquivo_de_entrada(porta).as_uri()],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            print("  请在浏览器中打开上面的地址")

    def encerrar(*_a) -> None:
        # 任务进行中，第一次 Ctrl+C 只提示：apt 半途而废会损坏 dpkg；
        # 第二次则强制退出
        if tarefa.ocupada() and not encerrar.avisou:
            encerrar.avisou = True
            print("\n  仍在安装：请等待完成，或再次按 Ctrl+C 强制退出")
            return
        parar.set()
    encerrar.avisou = False
    signal.signal(signal.SIGINT, encerrar)
    signal.signal(signal.SIGTERM, encerrar)
    while not parar.is_set():
        time.sleep(0.3)
    print("  正在关闭面板")
    httpd.shutdown()
    return 0
