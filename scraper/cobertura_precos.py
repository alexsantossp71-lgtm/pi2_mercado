# -*- coding: utf-8 -*-
"""
Relatório de cobertura de preços — medido sobre o BANCO que alimenta a API.

Por que este script existe
--------------------------
`relatorio_cobertura.py` lê os JSONs da raiz do repositório. Esses arquivos são
um recorte parcial (apenas a seção "Mercearia", 39.833 EANs, coleta de outubro)
e não correspondem ao catálogo real servido pela API (147.541 produtos no JSON
de `webapp/`, 124.427 carregados no banco). Por isso aquele relatório reporta
percentuais que não descrevem o produto publicado.

Este script mede a cobertura onde ela importa: na tabela `precos` do banco
(SQLite local `webapp/backend/dispensa.db` ou Neon/PostgreSQL via DATABASE_URL).

Métrica central: COMPARABILIDADE
--------------------------------
O app é um comparador. Um produto só cumpre essa função se tiver preço válido
e em estoque em DUAS OU MAIS lojas. Cobertura bruta ("tem algum preço") infla o
número e esconde o gargalo real, que é a sobreposição entre lojas.

Saídas
------
  - Tabelas no console.
  - JSON em scraper/cobertura_precos.json (use --json-out para mudar).
  - Com --kpi: valida limiares mínimos e sai com código != 0 se falhar.

Uso
---
  python3 scraper/cobertura_precos.py
  python3 scraper/cobertura_precos.py --kpi
  python3 scraper/cobertura_precos.py --relevancia-min 50 --top-categorias 30
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent
DB_PADRAO = RAIZ / "webapp" / "backend" / "dispensa.db"
OUT_PADRAO = BASE / "cobertura_precos.json"

# Preço vale como "comparável" apenas se estiver em estoque e com valor > 0.
PRECO_VALIDO = (
    "em_estoque = TRUE AND COALESCE(preco_promocional, preco_regular) > 0"
)

FAIXAS_RELEVANCIA = [
    (90, 100, "90-100  curado forte"),
    (70, 89, "70-89   curado"),
    (50, 69, "50-69   medio"),
    (20, 49, "20-49   fraco"),
    (9, 19, "9-19    residual"),
    (0, 8, "0-8     cauda longa"),
]

# Limiares do gate --kpi. São metas de projeto, não garantias do estado atual.
KPI = {
    "catalogo_com_preco_pct": 80.0,
    "comparaveis_nucleo_pct": 60.0,   # entre produtos com relevancia >= nucleo
    "idade_maxima_dias": 30,
    "lojas_ativas_min": 2,
}


# --------------------------------------------------------------------------- #
# Conexão
# --------------------------------------------------------------------------- #
class Conexao:
    """Envelopa SQLite e PostgreSQL com a mesma interface mínima."""

    def __init__(self, conn, is_postgres: bool, rotulo: str):
        self.conn = conn
        self.is_postgres = is_postgres
        self.rotulo = rotulo

    def q(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        if self.is_postgres:
            sql = sql.replace("?", "%s")
        cur.execute(sql, params)
        linhas = cur.fetchall()
        cur.close()
        return [tuple(r) for r in linhas]

    def um(self, sql: str, params: tuple = ()):
        r = self.q(sql, params)
        return r[0] if r else None

    def close(self):
        self.conn.close()


def abrir_conexao(caminho_db: Path | None) -> Conexao:
    url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if url:
        import psycopg2  # import tardio: só necessário no modo Postgres

        conn = psycopg2.connect(url.strip().strip("'\""), connect_timeout=15)
        return Conexao(conn, True, "Neon/PostgreSQL (DATABASE_URL)")

    caminho = caminho_db or DB_PADRAO
    if not caminho.exists():
        raise SystemExit(
            f"Banco não encontrado em {caminho}.\n"
            "Defina DATABASE_URL para medir o Neon ou use --db para apontar o SQLite."
        )
    conn = sqlite3.connect(str(caminho))
    return Conexao(conn, False, f"SQLite {caminho}")


# --------------------------------------------------------------------------- #
# Coleta de métricas
# --------------------------------------------------------------------------- #
def pct(parte: int, total: int) -> float:
    return round(parte / total * 100, 2) if total else 0.0


def metricas_globais(db: Conexao) -> dict:
    total = db.um("SELECT COUNT(*) FROM produtos")[0]
    linhas = db.um("SELECT COUNT(*) FROM precos")[0]
    com_preco = db.um("SELECT COUNT(DISTINCT produto_id) FROM precos")[0]
    com_valido = db.um(
        f"SELECT COUNT(DISTINCT produto_id) FROM precos WHERE {PRECO_VALIDO}"
    )[0]
    return {
        "produtos_catalogo": total,
        "linhas_preco": linhas,
        "produtos_com_preco": com_preco,
        "produtos_com_preco_pct": pct(com_preco, total),
        "produtos_sem_preco": total - com_preco,
        "produtos_sem_preco_pct": pct(total - com_preco, total),
        "produtos_com_preco_valido": com_valido,
        "produtos_com_preco_valido_pct": pct(com_valido, total),
    }


def metricas_por_loja(db: Conexao, total: int) -> list[dict]:
    linhas = db.q(
        f"""SELECT l.id, l.nome,
                   COUNT(p.id),
                   SUM(CASE WHEN {PRECO_VALIDO} THEN 1 ELSE 0 END),
                   MIN(p.data_coleta), MAX(p.data_coleta)
            FROM lojas l LEFT JOIN precos p ON p.loja_id = l.id
            GROUP BY l.id, l.nome ORDER BY COUNT(p.id) DESC"""
    )
    saida = []
    for lid, nome, n, validos, dmin, dmax in linhas:
        n = n or 0
        validos = validos or 0
        # A data MÁXIMA engana quando um punhado de linhas foi recoletado:
        # o Carrefour tem 46 linhas de outubro sobre ~91 mil de setembro.
        # A data predominante descreve melhor a idade real do lote.
        datas = db.q(
            "SELECT data_coleta, COUNT(*) FROM precos WHERE loja_id = ? "
            "AND data_coleta IS NOT NULL GROUP BY data_coleta ORDER BY COUNT(*) DESC",
            (lid,),
        )
        dominante, n_dominante = (datas[0] if datas else (None, 0))
        saida.append({
            "loja_id": lid,
            "loja": nome,
            "linhas_preco": n,
            "cobertura_catalogo_pct": pct(n, total),
            "precos_validos": validos,
            "precos_validos_pct": pct(validos, total),
            "data_coleta_min": str(dmin) if dmin else None,
            "data_coleta_max": str(dmax) if dmax else None,
            "data_coleta_dominante": str(dominante) if dominante else None,
            "linhas_na_data_dominante": n_dominante,
            "pct_na_data_dominante": pct(n_dominante, n),
            "idade_dias": idade_em_dias(dominante),
            "idade_dias_mais_recente": idade_em_dias(dmax),
            "datas_distintas": len(datas),
        })
    return saida


def idade_em_dias(valor) -> int | None:
    if not valor:
        return None
    if isinstance(valor, (date, datetime)):
        d = valor.date() if isinstance(valor, datetime) else valor
    else:
        try:
            d = datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return (date.today() - d).days


def comparabilidade(db: Conexao, total: int) -> dict:
    dist = dict(db.q(
        f"""SELECT nl, COUNT(*) FROM (
                SELECT produto_id, COUNT(DISTINCT loja_id) AS nl
                FROM precos WHERE {PRECO_VALIDO} GROUP BY produto_id
            ) t GROUP BY nl ORDER BY nl"""
    ))
    com2 = sum(v for k, v in dist.items() if k >= 2)
    com3 = sum(v for k, v in dist.items() if k >= 3)
    return {
        "distribuicao_por_n_lojas": {str(k): v for k, v in sorted(dist.items())},
        "produtos_1_loja": dist.get(1, 0),
        "produtos_1_loja_pct": pct(dist.get(1, 0), total),
        "comparaveis_2mais": com2,
        "comparaveis_2mais_pct": pct(com2, total),
        "comparaveis_3mais": com3,
        "comparaveis_3mais_pct": pct(com3, total),
    }


def sobreposicao_pares(db: Conexao) -> list[dict]:
    lojas = db.q("SELECT id, nome FROM lojas ORDER BY id")
    conjuntos = {}
    for lid, nome in lojas:
        ids = db.q(
            f"SELECT DISTINCT produto_id FROM precos WHERE loja_id = ? AND {PRECO_VALIDO}",
            (lid,),
        )
        conjuntos[lid] = (nome, {r[0] for r in ids})
    saida = []
    ordenadas = sorted(conjuntos, key=lambda k: -len(conjuntos[k][1]))
    for i, a in enumerate(ordenadas):
        for b in ordenadas[i + 1:]:
            na, sa = conjuntos[a]
            nb, sb = conjuntos[b]
            comum = len(sa & sb)
            menor = min(len(sa), len(sb))
            saida.append({
                "loja_a": na, "loja_b": nb,
                "itens_a": len(sa), "itens_b": len(sb),
                "em_comum": comum,
                "pct_do_menor": pct(comum, menor),
            })
    return saida


def por_faixa_relevancia(db: Conexao, total: int) -> list[dict]:
    saida = []
    for lo, hi, rotulo in FAIXAS_RELEVANCIA:
        linha = db.um(
            f"""SELECT COUNT(*),
                   SUM(CASE WHEN EXISTS (SELECT 1 FROM precos x
                        WHERE x.produto_id = pr.id) THEN 1 ELSE 0 END),
                   SUM(CASE WHEN (SELECT COUNT(DISTINCT x.loja_id) FROM precos x
                        WHERE x.produto_id = pr.id AND {PRECO_VALIDO}) >= 2
                        THEN 1 ELSE 0 END)
                FROM produtos pr WHERE pr.relevancia BETWEEN ? AND ?""",
            (lo, hi),
        )
        n, cp, c2 = linha[0], linha[1] or 0, linha[2] or 0
        if not n:
            continue
        saida.append({
            "faixa": rotulo, "min": lo, "max": hi,
            "produtos": n, "pct_catalogo": pct(n, total),
            "com_preco": cp, "com_preco_pct": pct(cp, n),
            "comparaveis_2mais": c2, "comparaveis_2mais_pct": pct(c2, n),
        })
    return saida


def nucleo_util(db: Conexao, relevancia_min: int) -> dict:
    linha = db.um(
        f"""SELECT COUNT(*),
               SUM(CASE WHEN EXISTS (SELECT 1 FROM precos x
                    WHERE x.produto_id = pr.id) THEN 1 ELSE 0 END),
               SUM(CASE WHEN (SELECT COUNT(DISTINCT x.loja_id) FROM precos x
                    WHERE x.produto_id = pr.id AND {PRECO_VALIDO}) >= 2
                    THEN 1 ELSE 0 END),
               SUM(CASE WHEN (SELECT COUNT(DISTINCT x.loja_id) FROM precos x
                    WHERE x.produto_id = pr.id AND {PRECO_VALIDO}) >= 3
                    THEN 1 ELSE 0 END)
            FROM produtos pr WHERE pr.relevancia >= ?""",
        (relevancia_min,),
    )
    n, cp, c2, c3 = linha[0], linha[1] or 0, linha[2] or 0, linha[3] or 0
    return {
        "relevancia_min": relevancia_min,
        "produtos": n,
        "com_preco": cp, "com_preco_pct": pct(cp, n),
        "comparaveis_2mais": c2, "comparaveis_2mais_pct": pct(c2, n),
        "comparaveis_3mais": c3, "comparaveis_3mais_pct": pct(c3, n),
    }


def por_categoria(db: Conexao, limite: int) -> list[dict]:
    linhas = db.q(
        f"""SELECT pr.categoria, COUNT(*) AS n,
               SUM(CASE WHEN EXISTS (SELECT 1 FROM precos x
                    WHERE x.produto_id = pr.id) THEN 1 ELSE 0 END),
               SUM(CASE WHEN (SELECT COUNT(DISTINCT x.loja_id) FROM precos x
                    WHERE x.produto_id = pr.id AND {PRECO_VALIDO}) >= 2
                    THEN 1 ELSE 0 END)
            FROM produtos pr GROUP BY pr.categoria ORDER BY n DESC"""
    )
    saida = []
    for cat, n, cp, c2 in linhas[:limite]:
        saida.append({
            "categoria": cat, "produtos": n,
            "com_preco": cp or 0, "com_preco_pct": pct(cp or 0, n),
            "comparaveis_2mais": c2 or 0, "comparaveis_2mais_pct": pct(c2 or 0, n),
        })
    return saida


def categorias_duplicadas(db: Conexao) -> list[dict]:
    """Detecta categorias que diferem só por caixa/acento — fragmentam o catálogo."""
    linhas = db.q("SELECT categoria, COUNT(*) FROM produtos GROUP BY categoria")
    import unicodedata

    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.lower().strip()

    grupos: dict[str, list] = {}
    for cat, n in linhas:
        grupos.setdefault(norm(cat), []).append({"categoria": cat, "produtos": n})
    return [
        {"chave": k, "variantes": sorted(v, key=lambda x: -x["produtos"])}
        for k, v in sorted(grupos.items()) if len(v) > 1
    ]


def qualidade_catalogo(db: Conexao, total: int) -> dict:
    """Produtos que existem no banco mas não servem ao usuário.

    O importador cadastra automaticamente preços "órfãos" (EAN visto na coleta
    sem ficha no catálogo). Eles entram como 'Produto EAN <numero>', sem nome
    real, marca ou imagem. Contam como catálogo e nunca viram comparação.
    """
    placeholder = db.um(
        "SELECT COUNT(*) FROM produtos WHERE nome LIKE 'Produto EAN %'"
    )[0]
    sem_marca = db.um(
        "SELECT COUNT(*) FROM produtos WHERE marca IN "
        "('Não Informada', 'Não Informado', '') OR marca IS NULL"
    )[0]
    sem_imagem = db.um(
        "SELECT COUNT(*) FROM produtos WHERE imagem_url IS NULL OR imagem_url = ''"
    )[0]

    util = total - placeholder
    uteis_com_preco = db.um(
        "SELECT COUNT(*) FROM produtos pr WHERE pr.nome NOT LIKE 'Produto EAN %' "
        "AND EXISTS (SELECT 1 FROM precos x WHERE x.produto_id = pr.id)"
    )[0]
    uteis_comparaveis = db.um(
        f"""SELECT COUNT(*) FROM produtos pr
            WHERE pr.nome NOT LIKE 'Produto EAN %'
              AND (SELECT COUNT(DISTINCT x.loja_id) FROM precos x
                   WHERE x.produto_id = pr.id AND {PRECO_VALIDO}) >= 2"""
    )[0]

    eans = [r[0] for r in db.q("SELECT gtin_ean FROM produtos WHERE gtin_ean IS NOT NULL")]
    invalidos = sum(1 for e in eans if not ean13_valido(str(e)))

    return {
        "produtos_placeholder": placeholder,
        "produtos_placeholder_pct": pct(placeholder, total),
        "produtos_sem_marca": sem_marca,
        "produtos_sem_marca_pct": pct(sem_marca, total),
        "produtos_sem_imagem": sem_imagem,
        "produtos_sem_imagem_pct": pct(sem_imagem, total),
        "ean13_invalido": invalidos,
        "ean13_invalido_pct": pct(invalidos, total),
        "catalogo_util": util,
        "catalogo_util_com_preco": uteis_com_preco,
        "catalogo_util_com_preco_pct": pct(uteis_com_preco, util),
        "catalogo_util_comparavel": uteis_comparaveis,
        "catalogo_util_comparavel_pct": pct(uteis_comparaveis, util),
    }


def ean13_valido(ean: str) -> bool:
    if not ean or len(ean) != 13 or not ean.isdigit():
        return False
    soma = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(ean[:12]))
    return (10 - soma % 10) % 10 == int(ean[12])


def integridade(db: Conexao, total: int) -> dict:
    sem_ean = db.um(
        "SELECT COUNT(*) FROM produtos WHERE gtin_ean IS NULL OR TRIM(gtin_ean) = ''"
    )[0]
    distintos = db.um(
        "SELECT COUNT(DISTINCT gtin_ean) FROM produtos "
        "WHERE gtin_ean IS NOT NULL AND TRIM(gtin_ean) <> ''"
    )[0]
    dup = db.um(
        """SELECT COUNT(*) FROM (
               SELECT gtin_ean FROM produtos
               WHERE gtin_ean IS NOT NULL AND TRIM(gtin_ean) <> ''
               GROUP BY gtin_ean HAVING COUNT(*) > 1) t"""
    )[0]
    orfaos = db.um(
        "SELECT COUNT(*) FROM precos p WHERE NOT EXISTS "
        "(SELECT 1 FROM produtos pr WHERE pr.id = p.produto_id)"
    )[0]
    sem_cep = db.um("SELECT COUNT(*) FROM precos WHERE cep_coleta IS NULL")[0]
    linhas_preco = db.um("SELECT COUNT(*) FROM precos")[0]
    zerados = db.um(
        "SELECT COUNT(*) FROM precos "
        "WHERE COALESCE(preco_promocional, preco_regular) IS NULL "
        "OR COALESCE(preco_promocional, preco_regular) <= 0"
    )[0]
    return {
        "produtos_sem_ean": sem_ean,
        "eans_distintos": distintos,
        "eans_duplicados": dup,
        "precos_orfaos": orfaos,
        "precos_sem_cep": sem_cep,
        "precos_sem_cep_pct": pct(sem_cep, linhas_preco),
        "precos_sem_valor": zerados,
        "precos_sem_valor_pct": pct(zerados, linhas_preco),
    }


# --------------------------------------------------------------------------- #
# Impressão
# --------------------------------------------------------------------------- #
def barra(p: float, largura: int = 22) -> str:
    cheio = int(round(p / 100 * largura))
    return "█" * cheio + "·" * (largura - cheio)


def imprimir(rel: dict, top_categorias: int) -> None:
    g = rel["global"]
    print("=" * 78)
    print("COBERTURA DE PREÇOS — Dispensa Planejada Santos")
    print(f"Fonte: {rel['fonte']}")
    print(f"Gerado em: {rel['gerado_em']}")
    print("=" * 78)

    print("\n[1] CATÁLOGO E PREÇOS")
    print(f"  Produtos no catálogo .......... {g['produtos_catalogo']:>9,}")
    print(f"  Linhas de preço ............... {g['linhas_preco']:>9,}")
    print(f"  Produtos com algum preço ...... {g['produtos_com_preco']:>9,}"
          f"  ({g['produtos_com_preco_pct']:>5.1f}%) {barra(g['produtos_com_preco_pct'])}")
    print(f"  Produtos com preço válido ..... {g['produtos_com_preco_valido']:>9,}"
          f"  ({g['produtos_com_preco_valido_pct']:>5.1f}%) {barra(g['produtos_com_preco_valido_pct'])}")
    print(f"  Produtos sem preço nenhum ..... {g['produtos_sem_preco']:>9,}"
          f"  ({g['produtos_sem_preco_pct']:>5.1f}%)")

    print("\n[2] POR LOJA  (preço válido = em estoque e valor > 0)")
    print(f"  {'loja':<30}{'linhas':>9}{'válidos':>9}{'% cat':>8}"
          f"{'coleta dom.':>13}{'idade':>7}{'% no lote':>11}")
    for l in rel["por_loja"]:
        idade = f"{l['idade_dias']}d" if l["idade_dias"] is not None else "-"
        print(f"  {l['loja'][:29]:<30}{l['linhas_preco']:>9,}{l['precos_validos']:>9,}"
              f"{l['precos_validos_pct']:>7.1f}%"
              f"{str(l['data_coleta_dominante'] or '-'):>13}{idade:>7}"
              f"{l['pct_na_data_dominante']:>10.1f}%")
    print("  (coleta dom. = data que concentra a maior parte das linhas da loja)")

    c = rel["comparabilidade"]
    print("\n[3] COMPARABILIDADE  (métrica central do app)")
    print("  Produtos por nº de lojas com preço válido:")
    for nl, qt in c["distribuicao_por_n_lojas"].items():
        print(f"    {nl} loja(s) ... {qt:>8,}  ({pct(qt, g['produtos_catalogo']):>5.2f}%)"
              f" {barra(pct(qt, g['produtos_catalogo']))}")
    print(f"\n  >>> COMPARÁVEIS (>=2 lojas): {c['comparaveis_2mais']:,}"
          f" ({c['comparaveis_2mais_pct']}% do catálogo)")
    print(f"  >>> COMPARÁVEIS (>=3 lojas): {c['comparaveis_3mais']:,}"
          f" ({c['comparaveis_3mais_pct']}% do catálogo)")

    print("\n[4] SOBREPOSIÇÃO ENTRE LOJAS")
    print(f"  {'par':<46}{'em comum':>10}{'% do menor':>12}")
    for s in rel["sobreposicao"]:
        par = f"{s['loja_a'][:20]} x {s['loja_b'][:20]}"
        print(f"  {par:<46}{s['em_comum']:>10,}{s['pct_do_menor']:>11.1f}%")

    print("\n[5] POR FAIXA DE RELEVÂNCIA")
    print(f"  {'faixa':<22}{'produtos':>10}{'% cat':>8}{'c/ preço':>10}{'>=2 lojas':>11}{'%':>8}")
    for f in rel["por_relevancia"]:
        print(f"  {f['faixa']:<22}{f['produtos']:>10,}{f['pct_catalogo']:>7.1f}%"
              f"{f['com_preco_pct']:>9.1f}%{f['comparaveis_2mais']:>11,}"
              f"{f['comparaveis_2mais_pct']:>7.1f}%")

    n = rel["nucleo"]
    print(f"\n[6] NÚCLEO ÚTIL  (relevância >= {n['relevancia_min']})")
    print(f"  Produtos ................ {n['produtos']:>8,}")
    print(f"  Com preço ............... {n['com_preco']:>8,}  ({n['com_preco_pct']:>5.1f}%)")
    print(f"  Comparáveis >=2 lojas ... {n['comparaveis_2mais']:>8,}  ({n['comparaveis_2mais_pct']:>5.1f}%)")
    print(f"  Comparáveis >=3 lojas ... {n['comparaveis_3mais']:>8,}  ({n['comparaveis_3mais_pct']:>5.1f}%)")

    print(f"\n[7] POR CATEGORIA  (top {top_categorias} por tamanho)")
    print(f"  {'categoria':<34}{'produtos':>10}{'c/ preço':>10}{'>=2 lojas':>11}{'%':>8}")
    for cat in rel["por_categoria"]:
        print(f"  {cat['categoria'][:33]:<34}{cat['produtos']:>10,}"
              f"{cat['com_preco_pct']:>9.1f}%{cat['comparaveis_2mais']:>11,}"
              f"{cat['comparaveis_2mais_pct']:>7.1f}%")

    qc = rel["qualidade_catalogo"]
    print("\n[8] QUALIDADE DO CATÁLOGO")
    print(f"  Produtos placeholder 'Produto EAN ...' {qc['produtos_placeholder']:>9,}"
          f"  ({qc['produtos_placeholder_pct']:>5.1f}%)")
    print(f"  Sem marca identificada ............... {qc['produtos_sem_marca']:>9,}"
          f"  ({qc['produtos_sem_marca_pct']:>5.1f}%)")
    print(f"  Sem imagem ........................... {qc['produtos_sem_imagem']:>9,}"
          f"  ({qc['produtos_sem_imagem_pct']:>5.1f}%)")
    print(f"  EAN-13 com dígito verificador inválido {qc['ean13_invalido']:>9,}"
          f"  ({qc['ean13_invalido_pct']:>5.1f}%)")
    print(f"  --> catálogo útil (sem placeholders) . {qc['catalogo_util']:>9,}")
    print(f"      com preço ........................ {qc['catalogo_util_com_preco']:>9,}"
          f"  ({qc['catalogo_util_com_preco_pct']:>5.1f}%)")
    print(f"      comparável >=2 lojas ............. {qc['catalogo_util_comparavel']:>9,}"
          f"  ({qc['catalogo_util_comparavel_pct']:>5.2f}%)")

    i = rel["integridade"]
    print("\n[9] INTEGRIDADE")
    print(f"  Produtos sem EAN .............. {i['produtos_sem_ean']:>9,}")
    print(f"  EANs distintos ................ {i['eans_distintos']:>9,}")
    print(f"  EANs duplicados ............... {i['eans_duplicados']:>9,}")
    print(f"  Preços órfãos (sem produto) ... {i['precos_orfaos']:>9,}")
    print(f"  Preços sem valor .............. {i['precos_sem_valor']:>9,}  ({i['precos_sem_valor_pct']:>5.1f}%)")
    print(f"  Preços sem CEP de coleta ...... {i['precos_sem_cep']:>9,}  ({i['precos_sem_cep_pct']:>5.1f}%)")

    if rel["categorias_duplicadas"]:
        print("\n[10] CATEGORIAS FRAGMENTADAS  (mesma categoria, grafias diferentes)")
        for grupo in rel["categorias_duplicadas"]:
            vs = " | ".join(f"{v['categoria']} ({v['produtos']:,})" for v in grupo["variantes"])
            print(f"  - {vs}")


def avaliar_kpi(rel: dict) -> list[str]:
    falhas = []
    g, n = rel["global"], rel["nucleo"]
    if g["produtos_com_preco_pct"] < KPI["catalogo_com_preco_pct"]:
        falhas.append(
            f"catálogo com preço {g['produtos_com_preco_pct']}% "
            f"< meta {KPI['catalogo_com_preco_pct']}%"
        )
    if n["comparaveis_2mais_pct"] < KPI["comparaveis_nucleo_pct"]:
        falhas.append(
            f"núcleo comparável {n['comparaveis_2mais_pct']}% "
            f"< meta {KPI['comparaveis_nucleo_pct']}%"
        )
    ativas = [l for l in rel["por_loja"] if l["linhas_preco"] > 0]
    if len(ativas) < KPI["lojas_ativas_min"]:
        falhas.append(f"apenas {len(ativas)} loja(s) com preços")
    for l in ativas:
        if l["idade_dias"] is not None and l["idade_dias"] > KPI["idade_maxima_dias"]:
            falhas.append(
                f"{l['loja']}: coleta com {l['idade_dias']} dias "
                f"> limite {KPI['idade_maxima_dias']}"
            )
    return falhas


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Relatório de cobertura de preços medido sobre o banco."
    )
    ap.add_argument("--db", type=Path, default=None,
                    help="Caminho do SQLite (padrão: webapp/backend/dispensa.db). "
                         "Ignorado se DATABASE_URL estiver definida.")
    ap.add_argument("--json-out", type=Path, default=OUT_PADRAO,
                    help="Arquivo JSON de saída.")
    ap.add_argument("--relevancia-min", type=int, default=50,
                    help="Corte de relevância que define o núcleo útil (padrão: 50).")
    ap.add_argument("--top-categorias", type=int, default=20,
                    help="Quantas categorias listar (padrão: 20).")
    ap.add_argument("--kpi", action="store_true",
                    help="Valida os limiares e sai com código != 0 se falhar.")
    args = ap.parse_args()

    db = abrir_conexao(args.db)
    try:
        g = metricas_globais(db)
        total = g["produtos_catalogo"]
        rel = {
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
            "fonte": db.rotulo,
            "global": g,
            "por_loja": metricas_por_loja(db, total),
            "comparabilidade": comparabilidade(db, total),
            "sobreposicao": sobreposicao_pares(db),
            "por_relevancia": por_faixa_relevancia(db, total),
            "nucleo": nucleo_util(db, args.relevancia_min),
            "por_categoria": por_categoria(db, args.top_categorias),
            "qualidade_catalogo": qualidade_catalogo(db, total),
            "categorias_duplicadas": categorias_duplicadas(db),
            "integridade": integridade(db, total),
            "kpi_metas": KPI,
        }
    finally:
        db.close()

    imprimir(rel, args.top_categorias)

    falhas = avaliar_kpi(rel)
    rel["kpi_falhas"] = falhas

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(rel, f, ensure_ascii=False, indent=2)
    print(f"\nJSON gravado em {args.json_out}")

    if args.kpi:
        if falhas:
            print("\n[KPI FALHOU]")
            for f in falhas:
                print(f"  - {f}")
            sys.exit(1)
        print("\n[KPI OK] todos os limiares atendidos.")


if __name__ == "__main__":
    main()
