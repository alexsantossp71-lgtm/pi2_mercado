#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 Soudaki (Daki) — Coletor v2.0 com paginação profunda
=====================================================================
Extrai TODOS os produtos/preços de https://soudaki.com/shop/<secao>/

Estratégia em 3 camadas (tenta na ordem):
  1. __NEXT_DATA__ do HTML inicial  -> lote pré-carregado (como o v1)
  2. Rotas de dados do Next.js      -> /_next/data/<buildId>/...json
                                       (pega as páginas do infinite scroll)
  3. Fallback HTML SSR              -> /shop/<secao>/?page=N

VERIFICADO EM CAMPO (out/2026): a rolagem infinita do site já vem
COMPLETA no lote pré-carregado do __NEXT_DATA__ — não há paginação
de servidor. Use --sem-paginacao para pular a descoberta (economiza
~20s de testes 404 por seção).

IMPORTANTE: roda de IP brasileiro (a Cloudflare entrega a loja apenas
para tráfego BR; fora do Brasil o /shop/ responde 404 de Webflow).

Uso:
  python scrap_soudaki.py --probe --secao laticinios # diagnóstico da página
  python scrap_soudaki.py                           # coleta 1 seção teste
  python scrap_soudaki.py --secao laticinios
  python scrap_soudaki.py --secao all               # todas as 25 seções
  python scrap_soudaki.py --secao all --sem-paginacao  # rolagem infinita = lote completo
  python scrap_soudaki.py --secao laticinios --db   # coleta + grava no Neon
  python scrap_soudaki.py --integrar                # só integra JSONs -> Neon

Saída (pasta output/):
  produtos_soudaki_full.json   catálogo dedup por SKU
  precos_soudaki_full.json     preços/estoque do dia
  checkpoint_<secao>.json      retomada e padrão de paginação descoberto
=====================================================================
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("[ERRO] Falta o requests. Rode: pip install requests")

# ---------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------
BASE = "https://soudaki.com"
OUT = Path(__file__).resolve().parent / "output"
HOJE = date.today().isoformat()
LOJA_ID = 4  # Soudaki na tabela precos do Neon

SECOES = [
    "hortifruti", "bebidas", "laticinios", "padaria", "matinais", "saudaveis",
    "mercearia", "molhos-e-conservas", "acougue-e-peixaria", "churrasco",
    "congelados", "pratico-e-rapido", "biscoitos-e-salgadinhos",
    "chocolates-e-doces", "sorvetes-e-acai", "cervejas-e-drinks",
    "vinhos-e-espumantes", "destilados", "limpeza", "higiene-e-beleza",
    "utilidades", "pets", "bebe", "produtos-daki", "farmacia",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://soudaki.com/shop/",
}

RE_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
RE_EAN_IMAGEM = re.compile(r"BR_(\d{13})")
RE_APRESENTACAO = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|un|unid|unidade|cx)\b", re.IGNORECASE
)
RE_LINK_SUB = re.compile(r'href="(/shop/([a-z0-9\-]+)/([a-z0-9\-]+)/?)"')

MAX_PAGES_PADRAO = 60          # trava de segurança por seção
SLEEP_BASE = 0.8               # segundos entre requests (+ jitter)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------
# Sessão HTTP (com fallback para cloudscraper, se instalado)
# ---------------------------------------------------------------------
def criar_sessao():
    try:
        import cloudscraper  # type: ignore
        sess = cloudscraper.create_scraper()
        log("[sessão] cloudscraper ativo (bypass Cloudflare)")
        return sess
    except ImportError:
        sess = requests.Session()
        sess.headers.update({"User-Agent": random.choice(USER_AGENTS), **HEADERS})
        return sess


def _sleep() -> None:
    time.sleep(SLEEP_BASE + random.uniform(0, SLEEP_BASE * 0.6))


def baixar(sess, url: str, tentativas: int = 3):
    """GET com retry/backoff. Retorna Response ou None."""
    for t in range(tentativas):
        try:
            sess.headers["User-Agent"] = random.choice(USER_AGENTS)
            r = sess.get(url, timeout=30)
            if r.status_code == 200:
                return r
            if t < tentativas - 1:
                time.sleep(2 * (t + 1))
                continue
            log(f"  [HTTP {r.status_code}] {url}")
            return None
        except requests.RequestException as e:
            log(f"  [rede] {type(e).__name__} em {url} (tentativa {t + 1})")
            time.sleep(2 * (t + 1))
    return None


