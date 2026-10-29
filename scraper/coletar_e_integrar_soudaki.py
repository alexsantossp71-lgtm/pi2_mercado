# -*- coding: utf-8 -*-
"""
Coletor e Integrador Completo do Soudaki (Daki) - Todas as 25 Categorias.
Extrai produtos, preços e estoques direto de https://soudaki.com/shop/<secao>/
e grava diretamente no Neon PostgreSQL (loja_id = 4), vinculando por EAN-13
ou nome com produtos existentes no catálogo compartilhado.
"""

import sys
import re
import json
import time
from datetime import date
from pathlib import Path
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path("webapp/backend").resolve()))
from db import get_db_connection

LOJA_SOUDAKI_ID = 4
BASE_URL = "https://soudaki.com"
HOJE = date.today().isoformat()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

RE_EAN_IMAGEM = re.compile(r"BR_(\d{13})")

# Todas as 25 categorias confirmadas HTTP 200 no soudaki.com/shop/
SECOES = [
    "hortifruti", "bebidas", "laticinios", "padaria", "matinais", "saudaveis", 
    "mercearia", "molhos-e-conservas", "acougue-e-peixaria", "churrasco", 
    "congelados", "pratico-e-rapido", "biscoitos-e-salgadinhos", "chocolates-e-doces",
    "sorvetes-e-acai", "cervejas-e-drinks", "vinhos-e-espumantes", "destilados",
    "limpeza", "higiene-e-beleza", "utilidades", "pets", "bebe", "produtos-daki",
    "farmacia"
]

def extrair_ean(url: str):
    if not url:
        return None
    m = RE_EAN_IMAGEM.search(url)
    return m.group(1) if m else None

def coletar_secao(secao: str):
    url = f"{BASE_URL}/shop/{secao}/"
    for tentativa in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code != 200:
                return []
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if not m:
                return []
            data = json.loads(m.group(1))
            pp = data.get("props", {}).get("pageProps", {})
            preloaded = pp.get("preloadedProducts", {})

            itens = []
            for subcat, plist in preloaded.items():
                if not isinstance(plist, list):
                    continue
                for item in plist:
                    if not isinstance(item, dict):
                        continue
                    nome = (item.get("name") or "").strip()
                    if not nome:
                        continue
                    
                    preco = item.get("price", {}).get("amount")
                    try:
                        preco = float(preco) if preco is not None else None
                    except (ValueError, TypeError):
                        preco = None
                    if preco is None or preco <= 0:
                        continue

                    sku = item.get("sku")
                    cat_name = item.get("category", {}).get("categoryName") or secao.capitalize()
                    img_url = (item.get("packshot1_front_grid") or {}).get("url")
                    ean = extrair_ean(img_url)

                    inv = item.get("inventory", {})
                    qty = inv.get("quantity", 0)
                    em_est = bool(qty and qty > 0)

                    partes = [p for p in re.split(r"\s+", nome) if p]
                    marca = "Nao Informada"
                    if partes:
                        p0 = partes[0].strip("*")
                        if p0 and p0[0].isalpha():
                            marca = p0

                    itens.append({
                        "nome": nome,
                        "marca": marca,
                        "preco": preco,
                        "sku": sku,
                        "ean": ean,
                        "categoria": cat_name,
                        "subcategoria": subcat,
                        "em_estoque": em_est,
                        "imagem_url": img_url,
                        "secao": secao
                    })
            return itens
        except Exception as e:
            time.sleep(2 * (tentativa + 1))
    return []

