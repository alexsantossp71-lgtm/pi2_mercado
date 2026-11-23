/* ================================================================
   app.js — Orquestrador Principal
   Dispensa Planejada Santos
   Inicializa todos os módulos na ordem correta.
   ================================================================ */

import { buscarMarcasAPI, buscarMetaAPI, buscarProdutoPorIdAPI, buscarProdutosPorIdsAPI } from './api.js';
import { buscarProdutos } from './searchEngine.js';
import {
  onListaChange,
  restaurarDoStorage,
  limparLista,
  adicionarItem,
  atualizarPrecosLista,
  carregarListaNuvem,
  getTotalItens,
} from './shoppingList.js';
import { initUI, popularCategorias, renderLista, mostrarToast } from './ui.js';

/**
 * Expõe módulos no window para acesso cross-module em event handlers
 * (necessário enquanto não migramos para bundler/framework)
 */
window._dp_modules = {
  onListaChange
};

/**
 * Restaura a lista a partir de um link compartilhado (?c=CODIGO ou ?lista=CODIGO ou ?lista=id:qtd,...).
 * A URL tem precedência sobre o localStorage; o parâmetro é removido após a carga.
 */
async function restaurarDaURL() {
  const params = new URLSearchParams(location.search);
  const paramCodigo = params.get('c') || params.get('codigo');
  const paramLista = params.get('lista');

  if (!paramCodigo && !paramLista) return;

  // 1. Código curto na nuvem (?c=4162ff3b ou ?codigo=4162ff3b)
  if (paramCodigo) {
    try {
      const res = await carregarListaNuvem(paramCodigo.trim().toLowerCase());
      mostrarToast(`🛒 Lista compartilhada "<b>${res.nome || 'Lista'}</b>" carregada!`);
    } catch (e) {
      console.warn('[Share] Erro ao carregar lista da nuvem por código:', e);
      mostrarToast('⚠️ Não foi possível carregar a lista compartilhada.');
    }
    history.replaceState(null, '', location.pathname);
    return;
  }

  // 2. Parâmetro ?lista=...
  if (paramLista) {
    const raw = paramLista.trim();
    // Se não tiver ":" e tiver até 32 caracteres, tenta como código de nuvem
    if (!raw.includes(':') && raw.length <= 32) {
      try {
        const res = await carregarListaNuvem(raw.toLowerCase());
        mostrarToast(`🛒 Lista compartilhada "<b>${res.nome || 'Lista'}</b>" carregada!`);
        history.replaceState(null, '', location.pathname);
        return;
      } catch (e) {
        console.warn('[Share] Código de nuvem não encontrado, tentando formato legado:', e);
      }
    }

    // 3. Formato compacto de IDs (?lista=id:qtd,id:qtd,...)
    const pares = raw.split(',').map(p => p.trim()).filter(Boolean);
    const itemQtdMap = new Map();
    for (const par of pares) {
      const [idStr, qtdStr] = par.split(':');
      const id = parseInt(idStr, 10);
      const qtd = Math.max(1, parseInt(qtdStr, 10) || 1);
      if (id) itemQtdMap.set(id, qtd);
    }

    if (itemQtdMap.size > 0) {
      limparLista();
      try {
        const ids = [...itemQtdMap.keys()];
        // Busca TODOS os produtos em uma única requisição em lote (muito mais rápido!)
        const produtosMap = await buscarProdutosPorIdsAPI(ids);
        itemQtdMap.forEach((qtd, id) => {
          const produto = produtosMap.get(id);
          if (produto) {
            adicionarItem(produto, qtd);
          }
        });
        const total = getTotalItens();
        mostrarToast(`🛒 Lista compartilhada carregada (${total} ${total === 1 ? 'item' : 'itens'})!`);
      } catch (e) {
        console.warn('[Share] Falha ao carregar itens da lista em lote:', e);
      }
    }

    history.replaceState(null, '', location.pathname);
  }
}

/**
 * Ponto de entrada da aplicação.
 */
async function init() {
  console.log('[Dispensa Planejada] Inicializando...');

  // Mostra loading state
  const loading = document.getElementById('loadingOverlay');
  if (loading) loading.classList.remove('hidden');

  // 1. Omitimos o carregamento de JSON local! (Agora vai direto na API)
  if (loading) loading.classList.add('hidden');

  // 2. Popula o filtro com as classificações reais retornadas pela API
  await popularCategorias();

  // 2b. Carrega metadados (lojas + última coleta) e preenche header/footer
  try {
    const meta = await buscarMetaAPI();
    const pillData = document.getElementById('pillData');
    if (pillData && meta.ultima_coleta_fmt) {
      pillData.textContent = `🗓️ Dados: ${meta.ultima_coleta_fmt}`;
    }
    const pillDataCurto = document.getElementById('pillDataCurto');
    if (pillDataCurto && meta.ultima_coleta_fmt) {
      pillDataCurto.textContent = meta.ultima_coleta_fmt;
    }
    const footerLojas = document.getElementById('footerLojas');
    if (footerLojas && meta.lojas && meta.lojas.length) {
      const nomes = meta.lojas.map(l => l.nome);
      footerLojas.textContent = nomes.length > 1
        ? nomes.slice(0, -1).join(', ') + ' e ' + nomes[nomes.length - 1]
        : nomes[0];
    }
    const footerData = document.getElementById('footerData');
    if (footerData && meta.ultima_coleta_fmt) {
      footerData.textContent = meta.ultima_coleta_fmt;
    }
  } catch (e) {
    console.warn('[Meta] Falha ao carregar metadados:', e);
  }

  // 3. Restaura lista do localStorage e de link compartilhado (?lista=id:qtd,...)
  await restaurarDoStorage();
  await restaurarDaURL();

  // 3b. Atualiza preços da lista restaurada com dados frescos do SGBD
  // (snapshot salvo pode estar desatualizado ou vindo de link compartilhado)
  atualizarPrecosLista();

  // 4. Inicializa event bindings da UI
  initUI();

  // 5. Render inicial
  renderLista();

  // 6. Registra Service Worker (PWA)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch((err) => {
      console.warn('[PWA] Service Worker registration skipped or failed:', err);
    });
  }

  console.log('[Dispensa Planejada] Pronto!');
}

// Inicia quando o DOM estiver pronto
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
