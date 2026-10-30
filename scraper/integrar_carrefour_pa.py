#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 Integrador Neon — JSONs v2 do Carrefour e Pão de Açúcar
=====================================================================
Publica no Neon (ou SQLite local) os JSONs produzidos pelos coletores
v2 `scrap_carrefour.py` e `scrap_paodeacucar.py`, com o mesmo critério
dos integradores do Soudaki/Atacadão:

  * vínculo do produto por EAN-13 e, na falta, por nome (LOWER/TRIM);
  * preenchimento do EAN faltante do produto já existente;
  * produto novo criado com relevancia = 10 e `busca` (nome + marca +
    categoria, minúsculo) para a busca do app;
  * upsert de preço por (produto_id, loja_id) — o preço efetivo fica
    em preco_promocional (regra do app: COALESCE(promocional, regular));
  * cep_coleta fica NULL, como no Soudaki/Atacadão.

Categoria: usa o `corredor`/`categoria` do JSON resolvido contra as
categorias canônicas do catálogo (mesmos nomes usados pela
normalização do Neon). Itens sem EAN real (granel, códigos internos
"000000…") casam só por nome.

Filtro de conteúdo adulto (scraper/filtro_adulto.py) é aplicado antes
da gravação — itens bloqueados são contados e ignorados.

Uso (a partir da raiz do repo; precisa do .env com DATABASE_URL do
Neon para gravar em produção — sem ele cai no SQLite local):

  python scraper/integrar_carrefour_pa.py                 # simula (dry-run)
  python scraper/integrar_carrefour_pa.py --db            # grava
  python scraper/integrar_carrefour_pa.py --db --dry-run  # simula, explícito
  python scraper/integrar_carrefour_pa.py --arquivo scraper/carrefour/carrefour_produtos.json
  python scraper/integrar_carrefour_pa.py --limite 200    # teste curto

Por padrão lê `scraper/carrefour/carrefour_produtos.json` e
`scraper/pao_de_acucar/paodeacucar_produtos.json` (o que existir).
=====================================================================
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

ESTE_DIR = Path(__file__).resolve().parent
RAIZ_REPO = ESTE_DIR.parent

# filtro_adulto.py fica na raiz de scraper/ (mesmo diretório deste script)
sys.path.insert(0, str(ESTE_DIR))
try:
    from filtro_adulto import eh_produto_bloqueado
except ImportError:
    print("[AVISO] scraper/filtro_adulto.py não encontrado — filtro adulto DESLIGADO.")
    def eh_produto_bloqueado(nome="", marca="", secao=""):
        return False

# webapp/backend/db.py (get_db_connection: Neon ou SQLite local)
sys.path.insert(0, str(RAIZ_REPO / "webapp" / "backend"))

LOJA_IDS_VALIDOS = {1, 2}  # 1 Carrefour Ponta da Praia, 2 Pão de Açúcar

# ---------------------------------------------------------------------
# Categorias canônicas do catálogo (mesmos nomes da normalização do Neon)
# ---------------------------------------------------------------------
CANONICAS = {
    "Mercearia",
    "Açougue e Peixaria",
    "Hortifruti",
    "Frios e Laticínios",
    "Padaria e Matinais",
    "Congelados",
    "Bebidas",
    "Pratos Prontos e Massas Frescas",
    "Bebê e Infantil",
    "Limpeza e Lavanderia",
    "Higiene e Perfumaria",
    "Alimentos",
}

# Pares de unificação do normalizar_categorias_neon.py + seções das lojas
ALIASES = {
    "limpeza": "Limpeza e Lavanderia",
    "perfumaria": "Higiene e Perfumaria",
    "higiene e beleza": "Higiene e Perfumaria",
    "bebe e crianca": "Bebê e Infantil",
    "carnes aves e peixes": "Açougue e Peixaria",
    "carnes, aves e peixes": "Açougue e Peixaria",
    "matinais": "Padaria e Matinais",
}


def _norm(txt: str) -> str:
    """Minúsculo, sem acentos, espaços colapsados — para casar nomes de seção."""
    txt = unicodedata.normalize("NFD", (txt or "").lower())
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return " ".join(txt.split())


