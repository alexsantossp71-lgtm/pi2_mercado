# -*- coding: utf-8 -*-
"""
Coletor de Categorias do Carrefour com Gravação Direta no Banco (Neon Postgres + SQLite)
PI em Computação II - UNIVESP 2026.2

Coleta categorias essenciais da cesta básica direto de mercado.carrefour.com.br,
extrai GTIN/EAN e metadados das PDPs via ThreadPoolExecutor, e persiste
diretamente em produtos e precos (loja_id=1: Carrefour - Ponta da Praia).
"""

import os
import sys
import re
import json
import time
import datetime
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Configurar caminhos para importar db.py do backend
BACKEND_DIR = Path(__file__).resolve().parents[1] / "webapp" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import get_db_connection

CARREFOUR_LOJA_ID = 1
CEP_PADRAO = "11030-000"  # Ponta da Praia - Santos

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

CATEGORIAS = [
    {
        "slug": "arroz",
        "nome": "Arroz",
        "url": "https://mercado.carrefour.com.br/categoria/mercearia/alimentos-basicos/arroz",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "feijao",
        "nome": "Feijão",
        "url": "https://mercado.carrefour.com.br/categoria/mercearia/alimentos-basicos/feijao",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "oleos-e-azeites",
        "nome": "Óleos e Azeites",
        "url": "https://mercado.carrefour.com.br/categoria/mercearia/alimentos-basicos/oleos-e-azeites",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "acucar-e-adocantes",
        "nome": "Açúcar e Adoçantes",
        "url": "https://mercado.carrefour.com.br/categoria/mercearia/alimentos-basicos/acucar-e-adocantes",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "cafes",
        "nome": "Cafés",
        "url": "https://mercado.carrefour.com.br/categoria/mercearia/matinais-e-sobremesas/cafes",
        "categoria_db": "Mercearia"
    },
    {
        "slug": "leites",
        "nome": "Leites",
        "url": "https://mercado.carrefour.com.br/categoria/laticinios-e-queijos/leites",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "manteigas-e-margarinas",
        "nome": "Manteigas e Margarinas",
        "url": "https://mercado.carrefour.com.br/categoria/laticinios-e-queijos/manteigas-e-margarinas",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "bovinos",
        "nome": "Carnes Bovinas",
        "url": "https://mercado.carrefour.com.br/categoria/acougue-e-peixaria/bovinos",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "aves",
        "nome": "Aves",
        "url": "https://mercado.carrefour.com.br/categoria/acougue-e-peixaria/aves",
        "categoria_db": "Alimentos"
    },
    {
        "slug": "sabonetes",
        "nome": "Sabonetes",
        "url": "https://mercado.carrefour.com.br/categoria/higiene-e-beleza/cuidados-com-o-corpo/sabonetes",
        "categoria_db": "Higiene e Perfumaria"
    },
    {
        "slug": "cremes-dentais",
        "nome": "Cremes Dentais",
        "url": "https://mercado.carrefour.com.br/categoria/higiene-e-beleza/higiene-bucal/cremes-dentais",
        "categoria_db": "Higiene e Perfumaria"
    },
    {
        "slug": "sabao-em-po",
        "nome": "Sabão em Pó e Líquido",
        "url": "https://mercado.carrefour.com.br/categoria/limpeza/cuidado-com-as-roupas/sabao-em-po",
        "categoria_db": "Limpeza e Lavanderia"
    }
]

def coletar_detalhes_pdp(session, item_base):
    """Acessa a PDP do produto para extrair o EAN, imagem e marca."""
    url = item_base["url"]
    try:
        r = session.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return item_base
        
        r.encoding = "utf-8"
        text = r.text
        soup = BeautifulSoup(text, "html.parser")
        
        # 1. Busca EAN via regex (789... ou 790...)
        eans = re.findall(r'\b(789\d{10}|790\d{10})\b', text)
        if eans:
            item_base["gtin_ean"] = eans[0]
            
        # 2. Busca JSON-LD para imagem em alta resolução e marca
        s = soup.find("script", type="application/ld+json")
        if s and s.string:
            try:
                data = json.loads(s.string)
                if isinstance(data, dict):
                    if not item_base.get("gtin_ean") and data.get("gtin13"):
                        item_base["gtin_ean"] = str(data["gtin13"])
                    if data.get("image"):
                        item_base["imagem_url"] = data["image"]
                    if data.get("brand"):
                        brand_info = data["brand"]
                        if isinstance(brand_info, dict):
                            item_base["marca"] = brand_info.get("name", item_base.get("marca"))
                        elif isinstance(brand_info, str):
                            item_base["marca"] = brand_info
                    if data.get("offers") and isinstance(data["offers"], dict):
                        offer_price = data["offers"].get("price")
                        if offer_price and not item_base.get("preco_promocional"):
                            item_base["preco_promocional"] = float(offer_price)
            except Exception:
                pass
                
        # 3. Fallback de imagem caso não venha no JSON-LD
        if not item_base.get("imagem_url"):
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "vtexassets.com/arquivos/ids/" in src:
                    item_base["imagem_url"] = src.replace("96-96", "500-500")
                    break

    except Exception as e:
        pass
        
    return item_base

