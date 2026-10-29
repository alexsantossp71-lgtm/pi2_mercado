# -*- coding: utf-8 -*-
"""
Enriquecedor de Overlap: Atacadão Santos
Busca produtos com estoque em Carrefour e Pão de Açúcar que não possuem
preço no Atacadão e consulta a API VTEX do Atacadão para gravar direto
no Neon PostgreSQL e atualizar os arquivos locais.
"""

import sys
import time
from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path("webapp/backend").resolve()))
sys.path.insert(0, str(Path("scraper").resolve()))

from db import get_db_connection
from recoletar_por_ean import coletar_vtex

ATACADAO_LOJA_ID = 3
HOJE = date.today().isoformat()

def main():
    print("=" * 65)
    print("ENRIQUECIMENTO DE OVERLAP MULTI-LOJAS (ATACADÃO SANTOS)")
    print("=" * 65)

    conn = get_db_connection()
    c = conn.cursor()

    # Seleciona produtos presentes em Carrefour (1) e Pão de Açúcar (2) que faltam no Atacadão (3)
    query = """
        SELECT p.id, p.gtin_ean, p.nome, p.categoria, p.relevancia
        FROM produtos p
        WHERE p.gtin_ean IS NOT NULL
          AND LENGTH(p.gtin_ean) = 13
          AND EXISTS (SELECT 1 FROM precos pr WHERE pr.produto_id = p.id AND pr.loja_id = 1 AND (pr.em_estoque IS TRUE OR pr.em_estoque = TRUE))
          AND EXISTS (SELECT 1 FROM precos pr WHERE pr.produto_id = p.id AND pr.loja_id = 2 AND (pr.em_estoque IS TRUE OR pr.em_estoque = TRUE))
          AND NOT EXISTS (SELECT 1 FROM precos pr WHERE pr.produto_id = p.id AND pr.loja_id = 3 AND (pr.em_estoque IS TRUE OR pr.em_estoque = TRUE))
        ORDER BY p.relevancia DESC, p.id ASC
        LIMIT 2000
    """
    c.execute(query)
    candidatos = c.fetchall()
    print(f"Total de candidatos priorizados (Carrefour + PdA sem Atacadão): {len(candidatos)}")

    if not candidatos:
        print("Nenhum candidato pendente!")
        conn.close()
        return

    encontrados = 0
    indisponiveis = 0
    t0 = time.time()

    def processar_candidato(prod):
        ean = prod["gtin_ean"]
        res = coletar_vtex("atacadao", "https://www.atacadao.com.br", ean)
        return prod, res

    print("\nConsultando Atacadão via VTEX Simulation com fallback de CEP...")
    # Usar ThreadPool para acelerar as consultas
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(processar_candidato, p): p for p in candidatos}
        
        idx = 0
        for future in as_completed(futures):
            idx += 1
            prod, res = future.result()
            pid = prod["id"]
            ean = prod["gtin_ean"]
            nome = prod["nome"][:35]

            p_reg = res.get("preco_regular")
            p_prom = res.get("preco_promocional") or p_reg
            em_est = bool(res.get("em_estoque") and p_reg and p_reg > 0)
            cep = res.get("cep_coleta")

            # Gravar no Neon PostgreSQL
            # Verificar se já existe registro de preco
            c.execute("SELECT id FROM precos WHERE produto_id = %s AND loja_id = %s LIMIT 1", (pid, ATACADAO_LOJA_ID))
            preco_row = c.fetchone()

            if preco_row:
                c.execute(
                    "UPDATE precos SET preco_promocional = %s, preco_regular = %s, em_estoque = %s, "
                    "cep_coleta = %s, data_coleta = %s WHERE id = %s",
                    (p_prom, p_reg, em_est, cep, HOJE, preco_row["id"])
                )
            else:
                c.execute(
                    "INSERT INTO precos (produto_id, loja_id, preco_promocional, preco_regular, em_estoque, cep_coleta, data_coleta) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (pid, ATACADAO_LOJA_ID, p_prom, p_reg, em_est, cep, HOJE)
                )

            if em_est:
                encontrados += 1
                status_str = f"R$ {p_reg:.2f} (EM ESTOQUE)"
            else:
                indisponiveis += 1
                status_str = "Indisponível/Sem estoque"

            if idx % 10 == 0 or em_est:
                print(f"[{idx}/{len(candidatos)}] EAN {ean} | {nome:<35} -> {status_str}")

            # Commit periódico a cada 20 itens
            if idx % 20 == 0:
                conn.connection.commit()

    conn.connection.commit()
    conn.close()

    duracao = round(time.time() - t0, 1)
    print("\n" + "=" * 65)
    print(f"ENRIQUECIMENTO CONCLUÍDO EM {duracao}s")
    print(f"Novos preços em estoque no Atacadão: {encontrados}")
    print(f"Indisponíveis ou não localizados: {indisponiveis}")
    print("=" * 65)

if __name__ == "__main__":
    main()
