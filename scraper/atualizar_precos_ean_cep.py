# -*- coding: utf-8 -*-
"""
Atualização em lote de preços por EAN + CEP nos 3 supermercados.

Lê os EANs de um catálogo (padrão: scraper/catalogo_unificado.json) e, para
cada um, coleta preço/estoque no Atacadão, Carrefour e Pão de Açúcar usando
a busca por EAN com fallback de CEP (Santos 11060-002 -> São Paulo
01310-100), reutilizando as funções de recoletar_por_ean.py.

GARANTIA DE COBERTURA: ao final de cada rodada o script audita os 3 arquivos
de preços e verifica se TODO EAN do lote tem registro em TODAS as lojas.
EANs que ficarem sem registro em alguma loja entram numa nova rodada de
tentativa (até --max-tentativas). Nenhum EAN do lote fica fora dos 3
arquivos — na pior hipótese fica com em_estoque=false + observacao.

Uso:
    # Atualizar todos os EANs do catálogo:
    python atualizar_precos_ean_cep.py

    # Só os EANs que ainda faltam em algum dos 3 arquivos:
    python atualizar_precos_ean_cep.py --faltantes

    # Teste rápido com os 5 primeiros EANs / a partir de um índice:
    python atualizar_precos_ean_cep.py --limite 5
    python atualizar_precos_ean_cep.py --desde 100 --limite 20

    # EANs explícitos (ignora o catálogo):
    python atualizar_precos_ean_cep.py --eans 7896006751113 7891000100103
"""

import argparse
import json
import os
import sys
import time
from datetime import date

# Garante que o diretório do script esteja no path para importar o módulo base
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import recoletar_por_ean as recoleta

# Sempre atualiza com a data de hoje (o módulo base traz HOJE fixo)
recoleta.HOJE = date.today().isoformat()

ARQUIVO_CATALOGO = os.path.join(BASE, "catalogo_unificado.json")

LOJAS = ("atacadao", "carrefour", "pao_de_acucar")


# ---------------------------------------------------------------------------
# Catálogo / cobertura
# ---------------------------------------------------------------------------
def eans_do_catalogo(caminho: str = ARQUIVO_CATALOGO) -> list:
    """Extrai a lista de EANs válidos do catálogo unificado."""
    if not os.path.exists(caminho):
        print(f"AVISO: catálogo não encontrado: {caminho}")
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    produtos = dados.get("produtos", dados) if isinstance(dados, dict) else dados
    eans = []
    for p in produtos:
        ean = str(p.get("gtin_ean") or "").strip()
        if recoleta.ean_valido(ean) and ean not in eans:
            eans.append(ean)
    return eans


def auditar_cobertura(eans: list, lojas: tuple = LOJAS) -> dict:
    """Retorna {ean: [lojas faltantes]} para EANs sem registro em alguma loja."""
    faltantes = {}
    registros = {
        loja: recoleta.carregar_por_ean(recoleta.ARQUIVOS[loja]) for loja in lojas
    }
    for ean in eans:
        falta = [loja for loja in lojas if ean not in registros[loja]]
        if falta:
            faltantes[ean] = falta
    return faltantes


def auditar_sem_preco(eans: list, loja: str) -> dict:
    """Retorna {ean: [loja]} para EANs ainda sem preço/estoque na loja."""
    registros = recoleta.carregar_por_ean(recoleta.ARQUIVOS[loja])
    return {e: [loja] for e in eans
            if not registros.get(e, {}).get("em_estoque")}


def eans_faltantes_catalogo() -> list:
    """EANs do catálogo que ainda não constam em algum dos 3 arquivos."""
    eans = eans_do_catalogo()
    return list(auditar_cobertura(eans).keys())


