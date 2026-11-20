"""本机硬件及其所需的软件包。

全部来自 /sys 和 /proc：无需 root，也无需额外程序，在全新安装的 Debian 上即可
运行。程序页面用它只显示所发现硬件适用的目录项。

固件不逐个文件检查。一个模块会声明其支持的所有芯片的固件（btusb 同时列出
Realtek、MediaTek 和 Intel），这会误报缺失。改为由每个正在使用的驱动指示其所属
系列的固件包。
"""

from __future__ import annotations

from pathlib import Path

SYS = Path("/sys")

# 正在使用的驱动 -> 固件包。末尾带 * 的模式是前缀；不带时名称必须完全相同
# （"xe" 作为前缀会误匹配其他驱动）
FIRMWARE_POR_DRIVER = {
    "firmware-realtek": ("rtw_*", "rtw88*", "rtw89*", "rtl8*", "r8169", "r8152"),
    "firmware-iwlwifi": ("iwlwifi",),
    "firmware-atheros": ("ath9k_htc", "ath10k*", "ath11k*", "ath12k*", "ath6kl*"),
    "firmware-brcm80211": ("brcmfmac*", "brcmsmac"),
    "firmware-mediatek": ("mt7*",),
    "firmware-amd-graphics": ("amdgpu", "radeon"),
    "firmware-intel-graphics": ("i915", "xe"),
    "firmware-nvidia-graphics": ("nouveau",),
    "firmware-sof-signed": ("sof-audio*", "snd_sof*"),
    "firmware-libertas": ("libertas*", "mwifiex*"),
}

# btusb 服务于所有厂商；固件由 USB id 决定
BLUETOOTH_USB = {
    "0bda": ("Realtek", "firmware-realtek"),
    "8087": ("Intel", "firmware-iwlwifi"),
    "0e8d": ("MediaTek", "firmware-mediatek"),
    "0cf3": ("Qualcomm Atheros", "firmware-atheros"),
    "0a5c": ("Broadcom", ""),
}

VIDEO = {"0x8086": ("Intel", "video-intel"), "0x1002": ("AMD", "video-amd"),
         "0x10de": ("NVIDIA", "video-nvidia")}

# (USB 厂商、产品起始、名称)；产品为空对所有有效
LEITOR_DIGITAL = (
    ("27c6", "", "Goodix"), ("138a", "", "Validity"), ("147e", "", "Upek"),
    ("1c7a", "", "EgisTec"), ("10a5", "", "FPC"), ("2808", "", "Focal"),
    ("06cb", "00", "Synaptics"), ("04f3", "0c", "Elan"),
)

# 属于笔记本、平板或翻转本的 DMI 机箱类型
PORTATEIS = {"8", "9", "10", "11", "14", "30", "31", "32"}


def _ler(caminho: Path) -> str:
    try:
        return caminho.read_text(errors="replace").strip()
    except OSError:
        return ""


def _driver(dispositivo: Path) -> str:
    ligacao = dispositivo / "driver"
    try:
        return ligacao.resolve().name if ligacao.exists() else ""
    except OSError:
        return ""


def _bate(driver: str, padrao: str) -> bool:
    return driver.startswith(padrao[:-1]) if padrao.endswith("*") else driver == padrao


def _itens(pasta: Path, filtro: str = "*") -> list[Path]:
    try:
        return sorted(pasta.glob(filtro))
    except OSError:
        return []


def _fabricante_usb(dispositivo: Path) -> str:
    """设备的 idVendor；是接口（1-7:1.0）时取上级的。"""
    real = dispositivo.resolve()
    return (_ler(real / "idVendor") or _ler(real.parent / "idVendor")).lower()


def _processos() -> set[str]:
    nomes = set()
    for comm in _itens(Path("/proc"), "[0-9]*/comm"):
        nomes.add(_ler(comm))
    return nomes


def _non_free_firmware() -> bool:
    """apt 源中是否有 Debian 放置固件的组件。"""
    pasta = Path("/etc/apt/sources.list.d")
    arquivos = [Path("/etc/apt/sources.list"), *_itens(pasta, "*.list"),
                *_itens(pasta, "*.sources")]
    for arquivo in arquivos:
        for linha in _ler(arquivo).splitlines():
            if "non-free-firmware" in linha.split("#", 1)[0]:
                return True
    return False


