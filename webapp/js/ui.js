/* ================================================================
   ui.js — Renderização de UI / DOM Manipulation
   Dispensa Planejada Santos
   ================================================================ */

import { buscarMarcasAPI } from './api.js';
import { LOJAS, CHAVES_LOJA } from './dataLoader.js';
import { buscarProdutos } from './searchEngine.js';
import { getLista, getTotalItens, adicionarItem, removerItem, alterarQtd, limparLista, gerarTextoCompartilhamento } from './shoppingList.js';
import { fmtBRL, totalPorLoja, melhorLojaUnica, divisaoMultiLoja, disponivelEm, itensIndisponiveisPorLoja } from './priceCalculator.js';

/* ================================================================
   REFERÊNCIAS DOM
   ================================================================ */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const campoBusca       = $('#campoBusca');
const campoMarca       = $('#campoMarca');
const sugestoes        = $('#sugestoes');
const sugestoesMarca   = $('#sugestoesMarca');
const selectQtd        = $('#selectQtd');
const selectCategoria  = $('#selectCategoria');
const btnAdicionar     = $('#btnAdicionar');
const listaVazia       = $('#listaVazia');
const tabelaLista      = $('#tabelaLista');
const corpoLista       = $('#corpoLista');
const contagemItens    = $('#contagemItens');
const btnLimparLista   = $('#btnLimparLista');
const btnCalcular      = $('#btnCalcular');
const secaoResultados  = $('#resultados');
const secaoChecklist   = $('#modoChecklist');
const btnNovaBusca     = $('#btnNovaBusca');
const btnSairChecklist = $('#btnSairChecklist');
const btnCompartilhar  = $('#btnCompartilhar');

let produtoSelecionado = null;
let debounceTimerMarca;

/* ================================================================
   POPULADORES DE SELECT
   ================================================================ */
export async function popularMarcas(categoriaFiltro) {
  try {
    const marcas = await buscarMarcasAPI(categoriaFiltro);
    selectMarca.innerHTML = '<option value="">Todas as marcas</option>' +
      marcas.map(m => `<option value="${m.nome.replace(/"/g, '&quot;')}">${m.nome}</option>`).join('');
  } catch (err) {
    console.error('Erro ao popular marcas', err);
  }
}

/* ================================================================
   AUTOCOMPLETE / SUGESTÕES
   ================================================================ */
async function renderSugestoes() {
  const itens = await buscarProdutos(campoBusca.value, selectCategoria.value, selectMarca.value);

  if (!itens.length) {
    sugestoes.classList.add('hidden');
    return;
  }

  sugestoes.innerHTML = '';
  itens.forEach((p, i) => {
    const div = document.createElement('div');
    div.className = 'dropdown-item' + (i === 0 ? ' active' : '');
    const precoMin = p.preco && p.preco.length ? Math.min(...p.preco.filter(v => v != null)) : null;
    const precoExib = precoMin != null ? fmtBRL(precoMin) : 'Indisponível';

    // Build per-store price display
    let pricesHTML = '';
    CHAVES_LOJA.forEach((chave, idx) => {
      const loja = LOJAS[chave];
      const preco = p.preco && p.preco.length > idx ? p.preco[idx] : null;
      const disponivel = p.em_estoque && p.em_estoque.length > idx ? p.em_estoque[idx] : false;
      const precoTexto = disponivel && preco !== null ? fmtBRL(preco) : 'Indisponível';
      const cor = disponivel && preco !== null ? '' : 'text-muted';
      pricesHTML += `<span class="store-price ${cor}" title="${loja.nome}">${loja.icone} ${precoTexto}</span> `;
    });

    div.innerHTML = `
      <div>
        <p class="item-name">${p.nome}</p>
        <p class="item-meta">${p.categoria} • ${p.marca}</p>
      </div>
      <div class="store-prices">${pricesHTML}</div>
      <span class="item-price">${precoExib}</span>`;

    div.addEventListener('click', () => selecionarProduto(p));
    sugestoes.appendChild(div);
  });

  sugestoes.classList.remove('hidden');
}

