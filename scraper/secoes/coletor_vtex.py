# -*- coding: utf-8 -*-
"""
Coletor VTEX genérico (Carrefour e Atacadão).

Percorre todas as folhas-alvo de um arquivo de folhas (folhas_carrefour.json /
folhas_atacadao.json), paginando cada folha com truncamento em `limite_max`
(2.500, cap do offset da VTEX). Extrai EAN-13 e preço, deduplica por EAN e
grava:

  - produtos_ampliado.json          (cadastro unificado, dedup por EAN)
  - precos_{chave_loja}_ampliado.json (preço/estoque por loja)

Suporta retomada: o progresso é salvo a cada `checkpoint_a_cada` folhas em
arquivos .parcial; ao relançar, folhas concluídas são puladas.

Uso (biblioteca):
    from coletor_vtex import coletar_vtex
    coletar_vtex({...config...})
"""

import json
import os
import re
import sys
import time
from datetime import date

import requests

# Importa módulos do pacote scraper (funciona tanto de secoes/ quanto da raiz)
try:
    from ..ceps import CEPS as CEPS_LIST
    from ..gravar_precos_cep import gravar_precos_cep
except ImportError:
    # Fallback para execução direta de secoes/
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from ceps import CEPS as CEPS_LIST
    from gravar_precos_cep import gravar_precos_cep

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
RE_APRESENTACAO = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|un|unid|unidade)\b", re.IGNORECASE | re.VERBOSE
)


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


# ---------------------------------------------------------------------------
# Transformação VTEX -> Modelo
# ---------------------------------------------------------------------------
def extrair_ean(produto: dict) -> str | None:
    items = produto.get("items")
    if items:
        ean = items[0].get("ean")
        if ean_valido(ean):
            return str(ean).strip()
    for alt in produto.get("alternateIds") or []:
        if alt.get("type") == "EAN" and ean_valido(alt.get("value")):
            return str(alt["value"]).strip()
    return None


def extrair_preco(produto: dict) -> dict | None:
    items = produto.get("items")
    if not items:
        return None
    item = items[0]
    sellers = item.get("sellers") or []
    ofertas_validas = []
    for s in sellers:
        of = s.get("commertialOffer") or {}
        if "Price" not in of:
            continue
        preco = float(of.get("Price", 0) or 0)
        list_price = float(of.get("ListPrice", 0) or 0)
        disp = bool(of.get("IsAvailable", False))
        if preco <= 0:
            continue
        ofertas_validas.append({
            "preco_regular": round(list_price if list_price else preco, 2),
            "preco_promocional": round(preco, 2),
            "em_estoque": disp,
            "seller_default": s.get("sellerDefault", False),
        })
    if not ofertas_validas:
        return None
    ofertas_validas.sort(
        key=lambda x: (x["em_estoque"], x["seller_default"], x["preco_regular"]),
        reverse=True,
    )
    return ofertas_validas[0]


def transformar_produto(produto: dict, ean: str, secao: str, subsecao: str, hoje: str) -> dict:
    apresentacao = extrair_apresentacao(produto.get("productName", "")) or {}
    return {
        "gtin_ean": ean,
        "secao": secao,
        "subsecao": subsecao,
        "nome_completo": produto.get("productName", "").strip(),
        "marca": (produto.get("brand") or "Não Informada").strip(),
        "apresentacao": apresentacao,
        "imagem_url": (
            produto.get("image_front_url")
            or produto.get("image_url")
            or (produto.get("items") or [{}])[0].get("images", [{}])[0].get("imageUrl")
        ),
        "data_cadastro": hoje,
    }


def transformar_preco(ean: str, oferta: dict, nome_supermercado: str, hoje: str) -> dict:
    return {
        "gtin_ean": ean,
        "supermercado": nome_supermercado,
        "preco_regular": oferta["preco_regular"],
        "preco_promocional": oferta["preco_promocional"],
        "em_estoque": oferta["em_estoque"],
        "data_coleta": hoje,
    }


def transformar_preco_cep(ean: str, oferta: dict, nome_supermercado: str, hoje: str, cep: str) -> dict:
    """Transforma oferta de simulação VTEX para formato multi-CEP."""
    return {
        "gtin_ean": ean,
        "supermercado": nome_supermercado,
        "preco_regular": oferta["preco_regular"],
        "preco_promocional": oferta["preco_promocional"],
        "em_estoque": oferta["em_estoque"],
        "data_coleta": hoje,
        "cep_coleta": cep,
    }


