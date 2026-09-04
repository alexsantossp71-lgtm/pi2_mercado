/* ================================================================
   app.js — Orquestrador Principal
   Dispensa Planejada Santos
   Inicializa todos os módulos na ordem correta.
   ================================================================ */

import { buscarMarcasAPI } from './api.js';
import { buscarProdutos } from './searchEngine.js';
import { onListaChange, restaurarDoStorage } from './shoppingList.js';
import { initUI, renderLista } from './ui.js';

/**
 * Expõe módulos no window para acesso cross-module em event handlers
 * (necessário enquanto não migramos para bundler/framework)
 */
window._dp_modules = {
  onListaChange
};

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

  // 2. Popula filtro de marcas - removido pois agora é dinâmico (autocomplete)

  // 3. Restaura lista do localStorage
  await restaurarDoStorage();

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