def resolver_categoria(categoria_site: str, corredor: str) -> str:
    """Resolve a categoria canônica a partir do caminho do site e do corredor.

    Percorre os segmentos do caminho (funciona tanto na ordem raiz→folha do
    Carrefour "/Mercearia/Massas/" quanto na folha→raiz do PA "Frutas /
    Hortifruti / Alimentos") e devolve o primeiro que casar com uma categoria
    canônica/alias. Sem casamento, cai no corredor (com alias aplicado).
    """
    segmentos = [s.strip() for s in (categoria_site or "").split("/") if s.strip()]
    for seg in segmentos:
        n = _norm(seg)
        if seg in CANONICAS:
            return seg
        if n in ALIASES:
            return ALIASES[n]
        for canon in CANONICAS:
            if _norm(canon) == n:
                return canon
    if corredor in CANONICAS:
        return corredor
    return ALIASES.get(_norm(corredor), corredor or "Geral")


def ean_valido(ean) -> str | None:
    """EAN utilizável para casamento: 8–14 dígitos numéricos.

    Aceita códigos internos do GPA (`0000000*`) — o catálogo já os usa
    como chave (1.700+ produtos) e eles melhoram o casamento. Rejeita
    apenas vazio, não numérico e tudo zeros.
    """
    e = (str(ean or "").strip())
    if e.isdigit() and 8 <= len(e) <= 14 and set(e) != {"0"}:
        return e
    return None


def _apresentacao(p: dict) -> str | None:
    """Monta 'apresentacao' a partir de unidade + multiplicador do JSON v2.

    O JSON v2 não traz um campo 'apresentacao' pronto; ele tem 'unidade'
    ('un', 'kg', 'L'...) e 'multiplicador' (1.0, 6.0, 12.0...). Devolve
    algo como '6.0 un' quando o multiplicador > 1, ou só a unidade.
    """
    un = (p.get("unidade") or "").strip()
    mult = p.get("multiplicador")
    if mult is not None:
        try:
            mult = float(mult)
        except (TypeError, ValueError):
            mult = None
    if mult and mult != 1.0:
        return f"{mult:g} {un}".strip() or None
    return un or None


def _em_estoque(p: dict) -> bool:
    """Disponibilidade combinando 'disponivel' e 'estoque > 0'.

    O Carrefour usa 99999 como "infinito" — conta como em estoque. Se
    'estoque' for ausente, confia só em 'disponivel'.
    """
    if p.get("disponivel") is False:
        return False
    est = p.get("estoque")
    if est is None:
        return bool(p.get("disponivel"))
    try:
        return int(est) > 0
    except (TypeError, ValueError):
        return bool(p.get("disponivel"))


def _split_preco(p: dict) -> tuple:
    """Converte (preco, preco_original) -> (preco_promocional, preco_regular).

    Regra do schema: preco_promocional = NULL quando não há promoção.
    O app lê o preço efetivo como COALESCE(preco_promocional, preco_regular).
    Promo = preco estritamente menor que preco_original (tolerância 1 centavo).
    """
    preco = p.get("preco")
    original = p.get("preco_original")
    try:
        preco = round(float(preco), 2) if preco is not None else None
    except (TypeError, ValueError):
        preco = None
    try:
        original = round(float(original), 2) if original is not None else None
    except (TypeError, ValueError):
        original = None
    if preco is None:
        return (None, original)
    if original is None or abs(preco - original) < 0.005:
        # Sem promoção (ou sem original) — só regular
        return (None, original if original is not None else preco)
    # Tem promoção: preco < original
    return (preco, original)


def data_da_coleta(meta: dict) -> str:
    bruto = (meta or {}).get("coleta_em") or ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(bruto).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return date.today().isoformat()


def carregar_arquivo(caminho: Path, limite: int | None):
    """Lê um JSON v2 e devolve (loja_id, data_coleta, [produtos])."""
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    produtos = dados.get("produtos") or []
    loja_id = int(dados.get("loja_id") or 0)
    if loja_id not in LOJA_IDS_VALIDOS:
        raise SystemExit(f"[ERRO] {caminho.name}: loja_id inválido ({loja_id}); "
                         f"esperado 1 (Carrefour) ou 2 (Pão de Açúcar).")
    if limite:
        produtos = produtos[:limite]
    return loja_id, data_da_coleta(dados), produtos