async function renderSugestoesMarca() {
  const marcaTexto = campoMarca.value.trim();
  const categoriaFiltro = selectCategoria.value;

  if (!marcaTexto && !categoriaFiltro) {
    sugestoesMarca.classList.add('hidden');
    return;
  }

  try {
    const marcas = await buscarMarcasAPI(categoriaFiltro);

    // Filter marcas that match the text input
    const marcasFiltradas = marcas.filter(marca =>
      marca.nome.toLowerCase().includes(marcaTexto.toLowerCase())
    );

    if (!marcasFiltradas.length) {
      sugestoesMarca.classList.add('hidden');
      return;
    }

    sugestoesMarca.innerHTML = '';
    marcasFiltradas.forEach((marca, i) => {
      const div = document.createElement('div');
      div.className = 'dropdown-item' + (i === 0 ? ' active' : '');

      div.innerHTML = `
        <div>
          <p class="item-name">${marca.nome}</p>
        </div>`;

      div.addEventListener('click', () => selecionarMarca(marca.nome));
      sugestoesMarca.appendChild(div);
    });

    sugestoesMarca.classList.remove('hidden');
  } catch (err) {
    console.error('[ui] Erro ao buscar marcas:', err);
    sugestoesMarca.classList.add('hidden');
  }
}

function selecionarProduto(p) {
  campoBusca.value = p.nome;
  sugestoes.classList.add('hidden');
  produtoSelecionado = p;
  campoBusca.dataset.produtoId = p.id;
}

function selecionarMarca(marcaNome) {
  campoMarca.value = marcaNome;
  selectMarca.value = marcaNome;
  sugestoesMarca.classList.add('hidden');
  // Update products based on selected brand
  renderSugestoes();
}

/* ================================================================
   RENDERIZAÇÃO DA LISTA
   ================================================================ */
export function renderLista() {
  const lista = getLista();
  const totalItens = getTotalItens();

  if (!lista.size) {
    listaVazia.classList.remove('hidden');
    tabelaLista.classList.add('hidden');
    secaoResultados.classList.add('hidden');
    secaoChecklist.classList.add('hidden');
    return;
  }

  listaVazia.classList.add('hidden');
  tabelaLista.classList.remove('hidden');
  contagemItens.textContent = totalItens + (totalItens === 1 ? ' item' : ' itens');

  corpoLista.innerHTML = '';
  lista.forEach(({ produto, qtd }, id) => {
    const tr = document.createElement('tr');
    // Build per-store price display for the list row
    let pricesHTML = '';
    CHAVES_LOJA.forEach((chave, idx) => {
      const loja = LOJAS[chave];
      const preco = produto.preco && produto.preco.length > idx ? produto.preco[idx] : null;
      const disponivel = produto.em_estoque && produto.em_estoque.length > idx ? produto.em_estoque[idx] : false;
      const precoTexto = disponivel && preco !== null ? fmtBRL(preco) : 'Indisponível';
      const cor = disponivel && preco !== null ? '' : 'text-muted';
      pricesHTML += `<span class="store-price ${cor}" title="${loja.nome}">${loja.icone} ${precoTexto}</span> `;
    });
    const precoCell = `<div class="store-prices">${pricesHTML}</div>`;

    tr.innerHTML = `
      <td>
        <p class="product-name">${produto.nome}</p>
        <p class="product-meta">${produto.categoria} • ${produto.marca}</p>
      </td>
      <td class="text-center">
        <div class="qty-stepper">
          <button class="btnQtdMenos" aria-label="Diminuir quantidade de ${produto.nome}">−</button>
          <span class="qty-value">${qtd}</span>
          <button class="btnQtdMais" aria-label="Aumentar quantidade de ${produto.nome}">+</button>
        </div>
      </td>
      <td class="text-center col-mobile-hidden">${precoCell}</td>
      <td class="text-center">
        <button class="btn-icon btnRemover" title="Remover" aria-label="Remover ${produto.nome}">✕</button>
      </td>`;

    tr.querySelector('.btnQtdMenos').addEventListener('click', () => alterarQtd(id, -1));
    tr.querySelector('.btnQtdMais').addEventListener('click', () => alterarQtd(id, +1));
    tr.querySelector('.btnRemover').addEventListener('click', () => removerItem(id));

    corpoLista.appendChild(tr);
  });
}

