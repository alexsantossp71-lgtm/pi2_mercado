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

MAPA_CATEGORIAS = {
    "hortifruti": "Hortifruti",
    "bebidas": "Bebidas",
    "cervejas-e-drinks": "Bebidas",
    "vinhos-e-espumantes": "Bebidas",
    "destilados": "Bebidas",
    "laticinios": "Frios e Laticínios",
    "padaria": "Padaria e Matinais",
    "matinais": "Padaria e Matinais",
    "saudaveis": "Alimentos",
    "mercearia": "Mercearia",
    "molhos-e-conservas": "Mercearia",
    "biscoitos-e-salgadinhos": "Mercearia",
    "chocolates-e-doces": "Mercearia",
    "acougue-e-peixaria": "Carnes, Aves e Peixes",
    "churrasco": "Carnes, Aves e Peixes",
    "congelados": "Frios e Congelados",
    "pratico-e-rapido": "Alimentos",
    "sorvetes-e-acai": "Frios e Congelados",
    "limpeza": "Limpeza e Lavanderia",
    "higiene-e-beleza": "Higiene e Perfumaria",
    "utilidades": "Utilidades Domésticas",
    "pets": "Pet Care",
    "bebe": "Bebê e Infantil",
    "produtos-daki": "Alimentos",
    "farmacia": "Suplementos Alimentares",
}

def normalizar_categoria(cat_raw: str, secao: str) -> str:
    c = (cat_raw or "").strip()
    c_lower = c.lower()
    if "hortifruti" in c_lower or "fruta" in c_lower or "legume" in c_lower:
        return "Hortifruti"
    if "bebida" in c_lower or "refrigerante" in c_lower or "cerveja" in c_lower or "vinho" in c_lower:
        return "Bebidas"
    if "latic" in c_lower or "queijo" in c_lower or "iogurte" in c_lower:
        return "Frios e Laticínios"
    if "padaria" in c_lower or "matinal" in c_lower or "pão" in c_lower or "pao" in c_lower:
        return "Padaria e Matinais"
    if "carne" in c_lower or "peixe" in c_lower or "açougue" in c_lower or "acougue" in c_lower:
        return "Carnes, Aves e Peixes"
    if "limpeza" in c_lower:
        return "Limpeza e Lavanderia"
    if "higiene" in c_lower or "beleza" in c_lower or "perfum" in c_lower:
        return "Higiene e Perfumaria"
    if "pet" in c_lower:
        return "Pet Care"
    if "bebê" in c_lower or "bebe" in c_lower or "infantil" in c_lower:
        return "Bebê e Infantil"
    if "utilidade" in c_lower or "bazar" in c_lower:
        return "Utilidades Domésticas"
    if "congelado" in c_lower:
        return "Frios e Congelados"
    if "mercearia" in c_lower or "massa" in c_lower or "molho" in c_lower or "biscoito" in c_lower:
        return "Mercearia"
    return MAPA_CATEGORIAS.get(secao, c if c else "Mercearia")

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
                    cat_raw = item.get("category", {}).get("categoryName") or secao.capitalize()
                    cat_name = normalizar_categoria(cat_raw, secao)
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
            print(f"    [erro tentativa {tentativa+1}/3] {e}")
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
    todos_coletados_list = []
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
            todos_coletados_list.append(p)
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

    # Exportar também para os arquivos JSON (raiz, scraper/ e webapp/) para paridade de cache offline/local
    try:
        precos_json_list = []
        for p in todos_coletados_list:
            chave = p.get("ean") or p.get("sku")
            precos_json_list.append({
                "gtin_ean": chave,
                "supermercado": "Soudaki",
                "nome_completo": p["nome"],
                "marca": p["marca"],
                "secao": p["categoria"],
                "categoria": p["categoria"],
                "imagem_url": p["imagem_url"],
                "preco_regular": p["preco"],
                "preco_promocional": p["preco"],
                "em_estoque": 1 if p["em_estoque"] else 0,
                "data_coleta": HOJE
            })
        raiz_proj = Path(__file__).resolve().parent.parent
        for path_dest in [
            raiz_proj / "precos_soudaki_ampliado.json",
            raiz_proj / "scraper" / "precos_soudaki_ampliado.json",
            raiz_proj / "webapp" / "precos_soudaki_ampliado.json"
        ]:
            with open(path_dest, "w", encoding="utf-8") as f_out:
                json.dump(precos_json_list, f_out, indent=2, ensure_ascii=False)
        print(f"[JSON] precos_soudaki_ampliado.json exportado com sucesso para as 3 pastas!")
    except Exception as e_json:
        print(f"[Aviso] Falha ao exportar JSONs locais: {e_json}")

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