def simular_vtex_cep(base_url: str, item_id: str, seller_id: str, cep: str, headers: dict, timeout: int) -> dict | None:
    """
    Chama a API de simulação VTEX para um CEP específico.

    Retorna dict com preco_regular, preco_promocional, em_estoque ou None se falhar.
    """
    url = f"{base_url}/api/checkout/pub/orderForms/simulation"
    payload = {
        "items": [{
            "id": item_id,
            "quantity": 1,
            "seller": seller_id,
        }],
        "postalCode": cep.replace("-", ""),
        "country": "BRA",
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return None

    # Extrai preço e disponibilidade da resposta
    items = data.get("items", [])
    if not items:
        return None

    item = items[0]
    price = item.get("price", 0)  # em centavos
    availability = item.get("availability", "withoutStock")

    # Também verifica purchaseConditions para preço final
    purchase_conditions = data.get("purchaseConditions", {})
    item_purchase_conditions = purchase_conditions.get("itemPurchaseConditions", [])
    final_price = price
    for pc in item_purchase_conditions:
        if pc.get("itemId") == item_id:
            final_price = pc.get("price", price)
            break

    if availability == "available" and final_price > 0:
        preco = round(final_price / 100.0, 2)
        return {
            "preco_regular": preco,
            "preco_promocional": preco,
            "em_estoque": True,
        }
    elif availability == "withoutStock":
        return {
            "preco_regular": None,
            "preco_promocional": None,
            "em_estoque": False,
        }

    return None


# ---------------------------------------------------------------------------
# Coleta paginada de uma folha
# ---------------------------------------------------------------------------
def buscar_pagina(cfg: dict, slug: str, offset: int, limite: int) -> list:
    params = {"_from": offset, "_to": offset + limite - 1}
    if cfg.get("filtro_fq"):
        params["fq"] = cfg["filtro_fq"]
    headers = {"User-Agent": cfg["user_agent"]}
    url = f"{cfg['base_url']}/api/catalog_system/pub/products/search/{slug}"
    resp = requests.get(url, params=params, headers=headers, timeout=cfg["timeout"])
    resp.raise_for_status()
    return resp.json()


def coletar_folha(cfg: dict, folha: dict) -> tuple[int, int, int]:
    """Coleta uma folha. Retorna (produtos_validos, duplicados, sem_ean)."""
    slug = folha["slug"]
    limite = cfg["limite_max"]
    offset = 0
    validos = duplicados = sem_ean = 0
    vistos = cfg["vistos_execucao"]
    multi_cep = cfg.get("multi_cep", False)
    headers = {"User-Agent": cfg["user_agent"]}

    while offset < limite:
        try:
            produtos = buscar_pagina(cfg, slug, offset, cfg["pagina_tamanho"])
        except requests.exceptions.RequestException as err:
            cfg["erros"].append((slug, offset, type(err).__name__, str(err)))
            if offset == 0:
                return validos, duplicados, sem_ean
            break

        if not produtos:
            break

        for prod in produtos:
            ean = extrair_ean(prod)
            if not ean:
                sem_ean += 1
                continue
            if ean in vistos:
                duplicados += 1
                continue
            vistos.add(ean)

            # Extrai itemId e sellerId para simulação multi-CEP
            items = prod.get("items")
            item_id = None
            seller_id = None
            if items:
                item_id = items[0].get("itemId")
                sellers = items[0].get("sellers") or []
                if sellers:
                    seller_id = sellers[0].get("sellerId")

            # Preço do catálogo (sempre coletado)
            oferta = extrair_preco(prod)
            if not oferta:
                sem_ean += 1
                continue

            hoje = cfg["hoje"]
            if ean not in cfg["produtos"]:
                cfg["produtos"][ean] = transformar_produto(
                    prod, ean, folha["secao"], folha["nome"], hoje
                )
            cfg["precos"][ean] = transformar_preco(ean, oferta, cfg["nome_supermercado"], hoje)
            validos += 1

            # Multi-CEP: simula preço para cada CEP
            if multi_cep and item_id and seller_id:
                precos_cep = []
                for cep_info in CEPS_LIST:
                    cep = cep_info["cep"]
                    sim = simular_vtex_cep(cfg["base_url"], item_id, seller_id, cep, headers, cfg["timeout"])
                    if sim and sim.get("em_estoque") and sim.get("preco_promocional"):
                        precos_cep.append(transformar_preco_cep(ean, sim, cfg["nome_supermercado"], hoje, cep))
                    elif sim and not sim.get("em_estoque"):
                        # Produto sem estoque neste CEP - registra como indisponível
                        precos_cep.append({
                            "gtin_ean": ean,
                            "supermercado": cfg["nome_supermercado"],
                            "preco_regular": None,
                            "preco_promocional": None,
                            "em_estoque": False,
                            "data_coleta": hoje,
                            "cep_coleta": cep,
                        })
                    else:
                        # Fallback: usa preço do catálogo
                        precos_cep.append(transformar_preco_cep(ean, oferta, cfg["nome_supermercado"], hoje, cep))

                if precos_cep:
                    gravar_precos_cep(precos_cep, cfg["chave_loja"])

        offset += cfg["pagina_tamanho"]
        time.sleep(cfg["sleep"])
        if offset >= limite:
            break

    return validos, duplicados, sem_ean


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def coletar_vtex(cfg: dict) -> None:
    hoje = date.today().isoformat()
    cfg.setdefault("hoje", hoje)
    cfg.setdefault("vistos_execucao", set())

    # Arquivos de checkpoint
    parcial_produtos = cfg["arquivo_produtos"] + ".parcial"
    parcial_precos = cfg["arquivo_precos"] + ".parcial"
    arquivo_progresso = cfg["arquivo_precos"] + ".progresso.json"

    # Carrega estado anterior (retomada)
    cfg["produtos"] = carregar_por_ean(parcial_produtos)
    cfg["precos"] = carregar_por_ean(parcial_precos)
    cfg["erros"] = []
    feitas = set(carregar_lista(arquivo_progresso))
    em_retomada = bool(feitas or cfg["produtos"] or cfg["precos"])
    cfg["vistos_execucao"] |= set(cfg["produtos"].keys()) | set(cfg["precos"].keys())

    # Só numa execução limpa (sem retomada) o cadastro antigo desta loja é
    # removido para recálculo. Em retomada, preserva o já coletado.
    if not em_retomada:
        marcador = cfg["marcador_imagem"]
        if marcador:
            antes = set(cfg["produtos"].keys())
            cfg["produtos"] = {
                ean: p for ean, p in cfg["produtos"].items()
                if marcador not in (p.get("imagem_url") or "")
            }
            removidos = antes - set(cfg["produtos"].keys())
            cfg["vistos_execucao"] -= removidos
            cfg["precos"] = {ean: p for ean, p in cfg["precos"].items() if ean not in removidos}

    folhas = cfg["folhas"]
    pendentes = [f for f in folhas if f["slug"] not in feitas]
    print(f"=== Coletor {cfg['nome_supermercado']} (VTEX ampliado) ===")
    print(f"Folhas alvo: {len(folhas)} | já concluídas: {len(feitas)} | pendentes: {len(pendentes)}")
    print(f"Catálogo em retomada: {len(cfg['produtos'])} produtos | {len(cfg['precos'])} preços")
    print("-" * 72)

    total_validos = total_duplicados = total_sem_ean = 0
    n_concluidas = 0

    for i, folha in enumerate(pendentes, 1):
        validos, duplicados, sem_ean = coletar_folha(cfg, folha)
        total_validos += validos
        total_duplicados += duplicados
        total_sem_ean += sem_ean
        feitas.add(folha["slug"])
        n_concluidas += 1

        if n_concluidas % cfg["checkpoint_a_cada"] == 0 or n_concluidas == len(pendentes):
            salvar_json(parcial_produtos, list(cfg["produtos"].values()))
            salvar_json(parcial_precos, list(cfg["precos"].values()))
            salvar_json(arquivo_progresso, sorted(feitas))
            print(f"  [checkpoint {n_concluidas}/{len(pendentes)}] "
                  f"folha: {folha['slug'][:60]} | produtos: {len(cfg['produtos']):,} | "
                  f"preços: {len(cfg['precos']):,}")

    # Salva finais (remove parciais)
    salvar_json(cfg["arquivo_produtos"], list(cfg["produtos"].values()))
    salvar_json(cfg["arquivo_precos"], list(cfg["precos"].values()))
    for p in (parcial_produtos, parcial_precos, arquivo_progresso):
        if os.path.exists(p):
            os.remove(p)

    print("-" * 72)
    print(f"Folhas concluídas: {n_concluidas}")
    print(f"Produtos válidos (EAN+preço): {total_validos:,} | duplicados: {total_duplicados:,} | sem EAN/preço: {total_sem_ean:,}")
    print(f"Catálogo total: {len(cfg['produtos']):,} | preços {cfg['nome_supermercado']}: {len(cfg['precos']):,}")
    if cfg["erros"]:
        print(f"Erros de requisição: {len(cfg['erros'])} (primeiros 5):")
        for e in cfg["erros"][:5]:
            print("   ", e)
    print("Arquivos:")
    print(f"  {cfg['arquivo_produtos']}")
    print(f"  {cfg['arquivo_precos']}")
    print("-" * 72)
