/* ================================================================
   searchEngine.js — Motor de busca com autocomplete
   Dispensa Planejada Santos
   ================================================================ */

import { buscarProdutosAPI } from './api.js';

/* ================================================================
   RE-RANKING (no cliente)
   A API ordena por relevancia + nome alfabético, o que faz produtos
   cujo termo aparece NO MEIO do nome ("Doce de Leite...") ficarem
   antes de produtos que COMEÇAM com o termo ("Leite ...").
   Aqui reordenamos priorizando:
     1. termo no início do nome (prefixo)
     2. termo no início de uma palavra do nome
     3. relevancia (cadastro)
     4. nome alfabético
   ================================================================ */
function pontuar(produto, termos) {
  const nome = (produto.nome || '').toLowerCase();
  let pont = 0;

  // q quanto mais cedo o primeiro termo aparece no nome, melhor
  const posPrimeiro = nome.indexOf(termos[0]);
  if (posPrimeiro === 0) pont += 1000;                    // começa exatamente com o termo
  else if (posPrimeiro > 0) {
    const bordaPalavra = /\s/.test(nome[posPrimeiro - 1]);
    pont += bordaPalavra ? 700 : 400;                     // início de palavra vs meio de palavra
  }

  // bônus se TODOS os termos batem no início de alguma palavra
  if (termos.length > 1) {
    const todosInicioPalavra = termos.every(t => {
      const pos = nome.indexOf(t);
      return pos === 0 || (pos > 0 && /\s/.test(nome[pos - 1]));
    });
    if (todosInicioPalavra) pont += 300;
  }

  // desempates originais do SGBD
  pont += (produto.relevancia || 0);
  return pont;
}

function rerank(produtos, texto) {
  const termos = (texto || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!termos.length) return produtos;
  return [...produtos].sort((a, b) => {
    const dif = pontuar(b, termos) - pontuar(a, termos);
    if (dif !== 0) return dif;
    return (a.nome || '').localeCompare(b.nome || '', 'pt-BR');
  });
}

/**
 * Busca produtos por texto, categoria e marca usando a API backend.
 *
 * @param {string} texto - Termo de busca
 * @param {string} [categoriaFiltro] - Categoria selecionada
 * @param {string} [marcaFiltro] - Marca selecionada
 * @param {number} [limite=200] - Máximo de resultados
 * @returns {Promise<Array>} Produtos filtrados e ordenados
 */
export async function buscarProdutos(texto, categoriaFiltro = '', marcaFiltro = '', limite = 200) {
  const t = texto.trim();
  if (!t && !categoriaFiltro && !marcaFiltro) return [];

  try {
    const data = await buscarProdutosAPI(t, categoriaFiltro, marcaFiltro, 1);
    return rerank(data.produtos || [], t);
  } catch (err) {
    console.error('[searchEngine] Erro na busca:', err);
    return [];
  }
}
