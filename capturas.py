"""屏幕截图，用作页面上的预览。

包内自带的是通用示例，由 ferramentas/gerar_exemplos.py 在单独的会话中生成；
在用户拍摄自己的屏幕之前使用。
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import caminhos, config, motor

LARGURA = 1280


def nome_do_momento(cfg: dict[str, str] | None = None) -> str:
    """哪张预览对应当前生效的偏好。"""
    cfg = cfg or config.ler()
    tema = "escuro" if cfg.get("tema") == "escuro" else "claro"
    widget = "sem" if cfg.get("widget") == "nao" else "com"
    return f"{tema}-{widget}-widget"


def _redimensionar(origem: Path, destino: Path) -> bool:
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        pronto = subprocess.run(
            ["convert", str(origem), "-resize", f"{LARGURA}x", "-quality", "86",
             str(destino)], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pronto = False
    if not pronto:                      # 没有 ImageMagick，就保存原始 png
        try:
            destino.with_suffix(".png").write_bytes(origem.read_bytes())
            return True
        except OSError:
            return False
    return True


def tirar(nome: str, diz: Callable[[str], None]) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        bruto = Path(tmp.name)
    try:
        ok = subprocess.run(["xfce4-screenshooter", "-f", "-s", str(bruto)],
                            capture_output=True, timeout=60).returncode == 0
        if not ok or bruto.stat().st_size == 0:
            diz("  无法拍摄屏幕")
            return False
        destino = caminhos.CAPTURAS / f"{nome}.jpg"
        if _redimensionar(bruto, destino):
            diz(f"  预览已保存：{nome}")
            return True
        diz("  无法保存预览")
        return False
    except (OSError, subprocess.TimeoutExpired) as erro:
        diz(f"  截图失败：{erro}")
        return False
    finally:
        bruto.unlink(missing_ok=True)


def contar(segundos: int, diz: Callable[[str], None]) -> None:
    if segundos > 0:
        diz(f"  {segundos} 秒后截图，请把屏幕保持成你想展示的样子")
        time.sleep(segundos)


def capturar_atual(diz: Callable[[str], None], espera: int = 5) -> int:
    contar(espera, diz)
    return 0 if tirar(nome_do_momento(), diz) else 1


def capturar_todas(diz: Callable[[str], None], espera: int = 5) -> int:
    """依次遍历四种组合，最后恢复原始状态。"""
    from . import receitas                      # 延迟导入，避免循环

    original = config.ler()
    contar(espera, diz)
    falhas = 0
    for tema in ("escuro", "claro"):
        for widget in ("sim", "nao"):
            diz(f"  准备中：主题 {tema}，组件 {widget}")
            cfg = {**original, "tema": tema, "widget": widget}
            receitas.executar(apenas=["38", "40", "80"], refazer=True,
                              saida=lambda _t: None, cfg=cfg)
            time.sleep(4)
            if not tirar(f"{tema}-{'com' if widget == 'sim' else 'sem'}-widget", diz):
                falhas += 1
    diz("  正在恢复之前的状态")
    receitas.executar(apenas=["38", "40", "80"], refazer=True,
                      saida=lambda _t: None, cfg=original)
    return 1 if falhas else 0


def _tela() -> tuple[int, int]:
    """整个屏幕的宽度和高度。"""
    try:
        linha = subprocess.run(["xrandr", "--current"], capture_output=True,
                               text=True, timeout=10).stdout.splitlines()[0]
        partes = linha.split("current", 1)[1].split(",")[0].split("x")
        largura, altura = int(partes[0]), int(partes[1])
        if largura > 0 and altura > 0:
            return largura, altura
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
        pass
    return 1920, 1200


def _tamanho_da_tela() -> str:
    """显示器的宽高比，按窗口大小缩小。"""
    largura, altura = _tela()
    return f"{LARGURA}x{round(altura * LARGURA / largura)}"


def previa_login(diz: Callable[[str], None], cfg: dict[str, str] | None = None,
                 destino: Path | None = None) -> int:
    """按请求的选项组装登录界面，并在窗口中将其拍摄下来。

    使用 LightDM 的测试模式，它无需 root 即可启动单独的守护进程并即时读取配置。
    `dm-tool add-nested-seat` 不可用：创建 seat 的是已在运行的守护进程，会显示
    旧的 greeter。
    """
    import os
    import shutil
    from . import receitas                      # 延迟导入，避免循环

    lightdm = shutil.which("lightdm") or "/usr/sbin/lightdm"
    faltam = [nome for nome, ok in (
        ("xserver-xephyr", shutil.which("Xephyr")),
        ("lightdm", Path(lightdm).is_file()),
        ("lightdm-gtk-greeter", Path("/usr/sbin/lightdm-gtk-greeter").is_file()),
        ("imagemagick", shutil.which("convert")),
    ) if not ok]
    if faltam:
        diz("  生成预览还需安装：" + ", ".join(faltam))
        return 1

    receita = receitas.por_id().get("97")
    if receita is None:
        diz("  找不到登录界面的配方")
        return 1
    # 临时目录，结束时删除；只留下照片，与其他预览放在一起
    pasta = Path(tempfile.mkdtemp(prefix="d3bian-init-previa-login-"))
    try:
        return _previa_login(diz, {**config.ler(), **(cfg or {})}, receita, pasta, lightdm,
                             destino or caminhos.CAPTURAS / "login.jpg")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def _previa_login(diz: Callable[[str], None], cfg: dict[str, str], receita,
                  pasta: Path, lightdm: str, destino: Path) -> int:
    import os
    import shutil

    # 与安装相同的步骤，组装到预览目录中，不写入系统
    ctx = motor.montar_contexto(cfg)
    ctx.update(login_dir=str(pasta), login_raiz=str(pasta), login_instalar="nao")
    try:
        motor.Motor(ctx, saida=diz).rodar(receita.passos)
    except motor.ErroDePasso as erro:
        diz(f"  无法生成预览：{erro}")
        return 1
    for sub in ("run", "log", "cache", "bin"):
        (pasta / sub).mkdir(parents=True, exist_ok=True)

    # greeter 在系统的 XDG 目录中查找配置和主题
    envelope = pasta / "greeter.sh"
    envelope.write_text(
        "#!/bin/sh\n"
        f"export XDG_CONFIG_DIRS='{pasta}/xdg'\n"
        f"export XDG_DATA_DIRS='{pasta}/share:/usr/local/share:/usr/share'\n"
        'exec "$@"\n')
    envelope.chmod(0o755)
    # 在测试模式下，LightDM 通过 PATH 调用 Xephyr，无法指定尺寸
    xephyr = pasta / "bin" / "Xephyr"
    xephyr.write_text("#!/bin/sh\n"
                      f"exec {shutil.which('Xephyr')} -screen {_tamanho_da_tela()} \"$@\"\n")
    xephyr.chmod(0o755)
    ajustes = pasta / "lightdm.conf"
    ajustes.write_text(
        "[Seat:*]\n"
        "greeter-session=lightdm-gtk-greeter\n"
        f"greeter-wrapper={envelope}\n"
        f"greeter-hide-users={ctx['login_esconder_usuarios']}\n"
        "greeter-show-manual-login=true\n")

    diz("  正在窗口中打开登录界面")
    try:
        daemon = subprocess.Popen(
            [lightdm, "--test-mode", "-c", str(ajustes), f"--run-dir={pasta}/run",
             f"--log-dir={pasta}/log", f"--cache-dir={pasta}/cache"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            env={**os.environ, "PATH": f"{pasta}/bin:{os.environ.get('PATH', '')}"})
    except OSError as erro:
        diz(f"  无法以测试模式启动 lightdm：{erro}")
        return 1

    try:
        tela, autorizacao = "", ""
        for _ in range(30):
            time.sleep(1)
            if daemon.poll() is not None:
                break
            try:
                listagem = subprocess.run(["pgrep", "-a", "Xephyr"], capture_output=True,
                                          text=True, timeout=10).stdout
            except (OSError, subprocess.TimeoutExpired):
                listagem = ""
            # 只要本次预览的 Xephyr，通过授权目录识别
            for linha in listagem.splitlines():
                if str(pasta) in linha:
                    partes = linha.split()
                    tela = next((p for p in partes if p.startswith(":") and p[1:].isdigit()), "")
                    # 测试模式下的 Xephyr 需要 LightDM 写入的 cookie；
                    # 没有它，import 只能靠环境碰巧连接
                    if "-auth" in partes and partes.index("-auth") + 1 < len(partes):
                        autorizacao = partes[partes.index("-auth") + 1]
            if tela and (pasta / "log" / "seat0-greeter.log").exists():
                break
        if not tela:
            diz("  登录界面没有打开；lightdm 日志的最后几行：")
            try:
                for linha in (pasta / "log" / "lightdm.log").read_text().splitlines()[-8:]:
                    diz("    " + linha)
            except OSError:
                pass
            return 1
        time.sleep(5)                    # greeter 加载主题和背景
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            bruto = Path(tmp.name)
        try:
            ambiente = {**os.environ, "DISPLAY": tela}
            if autorizacao:
                ambiente["XAUTHORITY"] = autorizacao
            subprocess.run(["import", "-window", "root", str(bruto)],
                           env=ambiente, capture_output=True, timeout=40)
            if bruto.stat().st_size and _redimensionar(bruto, destino):
                diz("  登录界面预览已保存")
            else:
                diz("  窗口已打开，但无法拍摄")
                return 1
        except (OSError, subprocess.TimeoutExpired):
            diz("  窗口已打开，但无法拍摄")
            return 1
        finally:
            bruto.unlink(missing_ok=True)
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=15)
        except subprocess.TimeoutExpired:
            daemon.kill()
    diz("  这是选中选项后的界面；真正的界面会在应用并重启后改变")
    return 0


# 供服务器组装上下文使用，无需重新导入 motor
montar_contexto = motor.montar_contexto
