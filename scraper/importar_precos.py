# -*- coding: utf-8 -*-
"""
Importa preços dos JSONs para o banco, sem recriar o catálogo.

Por que existe
--------------
`webapp/backend/importar_json_para_sqlite.py` apaga o banco e reconstrói tudo
a partir de `webapp/*.json`. Isso tem dois problemas:

  1. desfaz a consolidação do Soudaki (os pares aplicados em
     `scraper/parear_soudaki_pa.py --aplicar` se perdem);
  2. lê só `webapp/`, ignorando coletas maiores guardadas na raiz do
     repositório e em `scraper/`.

O levantamento das coletas disponíveis mostrou o tamanho do que ficava de
fora — por exemplo, 20.792 preços do Atacadão na raiz contra 3.799 no banco.

Regra de frescor
----------------
Um preço só é gravado quando é MAIS NOVO que o que já está no banco. Coleta
antiga nunca sobrescreve coleta recente; serve apenas para preencher buracos
(produto que não tem preço nenhum daquela loja). A data real da coleta é
preservada em `data_coleta`, então a idade de cada preço continua auditável.

Uso
---
    python3 scraper/importar_precos.py              # simula
    python3 scraper/importar_precos.py --aplicar    # grava (faz backup)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB_PADRAO = RAIZ / "webapp" / "backend" / "dispensa.db"

LOJAS = {"carrefour": 1, "pao_de_acucar": 2, "atacadao": 3, "soudaki": 4}

# Todas as coletas conhecidas. A regra de frescor decide quem prevalece, então
# listar uma coleta antiga é seguro: ela só preenche o que estiver vazio.
FONTES_PRECOS = [
    # (caminho relativo à raiz, chave da loja)
    ("precos_carrefour_ampliado.json", "carrefour"),
    ("precos_pao_de_acucar_ampliado.json", "pao_de_acucar"),
    ("precos_atacadao_ampliado.json", "atacadao"),
    ("scraper/precos_carrefour_ampliado.json", "carrefour"),
    ("scraper/precos_pao_de_acucar_ampliado.json", "pao_de_acucar"),
    ("scraper/precos_atacadao_ampliado.json", "atacadao"),
    ("scraper/precos_soudaki_ampliado.json", "soudaki"),
    ("scraper/precos_carrefour_matinais.json", "carrefour"),
    ("scraper/precos_pao_de_acucar_matinais.json", "pao_de_acucar"),
    ("webapp/precos_carrefour_ampliado.json", "carrefour"),
    ("webapp/precos_pao_de_acucar_ampliado.json", "pao_de_acucar"),
    ("webapp/precos_atacadao_ampliado.json", "atacadao"),
    ("webapp/precos_atacadao_matinais.json", "atacadao"),
    ("webapp/precos_soudaki_ampliado.json", "soudaki"),
]

# Catálogos usados para criar produtos que têm preço mas não existem na base.
FONTES_PRODUTOS = [
    "scraper/produtos_ampliado.json",
    "produtos_ampliado.json",
    "scraper/produtos_carrefour.json",
    "scraper/produtos_pa.json",
    "scraper/produtos_atacadao.json",
    "scraper/produtos_soudaki.json",
    "webapp/produtos_matinais.json",
]


def ean13_valido(ean) -> bool:
    e = str(ean or "").strip()
    if len(e) != 13 or not e.isdigit():
        return False
    s = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(e[:12]))
    return (10 - s % 10) % 10 == int(e[12])


def para_float(v):
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def para_bool(v) -> int:
    return 1 if str(v).strip().lower() in ("true", "1", "sim", "yes") else 0


def data_de(reg) -> str:
    """Data de coleta normalizada para AAAA-MM-DD. Vazia ordena como a mais antiga."""
    return str(reg.get("data_coleta") or "")[:10]


def carregar_json(caminho: Path):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def ler_precos() -> tuple[dict, list]:
    """Melhor preço por (ean, loja): o mais recente entre todas as fontes."""
    melhor: dict[tuple[str, int], dict] = {}
    resumo = []
    for rel, chave in FONTES_PRECOS:
        caminho = RAIZ / rel
        if not caminho.exists():
            continue
        dados = carregar_json(caminho)
        if not isinstance(dados, list):
            resumo.append((rel, chave, 0, 0, "-", "ilegível"))
            continue

        loja = LOJAS[chave]
        validos = novos = 0
        datas = Counter()
        for reg in dados:
            ean = str(reg.get("gtin_ean") or "").strip()
            if not ean13_valido(ean):
                continue
            # Preço de outra praça não entra: o comparador é de Santos.
            # O arquivo de agosto do Atacadão traz 6 registros da capital.
            cep = str(reg.get("cep_coleta") or "").strip()
            if cep and not cep.startswith("11"):
                continue
            preco = para_float(reg.get("preco_promocional")) or \
                para_float(reg.get("preco_regular"))
            if preco is None:
                continue
            validos += 1
            dt = data_de(reg)
            datas[dt[:7]] += 1
            k = (ean, loja)
            if k not in melhor or dt > melhor[k]["data"]:
                if k not in melhor:
                    novos += 1
                melhor[k] = {
                    "data": dt,
                    "promocional": para_float(reg.get("preco_promocional")) or preco,
                    "regular": para_float(reg.get("preco_regular")) or preco,
                    "estoque": para_bool(reg.get("em_estoque")),
                }
        faixa = f"{min(datas)}..{max(datas)}" if datas else "-"
        resumo.append((rel, chave, len(dados), validos, faixa, ""))
    return melhor, resumo


def ler_metadados(eans: set[str]) -> dict:
    """Metadados só dos EANs pedidos, para não carregar catálogos inteiros."""
    meta: dict[str, dict] = {}
    for rel in FONTES_PRODUTOS:
        caminho = RAIZ / rel
        if not caminho.exists() or not eans - set(meta):
            continue
        dados = carregar_json(caminho)
        if not isinstance(dados, list):
            continue
        for reg in dados:
            ean = str(reg.get("gtin_ean") or "").strip()
            if ean in eans and ean not in meta:
                nome = (reg.get("nome_completo") or reg.get("nome") or "").strip()
                if nome:
                    meta[ean] = reg
    return meta


def apresentacao_de(reg) -> str | None:
    raw = reg.get("apresentacao")
    if isinstance(raw, dict):
        qtd, un = raw.get("quantidade"), raw.get("unidade_medida") or ""
        return f"{qtd}{un}" if qtd is not None else None
    return str(raw) if raw else None


def importar(db: sqlite3.Connection, aplicar: bool, caminho_db: Path,
              criar_produtos: bool = False) -> dict:
    cur = db.cursor()

    print("Lendo coletas...")
    melhor, resumo = ler_precos()
    print(f"\n{'ARQUIVO':<48}{'LOJA':<15}{'REG':>8}{'VÁLIDOS':>9}  PERÍODO")
    print("-" * 94)
    for rel, chave, total, validos, faixa, obs in resumo:
        print(f"{rel:<48}{chave:<15}{total:>8}{validos:>9}  {faixa} {obs}")
    print(f"\n  {len(melhor)} pares (produto, loja) distintos nas coletas")

    # Estado atual
    cat = {r[0]: r[1] for r in cur.execute(
        "SELECT gtin_ean, id FROM produtos WHERE gtin_ean IS NOT NULL")}
    atual = {}
    for pid, loja, dt, ean in cur.execute(
            "SELECT pr.produto_id, pr.loja_id, pr.data_coleta, p.gtin_ean "
            "FROM precos pr JOIN produtos p ON p.id = pr.produto_id "
            "WHERE p.gtin_ean IS NOT NULL"):
        atual[(ean, loja)] = (pid, str(dt or "")[:10])

    inserir, atualizar, ignorar = [], [], 0
    for (ean, loja), reg in melhor.items():
        if (ean, loja) in atual:
            pid, dt_db = atual[(ean, loja)]
            if reg["data"] > dt_db:
                atualizar.append((ean, loja, reg, pid))
            else:
                ignorar += 1
        else:
            inserir.append((ean, loja, reg))

    faltantes = {e for e, _, _ in inserir if e not in cat}
    print(f"  {len(faltantes)} EANs com preço não existem no catálogo")

    # Criar esses produtos foi medido e rende pouco: de 21.982 criados numa
    # execução de teste, só 28 (0,1%) ficaram comparáveis — os outros 21.954
    # entram com uma loja só, inflando o catálogo em 18% e o arquivo do banco
    # de 67 para 81 MB. O ganho de comparabilidade vem de preencher preços em
    # produtos que JÁ existem. Por isso o padrão é não criar.
    meta = {}
    if criar_produtos:
        meta = ler_metadados(faltantes) if faltantes else {}
        print(f"  metadados encontrados para {len(meta)}; "
              f"{len(faltantes - set(meta))} ficam de fora (sem nome)")
    else:
        print("  (não serão criados; use --criar-produtos para incluí-los)")

    inserir = [x for x in inserir if x[0] in cat or x[0] in meta]

    print("\n" + "=" * 70)
    print("PLANO")
    print("=" * 70)
    print(f"  produtos a criar ........ {len(meta)}")
    print(f"  preços a inserir ........ {len(inserir)}")
    print(f"  preços a atualizar ...... {len(atualizar)}  (coleta mais recente)")
    print(f"  preços ignorados ........ {ignorar}  (banco já tem igual ou mais novo)")

    por_loja = Counter()
    for ean, loja, _ in inserir:
        por_loja[loja] += 1
    inv = {v: k for k, v in LOJAS.items()}
    if por_loja:
        print("\n  novos preços por loja:")
        for loja, n in sorted(por_loja.items()):
            print(f"    {inv[loja]:<16} {n:>7}")

    if not aplicar:
        print("\nSimulação. Use --aplicar para gravar.")
        return {}

    backup = caminho_db.with_suffix(f".bak-{datetime.now():%Y%m%d%H%M%S}.db")
    shutil.copy2(caminho_db, backup)
    print(f"\n  backup: {backup}")

    # Produtos novos, em ordem estável de EAN.
    criados = 0
    for ean in sorted(meta):
        reg = meta[ean]
        nome = (reg.get("nome_completo") or reg.get("nome") or "").strip()
        categoria = (reg.get("subsecao") or reg.get("secao")
                     or reg.get("categoria") or "Geral")
        cur.execute(
            "INSERT INTO produtos (gtin_ean, nome, categoria, marca, "
            "relevancia, imagem_url, apresentacao) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ean, nome, categoria, reg.get("marca") or "Não Informada", 0,
             reg.get("imagem_url"), apresentacao_de(reg)))
        pid = cur.lastrowid
        cur.execute(
            "INSERT INTO produtos_fts (id, nome, categoria, marca) "
            "VALUES (?, ?, ?, ?)",
            (pid, nome, categoria, reg.get("marca") or "Não Informada"))
        cat[ean] = pid
        criados += 1

    inseridos = 0
    for ean, loja, reg in sorted(inserir, key=lambda x: (x[0], x[1])):
        cur.execute(
            "INSERT INTO precos (produto_id, loja_id, preco_promocional, "
            "preco_regular, em_estoque, cep_coleta, data_coleta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cat[ean], loja, reg["promocional"], reg["regular"],
             reg["estoque"], None, reg["data"]))
        inseridos += 1

    atualizados = 0
    for ean, loja, reg, pid in sorted(atualizar, key=lambda x: (x[0], x[1])):
        cur.execute(
            "UPDATE precos SET preco_promocional = ?, preco_regular = ?, "
            "em_estoque = ?, data_coleta = ? WHERE produto_id = ? AND loja_id = ?",
            (reg["promocional"], reg["regular"], reg["estoque"], reg["data"],
             pid, loja))
        atualizados += 1

    db.commit()
    print(f"  produtos criados ... {criados}")
    print(f"  preços inseridos ... {inseridos}")
    print(f"  preços atualizados . {atualizados}")
    print("  compactando (VACUUM)...")
    db.execute("VACUUM")
    print(f"  arquivo: {caminho_db.stat().st_size:,} bytes".replace(",", "."))
    return {"criados": criados, "inseridos": inseridos,
            "atualizados": atualizados}


def relatar(db: sqlite3.Connection) -> None:
    q = lambda s: db.execute(s).fetchone()[0]  # noqa: E731
    print("\n" + "=" * 70)
    print("ESTADO DO BANCO")
    print("=" * 70)
    print(f"  produtos ................ {q('SELECT COUNT(*) FROM produtos'):>8}")
    print(f"  preços .................. {q('SELECT COUNT(*) FROM precos'):>8}")
    for lid, chave in db.execute("SELECT id, chave FROM lojas ORDER BY id"):
        n = db.execute("SELECT COUNT(*) FROM precos WHERE loja_id=?",
                       (lid,)).fetchone()[0]
        print(f"    {chave:<18} {n:>8}")
    comp = q("SELECT COUNT(*) FROM (SELECT produto_id FROM precos "
             "GROUP BY produto_id HAVING COUNT(DISTINCT loja_id) >= 2)")
    total = q("SELECT COUNT(*) FROM produtos")
    print(f"  comparáveis (>=2 lojas) . {comp:>8}  ({comp/max(total,1)*100:.2f}%)")
    print("\n  idade dos preços:")
    for mes, n in db.execute(
            "SELECT substr(data_coleta,1,7) m, COUNT(*) FROM precos "
            "GROUP BY m ORDER BY m"):
        print(f"    {mes}  {n:>8}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Importa preços para o banco.")
    ap.add_argument("--db", type=Path, default=DB_PADRAO)
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--criar-produtos", action="store_true",
                    help="Também cria produtos que têm preço mas não estão no "
                         "catálogo. Medido: +18%% de catálogo para +0,1%% de "
                         "comparáveis.")
    args = ap.parse_args()

    if not args.db.exists():
        sys.exit(f"Banco não encontrado: {args.db}")

    db = sqlite3.connect(str(args.db))
    try:
        importar(db, args.aplicar, args.db, args.criar_produtos)
        if args.aplicar:
            relatar(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