/* ================================================================
   RENDERIZAÇÃO DOS RESULTADOS
   ================================================================ */
export function renderResultados() {
  const lista = getLista();
  const { loja, total, piorLoja, economia } = melhorLojaUnica(lista);
  const todosTotais = totalPorLoja(lista);
  const faltas = itensIndisponiveisPorLoja(lista);
  const notaFalta = (k) => faltas[k] > 0
    ? `<p class="store-missing">${faltas[k]} ${faltas[k] === 1 ? 'item indisponível' : 'itens indisponíveis'} nesta loja</p>`
    : '';

  // OPÇÃO 1: Melhor loja única
  const r1 = $('#resultadoLojaUnica');
  r1.innerHTML = CHAVES_LOJA.map(k => {
    const melhor = k === loja;
    const cardClass = melhor ? 'card-highlight' : 'card-flat';
    return `
      <div class="${cardClass} store-card">
        <div class="store-header">
          <span>${LOJAS[k].icone}</span>
          <p class="store-name">${LOJAS[k].nome}</p>
          ${melhor ? '<span class="badge badge-primary" style="margin-left:auto">MELHOR</span>' : ''}
        </div>
        <p class="store-price ${melhor ? 'is-best' : ''}">${fmtBRL(todosTotais[k])}</p>
        ${notaFalta(k)}
      </div>`;
  }).join('');

  // OPÇÃO 2: Multi-loja
  const { distribuicao, lojasOrdenadas, total: totalOtim, indisponiveis } = divisaoMultiLoja(lista);
  $('#valorTotalOtimizado').textContent = fmtBRL(totalOtim);
  const economiaMulti = piorLoja != null ? todosTotais[piorLoja] - totalOtim : 0;
  $('#economiaMulti').textContent = fmtBRL(economiaMulti);

  const divLojas = $('#divisaoLojas');
  divLojas.innerHTML = '';
  CHAVES_LOJA.forEach(k => {
    const itens = distribuicao[k];
    if (!itens.length) return;
    const soma = itens.reduce((s, i) => s + i.custo, 0);
    const card = document.createElement('div');
    card.className = 'card-flat split-store-card';
    card.innerHTML = `
      <div class="split-header">
        <p class="split-store-name">${LOJAS[k].icone} ${LOJAS[k].nome}</p>
        <span class="split-store-total">${fmtBRL(soma)}</span>
      </div>
      <ul class="split-items">
        ${itens.map(i => `<li><span>${i.qtd}× ${i.nome}</span><span class="item-cost">${fmtBRL(i.custo)}</span></li>`).join('')}
      </ul>`;
    divLojas.appendChild(card);
  });

  if (indisponiveis.length) {
    const cardIndisp = document.createElement('div');
    cardIndisp.className = 'card-flat split-store-card split-unavailable';
    cardIndisp.innerHTML = `
      <div class="split-header">
        <p class="split-store-name">🚫 Indisponíveis</p>
        <span class="split-store-total price-unavailable">—</span>
      </div>
      <ul class="split-items">
        ${indisponiveis.map(i => `<li><span>${i.qtd}× ${i.nome}</span><span class="price-unavailable">indisponível</span></li>`).join('')}
      </ul>`;
    divLojas.appendChild(cardIndisp);
  }

  // Comparativo geral
  const comp = $('#comparativoGeral');
  const melhorComp = Math.min(...Object.values(todosTotais).filter(v => v > 0));
  comp.innerHTML = CHAVES_LOJA.map(k => {
    const v = todosTotais[k];
    const ehMelhor = v === melhorComp && v > 0;
    const ringClass = ehMelhor ? 'card-highlight' : 'card-flat';
    return `
      <div class="${ringClass} store-card">
        <p class="store-name">${LOJAS[k].icone} ${LOJAS[k].nome}</p>
        <p class="store-price">${fmtBRL(v)}</p>
        ${notaFalta(k)}
        ${ehMelhor
          ? '<span class="best-indicator">⭐ MENOR PREÇO</span>'
          : `<span class="diff-indicator">+${fmtBRL(v - melhorComp)} vs. menor</span>`}
      </div>`;
  }).join('');

  secaoResultados.classList.remove('hidden');
  secaoResultados.scrollIntoView({ behavior: 'smooth' });
}

