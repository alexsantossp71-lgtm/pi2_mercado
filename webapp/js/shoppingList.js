/* ================================================================
   shoppingList.js — CRUD da lista de compras com persistência
   Dispensa Planejada Santos
   ================================================================ */

import { LOJAS } from './dataLoader.js';
import { fmtBRL, melhorLojaUnica, divisaoMultiLoja } from './priceCalculator.js';

const STORAGE_KEY = 'dispensa_planejada_lista';

/**
 * Estado da lista de compras.
 * Map<id, { produto, qtd }>
 */
const lista = new Map();

/** Callbacks registrados para mudanças na lista */
const listeners = [];

/**
 * Registra um callback chamado sempre que a lista muda.
 * @param {Function} fn - Callback(lista: Map)
 */
export function onListaChange(fn) {
  listeners.push(fn);
}

/** Notifica todos os listeners */
function notificar() {
  salvarNoStorage();
  listeners.forEach(fn => fn(lista));
}

/**
 * Adiciona um produto à lista (ou incrementa qtd se já existe).
 * @param {Object} produto - Objeto do produto
 * @param {number} qtd - Quantidade a adicionar
 */
export function adicionarItem(produto, qtd = 1) {
  const atual = lista.get(produto.id);
  if (atual) {
    atual.qtd += qtd;
  } else {
    lista.set(produto.id, { produto, qtd });
  }
  notificar();
}

/**
 * Remove um produto da lista.
 * @param {number} id - ID do produto
 */
export function removerItem(id) {
  lista.delete(id);
  notificar();
}

/**
 * Altera a quantidade de um item.
 * @param {number} id - ID do produto
 * @param {number} delta - +1 ou -1
 */
export function alterarQtd(id, delta) {
  const item = lista.get(id);
  if (!item) return;
  item.qtd += delta;
  if (item.qtd <= 0) {
    lista.delete(id);
  }
  notificar();
}

/** Limpa toda a lista */
export function limparLista() {
  lista.clear();
  notificar();
}

/** Retorna a Map da lista */
export function getLista() {
  return lista;
}

/** Retorna o total de itens (soma das quantidades) */
export function getTotalItens() {
  let total = 0;
  lista.forEach(({ qtd }) => { total += qtd; });
  return total;
}

/* ================================================================
   PERSISTÊNCIA (localStorage)
   ================================================================ */

/** Salva a lista no localStorage */
function salvarNoStorage() {
  try {
    const data = [];
    lista.forEach(({ produto, qtd }, id) => {
      data.push({ id, qtd, produto });
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // localStorage indisponível (modo privado, etc.) — ignora silenciosamente
  }
}

/**
 * Restaura a lista do localStorage.
 */
export async function restaurarDoStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    data.forEach(({ id, qtd, produto }) => {
      if (produto) {
        lista.set(id, { produto, qtd });
      }
    });
    if (lista.size > 0) {
      notificar();
    }
  } catch {
    // Dados corrompidos - ignora
  }
}

/**
 * Gera texto formatado da lista para compartilhamento (ex: WhatsApp).
 * @returns {string}
 */
export function gerarTextoCompartilhamento() {
  if (!lista.size) return '';

  let texto = '🛒 *Minha Lista — Despensa Planejada Santos*\n\n';

  lista.forEach(({ produto, qtd }) => {
    const precos = (produto.preco || []).filter(v => v != null);
    const menor = precos.length ? Math.min(...precos) : null;
    const precoStr = menor != null ? ` → ${fmtBRL(menor)}` : ' → ⚠️ indisponível';
    texto += `• ${qtd}× ${produto.nome}${precoStr}\n`;
  });

  // Resultado do cálculo: a parte que realmente vale compartilhar
  const { loja, total, piorLoja, economia } = melhorLojaUnica(lista);
  const { distribuicao, lojasOrdenadas, total: totalMulti, indisponiveis } = divisaoMultiLoja(lista);

  if (loja) {
    texto += `\n🏆 *Melhor loja única:* ${LOJAS[loja].nome} — ${fmtBRL(total)}`;
    if (economia > 0 && piorLoja) {
      texto += ` (economia de ${fmtBRL(economia)} vs. ${LOJAS[piorLoja].nome})`;
    }
    texto += '\n';
  }

  if (lojasOrdenadas.length > 1) {
    texto += `\n💰 *Dividindo entre lojas:* ${fmtBRL(totalMulti)}\n`;
    lojasOrdenadas.forEach(k => {
      const itens = distribuicao[k];
      const soma = itens.reduce((s, i) => s + i.custo, 0);
      texto += `  ${LOJAS[k].icone} ${LOJAS[k].nome}: ${fmtBRL(soma)} (${itens.length} ${itens.length === 1 ? 'item' : 'itens'})\n`;
    });
  }

  if (indisponiveis.length) {
    texto += `\n🚫 *Sem oferta em nenhuma loja:* ${indisponiveis.map(i => `${i.qtd}× ${i.nome}`).join(', ')}\n`;
  }

  texto += `\n*Total otimizado: ${fmtBRL(totalMulti)}*`;
  texto += '\n📱 Feito com Despensa Planejada Santos';
  return texto;
}

/**
 * Gera código compacto da lista para URL de compartilhamento.
 * Formato: "id:qtd,id:qtd,..." (ex: "12:2,45:1")
 * @returns {string}
 */
export function gerarCodigoLista() {
  const partes = [];
  lista.forEach(({ qtd }, id) => {
    partes.push(`${id}:${qtd}`);
  });
  return partes.join(',');
}
