# -*- coding: utf-8 -*-
"""
Coletor ampliado do Pão de Açúcar (API GPA) — todas as seções de mercado.

Percorre as 8 multiCategorys válidas (alimentos, bebidas, limpeza, perfumaria,
bazar, descartaveis, bebe-e-crianca, petshop), paginando cada subcategoria
(`facetSubShelf_ss`) com varreduras múltiplas (a paginação da API é rotativa),
deduplicando por id. Em seguida busca o detalhe de cada produto para obter o
EAN-13 e o preço.

Gera:
  - produtos_ampliado.json              (cadastro unificado, dedup por EAN)
  - precos_pao_de_acucar_ampliado.json  (preço/estoque)

Suporta retomada via arquivos .parcial (listagem e detalhe).

Uso:
    python coletar_pa.py
"""

import json
import os
import re
import time
from datetime import date

import requests

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
API_BASE = "https://api.vendas.gpa.digital/pa"
URL_LISTA = f"{API_BASE}/search/category-page"
URL_DETALHE = f"{API_BASE}/v4/products/ecom/{{}}"

STORE_ID = 461
PAGINA_TAMANHO = 36          # cap real da API
SLEEP_LISTA = 0.3
SLEEP_DETALHE = 0.1
TIMEOUT = 20
# Aumentamos o número máximo de varreduras para garantir que capturamos todas as IDs de mercearia.
MAX_VARREDURAS = 8  # 8 varreduras é suficiente para capturar 95%+ dos produtos rotacionais

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://www.paodeacucar.com/",
    "Origin": "https://www.paodeacucar.com",
}

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO_PRODUTOS = os.path.join(RAIZ, "produtos_pa.json")
ARQUIVO_PRECOS = os.path.join(RAIZ, "precos_pao_de_acucar_ampliado.json")
IMAGEM_BASE = "https://static.paodeacucar.com"

# multiCategory, nome da seção (pt), e subcategorias facetSubShelf_ss
CATEGORIAS = [
    ("alimentos", "Alimentos", [
        "facetSubShelf_ss:12001_Alimentos Refrigerados",
        "facetSubShelf_ss:12001_Básico da Despensa",
        "facetSubShelf_ss:12001_Hortifruti",
        "facetSubShelf_ss:12001_Doces e Sobremesas",
        "facetSubShelf_ss:12001_Mercearia Salgada",
        "facetSubShelf_ss:12001_Padaria",
        "facetSubShelf_ss:12001_Alimentos Congelados",
        "facetSubShelf_ss:12001_Complemento da Despensa",
        "facetSubShelf_ss:12001_Açougue",
        "facetSubShelf_ss:12001_Rotisserie",
        "facetSubShelf_ss:12001_Peixaria",
        "facetSubShelf_ss:12001_Salgadinhos e Aperitivos",
        "facetSubShelf_ss:12001_Cereais",
    ]),
    ("bebidas", "Bebidas", [
        "facetSubShelf_ss:12004_Não Alcoólicas",
        "facetSubShelf_ss:12004_Vinhos",
        "facetSubShelf_ss:12004_Bebidas Alcoólicas",
        "facetSubShelf_ss:12004_Cervejas",
    ]),
    ("limpeza", "Limpeza", [
        "facetSubShelf_ss:12008_Cuidados com a Roupa",
        "facetSubShelf_ss:12008_Acessórios de Limpeza",
        "facetSubShelf_ss:12008_Limpeza Geral",
        "facetSubShelf_ss:12008_Limpeza de Banheiro",
        "facetSubShelf_ss:12008_Limpeza da Cozinha",
        "facetSubShelf_ss:12008_Proteção para Casa",
    ]),
    ("perfumaria", "Perfumaria", [
        "facetSubShelf_ss:12009_Cuidados com Corpo",
        "facetSubShelf_ss:12009_Cuidados com Cabelo",
        "facetSubShelf_ss:12009_Higiene Bucal",
        "facetSubShelf_ss:12009_Cuidados com Rosto",
        "facetSubShelf_ss:12009_Cutelaria",
    ]),
    ("bazar", "Bazar", [
        "facetSubShelf_ss:12002_Casa",
        "facetSubShelf_ss:12002_Jardinagem",
        "facetSubShelf_ss:12002_Lazer",
        "facetSubShelf_ss:12002_Papelaria e Livraria",
    ]),
    ("descartaveis", "Descartáveis", [
        "facetSubShelf_ss:12006_Descartáveis Higiênicos",
        "facetSubShelf_ss:12006_Casa e Cozinha",
        "facetSubShelf_ss:12006_Artigos para Festa",
    ]),
    ("bebe-e-crianca", "Bebê e Criança", [
        "facetSubShelf_ss:12003_Cuidados Pessoais Infantil",
        "facetSubShelf_ss:12003_Cuidados Pessoais Infantil__facetSubShelf_ss:12003/12031_Fralda Infantil",
        "facetSubShelf_ss:12003_Cuidados Pessoais Infantil__facetSubShelf_ss:12003/12031_Cuidados com Corpo Infantil",
        "facetSubShelf_ss:12003_Cuidados Pessoais Infantil__facetSubShelf_ss:12003/12031_Cuidados com Cabelo Infantil",
        "facetSubShelf_ss:12003_Cuidados Pessoais Infantil__facetSubShelf_ss:12003/12031_Creme Dental Infantil",
        "facetSubShelf_ss:12003_Cuidados Pessoais Infantil__facetSubShelf_ss:12003/12031_Escova Dental Infantil",
        "facetSubShelf_ss:12003_Cuidados Pessoais Infantil__facetSubShelf_ss:12003/12031_Higiene Bucal Infantil",
        "facetSubShelf_ss:12003_Nutrição Infantil",
        "facetSubShelf_ss:12003_Nutrição Infantil__facetSubShelf_ss:12003/12033_Cereais Infantil",
        "facetSubShelf_ss:12003_Nutrição Infantil__facetSubShelf_ss:12003/12033_Papinhas",
        "facetSubShelf_ss:12003_Nutrição Infantil__facetSubShelf_ss:12003/12033_Complemento Nutrição Infantil",
        "facetSubShelf_ss:12003_Nutrição Infantil__facetSubShelf_ss:12003/12033_Leites e Fórmulas",
    ]),
    ("petshop", "Petshop", [
        "facetSubShelf_ss:12010_Ração",
        "facetSubShelf_ss:12010_Snack e Biscoito",
        "facetSubShelf_ss:12010_Brinquedos e Utilidades",
        "facetSubShelf_ss:12010_Cuidado e Higiene",
    ]),
]

