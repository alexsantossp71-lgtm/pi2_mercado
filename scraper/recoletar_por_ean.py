# -*- coding: utf-8 -*-
"""
Recoleta pontual de preço/estoque por GTIN/EAN para Atacadão, Carrefour e
Pão de Açúcar, com fallback de CEP (Santos 11060-002 → São Paulo
01310-100 → Campinas 13010-000 → Ribeirão Preto 14010-000).

Para cada EAN informado, grava SEMPRE um registro por loja nos arquivos da
raiz do projeto (dedup por gtin_ean + sobrescreve), mesmo quando o produto
está indisponível (preco_regular: null, preco_promocional: null,
em_estoque: false).

Arquivos gravados:
  - precos_atacadao_ampliado.json
  - precos_carrefour_ampliado.json
  - precos_pao_de_acucar_ampliado.json

Uso:
    python recoletar_por_ean.py 7896006751113 [mais EANs...]
"""

import json
import os
import random
import shutil
import sys
import time

import requests

try:
    from .ceps import CEPA_PADRAO, ceps_strings
except ImportError:
    from ceps import CEPA_PADRAO, ceps_strings

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
HOJE = "2026-08-23"
TIMEOUT = 20
SLEEP = 1.0

# CEPS agora vem do módulo centralizado ceps.py (lista de strings para compatibilidade)
CEPS = ceps_strings()
CEPA_PADRAO_CEP = CEPA_PADRAO["cep"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARQUIVOS = {
    "atacadao": os.path.join(RAIZ, "precos_atacadao_ampliado.json"),
    "carrefour": os.path.join(RAIZ, "precos_carrefour_ampliado.json"),
    "pao_de_acucar": os.path.join(RAIZ, "precos_pao_de_acucar_ampliado.json"),
}

NOME_SUPERMERCADO = {
    "atacadao": "Atacadão",
    "carrefour": "Carrefour",
    "pao_de_acucar": "Pão de Açúcar",
}

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def ean_valido(ean) -> bool:
    if not ean:
        return False
    ean = str(ean).strip()
    return ean.isdigit() and len(ean) == 13


def carregar_por_ean(caminho: str) -> dict:
    """Carrega JSON existente e retorna {gtin_ean: registro}."""
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


def salvar_json(caminho: str, dados: list) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


def backup_antes(caminho: str) -> None:
    """Cria backup .bak antes da primeira escrita em cada arquivo."""
    if not os.path.exists(caminho):
        return
    bak = caminho + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(caminho, bak)


def gravar_registro(chave_loja: str, ean: str, registro: dict) -> None:
    """Lê -> atualiza/insere (dedup por gtin_ean) -> salva. Cria .bak na 1ª escrita."""
    caminho = ARQUIVOS[chave_loja]
    backup_antes(caminho)
    dados = carregar_por_ean(caminho)
    dados[ean] = registro
    salvar_json(caminho, list(dados.values()))


# ---------------------------------------------------------------------------
# VTEX (Atacadão e Carrefour)
# ---------------------------------------------------------------------------
def buscar_produto_vtex(base_url: str, ean: str) -> dict | None:
    """GET /api/catalog_system/pub/products/search?fq=alternateIds_Ean:{ean}.

    Retorna o primeiro item (itemId, sellerId, ean) ou None se vazio.
    """
    url = f"{base_url}/api/catalog_system/pub/products/search"
    params = {"fq": f"alternateIds_Ean:{ean}"}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    dados = resp.json()
    if not isinstance(dados, list) or not dados:
        return None
    item = (dados[0].get("items") or [{}])[0]
    sellers = item.get("sellers") or []
    if not item.get("itemId") or not sellers:
        return None
    return {
        "itemId": item["itemId"],
        "sellerId": sellers[0].get("sellerId"),
        "ean": item.get("ean"),
    }


def simular_vtex(base_url: str, item: dict, cep: str) -> dict | None:
    """POST /api/checkout/pub/orderForms/simulation.

    Retorna dict com availability, price (centavos) e friendlyName da loja,
    ou None se a resposta não tiver items.
    """
    url = f"{base_url}/api/checkout/pub/orderForms/simulation"
    payload = {
        "items": [{
            "id": item["itemId"],
            "quantity": 1,
            "seller": item["sellerId"],
        }],
        "country": "BRA",
        "postalCode": cep,
    }
    resp = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    dados = resp.json()
    items = dados.get("items") or []
    if not items:
        return None
    it = items[0]
    availability = it.get("availability")
    price = it.get("price")
    friendly_name = None
    try:
        pcs = dados.get("purchaseConditions") or {}
        ipc = (pcs.get("itemPurchaseConditions") or [{}])[0]
        slas = ipc.get("slas") or []
        if slas:
            friendly_name = slas[0].get("pickupStoreInfo", {}).get("friendlyName")
    except (AttributeError, IndexError, TypeError):
        friendly_name = None
    return {
        "availability": availability,
        "price": price,
        "friendlyName": friendly_name,
    }


def coletar_vtex(chave_loja: str, base_url: str, ean: str) -> dict:
    """Coleta preço/estoque de uma loja VTEX com fallback de CEP."""
    try:
        item = buscar_produto_vtex(base_url, ean)
    except requests.exceptions.RequestException as err:
        return registro_indisponivel(
            chave_loja, ean, f"erro_catalogo:{type(err).__name__}"
        )
    if not item:
        return registro_indisponivel(chave_loja, ean, "nao_cadastrado")

    for cep in CEPS:
        try:
            sim = simular_vtex(base_url, item, cep)
        except requests.exceptions.RequestException:
            continue
        if not sim:
            continue
        availability = sim.get("availability")
        price = sim.get("price")
        if availability == "available" and price and price > 0:
            return {
                "gtin_ean": ean,
                "supermercado": NOME_SUPERMERCADO[chave_loja],
                "preco_regular": round(float(price) / 100.0, 2),
                "preco_promocional": round(float(price) / 100.0, 2),
                "em_estoque": True,
                "data_coleta": HOJE,
                "cep_coleta": cep,
                "loja_coleta": sim.get("friendlyName"),
            }
        if availability == "withoutStock":
            return registro_indisponivel(
                chave_loja, ean, "sem_estoque", cep=cep
            )
    # Nenhum CEP respondeu com disponibilidade -> indisponível
    return registro_indisponivel(chave_loja, ean, "sem_resposta_simulacao")


# ---------------------------------------------------------------------------
# Carrefour - Estratégia anti-bloqueio
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

def _make_session() -> requests.Session:
    """Cria sessão com cookies da home page."""
    s = requests.Session()
    ua = random.choice(USER_AGENTS)
    s.headers.update({
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": "https://www.carrefour.com.br/",
    })
    # Warm-up: acessa home para pegar cookies
    try:
        s.get("https://www.carrefour.com.br", timeout=TIMEOUT)
        time.sleep(1)
    except requests.exceptions.RequestException:
        pass
    return s


def _buscar_produto_vtex_session(session: requests.Session, base_url: str, ean: str) -> dict | None:
    """Busca produto via API VTEX usando sessão."""
    url = f"{base_url}/api/catalog_system/pub/products/search"
    params = {"fq": f"alternateIds_Ean:{ean}"}
    resp = session.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    dados = resp.json()
    if not isinstance(dados, list) or not dados:
        return None
    item = (dados[0].get("items") or [{}])[0]
    sellers = item.get("sellers") or []
    if not item.get("itemId") or not sellers:
        return None
    return {
        "itemId": item["itemId"],
        "sellerId": sellers[0].get("sellerId"),
        "ean": item.get("ean"),
    }


def _simular_vtex_session(session: requests.Session, base_url: str, item: dict, cep: str) -> dict | None:
    """Simula checkout via API VTEX usando sessão."""
    url = f"{base_url}/api/checkout/pub/orderForms/simulation"
    payload = {
        "items": [{"id": item["itemId"], "quantity": 1, "seller": item["sellerId"]}],
        "country": "BRA",
        "postalCode": cep,
    }
    resp = session.post(url, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    dados = resp.json()
    items = dados.get("items") or []
    if not items:
        return None
    it = items[0]
    availability = it.get("availability")
    price = it.get("price")
    friendly_name = None
    try:
        pcs = dados.get("purchaseConditions") or {}
        ipc = (pcs.get("itemPurchaseConditions") or [{}])[0]
        slas = ipc.get("slas") or []
        if slas:
            friendly_name = slas[0].get("pickupStoreInfo", {}).get("friendlyName")
    except (AttributeError, IndexError, TypeError):
        friendly_name = None
    return {"availability": availability, "price": price, "friendlyName": friendly_name}


def _parse_search_page(html: str, ean: str) -> dict | None:
    """Tenta extrair preço da página de busca HTML (fallback)."""
    import re
    # Procura JSON-LD com Product
    json_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    for js in json_matches:
        try:
            data = json.loads(js.strip())
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "Product":
                        offers = item.get("offers", {})
                        price = offers.get("price")
                        if price:
                            return {"price": float(price), "availability": "available"}
            elif isinstance(data, dict) and data.get("@type") == "Product":
                offers = data.get("offers", {})
                price = offers.get("price")
                if price:
                    return {"price": float(price), "availability": "available"}
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def coletar_carrefour(ean: str) -> dict:
    """Carrefour com sessão persistente, rotação de UA, delays maiores, fallback HTML e Playwright."""
    # Kill-switch (lido em tempo de chamada): só pula o Playwright (etapa 2),
    # mantendo VTEX/HTML (etapa 1) — senão o Carrefour ficaria 100% indisponível.
    base = "https://www.carrefour.com.br"
    alternativo = "https://mercado.carrefour.com.br"
    
    # 1. Tenta API VTEX com sessão (rápido)
    for host in (base, alternativo):
        for tentativa in range(1, 3):  # Reduzido para 2 tentativas
            session = _make_session()
            try:
                item = _buscar_produto_vtex_session(session, host, ean)
                if item:
                    for cep in CEPS:
                        sim = _simular_vtex_session(session, host, item, cep)
                        if sim and sim.get("availability") == "available" and sim.get("price", 0) > 0:
                            return {
                                "gtin_ean": ean,
                                "supermercado": NOME_SUPERMERCADO["carrefour"],
                                "preco_regular": round(float(sim["price"]) / 100.0, 2),
                                "preco_promocional": round(float(sim["price"]) / 100.0, 2),
                                "em_estoque": True,
                                "data_coleta": HOJE,
                                "cep_coleta": cep,
                                "loja_coleta": sim.get("friendlyName"),
                            }
                        if sim and sim.get("availability") == "withoutStock":
                            return registro_indisponivel("carrefour", ean, "sem_estoque", cep=cep)
                
                # Fallback HTML
                search_url = f"{host}/busca/{ean}"
                resp = session.get(search_url, timeout=TIMEOUT)
                if resp.status_code == 200:
                    parsed = _parse_search_page(resp.text, ean)
                    if parsed and parsed.get("price"):
                        return {
                            "gtin_ean": ean,
                            "supermercado": NOME_SUPERMERCADO["carrefour"],
                            "preco_regular": round(parsed["price"], 2),
                            "preco_promocional": round(parsed["price"], 2),
                            "em_estoque": True,
                            "data_coleta": HOJE,
                            "cep_coleta": "html_fallback",
                            "loja_coleta": "Carrefour - Busca Web",
                        }
                
            except requests.exceptions.RequestException:
                if tentativa < 2:
                    time.sleep(3 * tentativa)
                continue
            except Exception:
                if tentativa < 2:
                    time.sleep(3 * tentativa)
                continue
        time.sleep(5)
    
    # 2. Fallback Playwright (mais lento mas resolve Cloudflare)
    # Respeita o kill-switch: se definido, pula o browser e vai direto ao indisponível.
    if os.environ.get("DISABLE_CARREFOUR_PLAYWRIGHT"):
        print("[carrefour] Playwright desativado via DISABLE_CARREFOUR_PLAYWRIGHT; "
              "usando apenas VTEX/HTML")
    else:
        print("  Carrefour: tentando Playwright...")
        try:
            result = _coletar_carrefour_playwright(ean)
            if result:
                return result
        except Exception as err:
            print(f"  Playwright falhou: {err}")

    return registro_indisponivel("carrefour", ean, "catalogo_bloqueado")


def _coletar_carrefour_playwright(ean: str) -> dict:
    """Coleta preço Carrefour usando Playwright com stealth (resolve Cloudflare)."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    
    ua = random.choice(USER_AGENTS)
    search_url = f"https://www.carrefour.com.br/busca/{ean}"
    
    stealth = Stealth()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=ua,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        page = context.new_page()
        stealth.apply_stealth_sync(page)  # Aplica stealth na página
        
        try:
            # Navega para a página de busca
            page.goto(search_url, wait_until="networkidle", timeout=30000)
            
            # Aguarda possível challenge Cloudflare
            page.wait_for_timeout(3000)
            
            # Verifica se ainda está no challenge
            content = page.content()
            if "challenge" in content.lower() or "cloudflare" in content.lower():
                # Aguarda mais tempo para resolver
                page.wait_for_timeout(15000)
                content = page.content()
            
            # Tenta extrair JSON-LD
            parsed = _parse_search_page(content, ean)
            if parsed and parsed.get("price"):
                return {
                    "gtin_ean": ean,
                    "supermercado": NOME_SUPERMERCADO["carrefour"],
                    "preco_regular": round(parsed["price"], 2),
                    "preco_promocional": round(parsed["price"], 2),
                    "em_estoque": True,
                    "data_coleta": HOJE,
                    "cep_coleta": "playwright_html",
                    "loja_coleta": "Carrefour - Playwright",
                }
            
            # Tenta buscar seletores de preço na página
            price_selectors = [
                '[data-testid="price"]',
                '.price__value',
                '.product-price',
                '[itemprop="price"]',
                '.price',
            ]
            for selector in price_selectors:
                try:
                    element = page.query_selector(selector)
                    if element:
                        text = element.inner_text()
                        # Extrai número do texto (ex: "R$ 12,99")
                        import re
                        match = re.search(r'[\d.,]+', text.replace('.', '').replace(',', '.'))
                        if match:
                            price = float(match.group())
                            return {
                                "gtin_ean": ean,
                                "supermercado": NOME_SUPERMERCADO["carrefour"],
                                "preco_regular": round(price, 2),
                                "preco_promocional": round(price, 2),
                                "em_estoque": True,
                                "data_coleta": HOJE,
                                "cep_coleta": "playwright_selector",
                                "loja_coleta": "Carrefour - Playwright",
                            }
                except Exception:
                    continue
            
        except Exception as err:
            print(f"  Playwright error: {err}")
        finally:
            browser.close()
    
    return None


# ---------------------------------------------------------------------------
# Pão de Açúcar
# ---------------------------------------------------------------------------
def coletar_pa(ean: str) -> dict:
    """Tenta VTEX do PA; se falhar/vazio, usa fallback do arquivo atual."""
    base = "https://www.paodeacucar.com"
    try:
        item = buscar_produto_vtex(base, ean)
    except requests.exceptions.RequestException:
        item = None
    if item:
        for cep in CEPS:
            try:
                sim = simular_vtex(base, item, cep)
            except requests.exceptions.RequestException:
                continue
            if not sim:
                continue
            availability = sim.get("availability")
            price = sim.get("price")
            if availability == "available" and price and price > 0:
                return {
                    "gtin_ean": ean,
                    "supermercado": NOME_SUPERMERCADO["pao_de_acucar"],
                    "preco_regular": round(float(price) / 100.0, 2),
                    "preco_promocional": round(float(price) / 100.0, 2),
                    "em_estoque": True,
                    "data_coleta": HOJE,
                    "cep_coleta": cep,
                    "loja_coleta": sim.get("friendlyName"),
                }
            if availability == "withoutStock":
                return registro_indisponivel(
                    "pao_de_acucar", ean, "sem_estoque", cep=cep
                )
    # FALLBACK PA: usa registro atual do arquivo se em_estoque; senão indisponível
    caminho = ARQUIVOS["pao_de_acucar"]
    atual = carregar_por_ean(caminho).get(ean)
    if atual and atual.get("em_estoque"):
        atual["data_coleta"] = HOJE
        return atual
    return registro_indisponivel("pao_de_acucar", ean, "pa_sem_busca_por_ean")


# ---------------------------------------------------------------------------
# Registro indisponível
# ---------------------------------------------------------------------------
def registro_indisponivel(chave_loja: str, ean: str, observacao: str,
                          cep: str | None = None) -> dict:
    reg = {
        "gtin_ean": ean,
        "supermercado": NOME_SUPERMERCADO[chave_loja],
        "preco_regular": None,
        "preco_promocional": None,
        "em_estoque": False,
        "data_coleta": HOJE,
    }
    if cep:
        reg["cep_coleta"] = cep
    reg["observacao"] = observacao
    return reg


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def coletar_loja(chave_loja: str, ean: str) -> dict:
    if chave_loja == "atacadao":
        return coletar_vtex("atacadao", "https://www.atacadao.com.br", ean)
    if chave_loja == "carrefour":
        return coletar_carrefour(ean)
    if chave_loja == "pao_de_acucar":
        return coletar_pa(ean)
    raise ValueError(f"loja desconhecida: {chave_loja}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python recoletar_por_ean.py 7896006751113 [mais EANs...]")
        sys.exit(1)

    eans = [a.strip() for a in sys.argv[1:]]
    invalidos = [e for e in eans if not ean_valido(e)]
    if invalidos:
        print(f"EANs inválidos (ignorados): {invalidos}")
    eans = [e for e in eans if ean_valido(e)]
    if not eans:
        print("Nenhum EAN-13 válido informado.")
        sys.exit(1)

    print("=== Recoleta por EAN ===")
    print(f"Data: {HOJE} | EANs: {', '.join(eans)}")
    print("-" * 72)

    for ean in eans:
        print(f"\n[EAN {ean}]")
        for chave in ("atacadao", "carrefour", "pao_de_acucar"):
            try:
                reg = coletar_loja(chave, ean)
            except requests.exceptions.RequestException as err:
                reg = registro_indisponivel(
                    chave, ean, f"erro:{type(err).__name__}"
                )
            gravar_registro(chave, ean, reg)
            preco = reg.get("preco_regular")
            preco_txt = f"R$ {preco:.2f}" if preco is not None else "indisponível"
            obs = reg.get("observacao") or ""
            print(f"  {NOME_SUPERMERCADO[chave]:<14} -> {preco_txt} "
                  f"| estoque: {reg.get('em_estoque')} {obs}")
            time.sleep(SLEEP)

    print("-" * 72)
    print("Concluído. Arquivos atualizados:")
    for chave, caminho in ARQUIVOS.items():
        print(f"  {NOME_SUPERMERCADO[chave]:<14} {caminho}")


if __name__ == "__main__":
    main()