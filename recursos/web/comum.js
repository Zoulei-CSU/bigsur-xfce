/* ===========================================================================
   d3bian-init-bigsur-xfce - 页面公共部件
   - 顶部状态栏
   - 终端：固定在底部的面板，跟踪服务器的任务，带步骤、进度、日志，
     结束时显示清晰的结论框
   全部都在本函数内：各页面已自行声明 `$`。
   =========================================================================== */
(() => {
"use strict";

/* 每个操作（POST）都以 JSON 发送：服务器拒绝其他格式，使浏览器中任意打开的
   网站无法向面板发号施令。没有会话（未通过终端链接打开的页面）时只提示一次。 */
const _fetch = window.fetch.bind(window);
let avisouAcesso = false;
window.fetch = async (url, op = {}) => {
  if (op.method && op.method.toUpperCase() !== "GET") {
    op = {...op, headers: {"Content-Type": "application/json", ...(op.headers || {})}};
    if (op.body === undefined) op.body = "{}";
  }
  const r = await _fetch(url, op);
  if (r.status === 403 && !avisouAcesso) {
    avisouAcesso = true;
    alert("面板未接受此窗口。请通过终端中显示的链接打开（链接仅可使用一次）。");
  }
  return r;
};

const el = (tag, classe, texto) => {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (texto !== undefined) e.textContent = texto;
  return e;
};
const doisDigitos = n => String(n).padStart(2, "0");
const relogio = segundos => {
  const s = Math.max(0, Math.floor(segundos));
  const h = s / 3600 | 0, m = (s / 60 | 0) % 60;
  return (h ? doisDigitos(h) + ":" : "") + doisDigitos(m) + ":" + doisDigitos(s % 60);
};
const duracao = segundos => segundos < 60 ? `${Math.max(1, segundos | 0)} s` : `${segundos / 60 | 0} min`;

// ---- 顶部状态栏 -----------------------------------------------

// 检查项名称不说明该怎么做；状态栏需要说明
const O_QUE_FAZER = {
  "管理员权限": "请用 d3bian-init-bigsur-xfce 命令打开面板",
  "软件源访问": "无法访问 Debian 软件源",
  "系统": "此系统不是 Debian",
  "图形环境": "需要 XFCE",
  "图形会话": "请在图形会话中打开",
  "xfconf-query": "缺少 xfconf",
  "磁盘空间": "磁盘空间不足",
};

function faixa(){
  const barra = document.querySelector(".estado");
  if (!barra) return;
  const por = (id, txt) => { const e = document.getElementById(id); if (e) e.textContent = txt; };
  const inicio = Date.now();
  setInterval(() => por("eTempo", relogio((Date.now() - inicio) / 1000)), 1000);

  fetch("/api/verificacoes").then(r => r.json()).then(d => {
    const achar = n => (d.verificacoes || []).find(c => c.nome === n) || {};
    por("eDistro", (achar("系统").detalhe || "未知").replace(/GNU\/Linux /, ""));
    por("eDesktop", achar("图形环境").detalhe || "未知");
    const imp = d.impedimentos || [];
    barra.classList.toggle("atencao", imp.length > 0);
    por("ePronto", imp.length ? "注意" : "就绪");
    por("eSit", imp.length ? "[ " + imp.map(n => O_QUE_FAZER[n] || n).join("; ") + " ]" : "[ ok ]");
  }).catch(() => {
    barra.classList.add("atencao");
    por("ePronto", "已断开");
    por("eSit", "[ 服务器未运行 ]");
  });
}

// ---- 终端 --------------------------------------------------------------

const Terminal = (() => {
  const MAX_VISIVEIS = 3000;     // DOM 中的行数；完整文本仍可复制
  const p = {};                  // DOM 部件
  let montado = false;
  let linhas = [], lidas = 0, falhas = 0, timer = null, relogioTimer = null;
  let rodando = false, repondo = false, seguir = true;
  let etapas = [], porPacote = false, pctApt = null, atual = "";
  let inicioLocal = 0, inicioServidor = null, desvio = 0;
  let opcoes = {}, ouvintes = [], resultado = null;
  const tituloOriginal = document.title;

  function montar(){
    if (montado) return;
    montado = true;
    p.raiz = el("section", "terminal");
    p.raiz.hidden = true;
    p.raiz.setAttribute("aria-label", "任务终端");

    const topo = el("div", "t-topo");
    p.ponto = el("span", "t-estado");
    p.titulo = el("b", "t-titulo", "任务");
    p.atual = el("span", "t-atual");
    p.pct = el("span", "t-pct");
    p.tempo = el("span", "t-tempo", "00:00");
    p.btMin = el("button", "t-bt", "最小化");
    p.btFechar = el("button", "t-bt", "关闭");
    p.btMin.type = p.btFechar.type = "button";
    topo.append(p.ponto, p.titulo, p.atual, p.pct, p.tempo, p.btMin, p.btFechar);

    p.barra = el("div", "t-progresso");
    p.cheio = el("span");
    p.barra.appendChild(p.cheio);

    p.corpo = el("div", "t-corpo");
    p.lista = el("ol", "t-etapas");
    p.log = el("div", "t-log");
    p.log.setAttribute("role", "log");
    p.log.tabIndex = 0;
    p.corpo.append(p.lista, p.log);

    const rodape = el("div", "t-rodape");
    const rot = el("label");
    p.seguir = el("input");
    p.seguir.type = "checkbox"; p.seguir.checked = true;
    rot.append(p.seguir, document.createTextNode("跟随末尾"));
    p.btCopiar = el("button", "t-bt", "复制日志");
    p.btCopiar.type = "button";
    p.dica = el("span", "t-dica", "请保持此页面打开。");
    rodape.append(rot, p.btCopiar, p.dica);

    p.raiz.append(topo, p.barra, p.corpo, rodape);
    document.body.appendChild(p.raiz);

    // 面板占用的空间会变成页面底部的留白和固定栏的高度，
    // 否则会盖住用户想点的按钮
    new ResizeObserver(() => {
      const h = p.raiz.hidden ? 0 : p.raiz.offsetHeight;
      document.documentElement.style.setProperty("--term-h", h + "px");
    }).observe(p.raiz);

    p.btMin.addEventListener("click", e => { e.stopPropagation(); minimizar(!p.raiz.classList.contains("min")); });
    topo.addEventListener("click", () => { if (p.raiz.classList.contains("min")) minimizar(false); });
    p.btFechar.addEventListener("click", e => { e.stopPropagation(); fechar(); });
    p.btCopiar.addEventListener("click", copiar);
    p.seguir.addEventListener("change", () => { seguir = p.seguir.checked; if (seguir) aoFim(); });
    // 向上滚动会关闭“跟随”；回到末尾会重新开启
    p.log.addEventListener("scroll", () => {
      seguir = p.log.scrollHeight - p.log.scrollTop - p.log.clientHeight < 30;
      p.seguir.checked = seguir;
    });

    p.quadro = el("dialog", "t-quadro");
    document.body.appendChild(p.quadro);
    p.quadro.addEventListener("close", () => { document.title = tituloOriginal; });
  }

  // ---- 可见状态 -------------------------------------------------------

  function minimizar(sim){
    p.raiz.classList.toggle("min", sim);
    p.btMin.textContent = sim ? "展开" : "最小化";
    if (!sim && seguir) aoFim();
  }

  function fechar(){
    if (rodando) return;
    p.raiz.hidden = true;
    document.documentElement.style.setProperty("--term-h", "0px");
  }

  function aoFim(){ p.log.scrollTop = p.log.scrollHeight; }

  function classe(linha){
    if (/^==> /.test(linha)) return "l-etapa";
    if (/^\s*concluido:/.test(linha)) return "l-ok";
    if (/\bERRO\b|^E: |^pmerror:|erro inesperado|nao consegui|não consegui|无法/i.test(linha)) return "l-erro";
    if (/^W: |atencao:/i.test(linha)) return "l-alerta";
    return "";
  }

  function acrescentar(novas){
    const fragmento = document.createDocumentFragment();
    novas.forEach(linha => {
      if (!ler(linha)) return;
      linhas.push(linha);
      const s = el("span", classe(linha), linha + "\n");
      fragmento.appendChild(s);
    });
    p.log.appendChild(fragmento);
    while (p.log.childElementCount > MAX_VISIVEIS) p.log.firstElementChild.remove();
    if (seguir) aoFim();
  }

  // ---- 读取行 -----------------------------------------------------
  // 对机器行返回 false，它们转为进度并从日志中消失

  function ler(linha){
    let m;
    // 使用 APT::Status-Fd 的 apt：下载占进度条的 30%，安装占其余 70%
    if ((m = linha.match(/^pmstatus:(.+?):([\d.]+):(.*)$/))){
      const pkg = m[1].split(":")[0];
      if (pkg !== "dpkg-exec") marcarPacote(pkg);
      pctApt = 30 + parseFloat(m[2]) * 0.7;
      atual = m[3];
      return false;
    }
    if ((m = linha.match(/^dlstatus:\d+:([\d.]+):(.*)$/))){
      pctApt = parseFloat(m[1]) * 0.3;
      atual = m[2];
      return false;
    }
    if ((m = linha.match(/^==> (\S+) (.*)$/))){ iniciarEtapa(m[1], m[2]); return true; }
    if (/^\s*concluido:/.test(linha)){ fecharEtapa("feito"); return true; }
    if (/^\s*ERRO/.test(linha)){ fecharEtapa("erro"); return true; }
    if ((m = linha.match(/^\s*ja aplicado: (\S+)/))){ mudar(m[1], "feito"); return true; }
    if ((m = linha.match(/^\s*pulando (\S+)/))){ mudar(m[1], "pulado"); return true; }
    if ((m = linha.match(/^habilitando a fonte de (.*?):/))) atual = "正在启用源：" + m[1];
    return true;
  }

  const achar = id => etapas.find(e => e.id === id);
  const agora = () => Date.now() / 1000;

  function mudar(id, estado){
    const e = achar(id);
    if (!e) return;
    if (estado === "rodando" && e.estado !== "rodando") e.inicio = repondo ? null : agora();
    if (estado !== "rodando" && e.estado === "rodando" && e.inicio) e.fim = agora();
    e.estado = estado;
  }

  function iniciarEtapa(id, nome){
    if (!achar(id)) etapas.push({id, nome, estado: "espera"});
    etapas.filter(e => e.estado === "rodando").forEach(e => mudar(e.id, "feito"));
    mudar(id, "rodando");
    atual = nome;
  }

  function fecharEtapa(estado){
    etapas.filter(e => e.estado === "rodando").forEach(e => mudar(e.id, estado));
  }

  function marcarPacote(pkg){
    porPacote = true;
    const e = achar(pkg);
    if (!e || e.estado === "rodando") return;
    etapas.filter(x => x.estado === "rodando").forEach(x => mudar(x.id, "feito"));
    mudar(pkg, "rodando");
  }

  function porcentagem(){
    if (pctApt !== null) return Math.min(100, pctApt);
    if (!etapas.length) return null;
    const prontas = etapas.filter(e => ["feito", "pulado", "erro"].includes(e.estado)).length;
    return prontas / etapas.length * 100;
  }

  function desenhar(){
    const pct = porcentagem();
    p.barra.classList.toggle("indefinido", pct === null && rodando);
    p.cheio.style.width = pct === null ? "" : pct.toFixed(1) + "%";
    p.pct.textContent = pct === null ? "" : Math.floor(pct) + "%";

    const rodandoAgora = etapas.find(e => e.estado === "rodando");
    const indice = rodandoAgora ? etapas.indexOf(rodandoAgora) + 1 : 0;
    let texto = atual;
    if (rodandoAgora && etapas.length) texto = `第 ${indice} 步，共 ${etapas.length} 步 · ${rodandoAgora.nome}`
                                             + (porPacote && atual ? ` · ${atual}` : "");
    p.atual.textContent = texto;
    p.atual.title = texto;
    if (rodando) document.title = (pct === null ? "" : Math.floor(pct) + "% · ") + (opcoes.titulo || "任务");

    p.corpo.classList.toggle("sem-etapas", etapas.length === 0);
    p.lista.textContent = "";
    const MARCAS = {espera: "·", rodando: "▸", feito: "✓", erro: "✗", pulado: "–"};
    etapas.forEach(e => {
      const li = el("li", e.estado);
      li.append(el("span", "mk", MARCAS[e.estado]), el("span", "nm", e.nome));
      li.title = e.nome;
      if (e.inicio){
        const s = (e.fim || agora()) - e.inicio;
        if (e.estado === "rodando" || s >= 5) li.appendChild(el("span", "dur", duracao(s)));
      }
      p.lista.appendChild(li);
    });
    const vivo = p.lista.querySelector("li.rodando, li.erro");
    if (vivo) p.lista.scrollTop = vivo.offsetTop - p.lista.clientHeight / 2;
  }

  function atualizarTempo(){
    const s = inicioServidor !== null ? agora() - desvio - inicioServidor : agora() - inicioLocal;
    p.tempo.textContent = relogio(s);
    return s;
  }

  // ---- 与服务器的循环 ---------------------------------------------------

  async function passo(){
    let r = null;
    try { r = await fetch("/api/progresso?desde=" + lidas).then(x => x.json()); }
    catch (e) { r = null; }
    if (!r){
      if (++falhas >= 8) await terminar(null);
      return;
    }
    falhas = 0;
    if (typeof r.inicio === "number" && typeof r.agora === "number"){
      inicioServidor = r.inicio;
      desvio = agora() - r.agora;
    }
    if (r.linhas && r.linhas.length){
      lidas = r.total;
      acrescentar(r.linhas);
    }
    repondo = false;
    desenhar();
    if (!r.rodando && r.codigo !== null) await terminar(r.codigo);
  }

  async function ciclo(){
    await passo();
    if (rodando) timer = setTimeout(ciclo, 700);
  }

  const segurar = e => { e.preventDefault(); e.returnValue = ""; };

  function abrir(o){
    montar();
    clearTimeout(timer); clearInterval(relogioTimer);
    opcoes = o || {};
    linhas = []; lidas = 0; falhas = 0; seguir = true; p.seguir.checked = true;
    etapas = (opcoes.etapas || []).map(e => ({id: String(e.id), nome: e.nome, estado: "espera"}));
    porPacote = false; pctApt = null; atual = opcoes.atual || ""; resultado = null;
    inicioLocal = agora(); inicioServidor = null; repondo = !!opcoes.repondo;
    p.log.textContent = "";
    p.titulo.textContent = opcoes.titulo || "任务";
    p.dica.textContent = opcoes.dica || "请保持此页面打开。";
    p.raiz.classList.remove("ok", "erro", "min");
    p.raiz.classList.add("rodando");
    p.btMin.textContent = "最小化";
    p.btFechar.hidden = true;
    p.raiz.hidden = false;
    rodando = true;
    ouvintes.forEach(fn => fn(true));
    window.addEventListener("beforeunload", segurar);
    relogioTimer = setInterval(() => { atualizarTempo(); if (etapas.some(e => e.estado === "rodando")) desenhar(); }, 1000);
    desenhar();
    ciclo();
  }

  async function terminar(codigo){
    if (!rodando) return;
    rodando = false;
    clearTimeout(timer); clearInterval(relogioTimer);
    window.removeEventListener("beforeunload", segurar);
    const s = atualizarTempo();
    if (codigo === 0){
      etapas.forEach(e => {
        if (e.estado === "rodando" || (porPacote && e.estado === "espera")) mudar(e.id, "feito");
      });
      if (pctApt !== null) pctApt = 100;
      atual = "已无错误完成";
    } else {
      fecharEtapa("erro");
      atual = codigo === null ? "无法连接服务器" : `出错结束（代码 ${codigo}）`;
    }
    p.raiz.classList.remove("rodando");
    p.raiz.classList.add(codigo === 0 ? "ok" : "erro");
    p.btFechar.hidden = false;
    p.dica.textContent = codigo === 0 ? "" : "红色的行显示了停在哪里。";
    desenhar();
    ouvintes.forEach(fn => fn(false));

    let msg = null;
    try { msg = opcoes.aoTerminar ? await opcoes.aoTerminar(codigo) : null; }
    catch (e) { msg = null; }
    resultado = {codigo, ...padrao(codigo), ...(msg || {})};
    if (codigo !== 0){
      const erro = p.log.querySelector(".l-erro");
      if (erro){ seguir = false; p.seguir.checked = false; p.log.scrollTop = erro.offsetTop - 40; }
    }
    quadro(resultado, s);
  }

  function padrao(codigo){
    if (codigo === 0) return {bom: true, titulo: "已完成", texto: `${opcoes.titulo || "任务"}已无错误完成。`};
    if (codigo === null) return {bom: false, titulo: "无法连接服务器",
      texto: "本地面板已停止响应。请查看打开它的终端。"};
    return {bom: false, titulo: "出错结束", texto: `代码 ${codigo}。日志显示了停在哪里。`};
  }

  // ---- 结论框 ------------------------------------------------------

  function quadro(r, segundos){
    const q = p.quadro;
    q.className = "t-quadro " + (r.bom ? "ok" : "erro");
    q.textContent = "";
    const ic = el("div", "ic", r.bom ? "✓" : "✗");
    ic.setAttribute("aria-hidden", "true");
    const tt = el("p", "tt", r.titulo);
    tt.id = "tQuadroTitulo";
    q.setAttribute("aria-labelledby", "tQuadroTitulo");
    q.append(ic, tt);
    if (r.texto) q.appendChild(el("p", "tx", r.texto));
    if (segundos) q.appendChild(el("p", "dur", "总用时：" + relogio(segundos)));
    if (r.itens && r.itens.length){
      const ul = el("ul");
      r.itens.forEach(x => ul.appendChild(el("li", "", x)));
      q.appendChild(ul);
    }
    const acoes = el("div", "acoes");
    const verLog = el("button", "bt sec", "查看日志");
    const ok = el("button", "bt pri", r.bom ? "关闭" : "知道了");
    verLog.type = ok.type = "button";
    verLog.addEventListener("click", () => { q.close(); minimizar(false); p.log.focus(); });
    ok.addEventListener("click", () => { q.close(); if (r.bom) minimizar(true); });
    acoes.append(verLog, ok);
    q.appendChild(acoes);

    // 在另一个标签页的人会从标题看到结果
    document.title = (r.bom ? "✓ " : "✗ ") + r.titulo + " · d3bian-init-bigsur-xfce";
    if (q.open) q.close();
    q.showModal();
    ok.focus();
  }

  async function copiar(){
    const texto = linhas.join("\n");
    let deu = false;
    try { await navigator.clipboard.writeText(texto); deu = true; }
    catch (e) {
      const area = el("textarea");
      area.value = texto;
      area.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(area);
      area.select();
      try { deu = document.execCommand("copy"); } catch (e2) { deu = false; }
      area.remove();
    }
    p.btCopiar.textContent = deu ? "已复制" : "无法复制";
    setTimeout(() => { p.btCopiar.textContent = "复制日志"; }, 1800);
  }

  // ---- 页面使用的内容 ------------------------------------------------------

  return {
    // 为服务器刚开始的任务打开面板。
    // o: {titulo, etapas: [{id, nome}], dica, aoTerminar(codigo) -> {bom, titulo, texto, itens}}
    acompanhar: abrir,

    // 页面加载时：若服务器已在运行，从开头起带日志重新打开面板。
    // o: {titulo(rotulo), etapas(rotulo), aoTerminar(codigo)}
    async retomar(o = {}){
      let r;
      try { r = await fetch("/api/progresso?desde=0").then(x => x.json()); }
      catch (e) { return false; }
      if (!r || !r.rodando) return false;
      abrir({
        titulo: (o.titulo && o.titulo(r.rotulo)) || r.rotulo || "任务进行中",
        etapas: (o.etapas && o.etapas(r.rotulo)) || [],
        aoTerminar: o.aoTerminar,
        repondo: true,
      });
      return true;
    },

    // fn(ocupado) 在任务开始和结束时被调用
    aoMudar(fn){ ouvintes.push(fn); if (rodando) fn(true); },
    ocupado: () => rodando,

    // 独立结论框，用于任务开始前的错误
    avisar(bom, titulo, texto, itens){ montar(); quadro({bom, titulo, texto, itens}, 0); },
  };
})();

window.Terminal = Terminal;
// 此文件在页面正文之前加载；状态栏等待它存在
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", faixa);
else faixa();
})();