def detectar() -> dict:
    """机器有哪些硬件、目录规则使用的标记，以及所需的固件。"""
    tags: set[str] = set()
    dispositivos: list[dict] = []
    firmware: dict[str, list[str]] = {}

    def achou(tag: str, nome: str, detalhe: str = "") -> None:
        tags.add(tag)
        dispositivos.append({"tipo": tag, "nome": nome, "detalhe": detalhe})

    def pede(pacote: str, driver: str) -> None:
        usos = firmware.setdefault(pacote, [])
        if driver not in usos:
            usos.append(driver)

    # 处理器；虚拟机中微码不适用，因此不显示
    cpu: dict[str, str] = {}
    for linha in _ler(Path("/proc/cpuinfo")).splitlines():
        chave, _, valor = linha.partition(":")
        cpu.setdefault(chave.strip(), valor.strip())
    virtual = "hypervisor" in cpu.get("flags", "").split()
    modelo = " ".join(cpu.get("model name", "").split())
    if not virtual:
        if cpu.get("vendor_id") == "GenuineIntel":
            achou("cpu-intel", "处理器", modelo)
        elif cpu.get("vendor_id") == "AuthenticAMD":
            achou("cpu-amd", "处理器", modelo)
    if "cpu-intel" in tags and _ler(SYS / "class/dmi/id/chassis_type") in PORTATEIS:
        tags.add("termico-intel")

    # 视频：0x03 类的任何显卡，无论是否加载了驱动
    for placa in _itens(SYS / "bus/pci/devices"):
        if not _ler(placa / "class").startswith("0x03"):
            continue
        marca, tag = VIDEO.get(_ler(placa / "vendor").lower(), ("", ""))
        if tag:
            achou(tag, f"显卡 {marca}", _driver(placa) or "未加载驱动")

    for rede in _itens(SYS / "class/net"):
        if (rede / "wireless").is_dir() or (rede / "phy80211").exists():
            achou("wifi", "Wi-Fi", f"{rede.name}, {_driver(rede / 'device') or '无驱动'}")

    for hci in _itens(SYS / "class/bluetooth"):
        if ":" in hci.name:
            continue
        marca = BLUETOOTH_USB.get(_fabricante_usb(hci / "device"), ("", ""))[0]
        achou("bluetooth", "Bluetooth", ", ".join(filter(None, [hci.name, marca])))

    vistas: set[Path] = set()
    for video in _itens(SYS / "class/video4linux", "video*"):
        aparelho = (video / "device").resolve()
        if _driver(video / "device") != "uvcvideo" or aparelho in vistas:
            continue
        vistas.add(aparelho)
        achou("webcam", "摄像头", _ler(video / "name").split(":")[0])

    for fonte in _itens(SYS / "class/power_supply"):
        # scope=Device 是鼠标或耳机电池，不是本机的
        if _ler(fonte / "type") == "Battery" and _ler(fonte / "scope") != "Device":
            nome = " ".join(filter(None, [_ler(fonte / "manufacturer"), _ler(fonte / "model_name")]))
            achou("bateria", "电池", nome or fonte.name)

    for usb in _itens(SYS / "bus/usb/devices"):
        fab, prod = _ler(usb / "idVendor").lower(), _ler(usb / "idProduct").lower()
        for vendor, inicio, nome in LEITOR_DIGITAL:
            if fab == vendor and prod.startswith(inicio):
                achou("leitor-digital", "指纹读取器", nome)
                break

    # 固件：根据每个真实设备的驱动
    for barramento in ("pci", "usb", "sdio"):
        for aparelho in _itens(SYS / "bus" / barramento / "devices"):
            driver = _driver(aparelho)
            if not driver:
                continue
            if driver == "btusb":
                pacote = BLUETOOTH_USB.get(_fabricante_usb(aparelho), ("", ""))[1]
                if pacote:
                    pede(pacote, driver)
                continue
            for pacote, padroes in FIRMWARE_POR_DRIVER.items():
                if any(_bate(driver, p) for p in padroes):
                    pede(pacote, driver)

    # 声音服务器决定哪个蓝牙音频包适用
    rodando = _processos()
    if "pipewire-pulse" in rodando:
        tags.add("som-pipewire")
    elif "pulseaudio" in rodando or Path("/usr/bin/pulseaudio").exists():
        tags.add("som-pulseaudio")
    elif Path("/usr/bin/pipewire-pulse").exists():
        tags.add("som-pipewire")

    # tlp 与 power-profiles-daemon 冲突；apt 会用一个移除另一个
    if not Path("/usr/libexec/power-profiles-daemon").exists():
        tags.add("sem-power-profiles")
    if (SYS / "firmware/efi").is_dir():
        tags.add("uefi")

    return {"dispositivos": dispositivos, "tags": sorted(tags), "firmware": firmware,
            "virtual": virtual, "non_free_firmware": _non_free_firmware()}


def atende(item: dict, maquina: dict) -> bool:
    """目录项适用于本机吗？列表时所有标记都必须满足。"""
    regra = item.get("hardware")
    if not regra:
        return False
    exigidas = [regra] if isinstance(regra, str) else list(regra)
    tags = set(maquina.get("tags", []))
    for marca in exigidas:
        if marca == "firmware":
            if item.get("pkg") not in maquina.get("firmware", {}):
                return False
        elif marca not in tags:
            return False
    return True
