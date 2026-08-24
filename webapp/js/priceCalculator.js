/* ================================================================
   priceCalculator.js — Algoritmo de cálculo de preços
   Dispensa Planejada Santos
   ================================================================ */

import { CHAVES_LOJA, LOJAS } from './dataLoader.js';

/**
 * Formata valor em BRL.
 * @param {number} valor
 * @returns {string}
 */
export function fmtBRL(valor) {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

/**
 * Verifica se um produto está disponível numa loja específica.
 * Combina preco[i] não-nulo com em_estoque[i] !== false.
 * Se o array em_estoque estiver ausente, deduz de preco[i] == null.
 * @param {Object} produto
 * @param {number} i - índice da loja (0=carrefour, 1=pao_de_acucar, 2=atacadao)
 * @returns {boolean}
 */
export function disponivelEm(produto, i) {
  if (!produto.preco || produto.preco[i] == null) return false;
  if (Array.isArray(produto.em_estoque) && produto.em_estoque[i] === false) return false;
  return true;
}

/**
 * Conta, por loja, quantos produtos da lista estão indisponíveis.
 * @param {Map} lista - Map<id, { produto, qtd }>
 * @returns {Object} { carrefour: number, pao_de_acucar: number, atacadao: number }
 */
export function itensIndisponiveisPorLoja(lista) {
  const faltas = {};
  CHAVES_LOJA.forEach(k => { faltas[k] = 0; });

  lista.forEach(({ produto }) => {
    CHAVES_LOJA.forEach((k, i) => {
      if (!disponivelEm(produto, i)) faltas[k]++;
    });
  });

  return faltas;
}

/**
 * Calcula o total da lista por loja (tudo em uma loja só).
 * @param {Map} lista - Map<id, { produto, qtd }>
 * @returns {Object} { carrefour: number, pao_de_acucar: number, atacadao: number }
 */
export function totalPorLoja(lista) {
  const totais = {};
  CHAVES_LOJA.forEach(k => { totais[k] = 0; });

  lista.forEach(({ produto, qtd }) => {
    CHAVES_LOJA.forEach((k, i) => {
      if (produto.preco && produto.preco[i] != null) {
        totais[k] += produto.preco[i] * qtd;
      }
    });
  });

  return totais;
}

/**
 * Determina a melhor loja única (menor total global).
 * Desempate: prefere a loja com maior número de itens disponíveis,
 * para não premiar loja que cobre menos da lista.
 * @param {Map} lista
 * @returns {{ loja: string|null, total: number, piorLoja: string|null, economia: number, indisponiveis: Object }}
 */
export function melhorLojaUnica(lista) {
  const totais = totalPorLoja(lista);
  const indisponiveis = itensIndisponiveisPorLoja(lista);
  const comPreco = Object.keys(totais).filter(k => totais[k] > 0);

  if (!comPreco.length) {
    return { loja: null, total: 0, piorLoja: null, economia: 0, indisponiveis };
  }

  const ordenadas = comPreco.sort((a, b) =>
    totais[a] - totais[b] || indisponiveis[a] - indisponiveis[b]);
  const melhor = ordenadas[0];
  const pior = ordenadas[ordenadas.length - 1];

  return {
    loja: melhor,
    total: totais[melhor],
    piorLoja: pior,
    economia: totais[pior] - totais[melhor],
    indisponiveis
  };
}

/**
 * Calcula a divisão multi-loja (cada produto no mercado mais barato).
 * Produtos sem preço em NENHUMA loja são retornados em `indisponiveis`,
 * em vez de serem silenciosamente descartados.
 * @param {Map} lista
 * @returns {{ distribuicao: Object, lojasOrdenadas: string[], total: number, indisponiveis: Array }}
 */
export function divisaoMultiLoja(lista) {
  const distribuicao = {};
  CHAVES_LOJA.forEach(k => { distribuicao[k] = []; });
  const indisponiveis = [];
  let total = 0;

  lista.forEach(({ produto, qtd }) => {
    const precoDisponiveis = CHAVES_LOJA
      .map((k, i) => ({ k, v: produto.preco ? produto.preco[i] : null }))
      .filter(x => x.v != null);

    if (!precoDisponiveis.length) {
      indisponiveis.push({ nome: produto.nome, qtd });
      return;
    }
    precoDisponiveis.sort((a, b) => a.v - b.v);

    const { k: loja, v } = precoDisponiveis[0];
    const custo = v * qtd;
    distribuicao[loja].push({ nome: produto.nome, qtd, custo });
    total += custo;
  });

  const lojasOrdenadas = Object.keys(distribuicao)
    .filter(k => distribuicao[k].length)
    .sort((a, b) => {
      const somaA = distribuicao[a].reduce((s, i) => s + i.custo, 0);
      const somaB = distribuicao[b].reduce((s, i) => s + i.custo, 0);
      return somaB - somaA;
    });

  return { distribuicao, lojasOrdenadas, total, indisponiveis };
}