def integrar(arquivos: list[Path], gravar: bool, limite: int | None,
             sem_filtro: bool) -> None:
    from db import get_db_connection  # import tardio: só precisa do banco agora

    conn = get_db_connection()
    c = conn.cursor()
    postgres = getattr(conn, "is_postgres", False)
    motor = "Neon/Postgres" if postgres else "SQLite local"
    print(f"[banco] conectado ({motor}) | modo: "
          f"{'GRAVAÇÃO' if gravar else 'SIMULAÇÃO (dry-run)'}")

    c.execute("SELECT id, gtin_ean FROM produtos WHERE gtin_ean IS NOT NULL")
    ean_to_id = {(r["gtin_ean"] or "").strip(): r["id"] for r in c.fetchall()}
    c.execute("SELECT id, LOWER(TRIM(nome)) AS n FROM produtos")
    nome_to_id = {r["n"]: r["id"] for r in c.fetchall()}

    total = {"lidos": 0, "bloqueados": 0, "invalidos": 0, "match_ean": 0,
             "match_nome": 0, "novos": 0, "precos_novos": 0, "precos_atual": 0}

    for caminho in arquivos:
        loja_id, data_coleta, produtos = carregar_arquivo(caminho, limite)
        stats = dict.fromkeys(total, 0)
        stats["lidos"] = len(produtos)

        for p in produtos:
            nome = " ".join(str(p.get("nome") or "").split())
            variante = " ".join(str(p.get("variante") or "").split())
            if variante and variante.lower() not in nome.lower():
                nome = f"{nome} {variante}"
            if not nome:
                stats["invalidos"] += 1
                continue

            preco = p.get("preco")
            disponivel = bool(p.get("disponivel"))
            try:
                preco = round(float(preco), 2) if preco is not None else None
            except (TypeError, ValueError):
                preco = None
            if not disponivel or not preco or preco <= 0:
                stats["invalidos"] += 1
                continue

            marca = (str(p.get("marca") or "").strip() or "Não informada")
            categoria = resolver_categoria(p.get("categoria"), p.get("corredor") or "")

            if not sem_filtro and eh_produto_bloqueado(nome=nome, marca=marca,
                                                       secao=categoria):
                stats["bloqueados"] += 1
                continue

            ean = ean_valido(p.get("ean"))
            prod_id = ean_to_id.get(ean) if ean else None
            if prod_id:
                stats["match_ean"] += 1
            else:
                chave_nome = nome.lower().strip()
                prod_id = nome_to_id.get(chave_nome)
                if prod_id:
                    stats["match_nome"] += 1
                    if ean and ean not in ean_to_id:
                        if gravar:
                            c.execute("UPDATE produtos SET gtin_ean = ? "
                                      "WHERE id = ? AND gtin_ean IS NULL",
                                      (ean, prod_id))
                        ean_to_id[ean] = prod_id
                else:
                    stats["novos"] += 1
                    if not gravar:
                        continue
                    if postgres:
                        # Neon: coluna busca alimenta a busca do app
                        busca = f"{nome} {marca} {categoria}".lower()
                        c.execute(
                            "INSERT INTO produtos (gtin_ean, nome, categoria, "
                            "marca, relevancia, imagem_url, apresentacao, busca) "
                            "VALUES (?, ?, ?, ?, 10, ?, ?, ?) RETURNING id",
                            (ean, nome, categoria, marca,
                             p.get("imagem") or None,
                             _apresentacao(p), busca))
                    else:
                        # SQLite local não tem `busca` — o migrate_sqlite_to_neon
                        # a computa (nome + marca + categoria) na carga.
                        c.execute(
                            "INSERT INTO produtos (gtin_ean, nome, categoria, "
                            "marca, relevancia, imagem_url, apresentacao) "
                            "VALUES (?, ?, ?, ?, 10, ?, ?) RETURNING id",
                            (ean, nome, categoria, marca,
                             p.get("imagem") or None,
                             _apresentacao(p)))
                    prod_id = c.fetchone()["id"]
                    nome_to_id[nome.lower().strip()] = prod_id
                    if ean:
                        ean_to_id[ean] = prod_id

            # Preço: promoção em preco_promocional, lista em preco_regular.
            # Sem promo (preco == preco_original): preco_promocional = NULL.
            # O app lê: COALESCE(preco_promocional, preco_regular).
            preco_promo, preco_reg = _split_preco(p)
            # preco_promo pode ser None (sem promo), mas preco_reg é sempre >= preco
            # Validado acima: preco > 0 e disponivel=True
            if preco_reg is None:
                # Preço inválido após split (raro) — pula
                stats["invalidos"] += 1
                continue
            em_estoque = _em_estoque(p)

            if gravar:
                c.execute("SELECT id FROM precos WHERE produto_id = ? AND "
                          "loja_id = ? LIMIT 1", (prod_id, loja_id))
                linha = c.fetchone()
                vals = (preco_promo, preco_reg, em_estoque, data_coleta)
                if linha:
                    c.execute("UPDATE precos SET preco_promocional = ?, "
                              "preco_regular = ?, em_estoque = ?, data_coleta = ? "
                              "WHERE id = ?", vals + (linha["id"],))
                    stats["precos_atual"] += 1
                else:
                    try:
                        c.execute("INSERT INTO precos (produto_id, loja_id, "
                                  "preco_promocional, preco_regular, em_estoque, "
                                  "data_coleta) VALUES (?, ?, ?, ?, ?, ?)",
                                  (prod_id, loja_id) + vals)
                        stats["precos_novos"] += 1
                    except Exception as e:
                        # Pode ocorrer quando o JSON tem o mesmo produto 2x
                        # (nome duplicado sem EAN) e a segunda ocorrência
                        # bate no UNIQUE(produto_id, loja_id). Em SQLite a
                        # falha é isolada; em Postgres abortaria a transação.
                        n = stats.get("_skip_dup", 0) + 1
                        stats["_skip_dup"] = n
                        if n <= 3:
                            print(f"   [skip] produto_id={prod_id} "
                                  f"loja_id={loja_id} nome={nome[:50]!r}: {e}")
                        if postgres:
                            try:
                                conn.connection.rollback()
                            except Exception:
                                pass

        print(f"\n== {caminho.parent.name}/{caminho.name} → loja_id={loja_id} "
              f"(coleta {data_coleta})")
        for k, v in stats.items():
            total[k] += v
            print(f"   {k:>13}: {v}")

    if gravar:
        conn.connection.commit()
        print("\n[banco] ✔ alterações gravadas (commit).")
    else:
        print("\n[dry-run] nada gravado — rode com --db para aplicar.")
    conn.close()

    print("\n== TOTAIS ==")
    for k, v in total.items():
        print(f"   {k:>13}: {v}")