# ---------------------------------------------------------------------------
# Rodada de coleta
# ---------------------------------------------------------------------------
def rodada(eans: list, delay: float, lojas: tuple = LOJAS) -> dict:
    """Coleta cada EAN nas lojas e grava. Retorna contadores do resumo."""
    stats = {"com_preco": 0, "indisponivel": 0}
    total = len(eans)
    for i, ean in enumerate(eans, 1):
        print(f"[{i}/{total}] EAN {ean}")
        for loja in lojas:
            try:
                reg = recoleta.coletar_loja(loja, ean)
            except Exception as err:  # noqa: BLE001 - nunca aborta o lote
                reg = recoleta.registro_indisponivel(
                    loja, ean, f"erro:{type(err).__name__}"
                )
            try:
                recoleta.gravar_registro(loja, ean, reg)
            except OSError as err:
                print(f"  !! falha ao gravar {loja}: {err}")
            if reg.get("em_estoque"):
                stats["com_preco"] += 1
                txt = f"R$ {reg['preco_regular']:.2f}"
            else:
                stats["indisponivel"] += 1
                txt = f"indisponível ({reg.get('observacao', '')})"
            print(f"  {recoleta.NOME_SUPERMERCADO[loja]:<14} -> {txt}")
            time.sleep(delay)
    return stats


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Atualiza preços por EAN+CEP garantindo registro nas 3 lojas."
    )
    ap.add_argument("--eans", nargs="+", help="EAN-13 explícitos (pula o catálogo)")
    ap.add_argument("--faltantes", action="store_true",
                    help="Processa só EANs do catálogo sem registro em alguma loja")
    ap.add_argument("--catalogo", default=ARQUIVO_CATALOGO,
                    help="Caminho do catálogo unificado")
    ap.add_argument("--limite", type=int, default=None, help="Máximo de EANs")
    ap.add_argument("--desde", type=int, default=0, help="Índice inicial do lote")
    ap.add_argument("--delay", type=float, default=recoleta.SLEEP,
                    help="Espera entre requisições (s)")
    ap.add_argument("--max-tentativas", type=int, default=2,
                    help="Rodadas de retry para EANs que faltarem em alguma loja")
    ap.add_argument("--loja", choices=LOJAS, default=None,
                    help="Atualiza apenas esta loja")
    ap.add_argument("--sem-preco", action="store_true",
                    help="Processa EANs que estão sem preço/estoque na loja "
                         "(requer --loja; ignora o catálogo)")
    args = ap.parse_args()

    lojas = (args.loja,) if args.loja else LOJAS

    # 1. Monta o lote de EANs
    if args.sem_preco:
        if not args.loja:
            ap.error("--sem-preco requer --loja")
        registros = recoleta.carregar_por_ean(recoleta.ARQUIVOS[args.loja])
        eans = [e for e, r in registros.items()
                if not r.get("em_estoque") and recoleta.ean_valido(e)]
        print(f"EANs sem preço/estoque em "
              f"{recoleta.NOME_SUPERMERCADO[args.loja]}: {len(eans)}")
    elif args.eans:
        eans = [e.strip() for e in args.eans]
        invalidos = [e for e in eans if not recoleta.ean_valido(e)]
        if invalidos:
            print(f"EANs inválidos (ignorados): {invalidos}")
        eans = [e for e in eans if recoleta.ean_valido(e)]
    elif args.faltantes:
        eans = [e for e in eans_faltantes_catalogo()
                if recoleta.ean_valido(e)]
    else:
        eans = eans_do_catalogo(args.catalogo)

    if args.desde:
        eans = eans[args.desde:]
    if args.limite:
        eans = eans[: args.limite]

    if not eans:
        print("Nenhum EAN a processar. Cobertura já está completa ou lote vazio.")
        return

    print("=== Atualização de preços por EAN + CEP ===")
    lojas_txt = ", ".join(recoleta.NOME_SUPERMERCADO[l] for l in lojas)
    print(f"Data: {recoleta.HOJE} | lote: {len(eans)} EANs "
          f"| lojas: {lojas_txt} | CEPs: {', '.join(recoleta.CEPS)}")
    print("-" * 72)

    # 2. Rodadas de coleta com retry apenas dos que faltaram registro/preço
    auditar = (lambda lote: auditar_sem_preco(lote, args.loja)
               if args.sem_preco else
               lambda lote: auditar_cobertura(lote, lojas))
    pendentes = eans
    for tentativa in range(1, args.max_tentativas + 1):
        stats = rodada(pendentes, args.delay, lojas)
        pendente_map = auditar(eans)
        if not pendente_map:
            print("-" * 72)
            criterio = ("todos com preço em estoque" if args.sem_preco
                        else "todo EAN tem registro nas lojas do lote")
            print(f"Cobertura completa: {criterio}.")
            break
        if tentativa < args.max_tentativas:
            pendentes = list(pendente_map.keys())
            criterio = ("sem preço" if args.sem_preco else "com registro faltante")
            print(f"-> {len(pendentes)} EAN(s) {criterio}. "
                  f"Nova tentativa ({tentativa + 1}/{args.max_tentativas})...")
            time.sleep(3)
    else:
        pendente_map = auditar(eans)

    # 3. Relatório final de cobertura
    print("-" * 72)
    registros = {
        loja: recoleta.carregar_por_ean(recoleta.ARQUIVOS[loja]) for loja in lojas
    }
    for loja in lojas:
        cob = sum(1 for e in eans if e in registros[loja])
        est = sum(1 for e in eans
                  if registros[loja].get(e, {}).get("em_estoque"))
        print(f"  {recoleta.NOME_SUPERMERCADO[loja]:<14} "
              f"registrados: {cob}/{len(eans)} | com preço em estoque: {est}")

    pendente_map = auditar(eans)
    if pendente_map:
        rotulo = ("sem preço" if args.sem_preco else "sem registro completo")
        print(f"\nATENÇÃO: {len(pendente_map)} EAN(s) {rotulo}:")
        for ean, faltantes in pendente_map.items():
            lojas_txt = ", ".join(recoleta.NOME_SUPERMERCADO[l] for l in faltantes)
            print(f"  {ean} -> faltam: {lojas_txt}")
        sys.exit(2)
    if args.sem_preco:
        print("\nConcluído: todos os EANs do lote têm preço em estoque na loja.")
    else:
        print(f"\nConcluído: cada EAN do lote possui registro em "
              f"{', '.join(recoleta.NOME_SUPERMERCADO[l] for l in lojas)}.")


if __name__ == "__main__":
    main()
