"""一次一个长任务，行内容可供网页读取。

这里可以运行 Python 函数（应用配方）或外部进程（apt）。两种情况下页面都通过
相同地址跟踪。
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from typing import Callable

from . import estado

_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def sem_cores(texto: str) -> str:
    return _ESCAPE.sub("", texto)


class Tarefa:
    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._linhas: list[str] = []
        self.rodando = False
        self.codigo: int | None = None
        self.rotulo = ""
        self.inicio: float | None = None

    # ---- 读取 ---------------------------------------------------------
    def ocupada(self) -> bool:
        with self._trava:
            return self.rodando

    def instantaneo(self, desde: int = 0) -> dict:
        with self._trava:
            return {"linhas": self._linhas[desde:], "total": len(self._linhas),
                    "rodando": self.rodando, "codigo": self.codigo,
                    "rotulo": self.rotulo,
                    # 重新加载的页面需要开始时间来计算时钟；
                    # 服务器的“现在”会扣除两端时钟差
                    "inicio": self.inicio, "agora": time.time()}

    # ---- 写入 ---------------------------------------------------------
    def diz(self, texto: str) -> None:
        with self._trava:
            for linha in str(texto).splitlines() or [""]:
                self._linhas.append(sem_cores(linha))

    def _abrir(self, rotulo: str) -> bool:
        with self._trava:
            if self.rodando:
                return False
            self._linhas = []
            self.rodando = True
            self.codigo = None
            self.rotulo = rotulo
            self.inicio = time.time()
        return True

    def _fechar(self, codigo: int) -> None:
        with self._trava:
            self.codigo = codigo
            self.rodando = False

    # ---- 运行方式 -------------------------------------------------
    def funcao(self, rotulo: str, alvo: Callable[[Callable[[str], None]], int]) -> bool:
        """运行一个接收 `diz` 并返回代码的 Python 函数。"""
        if not self._abrir(rotulo):
            return False

        def envolver() -> None:
            try:
                codigo = int(alvo(self.diz) or 0)
            except Exception as erro:                  # 页面需要看到原因
                self.diz(f"意外错误：{erro}")
                estado.registrar(f"任务 '{rotulo}' 出错：{erro!r}")
                codigo = 1
            self._fechar(codigo)

        threading.Thread(target=envolver, daemon=True).start()
        return True

    def processo(self, rotulo: str, argumentos: list[str], root: bool = False) -> bool:
        """运行外部命令，逐行转发输出。"""
        if root:
            argumentos = ["sudo", "-n", *argumentos]
        if not self._abrir(rotulo):
            return False

        def envolver() -> None:
            self.diz("$ " + " ".join(shlex.quote(a) for a in argumentos))
            try:
                proc = subprocess.Popen(
                    argumentos, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, bufsize=1,
                    env={**os.environ, "DEBIAN_FRONTEND": "noninteractive", "TERM": "dumb"},
                )
                assert proc.stdout is not None
                for linha in proc.stdout:
                    self.diz(linha.rstrip("\n"))
                proc.wait()
                codigo = proc.returncode
            except OSError as erro:
                self.diz(f"无法执行：{erro}")
                codigo = 1
            self._fechar(codigo)

        threading.Thread(target=envolver, daemon=True).start()
        return True
