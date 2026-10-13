/* ================================================================
   app.js — Orquestrador Principal
   Dispensa Planejada Santos
   Inicializa todos os módulos na ordem correta.
   ================================================================ */

import { buscarMarcasAPI, buscarMetaAPI, buscarProdutoPorIdAPI } from './api.js';
import { buscarProdutos } from './searchEngine.js';
import { onListaChange, restaurarDoStorage, limparLista, adicionarItem } from './shoppingList.js';
import { initUI, popularCategorias, renderLista } from './ui.js';

/**
 * Expõe módulos no window para acesso cross-module em event handlers
 * (necessário enquanto não migramos para bundler/framework)
 */
window._dp_modules = {
  onListaChange
};

/**
 * Restaura a lista a partir de um link compartilhado (?lista=id:qtd,...).
 * A URL tem precedência sobre o localStorage; o parâmetro é removido após a carga.
 */
async function restaurarDaURL() {
  const params = new URLSearchParams(location.search);
  const codigo = params.get('lista');
  if (!codigo) return;

  limparLista();
  const pares = codigo.split(',').map(p => p.trim()).filter(Boolean);
  for (const par of pares) {
    const [idStr, qtdStr] = par.split(':');
    const id = parseInt(idStr, 10);
    const qtd = Math.max(1, parseInt(qtdStr, 10) || 1);
    if (!id) continue;
    try {
      const produto = await buscarProdutoPorIdAPI(id);
      adicionarItem(produto, qtd);
    } catch (e) {
      console.warn(`[Share] Produto ${id} não encontrado:`, e);
    }
  }

  // Limpa o parâmetro para não restaurar de novo em refresh
  history.replaceState(null, '', location.pathname);
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

  // 3. Restaura lista do localStorage
  await restaurarDoStorage();
  await restaurarDaURL();

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