/* ================================================================
   MODO CHECKLIST
   ================================================================ */
let totalItensChecklist = 0;

function renderChecklist() {
  const lista = getLista();
  const corpo = $('#checklistCorpo');
  const grupos = {};

  lista.forEach(({ produto, qtd }) => {
    if (!grupos[produto.categoria]) grupos[produto.categoria] = [];
    grupos[produto.categoria].push({ produto, qtd });
  });

  corpo.innerHTML = '';
  totalItensChecklist = 0;

  Object.entries(grupos).forEach(([categoria, itens]) => {
    const bloco = document.createElement('div');
    bloco.className = 'category-group';
    bloco.innerHTML = `<h4 class="category-title">${categoria}</h4>`;

    const listaUl = document.createElement('ul');
    listaUl.style.listStyle = 'none';
    listaUl.style.display = 'flex';
    listaUl.style.flexDirection = 'column';
    listaUl.style.gap = 'var(--space-2)';

    itens.forEach(({ produto, qtd }) => {
      totalItensChecklist += qtd;
      const li = document.createElement('li');
      li.className = 'checkbox-item';
      li.innerHTML = `
        <input type="checkbox" class="checkItem" data-id="${produto.id}" aria-label="Marcar ${produto.nome}">
        <div>
          <span class="check-label">${produto.nome}</span>
          <span class="check-qty">× ${qtd}</span>
        </div>`;

      li.querySelector('.checkItem').addEventListener('change', atualizarProgresso);
      listaUl.appendChild(li);
    });

    bloco.appendChild(listaUl);
    corpo.appendChild(bloco);
  });

  atualizarProgresso();
}

function atualizarProgresso() {
  const checks = $$('.checkItem');
  const marcados = [...checks].filter(c => c.checked).length;
  $('#checklistProgresso').textContent = `✅ ${marcados} de ${totalItensChecklist} itens marcados`;
}

/* ================================================================
   COMPARTILHAR VIA WHATSAPP
   ================================================================ */
function compartilharWhatsApp() {
  const texto = gerarTextoCompartilhamento();
  if (!texto) return;
  const url = `https://wa.me/?text=${encodeURIComponent(texto)}`;
  window.open(url, '_blank');
}

/* ================================================================
   DARK MODE TOGGLE
   ================================================================ */
function initThemeToggle() {
  const toggle = $('#themeToggle');
  if (!toggle) return;

  // Restaurar preferência salva
  const savedTheme = localStorage.getItem('dispensa_theme');
  if (savedTheme === 'dark') {
    document.documentElement.classList.add('dark');
    toggle.textContent = '☀️';
  } else if (savedTheme === 'light') {
    document.documentElement.classList.add('light');
    toggle.textContent = '🌙';
  }

  toggle.addEventListener('click', () => {
    const isDark = document.documentElement.classList.toggle('dark');
    document.documentElement.classList.toggle('light', !isDark);
    toggle.textContent = isDark ? '☀️' : '🌙';
    localStorage.setItem('dispensa_theme', isDark ? 'dark' : 'light');
  });
}

/* ================================================================
   EVENT BINDINGS
   ================================================================ */