# ---------------------------------------------------------------------
# Parsing do __NEXT_DATA__ (resiliente a renomeação de chaves)
# ---------------------------------------------------------------------
def extrair_next_data(html: str):
    m = RE_NEXT_DATA.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parece_produto(d) -> bool:
    """Heurística: item de catálogo tem nome + preço ou sku."""
    if not isinstance(d, dict):
        return False
    tem_nome = bool(d.get("name") or d.get("nome"))
    tem_preco = isinstance(d.get("price"), (dict, float, int)) or bool(d.get("sku"))
    return tem_nome and tem_preco


def varrer_listas_de_produtos(obj, achados=None, _profundidade=0):
    """Caminha pela estrutura e devolve listas que contêm produtos,
    qualquer que seja a chave (preloadedProducts, products, items...)."""
    if achados is None:
        achados = []
    if _profundidade > 8 or not isinstance(obj, (dict, list)):
        return achados
    if isinstance(obj, list):
        if obj and all(parece_produto(p) for p in obj[:3]):
            achados.append(obj)
        else:
            for p in obj:
                varrer_listas_de_produtos(p, achados, _profundidade + 1)
    else:
        for v in obj.values():
            varrer_listas_de_produtos(v, achados, _profundidade + 1)
    return achados


def normalizar_item(raw: dict, secao_default: str):
    """Converte o item cru do Daki no schema do projeto."""
    nome = (raw.get("name") or raw.get("nome") or "").strip()
    if not nome:
        return None

    preco = raw.get("price")
    if isinstance(preco, dict):
        preco = preco.get("amount")
    try:
        preco = float(preco) if preco is not None else None
    except (TypeError, ValueError):
        preco = None
    if preco is None or preco <= 0:
        return None

    img = None
    pk = raw.get("packshot1_front_grid")
    if isinstance(pk, dict):
        img = pk.get("url")
    elif raw.get("imagem_url"):
        img = raw.get("imagem_url")

    m_ean = RE_EAN_IMAGEM.search(img or "")
    ean = m_ean.group(1) if m_ean else raw.get("gtin_ean")

    inv = raw.get("inventory")
    qty = inv.get("quantity", 0) if isinstance(inv, dict) else 0
    em_estoque = bool(qty and qty > 0)

    cat_obj = raw.get("category")
    if isinstance(cat_obj, dict) and cat_obj.get("categoryName"):
        cat = cat_obj["categoryName"]
    else:
        cat = secao_default.capitalize()

    # marca: primeira palavra alfabética do nome (mesma heurística do v1)
    partes = [p for p in re.split(r"\s+", nome) if p]
    marca = "Nao Informada"
    if partes:
        p0 = partes[0].strip("*")
        if p0 and p0[0].isalpha():
            marca = p0

    m_apre = RE_APRESENTACAO.search(nome)
    apresentacao = None
    if m_apre:
        qtd = m_apre.group(1).replace(",", ".")
        un = m_apre.group(2).lower()
        un = "un" if un in ("unid", "unidade") else un
        apresentacao = f"{qtd}{un}"

    sku = raw.get("sku") or f"{nome}|{preco:.2f}"

    return {
        "sku": sku,
        "gtin_ean": ean,
        "nome": nome,
        "marca": marca,
        "categoria": cat,
        "subcategoria": raw.get("_subcategoria"),
        "apresentacao": apresentacao,
        "preco": preco,
        "em_estoque": em_estoque,
        "imagem_url": img,
        "secao": secao_default,
    }


def colher_produtos(next_data, secao_default: str):
    """Extrai todos os produtos de um payload __NEXT_DATA__/rota de dados."""
    if not isinstance(next_data, dict):
        return []
    pp = next_data.get("props", {}).get("pageProps", {})
    itens = []
    for lista in varrer_listas_de_produtos(pp):
        for raw in lista:
            norm = normalizar_item(raw, secao_default)
            if norm:
                itens.append(norm)
    return itens


