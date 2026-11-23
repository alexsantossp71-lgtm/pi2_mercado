/* ================================================================
   shoppingList.js — CRUD da lista de compras com persistência
   Dispensa Planejada Santos
   ================================================================ */

import { LOJAS } from './dataLoader.js';
import { fmtBRL, melhorLojaUnica, divisaoMultiLoja } from './priceCalculator.js';
import { buscarProdutosPorIdsAPI, salvarListaAPI, buscarListaAPI, excluirListaAPI } from './api.js';

const STORAGE_KEY = 'dispensa_planejada_lista';
const SAVED_LISTS_KEY = 'dispensa_planejada_listas_salvas';

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

/**
 * Atualiza (in place) os produtos da lista com dados frescos do SGBD.
 * A lista salva no localStorage carrega um snapshot do produto com os preços
 * da época em que foi adicionada; aqui buscamos o estado atual em uma única
 * chamada em lote (POST /api/produtos/lote) e substituímos os objetos.
 * Em caso de falha (offline etc.) a lista segue com o snapshot — nada quebra.
 */
export async function atualizarPrecosLista() {
  if (!lista.size) return;
  const ids = [...lista.keys()];
  try {
    const mapa = await buscarProdutosPorIdsAPI(ids);
    let alterados = 0;
    lista.forEach((item, id) => {
      const fresco = mapa.get(id);
      if (fresco) {
        item.produto = fresco;
        alterados++;
      }
    });
    if (alterados) notificar();
  } catch (e) {
    console.warn('[shoppingList] Refresh de preços ignorado:', e);
  }
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
  const { loja, total, piorLoja, economia, cobertura } = melhorLojaUnica(lista);
  const { distribuicao, lojasOrdenadas, total: totalMulti, indisponiveis } = divisaoMultiLoja(lista);

  if (loja) {
    texto += `\n🏆 *Melhor loja única:* ${LOJAS[loja].nome} — ${fmtBRL(total)}`;
    if (cobertura && cobertura.total > 0 && cobertura.disponiveis < cobertura.total) {
      texto += ` (cobre ${cobertura.disponiveis} de ${cobertura.total} itens)`;
    }
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

/* ================================================================
   GERENCIADOR DE MÚLTIPLAS LISTAS (LOCAL E NUVEM)
   ================================================================ */

/**
 * Retorna todas as listas salvas no localStorage.
 * @returns {Array<Object>}
 */
export function obterListasSalvasLocal() {
  try {
    const raw = localStorage.getItem(SAVED_LISTS_KEY);
    if (!raw) return [];
    const listas = JSON.parse(raw);
    return Array.isArray(listas) ? listas : [];
  } catch {
    return [];
  }
}

/**
 * Salva a lista ativa atual com um nome no localStorage.
 * @param {string} nome - Nome descritivo da lista
 * @param {string|null} codigo - Código de compartilhamento na nuvem (opcional)
 * @returns {Object} A lista salva
 */
export function salvarListaAtualComo(nome, codigo = null) {
  if (!lista.size) {
    throw new Error('A lista está vazia. Adicione itens antes de salvar.');
  }

  const listas = obterListasSalvasLocal();
  const agora = new Date().toISOString();
  const itens = [];
  lista.forEach(({ produto, qtd }, id) => {
    itens.push({ id, qtd, produto });
  });

  const nomeLimpo = (nome || '').trim() || `Lista de ${new Date().toLocaleDateString('pt-BR')}`;
  
  // Se já existir lista com o mesmo código ou nome, atualiza
  const idxExistente = listas.findIndex(l => (codigo && l.codigo === codigo) || l.nome.toLowerCase() === nomeLimpo.toLowerCase());

  const listaObjeto = {
    id: idxExistente >= 0 ? listas[idxExistente].id : 'lista_' + Date.now().toString(36),
    codigo: codigo || (idxExistente >= 0 ? listas[idxExistente].codigo : null),
    nome: nomeLimpo,
    totalItens: getTotalItens(),
    itens,
    criadoEm: idxExistente >= 0 ? listas[idxExistente].criadoEm : agora,
    atualizadoEm: agora,
  };

  if (idxExistente >= 0) {
    listas[idxExistente] = listaObjeto;
  } else {
    listas.unshift(listaObjeto);
  }

  try {
    localStorage.setItem(SAVED_LISTS_KEY, JSON.stringify(listas));
  } catch (e) {
    console.warn('[Storage] Falha ao persistir listas salvas:', e);
  }

  return listaObjeto;
}

/**
 * Carrega uma lista salva para ser a lista ativa atual.
 * @param {string} id - ID da lista salva
 */
export function carregarListaSalva(id) {
  const listas = obterListasSalvasLocal();
  const encontrada = listas.find(l => l.id === id || l.codigo === id);
  if (!encontrada) {
    throw new Error('Lista salva não encontrada.');
  }

  lista.clear();
  (encontrada.itens || []).forEach(({ id: itemId, qtd, produto }) => {
    if (produto && itemId) {
      lista.set(itemId, { produto, qtd: Number(qtd) || 1 });
    }
  });

  notificar();
  return encontrada;
}

/**
 * Exclui uma lista salva localmente.
 * @param {string} id - ID da lista salva
 */
export function excluirListaSalva(id) {
  const listas = obterListasSalvasLocal();
  const novasListas = listas.filter(l => l.id !== id && l.codigo !== id);
  localStorage.setItem(SAVED_LISTS_KEY, JSON.stringify(novasListas));
  return novasListas;
}

/**
 * Exporta a lista atual como um arquivo JSON para download.
 * @param {string} nomeArquivo
 */
export function exportarListaJSON(nomeArquivo = 'minha_lista_dispensa') {
  if (!lista.size) {
    throw new Error('A lista está vazia. Adicione itens antes de exportar.');
  }

  const itens = [];
  lista.forEach(({ produto, qtd }, id) => {
    itens.push({ id, qtd, produto });
  });

  const payload = {
    app: 'Despensa Planejada Santos',
    versao: '2.0.0',
    exportadoEm: new Date().toISOString(),
    totalItens: getTotalItens(),
    itens,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${nomeArquivo.replace(/\s+/g, '_')}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Importa uma lista de um texto JSON (carregado de arquivo).
 * @param {string} jsonTexto
 */
export function importarListaJSON(jsonTexto) {
  let dados;
  try {
    dados = JSON.parse(jsonTexto);
  } catch {
    throw new Error('Arquivo JSON inválido ou corrompido.');
  }

  const itens = Array.isArray(dados) ? dados : (dados.itens || []);
  if (!Array.isArray(itens) || !itens.length) {
    throw new Error('O arquivo não contém itens válidos de lista de compras.');
  }

  lista.clear();
  let importados = 0;
  itens.forEach(item => {
    const prod = item.produto || item;
    const id = item.id || prod.id;
    const qtd = Number(item.qtd) || 1;
    if (id && prod) {
      lista.set(id, { produto: prod, qtd });
      importados++;
    }
  });

  if (!importados) {
    throw new Error('Nenhum produto válido foi identificado no arquivo.');
  }

  notificar();
  return {
    sucesso: true,
    totalItens: getTotalItens(),
    nome: dados.nome || 'Lista Importada'
  };
}

/**
 * Salva a lista ativa no servidor/nuvem (API) e sincroniza localmente.
 * @param {string} nome
 * @param {string|null} codigo
 */
export async function salvarListaNuvem(nome, codigo = null) {
  if (!lista.size) {
    throw new Error('A lista está vazia. Adicione itens antes de salvar.');
  }

  const itens = [];
  lista.forEach(({ produto, qtd }, id) => {
    itens.push({ id, qtd, produto });
  });

  const res = await salvarListaAPI(nome, itens, codigo);
  // Salva ou atualiza no localStorage com o código retornado
  salvarListaAtualComo(res.nome, res.codigo);
  return res;
}

/**
 * Recupera uma lista da nuvem pelo código, popula a lista ativa e salva no histórico local.
 * @param {string} codigo
 */
export async function carregarListaNuvem(codigo) {
  const res = await buscarListaAPI(codigo);
  if (!res || !Array.isArray(res.itens)) {
    throw new Error('Resposta inválida do servidor.');
  }

  lista.clear();
  res.itens.forEach(({ id, qtd, produto }) => {
    if (id && produto) {
      lista.set(id, { produto, qtd: Number(qtd) || 1 });
    }
  });

  notificar();

  // Salva no histórico local para acesso rápido posterior
  salvarListaAtualComo(res.nome, res.codigo);

  return res;
}