def main():
    print("=" * 65)
    print("INICIANDO VARREDURA E SINCRONIZAÇÃO COMPLETA: SOUDAKI (DAKI)")
    print("=" * 65)

    conn = get_db_connection()
    c = conn.cursor()
    print("[Banco] Conectado ao Neon PostgreSQL")

    # Mapear todos os produtos por EAN e por nome no banco para match ultra-rápido
    print("[Cache] Carregando índices de EANs e nomes do banco...")
    c.execute("SELECT id, gtin_ean FROM produtos WHERE gtin_ean IS NOT NULL")
    ean_to_id = {r["gtin_ean"]: r["id"] for r in c.fetchall()}
    print(f"[Cache] {len(ean_to_id)} EANs carregados")

    c.execute("SELECT id, LOWER(TRIM(nome)) as nome_norm FROM produtos")
    nome_to_id = {r["nome_norm"]: r["id"] for r in c.fetchall()}
    print(f"[Cache] {len(nome_to_id)} Nomes carregados")

    vistos_skus = set()
    total_coletados = 0
    total_com_ean = 0
    total_match_ean = 0
    total_match_nome = 0
    total_novos_prods = 0
    total_precos_gravados = 0

    t0 = time.time()

    for idx, secao in enumerate(SECOES, 1):
        print(f"\n[{idx}/{len(SECOES)}] Coletando seção: /shop/{secao}/...")
        produtos_secao = coletar_secao(secao)
        print(f"  -> {len(produtos_secao)} itens recebidos da seção")

        for p in produtos_secao:
            sku = p["sku"] or p["nome"]
            if sku in vistos_skus:
                continue
            vistos_skus.add(sku)
            total_coletados += 1

            ean = p["ean"]
            nome = p["nome"]
            nome_norm = nome.lower().strip()
            marca = p["marca"]
            cat = p["categoria"]
            preco = p["preco"]
            em_est = p["em_estoque"]
            img = p["imagem_url"]

            if ean:
                total_com_ean += 1

            # 1. Tentar match por EAN
            prod_id = None
            if ean and ean in ean_to_id:
                prod_id = ean_to_id[ean]
                total_match_ean += 1

            # 2. Tentar match por Nome
            if not prod_id and nome_norm in nome_to_id:
                prod_id = nome_to_id[nome_norm]
                total_match_nome += 1
                # Se achou por nome e agora temos o EAN da Soudaki, preenche no produto caso estivesse vazio
                if ean and ean not in ean_to_id:
                    c.execute("UPDATE produtos SET gtin_ean = %s WHERE id = %s AND gtin_ean IS NULL", (ean, prod_id))
                    ean_to_id[ean] = prod_id

            # 3. Se não existe, cria novo produto no catálogo
            if not prod_id:
                busca_txt = f"{nome} {marca} {cat}".lower()
                c.execute(
                    "INSERT INTO produtos (gtin_ean, nome, categoria, marca, relevancia, imagem_url, busca) "
                    "VALUES (%s, %s, %s, %s, 10, %s, %s) RETURNING id",
                    (ean, nome, cat, marca, img, busca_txt)
                )
                prod_id = c.fetchone()["id"]
                nome_to_id[nome_norm] = prod_id
                if ean:
                    ean_to_id[ean] = prod_id
                total_novos_prods += 1

            # 4. Grava / Atualiza o preço da Soudaki (loja_id = 4)
            c.execute(
                "SELECT id FROM precos WHERE produto_id = %s AND loja_id = %s LIMIT 1",
                (prod_id, LOJA_SOUDAKI_ID)
            )
            p_row = c.fetchone()
            if p_row:
                c.execute(
                    "UPDATE precos SET preco_promocional = %s, preco_regular = %s, em_estoque = %s, "
                    "data_coleta = %s WHERE id = %s",
                    (preco, preco, em_est, HOJE, p_row["id"])
                )
            else:
                c.execute(
                    "INSERT INTO precos (produto_id, loja_id, preco_promocional, preco_regular, em_estoque, data_coleta) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (prod_id, LOJA_SOUDAKI_ID, preco, preco, em_est, HOJE)
                )
            total_precos_gravados += 1

        conn.connection.commit()
        time.sleep(0.5)

    conn.close()
    duracao = round(time.time() - t0, 1)

    print("\n" + "=" * 65)
    print(f"VARREDURA SOUDAKI FINALIZADA EM {duracao}s!")
    print(f"Total de produtos únicos processados: {total_coletados}")
    print(f"Com EAN identificado: {total_com_ean}")
    print(f"Match por EAN no catálogo: {total_match_ean}")
    print(f"Match por Nome no catálogo: {total_match_nome}")
    print(f"Novos produtos adicionados: {total_novos_prods}")
    print(f"Preços atualizados/inseridos no Neon: {total_precos_gravados}")
    print("=" * 65)

if __name__ == "__main__":
    main()
