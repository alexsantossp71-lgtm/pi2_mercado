# -*- coding: utf-8 -*-
"""
Pareamento Soudaki x Pão de Açúcar — busca a maior paridade possível.

Problema
--------
O Soudaki (plataforma JOKR/Daki) não publica EAN para a maior parte do
sortimento: dos 1.539 produtos coletados, apenas 362 (23,5%) têm EAN-13 com
dígito verificador válido. Os outros 1.177 usam SKU interno (15000004818,
20000000533, ...). Como o cruzamento entre lojas é feito por EAN, esses itens
nunca encontram par — hoje só 261 produtos (17,0%) são comparáveis com o PA.

Estratégia
----------
Casar o que o EAN não casa, usando marca + tamanho + núcleo descritivo do nome.

  Faixa A  EAN-13 idêntico                                   (certeza)
  Faixa B  mesma marca + mesmo tamanho + Jaccard >= 0.60     (alta)
  Faixa C  mesma marca + mesmo tamanho + Jaccard >= 0.40     (revisar)
  Faixa D  sem candidato                                     (coletar no PA)

Guardas contra falso positivo:
  - tamanhos normalizados (1 litro == 1l == 1000ml) precisam bater;
  - marcadores de embalagem múltipla (kit, bipack, pack, leve/pague) precisam
    bater dos dois lados — "Bipack Coca-Cola 2L" não é "Kit Coca + Fanta";
  - exige no mínimo 2 tokens descritivos em comum;
  - um produto do PA só pode ser usado por um produto do Soudaki (o de maior
    escore), evitando que vários sabores colapsem no mesmo par.

Saídas
------
  scraper/pareamento_soudaki_pa.json   mapa completo com escore e faixa
  scraper/pareamento_soudaki_pa.csv    planilha de revisão (faixas B e C)
  scraper/gap_soudaki_pa.txt           itens sem par, para coleta dirigida

Uso
---
  python3 scraper/parear_soudaki_pa.py                  # analisa e relata
  python3 scraper/parear_soudaki_pa.py --incluir-c      # aceita a faixa C
  python3 scraper/parear_soudaki_pa.py --aplicar        # grava no banco
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent
DB_PADRAO = RAIZ / "webapp" / "backend" / "dispensa.db"

LOJA_SOUDAKI = 4
LOJA_PA = 2

LIMIAR_B = 0.60
LIMIAR_C = 0.40
MIN_TOKENS_COMUNS = 2

# Um token só vale como marca se for predominantemente marca, não categoria.
RAZAO_MARCA = 0.5

# Palavras que não distinguem produto e só inflam a similaridade.
# "com" e "sem" NÃO entram aqui: são o que separa margarina com sal de
# margarina sem sal, e água com gás de água sem gás.
RUIDO = {
    "garrafa", "caixa", "cx", "pacote", "pct", "embalagem", "emb",
    "para", "tipo", "und", "unid", "unidade", "unidades", "pote", "lata",
    "vidro", "frasco", "saco", "bandeja", "display", "prox", "vencim", "venc",
    "the", "dia", "sabor",
    # formato e marketing: variam entre as lojas sem mudar o produto
    "sache", "refil", "squeeze", "pouch", "economica", "economico", "premium",
    "edition", "gelada", "ambiente", "vasilhame", "retornavel", "promocional",
    "pcte", "original", "leve", "gratis",
}

# Se um lado é embalagem múltipla e o outro não, não são o mesmo produto.
MULTIPACK = {"kit", "bipack", "pack", "leve", "pague", "multipack", "combo"}

# Atributos que invertem o produto. Quando os dois lados declaram o mesmo
# eixo com polaridade diferente, o par é recusado mesmo com escore alto.
EIXOS = {
    "sal": (r"\bsem\s+sal\b|\bzero\s+sal\b", r"\bcom\s+sal\b|\bsalgad"),
    "gas": (r"\bsem\s+gas\b|\bnatural\b(?=.*agua)", r"\bcom\s+gas\b|\bgaseific"),
    "acucar": (r"\bzero\s+a[cz]ucar\b|\bsem\s+a[cz]ucar\b|\bdiet\b|\bzero\b",
               r"\bcom\s+a[cz]ucar\b|\badoc"),
    "lactose": (r"\bzero\s+lactose\b|\bsem\s+lactose\b", r"\bcom\s+lactose\b"),
    "cafeina": (r"\bdescafeinad", r"\bcom\s+cafeina\b"),
    "alcool": (r"\bsem\s+alcool\b", r"\bcom\s+alcool\b"),
}

# Eixo de teor: desnatado != integral != semidesnatado.
TEOR = ("desnatad", "semidesnatad", "integral", "light", "zero")


# --------------------------------------------------------------------------- #
# Normalização
# --------------------------------------------------------------------------- #
def limpa(texto: str) -> str:
    t = html.unescape(texto or "")           # nomes vêm com Johnson&#39;s
    t = re.sub(r"\*\*[^*]*\*\*", " ", t)      # marcador **Prox Vencim**
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()


def tamanho(texto: str):
    """Normaliza a última medida citada para (valor, unidade-base)."""
    t = limpa(texto).replace(",", ".")
    achados = re.findall(
        r"(\d+(?:\.\d+)?)\s*(kg|g|gr|l|lt|litros?|ml|un|und|unidades?)\b", t
    )
    if not achados:
        return None
    valor, unidade = achados[-1]
    valor = float(valor)
    if unidade == "kg":
        return (round(valor * 1000), "g")
    if unidade in ("g", "gr"):
        return (round(valor), "g")
    if unidade in ("l", "lt", "litro", "litros"):
        return (round(valor * 1000), "ml")
    if unidade == "ml":
        return (round(valor), "ml")
    return (round(valor), "un")


def tokens(texto: str) -> list[str]:
    t = re.sub(
        r"\d+(?:[.,]\d+)?\s*(kg|g|gr|l|lt|litros?|ml|un|und|unidades?)\b",
        " ", limpa(texto),
    )
    return [w for w in re.sub(r"[^a-z0-9]", " ", t).split()
            if len(w) > 2 and w not in RUIDO]


def marca_limpa(marca: str) -> str:
    m = re.sub(r"[^a-z0-9 ]", " ", limpa(marca)).strip()
    if m in ("nao informada", "nao informado", ""):
        return ""
    return re.sub(r"\s+", " ", m)


def ean13_valido(ean: str) -> bool:
    ean = str(ean or "")
    if len(ean) != 13 or not ean.isdigit():
        return False
    soma = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(ean[:12]))
    return (10 - soma % 10) % 10 == int(ean[12])


def multipack(conjunto: set[str]) -> bool:
    return bool(conjunto & MULTIPACK)


def qualificadores(nome: str) -> dict[str, str]:
    """Lê os atributos que invertem o produto (sem sal x com sal, etc.)."""
    t = limpa(nome)
    achados = {}
    for eixo, (negativo, positivo) in EIXOS.items():
        tem_neg = re.search(negativo, t) is not None
        tem_pos = re.search(positivo, t) is not None
        if tem_neg and not tem_pos:
            achados[eixo] = "-"
        elif tem_pos and not tem_neg:
            achados[eixo] = "+"
    teores = [p for p in TEOR if p in t]
    if teores:
        achados["teor"] = "|".join(sorted(teores))
    return achados


def conflita(a: dict[str, str], b: dict[str, str]) -> bool:
    """Verdadeiro quando os dois lados declaram o mesmo eixo de forma oposta."""
    return any(a[k] != b[k] for k in set(a) & set(b))


def variantes_incompativeis(a: set[str], b: set[str]) -> bool:
    """Recusa quando cada lado carrega um descritivo que o outro não tem.

    'Queijo Prato Vigor' x 'Queijo Cheddar Vigor' compartilham marca, tamanho e
    a palavra queijo; o que os separa é um token exclusivo de cada lado. Quando
    isso acontece dos dois lados ao mesmo tempo, trata-se de sabor ou variante
    diferente. Um lado só com tokens extras continua válido — é apenas um nome
    mais descritivo do mesmo item.
    """
    so_a = [t for t in a - b if len(t) >= 3]
    so_b = [t for t in b - a if len(t) >= 3]
    return bool(so_a and so_b)


# --------------------------------------------------------------------------- #
# Pareamento
# --------------------------------------------------------------------------- #
def construir_vocabulario_marcas(produtos_pa) -> dict[str, int]:
    """Tokens que funcionam como marca no catálogo do PA.

    Só contar aparições no campo 'marca' não basta: 'café' aparece como marca
    em 'Astro Café' e 'Café Brasileiro', mas é palavra de categoria em outros
    365 nomes. Aceitar 'café' como marca fazia o 3 Corações casar com o Café
    Brasileiro. O filtro mantém o token apenas quando ele é predominantemente
    marca — razão entre uso como marca e uso total no nome.
    """
    como_marca: dict[str, int] = defaultdict(int)
    como_nome: dict[str, int] = defaultdict(int)
    for _, _, nome, marca in produtos_pa:
        for palavra in marca_limpa(marca).split():
            if len(palavra) >= 4:
                como_marca[palavra] += 1
        for palavra in set(tokens(nome)):
            como_nome[palavra] += 1

    return {
        palavra: n for palavra, n in como_marca.items()
        if n / max(como_nome.get(palavra, n), 1) >= RAZAO_MARCA
    }


def detectar_marca(nome: str, marca: str, vocab: dict[str, int]) -> str:
    """Usa o campo marca; se for inútil, procura a marca dentro do nome.

    O Soudaki preenche 'marca' com lixo ('Ovos', 'Ovo'), mas quase sempre
    escreve a marca no nome do produto.
    """
    candidatos = [w for w in marca_limpa(marca).split()
                  if len(w) >= 4 and w in vocab]
    if candidatos:
        # Desempate explícito: a ordem de iteração de um set de strings muda a
        # cada processo (hash randomizado), e com ela o pareamento inteiro.
        return min(sorted(set(candidatos)), key=lambda w: (-vocab[w], w))
    for palavra in tokens(nome):
        if palavra in vocab:
            return palavra
    return ""


def parear(db: sqlite3.Connection) -> dict:
    cur = db.cursor()

    def q(sql, *p):
        return cur.execute(sql, p).fetchall()

    soudaki = q(
        "SELECT p.id, p.gtin_ean, p.nome, p.marca FROM precos x "
        "JOIN produtos p ON p.id = x.produto_id WHERE x.loja_id = ?", LOJA_SOUDAKI
    )
    pa = q(
        "SELECT p.id, p.gtin_ean, p.nome, p.marca FROM precos x "
        "JOIN produtos p ON p.id = x.produto_id WHERE x.loja_id = ?", LOJA_PA
    )
    ids_pa = {r[0] for r in pa}

    vocab = construir_vocabulario_marcas(pa)

    # Indexa o PA por token de marca para não varrer 15 mil itens por consulta.
    indice: dict[str, list] = defaultdict(list)
    for pid, pean, pnome, pmarca in pa:
        marca = detectar_marca(pnome, pmarca, vocab)
        registro = (pid, pean, pnome, marca, tamanho(pnome),
                    set(tokens(pnome)), qualificadores(pnome))
        if marca:
            indice[marca].append(registro)

    pares, sem_par = [], []
    for sid, sean, snome, smarca in soudaki:
        if sid in ids_pa:  # Faixa A: mesmo produto_id, ou seja, mesmo EAN
            pares.append({
                "faixa": "A", "escore": 1.0,
                "soudaki_id": sid, "soudaki_ean": sean, "soudaki_nome": snome,
                "pa_id": sid, "pa_ean": sean, "pa_nome": snome,
                "motivo": "EAN-13 idêntico",
            })
            continue

        marca = detectar_marca(snome, smarca, vocab)
        tam = tamanho(snome)
        nucleo = set(tokens(snome)) - {marca}
        quali = qualificadores(snome)

        melhor = None
        if marca and nucleo:
            for pid, pean, pnome, pmarca, ptam, ptoks, pquali in indice[marca]:
                alvo = ptoks - {marca}
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
                comuns = nucleo & alvo
                if len(comuns) < MIN_TOKENS_COMUNS:
                    continue
                escore = round(len(comuns) / len(nucleo | alvo), 3)
                # Empate resolvido pelo menor produto_id, para o resultado
                # não depender da ordem em que o banco devolveu as linhas.
                chave = (-escore, pid)
                if melhor is None or chave < melhor["_chave"]:
                    melhor = {
                        "_chave": chave, "escore": escore,
                        "pa_id": pid, "pa_ean": pean, "pa_nome": pnome,
                    }

        if melhor:
            melhor.pop("_chave", None)
        if melhor and melhor["escore"] >= LIMIAR_C:
            pares.append({
                "faixa": "B" if melhor["escore"] >= LIMIAR_B else "C",
                "escore": melhor["escore"],
                "soudaki_id": sid, "soudaki_ean": sean, "soudaki_nome": snome,
                "pa_id": melhor["pa_id"], "pa_ean": melhor["pa_ean"],
                "pa_nome": melhor["pa_nome"],
                "motivo": f"marca '{marca}' + tamanho {tam} + Jaccard {melhor['escore']}",
            })
        else:
            sem_par.append({
                "soudaki_id": sid, "soudaki_ean": sean, "soudaki_nome": snome,
                "marca_detectada": marca,
                "ean_valido": ean13_valido(sean),
            })

    pares = resolver_conflitos(pares, sem_par)
    return {"pares": pares, "sem_par": sem_par, "total_soudaki": len(soudaki),
            "total_pa": len(pa)}


def resolver_conflitos(pares: list[dict], sem_par: list[dict]) -> list[dict]:
    """Um produto do PA não pode servir de par para vários itens do Soudaki.

    Sem isso, quatro sabores de iogurte da mesma marca e tamanho colapsariam
    todos no mesmo registro do PA. Fica o de maior escore; os demais voltam
    para a lista de coleta.
    """
    por_pa: dict[int, list[dict]] = defaultdict(list)
    for p in pares:
        por_pa[p["pa_id"]].append(p)

    mantidos = []
    for pa_id in sorted(por_pa):
        grupo = por_pa[pa_id]
        if len(grupo) == 1 or grupo[0]["faixa"] == "A":
            mantidos.extend(grupo)
            continue
        grupo.sort(key=lambda x: (x["faixa"] != "A", -x["escore"],
                                  x["soudaki_id"]))
        mantidos.append(grupo[0])
        for perdedor in grupo[1:]:
            sem_par.append({
                "soudaki_id": perdedor["soudaki_id"],
                "soudaki_ean": perdedor["soudaki_ean"],
                "soudaki_nome": perdedor["soudaki_nome"],
                "marca_detectada": "",
                "ean_valido": ean13_valido(perdedor["soudaki_ean"]),
                "nota": f"disputou o par {perdedor['pa_ean']} e perdeu",
            })
    return mantidos


# --------------------------------------------------------------------------- #
# Aplicação no banco
# --------------------------------------------------------------------------- #
def aplicar(db: sqlite3.Connection, pares: list[dict], caminho_db: Path) -> dict:
    """Move o preço do Soudaki para o produto do PA e remove a ficha duplicada.

    O item do Soudaki com SKU interno é uma ficha duplicada do mesmo produto
    que o PA já tem com EAN. Consolidar os dois num único produto_id é o que
    torna a comparação possível na API, que cruza preços por produto_id.
    """
    backup = caminho_db.with_suffix(f".bak-{datetime.now():%Y%m%d%H%M%S}.db")
    shutil.copy2(caminho_db, backup)

    cur = db.cursor()
    movidos = removidos = conflitos = 0
    for p in pares:
        if p["faixa"] == "A":
            continue
        sid, pid = p["soudaki_id"], p["pa_id"]
        linha = cur.execute(
            "SELECT preco_promocional, preco_regular, em_estoque, cep_coleta, "
            "data_coleta FROM precos WHERE produto_id = ? AND loja_id = ?",
            (sid, LOJA_SOUDAKI),
        ).fetchone()
        if not linha:
            continue
        ja_tem = cur.execute(
            "SELECT 1 FROM precos WHERE produto_id = ? AND loja_id = ?",
            (pid, LOJA_SOUDAKI),
        ).fetchone()
        if ja_tem:
            conflitos += 1
            continue
        cur.execute(
            "INSERT INTO precos (produto_id, loja_id, preco_promocional, "
            "preco_regular, em_estoque, cep_coleta, data_coleta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, LOJA_SOUDAKI, linha[0], linha[1], linha[2], linha[3], linha[4]),
        )
        cur.execute("DELETE FROM precos WHERE produto_id = ? AND loja_id = ?",
                    (sid, LOJA_SOUDAKI))
        movidos += 1
        restantes = cur.execute(
            "SELECT COUNT(*) FROM precos WHERE produto_id = ?", (sid,)
        ).fetchone()[0]
        if restantes == 0:
            cur.execute("DELETE FROM produtos WHERE id = ?", (sid,))
            cur.execute("DELETE FROM produtos_fts WHERE id = ?", (sid,))
            removidos += 1
    db.commit()

    # Sem VACUUM o arquivo cresce mesmo depois de apagar centenas de fichas:
    # o SQLite mantém as páginas liberadas reservadas para reuso.
    tamanho_antes = caminho_db.stat().st_size
    db.execute("VACUUM")
    tamanho_depois = caminho_db.stat().st_size

    return {"backup": str(backup), "precos_movidos": movidos,
            "produtos_removidos": removidos, "conflitos": conflitos,
            "bytes_antes": tamanho_antes, "bytes_depois": tamanho_depois}


# --------------------------------------------------------------------------- #
# Relatório
# --------------------------------------------------------------------------- #
def relatar(res: dict, incluir_c: bool) -> dict:
    pares, sem_par = res["pares"], res["sem_par"]
    total = res["total_soudaki"]
    por_faixa = defaultdict(list)
    for p in pares:
        por_faixa[p["faixa"]].append(p)

    a, b, c = len(por_faixa["A"]), len(por_faixa["B"]), len(por_faixa["C"])
    aplicaveis = a + b + (c if incluir_c else 0)

    print("=" * 76)
    print("PAREAMENTO SOUDAKI x PÃO DE AÇÚCAR")
    print("=" * 76)
    print(f"\nProdutos Soudaki ......... {total:>6}")
    print(f"Universo Pão de Açúcar ... {res['total_pa']:>6}")
    print("\nPAREAMENTO POR FAIXA")
    print(f"  A  EAN-13 idêntico ................... {a:>6}  ({a/total*100:>5.1f}%)")
    print(f"  B  marca+tamanho+Jaccard>={LIMIAR_B} ...... {b:>6}  ({b/total*100:>5.1f}%)")
    print(f"  C  marca+tamanho+Jaccard>={LIMIAR_C} ...... {c:>6}  ({c/total*100:>5.1f}%)")
    print(f"  D  sem par ........................... {len(sem_par):>6}"
          f"  ({len(sem_par)/total*100:>5.1f}%)")
    print(f"\nPARIDADE ANTES ... {a:>6} / {total}  ({a/total*100:.1f}%)")
    print(f"PARIDADE DEPOIS .. {aplicaveis:>6} / {total}  ({aplicaveis/total*100:.1f}%)"
          f"   {'[A+B+C]' if incluir_c else '[A+B]'}")
    print(f"GANHO ............ {aplicaveis-a:>6} produtos"
          f"  (+{(aplicaveis-a)/total*100:.1f} p.p.)")

    com_ean = sum(1 for s in sem_par if s.get("ean_valido"))
    print("\nPOR QUE OS RESTANTES NÃO PAREIAM")
    print(f"  têm EAN-13 válido mas o PA não coletou .. {com_ean:>6}")
    print(f"  SKU interno Daki, sem EAN publicado ..... {len(sem_par)-com_ean:>6}")
    return {"A": a, "B": b, "C": c, "D": len(sem_par), "aplicaveis": aplicaveis}


def gravar_saidas(res: dict, resumo: dict) -> None:
    pares, sem_par = res["pares"], res["sem_par"]

    destino = BASE / "pareamento_soudaki_pa.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump({
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
            "resumo": resumo, "pares": pares, "sem_par": sem_par,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nMapa completo ....... {destino}")

    revisao = [p for p in pares if p["faixa"] in ("B", "C")]
    revisao.sort(key=lambda x: (x["faixa"], -x["escore"]))
    csv_path = BASE / "pareamento_soudaki_pa.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["faixa", "escore", "soudaki_codigo", "soudaki_nome",
                    "pa_ean", "pa_nome", "conferido"])
        for p in revisao:
            w.writerow([p["faixa"], p["escore"], p["soudaki_ean"],
                        p["soudaki_nome"], p["pa_ean"], p["pa_nome"], ""])
    print(f"Planilha de revisão . {csv_path}  ({len(revisao)} pares)")

    gap_path = BASE / "gap_soudaki_pa.txt"
    com_ean = [s for s in sem_par if s.get("ean_valido")]
    with open(gap_path, "w", encoding="utf-8") as f:
        f.write("# EANs presentes no Soudaki e ausentes na coleta do PA.\n")
        f.write("# Alvo de coleta dirigida no Pão de Açúcar.\n\n")
        for s in sorted(com_ean, key=lambda x: x["soudaki_ean"]):
            f.write(f"{s['soudaki_ean']}  # {s['soudaki_nome']}\n")
    print(f"Lista de coleta ..... {gap_path}  ({len(com_ean)} EANs)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Pareia produtos do Soudaki com o Pão de Açúcar."
    )
    ap.add_argument("--db", type=Path, default=DB_PADRAO)
    ap.add_argument("--incluir-c", action="store_true",
                    help="Trata a faixa C (0.40-0.60) como par válido.")
    ap.add_argument("--aplicar", action="store_true",
                    help="Grava a consolidação no banco (faz backup antes).")
    args = ap.parse_args()

    if not args.db.exists():
        sys.exit(f"Banco não encontrado: {args.db}")

    db = sqlite3.connect(str(args.db))
    try:
        res = parear(db)
        resumo = relatar(res, args.incluir_c)
        gravar_saidas(res, resumo)

        if args.aplicar:
            faixas = {"A", "B", "C"} if args.incluir_c else {"A", "B"}
            alvo = [p for p in res["pares"] if p["faixa"] in faixas]
            print("\nAplicando consolidação no banco...")
            info = aplicar(db, alvo, args.db)
            print(f"  backup ............. {info['backup']}")
            print(f"  preços movidos ..... {info['precos_movidos']}")
            print(f"  produtos removidos . {info['produtos_removidos']}")
            print(f"  conflitos ignorados  {info['conflitos']}")
            print(f"  banco (VACUUM) ..... {info['bytes_antes']:,} -> "
                  f"{info['bytes_depois']:,} bytes")
        else:
            print("\nNada foi gravado no banco. Use --aplicar para consolidar.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