export function initUI() {
  // Theme
  initThemeToggle();

  // Filtros
  selectCategoria.addEventListener('change', () => {
    selectMarca.value = '';
    popularMarcas(selectCategoria.value);
    renderSugestoes();
  });

  let debounceTimer;
  // Busca
  campoBusca.addEventListener('input', () => {
    produtoSelecionado = null;
    campoBusca.dataset.produtoId = '';

    if (campoBusca.value.trim().length > 0) {
      sugestoes.innerHTML = '<div class="dropdown-item" style="text-align: center; color: var(--color-text-muted);">⏳ Buscando...</div>';
      sugestoes.classList.remove('hidden');
    } else {
      sugestoes.classList.add('hidden');
    }

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      renderSugestoes();
    }, 500); // Espera 500ms apÃ³s a digitaÃ§Ã£o para buscar
  });
  campoBusca.addEventListener('focus', () => renderSugestoes());
  campoBusca.addEventListener('blur', () => setTimeout(() => sugestoes.classList.add('hidden'), 150));

  // Marca autocomplete
  campoMarca.addEventListener('input', () => {
    if (campoMarca.value.trim().length > 0) {
      sugestoesMarca.innerHTML = '<div class="dropdown-item" style="text-align: center; color: var(--color-text-muted);">⏳ Buscando marcas...</div>';
      sugestoesMarca.classList.remove('hidden');
    } else {
      sugestoesMarca.classList.add('hidden');
    }

    clearTimeout(debounceTimerMarca);
    debounceTimerMarca = setTimeout(() => {
      renderSugestoesMarca();
    }, 500);
  });
  campoMarca.addEventListener('focus', () => renderSugestoesMarca());
  campoMarca.addEventListener('blur', () => setTimeout(() => sugestoesMarca.classList.add('hidden'), 150));

  // Adicionar
  btnAdicionar.addEventListener('click', async () => {
    let id = parseInt(campoBusca.dataset.produtoId || '');
    let p = produtoSelecionado;

    if (!id || !p) {
      const resultados = await buscarProdutos(campoBusca.value, selectCategoria.value, selectMarca.value);
      const match = resultados[0];
      if (!match) { alert('Produto não encontrado. Selecione uma sugestão.'); return; }
      selecionarProduto(match);
      id = match.id;
      p = match;
    }

    const qtd = parseInt(selectQtd.value);
    adicionarItem(p, qtd);

    campoBusca.value = '';
    campoBusca.dataset.produtoId = '';
    produtoSelecionado = null;
  });

  // Limpar lista
  btnLimparLista.addEventListener('click', () => {
    if (!confirm('Limpar todos os itens da lista?')) return;
    limparLista();
  });

  // Calcular
  btnCalcular.addEventListener('click', () => {
    if (!getLista().size) { alert('Adicione ao menos um produto à lista.'); return; }
    renderResultados();
  });

  // Nova busca
  btnNovaBusca.addEventListener('click', () => {
    secaoResultados.classList.add('hidden');
    secaoChecklist.classList.add('hidden');
    document.getElementById('criador').scrollIntoView({ behavior: 'smooth' });
  });

  // Checklist
  const btnAbrirChecklist = document.createElement('button');
  btnAbrirChecklist.id = 'btnAbrirChecklist';
  btnAbrirChecklist.className = 'btn btn-primary btn-lg';
  btnAbrirChecklist.style.marginTop = 'var(--space-8)';
  btnAbrirChecklist.textContent = '✅ Abrir Modo Checklist de Compras';
  btnAbrirChecklist.addEventListener('click', () => {
    if (!getLista().size) { alert('Adicione itens à lista primeiro.'); return; }
    secaoChecklist.classList.remove('hidden');
    renderChecklist();
    secaoChecklist.scrollIntoView({ behavior: 'smooth' });
  });
  const compContainer = $('#comparativoGeral').closest('.card');
  if (compContainer) compContainer.appendChild(btnAbrirChecklist);

  btnSairChecklist.addEventListener('click', () => {
    secaoChecklist.classList.add('hidden');
    secaoResultados.scrollIntoView({ behavior: 'smooth' });
  });

  // Compartilhar
  if (btnCompartilhar) {
    btnCompartilhar.addEventListener('click', compartilharWhatsApp);
  }

  // Listener para re-render automático da lista
  const { onListaChange } = window._dp_modules;
  onListaChange(() => renderLista());
}