# ---------------------------------------------------------------------
# Descoberta de paginação (rotas /_next/data/<buildId>/...)
# ---------------------------------------------------------------------
def padroes_data_route(build_id: str, secao: str, subcats):
    b, s = build_id, secao
    sem_sub = [
        f"/_next/data/{b}/shop/{s}.json?secao={s}&page={{p}}",
        f"/_next/data/{b}/shop/{s}.json?page={{p}}",
        f"/_next/data/{b}/shop/{s}.json?slug={s}&page={{p}}",
        f"/_next/data/{b}/pt-BR/shop/{s}.json?page={{p}}",
        f"/_next/data/{b}/pt/shop/{s}.json?page={{p}}",
    ]
    com_sub = []
    for sub in list(subcats)[:5]:  # testa também rotas por subcategoria
        com_sub.append(f"/_next/data/{b}/shop/{s}/{sub}.json?page={{p}}")
        com_sub.append(f"/_next/data/{b}/shop/{s}/{sub}.json?secao={s}&page={{p}}")
    return sem_sub + com_sub


def testar_padrao(sess, template: str, skus_pagina1):
    """Página 2 de teste: sucesso se retorna produtos novos."""
    url = BASE + template.format(p=2)
    r = baixar(sess, url, tentativas=2)
    if r is None:
        return None
    try:
        if "application/json" in (r.headers.get("content-type") or ""):
            payload = r.json()
        else:
            payload = extrair_next_data(r.text)
            if payload is None:
                return None
    except ValueError:
        return None
    itens = colher_produtos(payload, "")
    if not itens:
        return None
    novos = {i["sku"] for i in itens} - skus_pagina1
    if not novos:
        return "sem-novos"  # rota existe mas ignora paginação
    return template


def descobrir_paginacao(sess, build_id, secao, subcats, skus_pagina1):
    if not build_id:
        log("[paginação] sem buildId — só lote pré-carregado")
        return None
    log(f"[paginação] testando padrões /_next/data/ (buildId={build_id[:12]}...)")
    for tpl in padroes_data_route(build_id, secao, subcats):
        res = testar_padrao(sess, tpl, skus_pagina1)
        _sleep()
        if res == "sem-novos":
            log(f"[paginação] responde mas não pagina: {tpl}")
        elif res:
            log(f"[paginação] ✔ PADRÃO FUNCIONANDO: {res}")
            return res
    # Fallback: SSR por querystring no HTML
    log("[paginação] testando fallback HTML ?page=2 ...")
    r = baixar(sess, f"{BASE}/shop/{secao}/?page=2", tentativas=2)
    if r is not None:
        itens = colher_produtos(extrair_next_data(r.text), secao)
        if itens and ({i["sku"] for i in itens} - skus_pagina1):
            log("[paginação] ✔ fallback HTML ?page=N funciona")
            return "HTML_PAGE"
    log("[paginação] nenhum padrão paginado — mantém lote pré-carregado")
    return None


def paginar(sess, template, secao, subcats, skus_vistos, max_pages):
    """Coleta páginas 2..N do padrão descoberto."""
    extras = []
    if template == "HTML_PAGE":
        for p in range(2, max_pages + 1):
            r = baixar(sess, f"{BASE}/shop/{secao}/?page={p}")
            if r is None:
                break
            itens = colher_produtos(extrair_next_data(r.text), secao)
            novos = [i for i in itens if i["sku"] not in skus_vistos]
            if not novos:
                log(f"[página {p}] sem produtos novos — fim")
                break
            for i in novos:
                skus_vistos.add(i["sku"])
            extras.extend(novos)
            log(f"[página {p}] +{len(novos)} novos (total extra: {len(extras)})")
            _sleep()
        return extras

    rotas = [("seção", template)]
    for sub in list(subcats)[:5]:
        if "/" + sub + ".json" in template:
            continue  # o template já é de subcategoria
        rotas.append((sub, template.replace(
            f"/shop/{secao}.json", f"/shop/{secao}/{sub}.json")))
    for rotulo, tpl in rotas:
        for p in range(2, max_pages + 1):
            r = baixar(sess, BASE + tpl.format(p=p))
            if r is None:
                break
            try:
                payload = r.json() if "json" in (r.headers.get("content-type") or "") \
                    else extrair_next_data(r.text)
            except ValueError:
                break
            itens = colher_produtos(payload, secao)
            novos = [i for i in itens if i["sku"] not in skus_vistos]
            if not novos:
                break
            for i in novos:
                skus_vistos.add(i["sku"])
            extras.extend(novos)
            log(f"[página {p} rot={rotulo}] +{len(novos)} novos (extra: {len(extras)})")
            _sleep()
    return extras


