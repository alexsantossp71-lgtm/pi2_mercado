# -*- coding: utf-8 -*-
"""
Integra a coleta do Soudaki ao banco, sem poluir o catálogo.

Regras de vinculação, nesta ordem:

  1. EAN-13 válido que já existe no catálogo  -> usa o produto existente.
     É o caso ideal: o preço do Soudaki entra no mesmo `produto_id` das
     outras lojas e o item vira comparável na hora.

  2. EAN-13 válido inédito                    -> cria produto com esse EAN.
     Fica pronto para casar quando outra loja coletar o mesmo código.

  3. Sem EAN, mas com equivalente no catálogo -> usa o produto existente.
     Reaproveita o pareador de `scraper/parear_soudaki_pa.py` (marca +
     tamanho + núcleo do nome, com as guardas de polaridade e variante).

  4. Sem EAN e sem equivalente                -> cria produto exclusivo do
     Soudaki, identificado como `SKU-SOUDAKI-<sku>`.

O passo 4 é a diferença principal em relação ao integrador antigo, que
gravava o SKU interno no campo `gtin_ean`. Isso produzia códigos como
`15000004818` posando de código de barras, que nunca cruzam com outra loja
e ainda contaminam qualquer relatório que conte "produtos com EAN".

Uso
---
    python3 scraper/soudaki/integrar_soudaki.py              # simula
    python3 scraper/soudaki/integrar_soudaki.py --aplicar    # grava
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent.parent
sys.path.insert(0, str(RAIZ / "scraper"))

from parear_soudaki_pa import (  # noqa: E402
    construir_vocabulario_marcas, conflita, detectar_marca, ean13_valido,
    limpa, multipack, qualificadores, tamanho, tokens,
    variantes_incompativeis, LIMIAR_B, MIN_TOKENS_COMUNS,
)

DB_PADRAO = RAIZ / "webapp" / "backend" / "dispensa.db"
ENTRADA = BASE / "produtos_soudaki.json"
PRECOS = BASE / "precos_soudaki.json"
LOJA_SOUDAKI = 4
PREFIXO_SKU = "SKU-SOUDAKI-"


def carregar_coleta(entrada: Path, precos: Path) -> list[dict]:
    if not entrada.exists() or not precos.exists():
        sys.exit(
            f"Coleta não encontrada ({entrada}, {precos}).\n"
            "Rode antes: python3 scraper/soudaki/coletar_soudaki.py"
        )
    with open(entrada, encoding="utf-8") as f:
        produtos = json.load(f)
    with open(precos, encoding="utf-8") as f:
        precos = {p["identificador"]: p for p in json.load(f)}
    for p in produtos:
        p["preco"] = precos.get(p["identificador"])
    return [p for p in produtos if p.get("preco")]


def indexar_catalogo(cur):
    """Carrega o catálogo em memória: por EAN e por marca, para o pareamento."""
    linhas = cur.execute(
        "SELECT id, gtin_ean, nome, marca FROM produtos"
    ).fetchall()
    por_ean = {}
    for pid, ean, nome, marca in linhas:
        if ean and ean13_valido(ean):
            por_ean.setdefault(ean, pid)

    # Índice por SKU do Soudaki, para que reexecutar atualize em vez de
    # duplicar. Cobre as duas formas que existem no banco:
    #   - `SKU-SOUDAKI-<sku>`, criado por este script;
    #   - `<sku>` cru, gravado pelo coletor antigo direto em gtin_ean.
    # Só entram produtos que já têm preço do Soudaki (ou o prefixo), para não
    # capturar identificadores estranhos de outras lojas.
    com_preco_soudaki = {
        r[0] for r in cur.execute(
            "SELECT DISTINCT produto_id FROM precos WHERE loja_id = ?",
            (LOJA_SOUDAKI,))
    }
    por_sku = {}
    for pid, ean, nome, marca in linhas:
        if not ean or ean13_valido(ean):
            continue
        if ean.startswith(PREFIXO_SKU):
            por_sku.setdefault(ean[len(PREFIXO_SKU):], pid)
        elif pid in com_preco_soudaki:
            por_sku.setdefault(ean, pid)

    # Alvos válidos do casamento por atributos: só produtos vendidos por
    # ALGUMA outra loja. Casar o Soudaki com um produto exclusivo do Soudaki
    # não gera comparação nenhuma — e, pior, torna o script não idempotente:
    # na segunda execução os itens passariam a casar com as próprias linhas
    # criadas na primeira, embaralhando o resultado a cada rodada.
    com_outra_loja = {
        r[0] for r in cur.execute(
            "SELECT DISTINCT produto_id FROM precos WHERE loja_id <> ?",
            (LOJA_SOUDAKI,))
    }

    # O vocabulário de marcas também sai só do catálogo de referência. Se
    # fosse montado sobre a tabela inteira, os produtos exclusivos gravados
    # por este script deslocariam as razões marca/nome e o pareamento mudaria
    # a cada reexecução.
    vocab = construir_vocabulario_marcas(
        [l for l in linhas if l[0] in com_outra_loja]
    )

    indice = defaultdict(list)
    for pid, ean, nome, marca in linhas:
        if pid not in com_outra_loja:
            continue
        mb = detectar_marca(nome, marca, vocab)
        if mb:
            indice[mb].append(
                (pid, ean, nome, mb, tamanho(nome), set(tokens(nome)),
                 qualificadores(nome))
            )
    return por_ean, por_sku, vocab, indice


# Marcadores que, sozinhos, já definem outro produto na prateleira.
# `conflita()` do pareador só dispara quando os DOIS lados declaram o eixo;
# na auditoria isso deixou passar "Red Bull Pomelo" x "Red Bull Pomelo Sem
# Açúcar" e "Coca-Cola Sem Açúcar" x "Coca-Cola Original" — mesmo tamanho,
# mesma marca, preços diferentes. Aqui a ausência também conta.
#
# Só entram marcadores cuja ausência significa mesmo "outro produto".
# `integral`, `desnatado` e afins ficaram DE FORA de propósito: na auditoria
# eles rejeitaram 7 pares corretos ("Aveia em Flocos Nestlé" x "Aveia em
# Flocos Integral Nestlé", "Farinha de Aveia Quaker" x "Farinha de Aveia
# Integral Quaker"), porque "integral" é descritor que o Soudaki costuma
# omitir. O eixo de teor já é tratado de forma simétrica por `conflita()`.
EXPRESSOES_DIETETICAS = {
    # "zero" sozinho é do eixo do açúcar; "zero lactose"/"zero álcool"
    # pertencem aos seus próprios eixos e não podem disparar este.
    "semacucar": (r"\bzero\b(?!\s*(lactose|alcool|gluten))", r"sem\s+acucar",
                  r"\bdiet\b", r"\blight\b"),
    "semlactose": (r"sem\s+lactose", r"zero\s+lactose", r"deslactosad"),
    "semcafeina": (r"descafeinad", r"sem\s+cafeina"),
    "semalcool": (r"sem\s+alcool", r"zero\s+alcool"),
    "semgluten": (r"sem\s+gluten", r"zero\s+gluten"),
}


def marcadores_dieteticos(nome: str) -> set[str]:
    """Eixos dietéticos declarados no nome."""
    t = limpa(nome)
    return {rotulo for rotulo, padroes in EXPRESSOES_DIETETICAS.items()
            if any(re.search(p, t) for p in padroes)}


def variante_dietetica_assimetrica(nome_a: str, nome_b: str) -> bool:
    """Um lado declara uma variante dietética e o outro silencia sobre ela.

    `conflita()` exige que os dois lados declarem o eixo, então deixava passar
    "Red Bull Pomelo" x "Red Bull Pomelo Sem Açúcar": mesma marca, mesmo
    tamanho, preços diferentes. Aqui a omissão também conta como divergência.
    """
    return marcadores_dieteticos(nome_a) != marcadores_dieteticos(nome_b)


def casar_por_atributos(nome, marca, vocab, indice):
    """Mesma lógica do pareador Soudaki x PA, aplicada ao catálogo inteiro."""
    mb = detectar_marca(nome, marca or "", vocab)
    if not mb:
        return None, 0.0
    tam = tamanho(nome)
    nucleo = set(tokens(nome)) - {mb}
    quali = qualificadores(nome)
    if not nucleo:
        return None, 0.0

    melhor, melhor_chave = None, None
    for pid, pean, pnome, pmarca, ptam, ptoks, pquali in indice[mb]:
        alvo = ptoks - {mb}
        if not alvo:
            continue
        if tam and ptam and tam != ptam:
            continue
        if multipack(nucleo) != multipack(alvo):
            continue
        if conflita(quali, pquali):
            continue
        if variantes_incompativeis(nucleo, alvo):
            continue
        if variante_dietetica_assimetrica(nome, pnome):
            continue
        comuns = nucleo & alvo
        if len(comuns) < MIN_TOKENS_COMUNS:
            continue
        escore = round(len(comuns) / len(nucleo | alvo), 3)
        chave = (-escore, pid)
        if melhor_chave is None or chave < melhor_chave:
            melhor, melhor_chave = (pid, escore), chave

    if melhor and melhor[1] >= LIMIAR_B:
        return melhor
    return None, 0.0


def prioridade(item: dict) -> tuple:
    """Ordena candidatos ao mesmo produto. Menor é melhor.

    Preferências, nesta ordem: item em estoque; preço efetivo mais baixo;
    código sem o sufixo `_exp` (lote a vencer não representa o preço normal);
    identificador, para desempate total.
    """
    pr = item.get("preco") or {}
    preco = pr.get("preco_promocional") or pr.get("preco_regular")
    sku = str(item.get("sku_soudaki") or "")
    return (
        0 if pr.get("em_estoque") else 1,
        preco if isinstance(preco, (int, float)) else float("inf"),
        1 if sku.endswith("_exp") else 0,
        str(item.get("identificador") or ""),
    )


def resolver_colisoes(plano: dict) -> int:
    """Garante um único item do Soudaki por produto do catálogo.

    A disputa é resolvida entre os dois grupos ao mesmo tempo: se um produto
    é alvo de um casamento por EAN e de outro por atributos, o EAN vence —
    é a evidência mais forte.
    """
    ranque = {"ean_existente": 0, "ja_existe": 1, "atributo": 2}
    melhor: dict[int, tuple] = {}
    for chave in ranque:
        for item, pid in plano[chave]:
            p = (ranque[chave],) + prioridade(item)
            if pid not in melhor or p < melhor[pid][0]:
                melhor[pid] = (p, item, chave)

    antes = sum(len(plano[c]) for c in ranque)
    for chave in ranque:
        plano[chave] = [(item, pid) for pid, (_, item, c)
                        in sorted(melhor.items()) if c == chave]
    return antes - len(melhor)


def integrar(db, coleta, aplicar: bool, caminho_db: Path) -> dict:
    cur = db.cursor()
    por_ean, por_sku, vocab, indice = indexar_catalogo(cur)
    print(f"  catálogo indexado: {len(por_ean)} EANs, {len(por_sku)} SKUs "
          f"do Soudaki, {len(indice)} marcas")

    plano = {"ean_existente": [], "ean_novo": [], "ja_existe": [],
             "atributo": [], "exclusivo": []}
    for item in coleta:
        ean = item.get("gtin_ean")
        nome = item["nome_completo"]
        marca = item.get("marca")

        if ean and ean13_valido(ean):
            if ean in por_ean:
                plano["ean_existente"].append((item, por_ean[ean]))
            else:
                plano["ean_novo"].append((item, None))
            continue

        # Mesmo SKU já no catálogo: reexecução deve atualizar, não duplicar.
        sku = str(item.get("sku_soudaki") or "")
        if sku and sku in por_sku:
            plano["ja_existe"].append((item, por_sku[sku]))
            continue

        pid, escore = casar_por_atributos(nome, marca, vocab, indice)
        if pid:
            plano["atributo"].append((item, pid))
        else:
            plano["exclusivo"].append((item, None))

    # Duas entradas do Soudaki podem apontar para o mesmo produto: o catálogo
    # tem 103 códigos com sufixo "_exp" (lote a vencer) que duplicam o item
    # base, além de embalagens repetidas em seções diferentes. Sem tratar
    # isso, o último a ser gravado sobrescreve o preço do primeiro conforme a
    # ordem do arquivo. Aqui a escolha é explícita e reprodutível.
    colisoes = resolver_colisoes(plano)

    total = len(coleta)
    reaproveita = (len(plano["ean_existente"]) + len(plano["atributo"])
                   + len(plano["ja_existe"]))
    print("\n" + "=" * 70)
    print("PLANO DE INTEGRAÇÃO")
    print("=" * 70)
    for rotulo, chave in (
        ("1. EAN já no catálogo (comparável na hora)", "ean_existente"),
        ("2. EAN novo (produto criado com EAN real)", "ean_novo"),
        ("3. SKU já no catálogo (atualiza no lugar)", "ja_existe"),
        ("4. Sem EAN, casado por atributos", "atributo"),
        ("5. Sem EAN e sem par (exclusivo do Soudaki)", "exclusivo"),
    ):
        n = len(plano[chave])
        print(f"  {rotulo:<46}{n:>6}  ({n/max(total,1)*100:>5.1f}%)")
    print(f"\n  vinculados a produto existente: {reaproveita}"
          f"  ({reaproveita/max(total,1)*100:.1f}%)")
    if colisoes:
        print(f"  itens descartados por colisão: {colisoes}"
              "  (duplicatas do Soudaki no mesmo produto)")

    if not aplicar:
        print("\nSimulação. Use --aplicar para gravar.")
        return {"total": total, "reaproveita": reaproveita}

    backup = caminho_db.with_suffix(f".bak-{datetime.now():%Y%m%d%H%M%S}.db")
    shutil.copy2(caminho_db, backup)
    print(f"\n  backup: {backup}")

    criados = precos_ins = precos_upd = precos_antigos = 0
    for chave, lista in plano.items():
        for item, pid in lista:
            if pid is None:
                ident = item["gtin_ean"] if chave == "ean_novo" else None
                cur.execute(
                    "INSERT INTO produtos (gtin_ean, nome, categoria, marca, "
                    "relevancia, imagem_url, apresentacao) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ident or f"SKU-SOUDAKI-{item['sku_soudaki']}",
                     item["nome_completo"], item.get("subsecao") or "Geral",
                     item.get("marca") or "Não Informada", 10,
                     item.get("imagem_url"), None),
                )
                pid = cur.lastrowid
                cur.execute(
                    "INSERT INTO produtos_fts (id, nome, categoria, marca) "
                    "VALUES (?, ?, ?, ?)",
                    (pid, item["nome_completo"], item.get("subsecao") or "Geral",
                     item.get("marca") or "Não Informada"),
                )
                criados += 1

            pr = item["preco"]
            existente = cur.execute(
                "SELECT id, data_coleta FROM precos "
                "WHERE produto_id = ? AND loja_id = ?",
                (pid, LOJA_SOUDAKI),
            ).fetchone()
            if existente:
                # Regra de frescor: coleta antiga não rebaixa preço mais novo.
                if str(pr["data_coleta"] or "")[:10] < str(existente[1] or "")[:10]:
                    precos_antigos += 1
                    continue
                cur.execute(
                    "UPDATE precos SET preco_promocional = ?, preco_regular = ?, "
                    "em_estoque = ?, data_coleta = ? WHERE id = ?",
                    (pr["preco_promocional"], pr["preco_regular"],
                     1 if pr["em_estoque"] else 0, pr["data_coleta"],
                     existente[0]),
                )
                precos_upd += 1
            else:
                cur.execute(
                    "INSERT INTO precos (produto_id, loja_id, preco_promocional, "
                    "preco_regular, em_estoque, cep_coleta, data_coleta) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (pid, LOJA_SOUDAKI, pr["preco_promocional"],
                     pr["preco_regular"], 1 if pr["em_estoque"] else 0,
                     None, pr["data_coleta"]),
                )
                precos_ins += 1
    db.commit()
    db.execute("VACUUM")

    print(f"  produtos criados ... {criados}")
    print(f"  preços inseridos ... {precos_ins}")
    print(f"  preços atualizados . {precos_upd}")
    if precos_antigos:
        print(f"  preços ignorados ... {precos_antigos}  (banco já tem mais novo)")
    return {"total": total, "reaproveita": reaproveita, "criados": criados}


def main() -> None:
    ap = argparse.ArgumentParser(description="Integra a coleta do Soudaki.")
    ap.add_argument("--db", type=Path, default=DB_PADRAO)
    ap.add_argument("--entrada", type=Path, default=ENTRADA,
                    help="JSON de produtos gerado pelo coletor")
    ap.add_argument("--precos", type=Path, default=PRECOS,
                    help="JSON de preços gerado pelo coletor")
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        sys.exit(f"Banco não encontrado: {args.db}")

    coleta = carregar_coleta(args.entrada, args.precos)
    com_ean = sum(1 for c in coleta if c.get("gtin_ean")
                  and ean13_valido(c["gtin_ean"]))
    print(f"Coleta: {len(coleta)} produtos, {com_ean} com EAN-13 válido "
          f"({com_ean/max(len(coleta),1)*100:.1f}%)")

    db = sqlite3.connect(str(args.db))
    try:
        integrar(db, coleta, args.aplicar, args.db)
    finally:
        db.close()

    if args.aplicar:
        print("\nConfira o efeito com:")
        print("  python3 scraper/cobertura_precos.py")


if __name__ == "__main__":
    main()