def coletar_categoria(categoria_info, session):
    """Raspa os cards de uma categoria e depois enriquece via PDPs paralelas."""
    url = categoria_info["url"]
    print(f"\n[Scraper] Coletando categoria: {categoria_info['nome']} ({url})...")
    
    try:
        r = session.get(url, headers=HEADERS, timeout=18)
        r.raise_for_status()
        r.encoding = "utf-8"
    except Exception as e:
        print(f"[Scraper] Erro ao carregar categoria {categoria_info['nome']}: {e}")
        return []
        
    soup = BeautifulSoup(r.text, "html.parser")
    links = soup.find_all("a", href=True)
    
    itens_brutos = []
    vistos = set()
    
    for a in links:
        href = a["href"]
        if not href.startswith("/produto/"):
            continue
        if href in vistos:
            continue
        vistos.add(href)
        
        text = a.get_text(" ", strip=True)
        precos_raw = re.findall(r'R\$\s*([\d,.]+)', text)
        precos = [float(p.replace(".", "").replace(",", ".")) for p in precos_raw]
        
        nome = text.split("R$")[0].strip()
        if not nome or len(nome) < 3:
            continue
            
        preco_regular = None
        preco_promocional = None
        if len(precos) == 1:
            preco_regular = precos[0]
            preco_promocional = precos[0]
        elif len(precos) >= 2:
            preco_regular = max(precos[:2])
            preco_promocional = min(precos[:2])
            
        itens_brutos.append({
            "nome": nome,
            "categoria": categoria_info["categoria_db"],
            "marca": "",
            "gtin_ean": None,
            "preco_regular": preco_regular,
            "preco_promocional": preco_promocional,
            "em_estoque": True if preco_promocional else False,
            "url": f"https://mercado.carrefour.com.br{href}",
            "imagem_url": None,
            "data_coleta": datetime.date.today().isoformat(),
            "cep_coleta": CEP_PADRAO
        })
        
    print(f"[Scraper] {len(itens_brutos)} produtos encontrados na listagem de {categoria_info['nome']}. Enriquecendo PDPs...")
    
    # Executa detalhamento em paralelo com até 5 threads
    itens_completos = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(coletar_detalhes_pdp, session, item) for item in itens_brutos]
        for f in as_completed(futures):
            try:
                res = f.result()
                itens_completos.append(res)
            except Exception:
                pass
                
    com_ean = sum(1 for it in itens_completos if it.get("gtin_ean"))
    print(f"[Scraper] Concluído {categoria_info['nome']}: {len(itens_completos)} itens ({com_ean} com EAN identificado).")
    return itens_completos