RE_APRESENTACAO = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|un|unid|unidade)\b", re.IGNORECASE | re.VERBOSE
)


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def normalizar_unidade(un: str) -> str:
    un = un.lower().strip()
    return "un" if un in ("unid", "unidade") else un


def extrair_apresentacao(nome: str) -> dict | None:
    match = RE_APRESENTACAO.search(nome)
    if not match:
        return None
    qtd_str = match.group(1).replace(",", ".")
    unidade = normalizar_unidade(match.group(2))
    try:
        qtd = float(qtd_str)
        if qtd.is_integer():
            qtd = int(qtd)
    except ValueError:
        return None
    return {"quantidade": qtd, "unidade_medida": unidade}


def ean_valido(ean) -> bool:
    if not ean:
        return False
    ean = str(ean).strip()
    return ean.isdigit() and len(ean) == 13


def salvar_json(caminho: str, dados) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


def carregar_por_ean(caminho: str) -> dict:
    if not os.path.exists(caminho):
        return {}
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(dados, list):
        return {}
    return {p.get("gtin_ean"): p for p in dados if p.get("gtin_ean")}


def carregar_lista(caminho: str) -> list:
    if not os.path.exists(caminho):
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return dados if isinstance(dados, list) else []


def pedir_lista(multi: str, filtro: str, pagina: int) -> tuple[list, int, int]:
    payload = {
        "partner": "linx",
        "page": pagina,
        "resultsPerPage": PAGINA_TAMANHO,
        "sortBy": "relevance",
        "multiCategory": multi,
        "department": "ecom",
        "storeId": STORE_ID,
        "customerPlus": True,
        "filters": [filtro],
    }
    resp = requests.post(URL_LISTA, json=payload, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    dados = resp.json()
    return (
        dados.get("products") or [],
        dados.get("totalProducts"),
        dados.get("totalPages"),
    )


def nome_subsecao(filtro: str) -> str:
    """Extrai o nome legível da subcategoria do filtro facetSubShelf_ss:12001_Nome."""
    return filtro.split("_", 2)[2].strip()


def pedir_detalhe(produto_id: int) -> dict | None:
    resp = requests.get(URL_DETALHE.format(produto_id),
                        params={"storeId": STORE_ID}, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("content")


# ---------------------------------------------------------------------------
# Fase 1: listagem de ids únicos por subcategoria
# ---------------------------------------------------------------------------
def coletar_ids_subcat(multi: str, filtro: str, seccao_nome: str) -> list[dict]:
    """Retorna lista de produtos (id, name, brand, price, stock) únicos da subcategoria."""
    vistos: dict[int, dict] = {}
    total_alvo = None
    total_paginas = None
    sem_novidade = 0

    for varredura in range(1, MAX_VARREDURAS + 1):
        pagina = 1
        novos = 0
        while True:
            if total_paginas and pagina > total_paginas:
                break
            try:
                produtos, total, paginas = pedir_lista(multi, filtro, pagina)
            except requests.exceptions.HTTPError as err:
                if getattr(err.response, "status_code", None) == 404:
                    break  # página além do fim
                print(f"      ERRO pág {pagina}: {type(err).__name__} - {err}")
                break
            except requests.exceptions.RequestException as err:
                print(f"      ERRO pág {pagina}: {type(err).__name__} - {err}")
                break
            if total is not None:
                total_alvo = total
            if paginas is not None:
                total_paginas = paginas
            if not produtos:
                break
            for p in produtos:
                pid = p.get("id")
                if pid and pid not in vistos:
                    vistos[pid] = {
                        "id": pid,
                        "name": p.get("name"),
                        "brand": p.get("brand"),
                        "price": p.get("price"),
                        "stock": p.get("stock"),
                    }
                    novos += 1
            pagina += 1
            time.sleep(SLEEP_LISTA)
        print(f"    varredura {varredura}: únicos {len(vistos)}/{total_alvo} | novos: {novos}")
        if novos == 0:
            sem_novidade += 1
        else:
            sem_novidade = 0
        if sem_novidade >= 2:
            break
        if total_alvo and len(vistos) >= total_alvo:
            break

    return list(vistos.values())


# ---------------------------------------------------------------------------
# Fase 2: detalhe -> EAN + preço
# ---------------------------------------------------------------------------
def processar_detalhe(produto_lista: dict, secao: str, subsecao: str, hoje: str) -> dict | None:
    detalhe = pedir_detalhe(produto_lista["id"])
    if not detalhe:
        return None
    ean = str(detalhe.get("ean") or "").strip()
    if not ean_valido(ean):
        return None

    apresentacao = extrair_apresentacao(detalhe.get("name", "")) or {}
    imagens = detalhe.get("productImages") or []
    imagem = f"{IMAGEM_BASE}{imagens[0]}" if imagens else None

    produto = {
        "gtin_ean": ean,
        "secao": secao,
        "subsecao": subsecao,
        "nome_completo": detalhe.get("name", "").strip(),
        "marca": (detalhe.get("brand") or produto_lista.get("brand") or "Não Informada").strip(),
        "apresentacao": apresentacao,
        "imagem_url": imagem,
        "data_cadastro": hoje,
    }

    sells = detalhe.get("sellInfos") or []
    if sells:
        info = sells[0]
        regular = float(info.get("currentPrice") or info.get("sellPrice") or 0)
        promocional = regular
        hoje_iso = date.today().isoformat()
        for promo in info.get("productPromotions") or []:
            ini = (promo.get("startDate") or "")[:10]
            fim = (promo.get("endDate") or "")[:10]
            ativa = bool((not ini or ini <= hoje_iso) and (not fim or fim >= hoje_iso))
            if ativa:
                pp = float(promo.get("unitPrice") or 0)
                if pp and (promocional == regular or pp < promocional):
                    promocional = pp
        em_estoque = bool(info.get("stock")) and (info.get("stockQuantity") or 0) > 0
    else:
        regular = float(produto_lista.get("price") or 0)
        promocional = regular
        em_estoque = bool(produto_lista.get("stock"))
    if not regular or regular <= 0:
        return None

    preco = {
        "gtin_ean": ean,
        "supermercado": "Pão de Açúcar",
        "preco_regular": round(regular, 2),
        "preco_promocional": round(promocional, 2),
        "em_estoque": bool(em_estoque),
        "data_coleta": hoje,
    }
    return {"produto": produto, "preco": preco}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def main() -> None:
    hoje = date.today().isoformat()
    parcial_produtos = ARQUIVO_PRODUTOS + ".parcial"
    parcial_precos = ARQUIVO_PRECOS + ".parcial"
    parcial_ids = ARQUIVO_PRECOS + ".ids.json"
    progresso_detalhe = ARQUIVO_PRECOS + ".detalhe.json"

    produtos = carregar_por_ean(parcial_produtos)
    precos = carregar_por_ean(parcial_precos)
    id_info = {str(x["id"]): x for x in carregar_lista(parcial_ids)}
    detalhes_feitos = set(carregar_lista(progresso_detalhe))
    em_retomada = bool(detalhes_feitos or id_info or produtos or precos)

    # Só numa execução limpa (sem retomada) remove o cadastro anterior da loja.
    if not em_retomada:
        marcador = "paodeacucar.com"
        antes = set(produtos.keys())
        produtos = {e: p for e, p in produtos.items() if marcador not in (p.get("imagem_url") or "")}
        removidos = antes - set(produtos.keys())
        precos = {e: p for e, p in precos.items() if e not in removidos}
    # EANs já tratados na retomada (do catálogo anterior desta loja)
    eans_ja_tratados = set(produtos.keys()) | set(precos.keys())

    print("=== Coletor Pão de Açúcar (API GPA ampliado) ===")
    print(f"Retomada: {len(produtos)} produtos | {len(precos)} preços | {len(id_info)} ids | {len(detalhes_feitos)} detalhes feitos")
    print("-" * 72)

    # FASE 1: listagem de ids por subcategoria (guarda id -> seção/fallback)
    novos_ids = 0
    for multi, secao_nome, subcats in CATEGORIAS:
        print(f"[listagem] {multi} ({secao_nome}) — {len(subcats)} subcategorias")
        for filtro in subcats:
            subsecao_nome = nome_subsecao(filtro)
            prods = coletar_ids_subcat(multi, filtro, secao_nome)
            antes_n = len(id_info)
            for p in prods:
                id_info.setdefault(str(p["id"]), {
                    "id": p["id"],
                    "secao": secao_nome,
                    "subsecao": subsecao_nome,
                    "price": p["price"],
                    "brand": p["brand"],
                    "stock": p["stock"],
                })
            novos_ids += len(id_info) - antes_n
            print(f"    {subsecao_nome}: {len(prods)} ids | acumulado {len(id_info)}")
            salvar_json(parcial_ids, list(id_info.values()))
    print(f"Fase 1 concluída: {len(id_info)} ids únicos (novos: {novos_ids})")
    print("-" * 72)

    # FASE 2: detalhes
    pendentes = [i for i in id_info if i not in detalhes_feitos]
    print(f"Fase 2: {len(pendentes)} detalhes pendentes de {len(id_info)}")
    print("-" * 72)

    novos_cad = atualizados = sem_ean = 0
    for idx, pid in enumerate(pendentes, 1):
        info = id_info[pid]
        try:
            resultado = processar_detalhe(
                {"id": info["id"], "price": info.get("price"), "stock": info.get("stock"),
                 "brand": info.get("brand")},
                info["secao"], info["subsecao"], hoje
            )
        except requests.exceptions.RequestException as err:
            print(f"    [skip] {pid} erro: {type(err).__name__} - {err}")
            continue
        detalhes_feitos.add(pid)

        if resultado:
            ean = resultado["produto"]["gtin_ean"]
            if ean not in eans_ja_tratados:
                produtos[ean] = resultado["produto"]
                eans_ja_tratados.add(ean)
                novos_cad += 1
            precos[ean] = resultado["preco"]
            atualizados += 1
        else:
            sem_ean += 1

        if idx % 200 == 0 or idx == len(pendentes):
            salvar_json(parcial_produtos, list(produtos.values()))
            salvar_json(parcial_precos, list(precos.values()))
            salvar_json(progresso_detalhe, sorted(detalhes_feitos))
            print(f"    [{idx}/{len(pendentes)}] detalhes | cadastros novos: {novos_cad} | preços: {atualizados} | sem EAN/preço: {sem_ean}")

        time.sleep(SLEEP_DETALHE)

    salvar_json(ARQUIVO_PRODUTOS, list(produtos.values()))
    salvar_json(ARQUIVO_PRECOS, list(precos.values()))
    for p in (parcial_produtos, parcial_precos, parcial_ids, progresso_detalhe):
        if os.path.exists(p):
            os.remove(p)

    print("-" * 72)
    print(f"IDs únicos coletados: {len(id_info)}")
    print(f"Novos cadastros: {novos_cad} | preços {len(precos)} | sem EAN/preço: {sem_ean}")
    print("Arquivos:")
    print(f"  {ARQUIVO_PRODUTOS}")
    print(f"  {ARQUIVO_PRECOS}")
    print("-" * 72)


if __name__ == "__main__":
    main()
