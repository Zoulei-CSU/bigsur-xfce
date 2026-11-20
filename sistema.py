"""环境检测和预检查。

所有图形环境专属内容都在这里。目前只实现了 XFCE，但调用方按能力而非桌面名称
询问，因此之后添加其他桌面无需改动配方。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path


def _roda(*argumentos: str, tempo: int = 10) -> subprocess.CompletedProcess:
    # 输出由代码解析（apt/dpkg 会按语言翻译），统一用 C 语言环境
    return subprocess.run(argumentos, capture_output=True, text=True, timeout=tempo,
                          env={**os.environ, "LC_ALL": "C"})


def tem(programa: str) -> bool:
    return shutil.which(programa) is not None


def distribuicao() -> dict[str, str]:
    dados: dict[str, str] = {}
    try:
        for linha in Path("/etc/os-release").read_text().splitlines():
            if "=" in linha:
                chave, _, valor = linha.partition("=")
                dados[chave.strip()] = valor.strip().strip('"')
    except OSError:
        pass
    return dados


def desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").strip()


def e_xfce() -> bool:
    return "XFCE" in desktop().upper() or tem("xfconf-query")


def sessao_grafica() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def sudo_liberado() -> bool:
    """有缓存的凭据，即可以无提示使用 sudo。"""
    try:
        return _roda("sudo", "-n", "true", tempo=6).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pacote_instalado(nome: str) -> bool:
    try:
        saida = _roda("dpkg-query", "-W", "-f=${db:Status-Status}", nome, tempo=8).stdout
        return saida.strip() == "installed"
    except (OSError, subprocess.TimeoutExpired):
        return False


def estado_pacotes(nomes: list[str]) -> dict[str, dict]:
    """对每个软件包：仓库是否提供以及是否已安装。"""
    fora = {n: {"disponivel": False, "instalado": False, "versao": ""} for n in nomes}
    if not nomes:
        return fora
    try:
        saida = _roda("dpkg-query", "-W", "-f=${binary:Package} ${db:Status-Status}\n",
                      *nomes, tempo=20).stdout
        for linha in saida.splitlines():
            partes = linha.split()
            if len(partes) == 2 and partes[1] == "installed":
                nome = partes[0].split(":")[0]
                if nome in fora:
                    fora[nome]["instalado"] = True
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        saida = _roda("apt-cache", "policy", *nomes, tempo=30).stdout
        atual = None
        for linha in saida.splitlines():
            if linha and not linha.startswith(" ") and linha.rstrip().endswith(":"):
                atual = linha.rstrip()[:-1].split(":")[0]
            elif atual in fora and ":" in linha:
                rotulo, _, valor = linha.strip().partition(":")
                # apt 会被翻译；"Candidat" 同时覆盖 Candidate 和 Candidato
                if rotulo.startswith("Candidat"):
                    valor = valor.strip()
                    if valor and valor not in ("(none)", "(nenhum)"):
                        fora[atual]["disponivel"] = True
                        fora[atual]["versao"] = valor
    except (OSError, subprocess.TimeoutExpired):
        pass
    return fora


def espaco_livre_gb(onde: Path | None = None) -> float:
    try:
        st = os.statvfs(str(onde or Path.home()))
        return st.f_bavail * st.f_frsize / 1e9
    except OSError:
        return -1.0


def _repositorios_do_apt() -> list[str]:
    """apt 源的 http(s) 地址，Debian 的排在最前。"""
    pasta = Path("/etc/apt/sources.list.d")
    arquivos = [Path("/etc/apt/sources.list"), *sorted(pasta.glob("*.list")),
                *sorted(pasta.glob("*.sources"))]
    enderecos: list[str] = []
    for arquivo in arquivos:
        try:
            texto = arquivo.read_text()
        except OSError:
            continue
        for linha in texto.splitlines():
            linha = linha.split("#", 1)[0].strip()
            if linha.startswith("URIs:"):
                enderecos += linha[5:].split()
            elif linha.startswith(("deb ", "deb-src ")):
                enderecos += [p for p in linha.split() if "://" in p][:1]
    vistos: dict[str, str] = {}
    for url in enderecos:
        host = url.split("://", 1)[-1].split("/", 1)[0]
        if url.startswith(("http://", "https://")) and host not in vistos:
            vistos[host] = url
    return sorted(vistos.values(), key=lambda u: "debian" not in u)


def _proxy_do_apt() -> dict[str, str]:
    """apt 使用的代理（如果有）；网络可能只能通过它访问。"""
    try:
        saida = _roda("apt-config", "shell", "HTTP", "Acquire::http::Proxy",
                      "HTTPS", "Acquire::https::Proxy", tempo=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    proxies: dict[str, str] = {}
    for linha in saida.splitlines():
        nome, _, valor = linha.partition("=")
        valor = shlex.split(valor)[0] if valor.strip() else ""
        if valor and valor.upper() != "DIRECT":
            proxies[nome.lower()] = valor
    return proxies


def repositorios_alcancaveis() -> tuple[bool, str]:
    """询问 apt 源是否有响应。

    不使用 curl：它不在 Debian 默认安装中，只随配方 10 到来，晚于本检查。
    任何 HTTP 响应，甚至 404，都足以证明服务器可达。
    """
    import urllib.error
    import urllib.request
    urls = _repositorios_do_apt()[:2] or ["http://deb.debian.org/debian/"]
    proxies = {**urllib.request.getproxies(), **_proxy_do_apt()}
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    hosts = []
    for url in urls:
        host = url.split("://", 1)[-1].split("/", 1)[0]
        hosts.append(host)
        try:
            abridor.open(urllib.request.Request(url, method="HEAD"), timeout=6).close()
            return True, host
        except urllib.error.HTTPError:
            return True, host
        except (OSError, ValueError):
            continue
    return False, ", ".join(hosts)


_CACHE: tuple[float, list[dict]] | None = None
VALIDADE = 30.0          # 秒


def verificacoes(usar_cache: bool = True) -> list[dict]:
    """预检查列表，采用网页绘制的格式。

    结果缓存半分钟：顶部状态栏在每个页面都会查询，其中一项还会访问网络。
    """
    global _CACHE
    import time
    if usar_cache and _CACHE and (time.monotonic() - _CACHE[0]) < VALIDADE:
        return _CACHE[1]
    lista = _verificar()
    _CACHE = (time.monotonic(), lista)
    return lista


def _verificar() -> list[dict]:
    saida: list[dict] = []

    def add(nome: str, ok: bool, detalhe: str, critico: bool = True) -> None:
        saida.append({"nome": nome, "ok": bool(ok), "detalhe": detalhe, "critico": critico})

    info = distribuicao()
    nome_distro = info.get("PRETTY_NAME", "") or "未识别"
    familia = (info.get("ID", "") + " " + info.get("ID_LIKE", "")).lower()
    add("系统", "debian" in familia, nome_distro)

    add("图形环境", e_xfce(), desktop() or "未知")
    add("图形会话", sessao_grafica(),
        "活动" if sessao_grafica() else "没有 DISPLAY；请在你的会话中运行")
    add("xfconf-query", tem("xfconf-query"),
        "存在" if tem("xfconf-query") else "缺失，随 xfconf 提供")

    liberado = sudo_liberado()
    add("管理员权限", liberado,
        "已在本会话中授权" if liberado
        else "无凭据；请用 d3bian-init-bigsur-xfce 命令打开面板")

    gb = espaco_livre_gb()
    add("磁盘空间", gb < 0 or gb >= 2.0,
        "未检查" if gb < 0 else f"主目录有 {gb:.1f} GB 可用",
        critico=gb >= 0)

    rede, hosts = repositorios_alcancaveis()
    add("软件源访问", rede,
        f"可达（{hosts}）" if rede else f"来自 {hosts} 无响应")

    return saida


def impedimentos(lista: list[dict] | None = None) -> list[str]:
    """失败的严重检查项名称。"""
    return [c["nome"] for c in (lista or verificacoes()) if c["critico"] and not c["ok"]]


def pacotes_instalados() -> set[str]:
    """当前已安装软件包的名称，不含架构；dpkg 无响应时为空。"""
    try:
        saida = subprocess.run(["dpkg-query", "-W", "-f=${binary:Package} ${db:Status-Status}\n"],
                               capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"}).stdout
    except OSError:
        return set()
    return {linha.split()[0].split(":")[0] for linha in saida.splitlines()
            if linha.endswith(" installed")}