def salvar_no_banco(itens, conn):
    """Grava ou atualiza os produtos e preços no banco relacional conectado."""
    cur = conn.cursor()
    is_postgres = getattr(conn, "is_postgres", False)
    
    total_atualizados = 0
    total_novos_precos = 0
    total_novos_produtos = 0
    
    for item in itens:
        gtin = item.get("gtin_ean")
        nome = item["nome"]
        categoria = item.get("categoria", "Alimentos")
        marca = item.get("marca") or ""
        imagem = item.get("imagem_url")
        p_prom = item.get("preco_promocional")
        p_reg = item.get("preco_regular")
        em_est = item.get("em_estoque", True)
        data_col = item.get("data_coleta")
        cep_col = item.get("cep_coleta", CEP_PADRAO)
        
        produto_id = None
        
        # 1. Tentar encontrar produto por EAN
        if gtin:
            if is_postgres:
                cur.execute("SELECT id, imagem_url FROM produtos WHERE gtin_ean = %s LIMIT 1", (gtin,))
            else:
                cur.execute("SELECT id, imagem_url FROM produtos WHERE gtin_ean = ? LIMIT 1", (gtin,))
            row = cur.fetchone()
            if row:
                produto_id = row["id"]
                # Atualizar imagem caso o banco não tenha e agora tenhamos
                if imagem and not row.get("imagem_url"):
                    if is_postgres:
                        cur.execute("UPDATE produtos SET imagem_url = %s WHERE id = %s", (imagem, produto_id))
                    else:
                        cur.execute("UPDATE produtos SET imagem_url = ? WHERE id = ?", (imagem, produto_id))
                        
        # 2. Se não encontrou por EAN mas tem nome, tentar por busca/nome exato
        if not produto_id:
            if is_postgres:
                cur.execute("SELECT id FROM produtos WHERE unaccent(nome) ILIKE unaccent(%s) LIMIT 1", (nome,))
            else:
                cur.execute("SELECT id FROM produtos WHERE nome = ? LIMIT 1", (nome,))
            row = cur.fetchone()
            if row:
                produto_id = row["id"]
                if gtin:
                    if is_postgres:
                        cur.execute("UPDATE produtos SET gtin_ean = %s WHERE id = %s AND gtin_ean IS NULL", (gtin, produto_id))
                    else:
                        cur.execute("UPDATE produtos SET gtin_ean = ? WHERE id = ? AND gtin_ean IS NULL", (gtin, produto_id))

        # 3. Se ainda não existe, cadastrar novo produto
        if not produto_id:
            busca_text = f"{nome} {marca} {categoria}".lower()
            if is_postgres:
                cur.execute(
                    """INSERT INTO produtos (gtin_ean, nome, categoria, marca, relevancia, imagem_url, busca)
                       VALUES (%s, %s, %s, %s, 10, %s, %s) RETURNING id""",
                    (gtin, nome, categoria, marca, imagem, busca_text)
                )
                r_ins = cur.fetchone()
                produto_id = r_ins["id"]
            else:
                cur.execute(
                    """INSERT INTO produtos (gtin_ean, nome, categoria, marca, relevancia, imagem_url)
                       VALUES (?, ?, ?, ?, 10, ?)""",
                    (gtin, nome, categoria, marca, imagem)
                )
                produto_id = cur.cursor.lastrowid
            total_novos_produtos += 1

        # 4. Atualizar ou inserir preço para Carrefour (CARREFOUR_LOJA_ID = 1)
        if produto_id and p_prom is not None:
            if is_postgres:
                cur.execute(
                    "SELECT id FROM precos WHERE produto_id = %s AND loja_id = %s LIMIT 1",
                    (produto_id, CARREFOUR_LOJA_ID)
                )
            else:
                cur.execute(
                    "SELECT id FROM precos WHERE produto_id = ? AND loja_id = ? LIMIT 1",
                    (produto_id, CARREFOUR_LOJA_ID)
                )
            preco_row = cur.fetchone()
            
            if preco_row:
                preco_id = preco_row["id"]
                if is_postgres:
                    cur.execute(
                        """UPDATE precos SET preco_promocional = %s, preco_regular = %s, em_estoque = %s,
                                              data_coleta = %s, cep_coleta = %s WHERE id = %s""",
                        (p_prom, p_reg, em_est, data_col, cep_col, preco_id)
                    )
                else:
                    cur.execute(
                        """UPDATE precos SET preco_promocional = ?, preco_regular = ?, em_estoque = ?,
                                              data_coleta = ?, cep_coleta = ? WHERE id = ?""",
                        (p_prom, p_reg, em_est, data_col, cep_col, preco_id)
                    )
                total_atualizados += 1
            else:
                if is_postgres:
                    cur.execute(
                        """INSERT INTO precos (produto_id, loja_id, preco_promocional, preco_regular, em_estoque, data_coleta, cep_coleta)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (produto_id, CARREFOUR_LOJA_ID, p_prom, p_reg, em_est, data_col, cep_col)
                    )
                else:
                    cur.execute(
                        """INSERT INTO precos (produto_id, loja_id, preco_promocional, preco_regular, em_estoque, data_coleta, cep_coleta)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (produto_id, CARREFOUR_LOJA_ID, p_prom, p_reg, em_est, data_col, cep_col)
                    )
                total_novos_precos += 1

    # Commit no banco
    if is_postgres:
        conn.connection.commit()
    else:
        conn.connection.commit()
        
    return total_atualizados, total_novos_precos, total_novos_produtos

def main():
    print("=" * 70)
    print("INICIANDO COLETOR AUTOMATIZADO CARREFOUR - CESTA BÁSICA")
    print("=" * 70)
    
    conn = get_db_connection()
    engine = "Neon PostgreSQL" if getattr(conn, "is_postgres", False) else "SQLite Local"
    print(f"[Banco de Dados] Conectado a: {engine}")
    
    session = requests.Session()
    todos_itens = []
    
    t_inicio = time.time()
    
    for cat in CATEGORIAS:
        itens_cat = coletar_categoria(cat, session)
        if itens_cat:
            todos_itens.extend(itens_cat)
            # Salvar no banco a cada categoria para segurança
            atualizados, novos_p, novos_prod = salvar_no_banco(itens_cat, conn)
            print(f"[Banco] Categoria {cat['nome']}: {atualizados} preços atualizados, {novos_p} novos preços, {novos_prod} novos produtos.")
        time.sleep(1.0)
        
    conn.close()
    
    duracao = round(time.time() - t_inicio, 1)
    
    # Salvar backup local JSON
    backup_path = Path(__file__).parent / "carrefour_cesta_basica_coletada.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(todos_itens, f, indent=2, ensure_ascii=False)
        
    print("\n" + "=" * 70)
    print(f"COLETA CONCLUÍDA EM {duracao}s!")
    print(f"Total de produtos coletados: {len(todos_itens)}")
    print(f"Produtos com EAN: {sum(1 for x in todos_itens if x.get('gtin_ean'))}")
    print(f"Backup gravado em: {backup_path}")
    print("=" * 70)

if __name__ == "__main__":
    main()