# ---------------------------------------------------------------------
# Coleta de uma seção
# ---------------------------------------------------------------------
def coletar_secao(sess, secao: str, max_pages: int, probe: bool,
                  sem_paginacao: bool = False):
    url = f"{BASE}/shop/{secao}/"
    log(f"== Seção /shop/{secao}/ ==")
    r = baixar(sess, url)
    if r is None:
        log("  [FALHA] página inacessível (403/404). Veja README: bloqueio Cloudflare.")
        return []

    nd = extrair_next_data(r.text)
    build_id = (nd or {}).get("buildId")
    log(f"  buildId: {build_id}")

    # subcategorias: primeiro pelos links do HTML...
    subcats = sorted({m.group(3) for m in RE_LINK_SUB.finditer(r.text or "")
                      if m.group(2) == secao})

    # ...depois pelas chaves de preloadedProducts (v1: dict subcat -> lista),
    # que são os slugs internos que o site usa nas rotas de dados
    pp_raw = (nd or {}).get("props", {}).get("pageProps", {}).get("preloadedProducts")
    if isinstance(pp_raw, dict):
        for k in pp_raw.keys():
            k = str(k).strip()
            if k and k not in subcats and re.fullmatch(r"[a-z0-9\-]+", k):
                subcats.append(k)
    if subcats:
        preview = ", ".join(subcats[:8])
        log(f"  subcategorias candidatas ({len(subcats)}): {preview}...")

    itens = colher_produtos(nd, secao)
    skus_p1 = {i["sku"] for i in itens}
    log(f"  lote pré-carregado: {len(itens)} registros ({len(skus_p1)} SKUs únicos)")

    if probe:
        pp = (nd or {}).get("props", {}).get("pageProps", {})
        print("\n  ---------- PROBE ----------")
        print(f"  buildId: {build_id}")
        print(f"  chaves de pageProps: {list(pp.keys())[:20]}")
        print(f"  subcategorias nos links: {subcats}")
        print(f"  SKUs pré-carregados: {len(skus_p1)}")
        print("  ---------------------------\n")
        return itens

    if sem_paginacao:
        log("  [paginação] pulada (--sem-paginacao): lote pré-carregado já é "
            "o catálogo completo da seção")
        padrao = None
    else:
        padrao = descobrir_paginacao(sess, build_id, secao, subcats, skus_p1)
    extras = []
    if padrao:
        extras = paginar(sess, padrao, secao, subcats, skus_p1, max_pages)

    todos = itens + extras
    OUT.mkdir(exist_ok=True)
    ckpt = {"secao": secao, "build_id": build_id, "padrao": padrao,
            "subcats": subcats, "quando": HOJE, "total": len(todos)}
    (OUT / f"checkpoint_{secao}.json").write_text(
        json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  TOTAL seção {secao}: {len(todos)} registros")
    return todos


# ---------------------------------------------------------------------
# Saída JSON (merge com execuções anteriores)
# ---------------------------------------------------------------------
def salvar_saida(todos_por_secao: dict):
    OUT.mkdir(exist_ok=True)
    f_prod = OUT / "produtos_soudaki_full.json"
    f_prec = OUT / "precos_soudaki_full.json"
    prods = json.loads(f_prod.read_text(encoding="utf-8")) if f_prod.exists() else []
    precs = json.loads(f_prec.read_text(encoding="utf-8")) if f_prec.exists() else []

    idx_prod = {p.get("sku"): p for p in prods}
    idx_prec = {p.get("sku"): p for p in precs}

    novos_p = novos_c = atualiz_c = 0
    for secao, itens in todos_por_secao.items():
        for it in itens:
            sku = it["sku"]
            reg_prod = {
                "sku": sku, "gtin_ean": it["gtin_ean"], "nome": it["nome"],
                "marca": it["marca"], "categoria": it["categoria"],
                "subcategoria": it["subcategoria"], "secao": it["secao"],
                "apresentacao": it["apresentacao"], "imagem_url": it["imagem_url"],
                "relevancia": 10, "data_cadastro": HOJE,
            }
            if sku in idx_prod:
                idx_prod[sku].update({k: v for k, v in reg_prod.items() if v})
            else:
                idx_prod[sku] = reg_prod
                novos_p += 1

            reg_prec = {
                "sku": sku, "gtin_ean": it["gtin_ean"], "nome": it["nome"],
                "supermercado": "Soudaki (Daki)",
                "preco_regular": it["preco"], "preco_promocional": it["preco"],
                "em_estoque": it["em_estoque"], "data_coleta": HOJE,
            }
            if sku in idx_prec:
                idx_prec[sku].update(reg_prec)
                atualiz_c += 1
            else:
                idx_prec[sku] = reg_prec
                novos_c += 1

    prods, precs = list(idx_prod.values()), list(idx_prec.values())
    f_prod.write_text(json.dumps(prods, ensure_ascii=False, indent=1), encoding="utf-8")
    f_prec.write_text(json.dumps(precs, ensure_ascii=False, indent=1), encoding="utf-8")

    com_ean = sum(1 for p in prods if p.get("gtin_ean"))
    log("-" * 60)
    log(f"JSON salvo: {f_prod.name}  ({len(prods)} produtos, +{novos_p} novos)")
    log(f"JSON salvo: {f_prec.name}  ({len(precs)} preços, +{novos_c} novos, "
        f"{atualiz_c} atualizados)")
    log(f"Cobertura EAN: {com_ean}/{len(prods)} "
        f"({100 * com_ean / max(len(prods), 1):.1f}%)")
    return f_prod, f_prec


# ---------------------------------------------------------------------
# Integração Neon (mesma lógica do coletar_e_integrar_soudaki.py v1)
# ---------------------------------------------------------------------
def integrar_neon(f_prod: Path, f_prec: Path, dry_run: bool):
    raiz_repo = Path(__file__).resolve().parents[2]
    caminho_db = raiz_repo / "webapp" / "backend"
    if not (caminho_db / "db.py").exists():
        log("[ERRO] Este script precisa estar em <repo>/scraper/soudaki/ para "
            "achar webapp/backend/db.py (ou rode a integração pelo script v1).")
        return
    sys.path.insert(0, str(caminho_db))
    try:
        from db import get_db_connection  # type: ignore
    except ImportError as e:
        log(f"[ERRO] não consegui importar db.py: {e}")
        return

    conn = get_db_connection()
    c = conn.cursor()
    motor = "Neon/Postgres" if getattr(conn, "is_postgres", False) else "SQLite local"
    log(f"[banco] conectado ({motor})")

    c.execute("SELECT id, gtin_ean FROM produtos WHERE gtin_ean IS NOT NULL")
    ean_to_id = {r["gtin_ean"]: r["id"] for r in c.fetchall()}
    c.execute("SELECT id, LOWER(TRIM(nome)) AS n FROM produtos")
    nome_to_id = {r["n"]: r["id"] for r in c.fetchall()}

    prods = json.loads(f_prod.read_text(encoding="utf-8"))
    precs = {p.get("sku"): p for p in json.loads(f_prec.read_text(encoding="utf-8"))}

    st = {"match_ean": 0, "match_nome": 0, "novos": 0, "precos": 0}
    for p in prods:
        ean = p.get("gtin_ean")
        nome = (p.get("nome") or "").lower().strip()
        prod_id = ean_to_id.get(ean) if ean else None
        if prod_id:
            st["match_ean"] += 1
        else:
            prod_id = nome_to_id.get(nome)
            if prod_id:
                st["match_nome"] += 1
                if ean and ean not in ean_to_id:
                    if not dry_run:
                        c.execute("UPDATE produtos SET gtin_ean = %s WHERE id = %s "
                                  "AND gtin_ean IS NULL", (ean, prod_id))
                    ean_to_id[ean] = prod_id
        if not prod_id:
            st["novos"] += 1
            if dry_run:
                continue
            busca = f"{p['nome']} {p['marca']} {p['categoria']}".lower()
            c.execute(
                "INSERT INTO produtos (gtin_ean, nome, categoria, marca, relevancia, "
                "imagem_url, apresentacao, busca) VALUES (%s,%s,%s,%s,10,%s,%s,%s) "
                "RETURNING id",
                (ean, p["nome"], p["categoria"], p["marca"], p.get("imagem_url"),
                 p.get("apresentacao"), busca))
            prod_id = c.fetchone()["id"]
            nome_to_id[nome] = prod_id
            if ean:
                ean_to_id[ean] = prod_id

        pc = precs.get(p["sku"])
        if not pc:
            continue
        st["precos"] += 1
        if dry_run:
            continue
        c.execute("SELECT id FROM precos WHERE produto_id = %s AND loja_id = %s LIMIT 1",
                  (prod_id, LOJA_ID))
        row = c.fetchone()
        vals = (pc["preco_promocional"], pc["preco_regular"], pc["em_estoque"], HOJE)
        if row:
            c.execute("UPDATE precos SET preco_promocional=%s, preco_regular=%s, "
                      "em_estoque=%s, data_coleta=%s WHERE id=%s", vals + (row["id"],))
        else:
            c.execute("INSERT INTO precos (produto_id, loja_id, preco_promocional, "
                      "preco_regular, em_estoque, data_coleta) VALUES (%s,%s,%s,%s,%s,%s)",
                      (prod_id, LOJA_ID) + vals)

    if dry_run:
        log(f"[dry-run] nada gravado. Match EAN: {st['match_ean']} | "
            f"Match nome: {st['match_nome']} | Novos: {st['novos']} | "
            f"Preços a gravar: {st['precos']}")
    else:
        conn.connection.commit()
        log(f"[banco] OK — match EAN: {st['match_ean']} | match nome: "
            f"{st['match_nome']} | produtos novos: {st['novos']} | "
            f"preços gravados: {st['precos']}")
    conn.close()


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Coletor Soudaki (Daki) v2")
    ap.add_argument("--secao", default="laticinios",
                    help="seção única (ex.: laticinios), 'all' para as 25, "
                         "ou lista separada por vírgula")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES_PADRAO,
                    help="trava de segurança de páginas por seção")
    ap.add_argument("--probe", action="store_true",
                    help="só diagnóstico da página (não salva)")
    ap.add_argument("--sem-paginacao", action="store_true",
                    help="pula a descoberta de paginação: a rolagem infinita "
                         "do site já traz o catálogo completo no pré-carregado")
    ap.add_argument("--db", action="store_true",
                    help="grava no Neon após coletar")
    ap.add_argument("--integrar", action="store_true",
                    help="não coleta; só integra JSONs existentes no Neon")
    ap.add_argument("--dry-run", action="store_true",
                    help="com --db/--integrar: mostra o que faria, sem gravar")
    args = ap.parse_args()

    sess = criar_sessao()

    if args.integrar:
        f_prod = OUT / "produtos_soudaki_full.json"
        f_prec = OUT / "precos_soudaki_full.json"
        if not f_prod.exists():
            sys.exit("[ERRO] JSONs não encontrados. Rode uma coleta primeiro.")
        integrar_neon(f_prod, f_prec, args.dry_run)
        return

    secoes = SECOES if args.secao == "all" else \
        [s.strip() for s in args.secao.split(",") if s.strip()]

    resultado = {}
    for i, s in enumerate(secoes, 1):
        log(f"[{i}/{len(secoes)}]")
        itens = coletar_secao(sess, s, args.max_pages, args.probe,
                              sem_paginacao=args.sem_paginacao)
        if args.probe:
            return
        if itens:
            resultado[s] = itens
        _sleep()

    if not resultado:
        sys.exit("[FIM] Nada coletado. Rode com --probe para diagnosticar.")

    f_prod, f_prec = salvar_saida(resultado)
    if args.db:
        integrar_neon(f_prod, f_prec, args.dry_run)
    log("[FIM] ✔")


if __name__ == "__main__":
    main()
