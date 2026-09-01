# -*- coding: utf-8 -*-
"""
Relatório de cobertura por categoria (secao/subsecao) do scrape CEP-fallback.

Lê os 3 arquivos de preços na RAIZ e o catálogo unificado, e emite:
  - total de EANs do universo;
  - por secao (e subsecao): nº de EANs, % em_estoque por loja, % em_estoque
    em >=2 das 3 lojas;
  - EANs ainda sem registro por loja (para re-run);
  - divisão dos valores de cep_coleta (Santos 11060-002 vs fallback).

Saída: tabela no console + JSON em scraper/relatorio_cobertura.json.
Com --kpi, faz a validação de gate (cada categoria não-isenta precisa >=50%
em_estoque em >=2 das 3 lojas) e sai com código != 0 se alguma falhar.

BASELINE ACEITA (2026-08-30): a cobertura atual é o baseline aprovado.
Limitações conhecidas que impedem elevar o % em estoque por re-coleta:
  - Carrefour bloqueia automação: piloto com Playwright habilitado em 12 EANs
    Alimentos retornou catalogo_bloqueado em 12/12.
  - Atacadão retorna nao_cadastrado para boa parte do catálogo: gap real de
    sortimento, não falha de coleta.
O gate --kpi é mantido apenas como diagnóstico, não como critério de aprovação.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE)

LOJAS = ("atacadao", "carrefour", "pao_de_acucar")
NOME = {"atacadao": "Atacadão", "carrefour": "Carrefour",
        "pao_de_acucar": "Pão de Açúcar"}
ARQ = {l: os.path.join(RAIZ, f"precos_{l}_ampliado.json") for l in LOJAS}
CATALOGO = os.path.join(RAIZ, "produtos_ampliado.json")
OUT = os.path.join(BASE, "relatorio_cobertura.json")

CEP_SANTOS = "11060-002"
EXEMPT = {"Bazar", "Descartáveis", "Petshop"}
THRESHOLD = 0.50


def carregar_por_ean(caminho):
    if not os.path.exists(caminho):
        return {}
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    recs = dados if isinstance(dados, list) else dados.get("precos", dados)
    m = {}
    for r in recs:
        e = str(r.get("gtin_ean") or "").strip()
        if e:
            m[e] = r
    return m


def carregar_catalogo():
    with open(CATALOGO, "r", encoding="utf-8") as f:
        dados = json.load(f)
    prods = dados.get("produtos", dados) if isinstance(dados, dict) else dados
    meta = {}
    for p in prods:
        e = str(p.get("gtin_ean") or "").strip()
        if e and e not in meta:
            meta[e] = {
                "secao": (p.get("secao") or "SEM_SECAO").strip() or "SEM_SECAO",
                "subsecao": (p.get("subsecao") or "").strip(),
                "nome_completo": p.get("nome_completo") or "",
            }
    return meta


def main():
    ap = argparse.ArgumentParser(description="Relatório de cobertura por categoria.")
    ap.add_argument("--kpi", action="store_true",
                    help="Valida o gate KPI e sai !=0 se alguma categoria falhar.")
    args = ap.parse_args()

    catalogo = carregar_catalogo()
    universo = list(catalogo.keys())
    precos = {l: carregar_por_ean(ARQ[l]) for l in LOJAS}

    # Por secao -> eans
    por_secao = defaultdict(list)
    for ean in universo:
        por_secao[catalogo[ean]["secao"]].append(ean)

    linhas = []
    falhas = []
    for secao in sorted(por_secao):
        eans = por_secao[secao]
        n = len(eans)
        por_loja = {}
        em2 = 0
        for ean in eans:
            ok = 0
            for l in LOJAS:
                rec = precos[l].get(ean)
                instock = bool(rec and rec.get("em_estoque"))
                por_loja.setdefault(l, 0)
                if instock:
                    por_loja[l] += 1
                    ok += 1
            if ok >= 2:
                em2 += 1
        pct = {l: (por_loja.get(l, 0) / n * 100 if n else 0) for l in LOJAS}
        pct2 = em2 / n * 100 if n else 0
        linhas.append({
            "secao": secao,
            "eans": n,
            "em_estoque_pct": {NOME[l]: round(pct[l], 1) for l in LOJAS},
            "em_estoque_2lojas_pct": round(pct2, 1),
            "isenta": secao in EXEMPT,
        })
        if secao not in EXEMPT and pct2 < THRESHOLD * 100:
            falhas.append((secao, round(pct2, 1)))

    # EANs sem registro por loja
    sem_registro = {l: [e for e in universo if e not in precos[l]] for l in LOJAS}

    # Split cep_coleta (Santos vs fallback) por loja
    cep_split = {}
    for l in LOJAS:
        santos = fallback = 0
        for rec in precos[l].values():
            cep = rec.get("cep_coleta") or ""
            if cep == CEP_SANTOS:
                santos += 1
            else:
                fallback += 1
        cep_split[NOME[l]] = {"santos": santos, "fallback": fallback}

    total_instock = {l: sum(1 for r in precos[l].values() if r.get("em_estoque"))
                     for l in LOJAS}

    relatorio = {
        "total_eans_universo": len(universo),
        "em_estoque_total": {NOME[l]: total_instock[l] for l in LOJAS},
        "por_secao": linhas,
        "sem_registro_por_loja": {NOME[l]: len(sem_registro[l]) for l in LOJAS},
        "cep_split": cep_split,
        "exempt_categories": sorted(EXEMPT),
        "kpi_threshold_pct": THRESHOLD * 100,
        "baseline_aceita": {
            "decidido_em": "2026-08-30",
            "observacao": ("Cobertura atual aceita como baseline. Carrefour "
                           "bloqueia automacao (piloto 0/12 com Playwright); "
                           "Atacadao nao_cadastrado = gap real de sortimento. "
                           "Gate --kpi e apenas diagnostico."),
        },
    }

    # Console
    print(f"Universo de EANs: {len(universo)}")
    print("Em estoque (total): " + ", ".join(
        f"{NOME[l]}={total_instock[l]}" for l in LOJAS))
    print(f"{'secao':<22} {'EANs':>6}  " +
          "  ".join(f"{NOME[l][:10]:>10}" for l in LOJAS) + "  >=2lojas  isenta")
    for ln in linhas:
        p = ln["em_estoque_pct"]
        print(f"{ln['secao']:<22} {ln['eans']:>6}  " +
              "  ".join(f"{p[NOME[l]]:>10.1f}" for l in LOJAS) +
              f"  {ln['em_estoque_2lojas_pct']:>7.1f}  {'S' if ln['isenta'] else ''}")
    print("\nSem registro por loja: " + ", ".join(
        f"{NOME[l]}={len(sem_registro[l])}" for l in LOJAS))
    print("Split cep_coleta (Santos vs fallback):")
    for l, v in cep_split.items():
        print(f"  {l}: santos={v['santos']} fallback={v['fallback']}")
    print(f"\nCategorias isentas do KPI: {sorted(EXEMPT)}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)
    print(f"\nJSON gravado em {OUT}")

    if args.kpi:
        if falhas:
            print("\n[KPI FALHOU] categorias não-isentas abaixo de "
                  f"{THRESHOLD*100:.0f}% em >=2 lojas:")
            for secao, pct in falhas:
                print(f"  - {secao}: {pct}%")
            sys.exit(1)
        print("\n[KPI OK] todas as categorias não-isentas atendem o gate.")


if __name__ == "__main__":
    main()