def main() -> None:
    padroes = [RAIZ_REPO / "scraper" / "carrefour" / "carrefour_produtos.json",
               RAIZ_REPO / "scraper" / "pao_de_acucar" / "paodeacucar_produtos.json"]
    ap = argparse.ArgumentParser(
        description="Integra os JSONs v2 do Carrefour/Pão de Açúcar no Neon")
    ap.add_argument("--arquivo", action="append", default=[],
                    help="JSON de coleta v2 (repita a opção p/ vários; "
                         "padrão: os dois caminhos padrão)")
    ap.add_argument("--limite", type=int, default=None,
                    help="processa só os N primeiros produtos de cada arquivo")
    ap.add_argument("--db", action="store_true",
                    help="grava no banco (sem isto, apenas simula)")
    ap.add_argument("--dry-run", action="store_true",
                    help="força simulação mesmo com --db")
    ap.add_argument("--sem-filtro-adulto", action="store_true",
                    help="desliga o filtro de produtos adultos")
    args = ap.parse_args()

    caminhos = [Path(a) for a in args.arquivo] or \
               [p for p in padroes if p.exists()]
    if not caminhos:
        raise SystemExit("[ERRO] nenhum JSON de coleta encontrado. "
                         "Rode o coletor v2 ou use --arquivo <caminho>.")
    gravar = args.db and not args.dry_run
    integrar(caminhos, gravar, args.limite, args.sem_filtro_adulto)


if __name__ == "__main__":
    main()
