#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 Limpeza de produtos com mojibake (double-encoded UTF-8) no Neon
=====================================================================
Detecta produtos cujo nome/marca/categoria sofreram double-encoding
UTF-8 — ou seja, o texto UTF-8 original foi interpretado como Latin-1
e re-codificado como UTF-8, produzindo caracteres como "Ã§" (Ã + §)
em vez de "ç", "Ã£" em vez de "ã", "Ã©" em vez de "é" etc.

Sintoma típico na base atual (Neon, out/2026):
    nome   = "LinguiÃ§a Toscana Seara 600Gr"   (mojibake)
    marca  = "Linguiça"                          (marca virou 1a palavra)
    ean    = NULL

O script faz, para cada produto mojibakeado:

  1. Tenta decodificar o nome (reverse: encode('latin-1').decode('utf-8'))
  2. Procura se já existe um produto CORRETO correspondente (por EAN
     ou por nome normalizado)
  3. Se existe versão correta: migra os preços do mojibakeado para o
     correto (preservando a loja_id) e DELETA o produto mojibakeado
  4. Se NÃO existe versão correta: CORRIGE o nome/marca/categoria
     in-place (decodifica o double-encoding)

Por padrão RODA EM --dry-run (só detecta e relata). Use --aplicar para
modificar o banco.

USO:

  # Detectar e relatar (não grava nada):
  DATABASE_URL="postgres://..." python scraper/limpar_mojibake.py

  # Aplicar correção:
  DATABASE_URL="postgres://..." python scraper/limpar_mojibake.py --aplicar

  # Só listar IDs afetados (para auditoria manual):
  DATABASE_URL="postgres://..." python scraper/limpar_mojibake.py --ids

Dependências: psycopg2-binary (Neon) ou sqlite3 (fallback local),
já listadas em scraper/requirements.txt.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

# Regex precisa de mojibake: U+00C3 (Ã) ou U+00C2 (Â) seguido de
# um char no range U+00A0..U+00BF (§, £, ©, ¡, ³, º, ª, µ, ¢, etc).
# Esse padrão só aparece quando UTF-8 foi lido como Latin-1 e re-codificado.
# Não confunde com "Ã" legítimo (em "São", "Não", "Coração") nem "Â"
# (em "Âmbar", "Ângulo") porque esses vêm SEM um segundo char no range.
MOJI_RE = re.compile(r'[\u00C3\u00C2][\u00A0-\u00BF]')


def tem_mojibake(texto: str) -> bool:
    """True se o texto contiver o padrão de double-encoding UTF-8."""
    if not texto:
        return False
    return bool(MOJI_RE.search(texto))


def decodificar_mojibake(texto: str) -> str:
    """Reverte o double-encoding: UTF-8 → Latin-1 → UTF-8.

    "LinguiÃ§a" (Ã + § como 2 chars Unicode) → "Linguiça" (ç como 1 char).
    Se a decodificação falhar (não é mojibake real), devolve o original.
    """
    if not texto:
        return texto
    try:
        # Cada char Unicode → byte Latin-1; conjunto de bytes → UTF-8 string
        return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto  # não era double-encoded; devolve intacto


# Alias de categoria — o Soudaki usa "Churrasco" como seção da loja,
# mas nossa categoria canônica é "Açougue e Peixaria". Mapeamentos
# espelhados do integrar_carrefour_pa.py / normalizar_categorias_neon.py.
ALIASES_CATEGORIA = {
    "churrasco": "Açougue e Peixaria",
    "carnes": "Açougue e Peixaria",
    "carnes aves e peixes": "Açougue e Peixaria",
    "carnes, aves e peixes": "Açougue e Peixaria",
    "limpeza": "Limpeza e Lavanderia",
    "perfumaria": "Higiene e Perfumaria",
    "higiene e beleza": "Higiene e Perfumaria",
    "bebe e crianca": "Bebê e Infantil",
    "bebes": "Bebê e Infantil",
    "matinais": "Padaria e Matinais",
}

# Categorias canônicas (mesmas do integrar_carrefour_pa.py)
CATEGORIAS_CANONICAS = {
    "Mercearia", "Açougue e Peixaria", "Hortifruti", "Frios e Laticínios",
    "Padaria e Matinais", "Congelados", "Bebidas",
    "Pratos Prontos e Massas Frescas", "Bebê e Infantil",
    "Limpeza e Lavanderia", "Higiene e Perfumaria", "Alimentos",
}


def _norm(txt: str) -> str:
    """Minúsculo, sem acentos, espaços colapsados."""
    import unicodedata
    t = unicodedata.normalize("NFD", (txt or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def resolver_categoria(categoria: str) -> str:
    """Normaliza categoria para a canônica do catálogo.

    Ex.: "Churrasco" → "Açougue e Peixaria"; "limpeza" → "Limpeza e Lavanderia".
    Se já é canônica ou não há alias, devolve inalterada.
    """
    if not categoria:
        return categoria
    if categoria in CATEGORIAS_CANONICAS:
        return categoria
    n = _norm(categoria)
    if n in ALIASES_CATEGORIA:
        return ALIASES_CATEGORIA[n]
    # Tenta casar com canônica normalizada
    for canon in CATEGORIAS_CANONICAS:
        if _norm(canon) == n:
            return canon
    return categoria


def _norm_nome(nome: str) -> str:
    """Normalização para match: lower + trim + colapsa espaços."""
    return " ".join((nome or "").lower().split())


# ---------------------------------------------------------------------
# Conexão com o banco (reaproveita webapp/backend/db.py)
# ---------------------------------------------------------------------
def abrir_conexao():
    raiz_repo = Path(__file__).resolve().parents[1]
    caminho_db = raiz_repo / "webapp" / "backend"
    if not (caminho_db / "db.py").exists():
        print(f"[ERRO] {caminho_db}/db.py não encontrado. "
              "Rode este script de <repo>/scraper/.", file=sys.stderr)
        sys.exit(1)
    sys.path.insert(0, str(caminho_db))
    from db import get_db_connection  # type: ignore
    return get_db_connection()


# ---------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------
def listar_mojibakeados(conn):
    """Devolve lista de dicts {id, gtin_ean, nome, marca, categoria}.

    Puxa todos os produtos (só as 5 colunas necessárias) e filtra no
    Python pelo regex preciso. Funciona tanto em Postgres (Neon) quanto
    em SQLite (local) sem depender de funções SQL específicas.
    """
    c = conn.cursor()
    c.execute("SELECT id, gtin_ean, nome, marca, categoria FROM produtos")
    out = []
    for r in c.fetchall():
        d = {"id": r["id"], "gtin_ean": r["gtin_ean"], "nome": r["nome"],
             "marca": r["marca"], "categoria": r["categoria"]}
        # Filtra os que têm o char Ã ou Â primeiro (otimização) e depois
        # confirma com o regex precisa (elimina "São", "Coração", "Âmbar")
        if (d["nome"] and ("\u00C3" in d["nome"] or "\u00C2" in d["nome"])) \
           or (d["marca"] and ("\u00C3" in d["marca"] or "\u00C2" in d["marca"])) \
           or (d["categoria"] and ("\u00C3" in d["categoria"] or "\u00C2" in d["categoria"])):
            if (tem_mojibake(d["nome"]) or tem_mojibake(d["marca"])
                    or tem_mojibake(d["categoria"])):
                out.append(d)
    return out


# ---------------------------------------------------------------------
# Limpeza
# ---------------------------------------------------------------------
def _buscar_correspondente(conn, moji, nome_corr):
    """Procura um produto CORRETO (não-mojibakeado) que corresponda ao
    mojibakeado, por EAN ou por nome normalizado. Devolve o id ou None.

    Exclui o próprio produto (moji['id']) da busca.
    """
    c = conn.cursor()
    # 1) Por EAN (mesmo EAN, id diferente, nome sem mojibake)
    if moji["gtin_ean"]:
        c.execute("""
            SELECT id FROM produtos
            WHERE gtin_ean = ? AND id != ?
            LIMIT 1
        """, (moji["gtin_ean"], moji["id"]))
        row = c.fetchone()
        if row:
            return row["id"]
    # 2) Por nome normalizado (nome decodificado, id diferente)
    if nome_corr:
        norm = _norm_nome(nome_corr)
        c.execute("""
            SELECT id FROM produtos
            WHERE LOWER(TRIM(nome)) = ? AND id != ?
            LIMIT 1
        """, (norm, moji["id"]))
        row = c.fetchone()
        if row:
            return row["id"]
    return None


def limpar(conn, aplicar: bool, so_ids: bool):
    c = conn.cursor()
    motor = "Neon/Postgres" if getattr(conn, "is_postgres", False) else "SQLite local"
    print(f"[banco] conectado ({motor}) | aplicar={aplicar}")

    mojis = listar_mojibakeados(conn)
    print(f"[detect] {len(mojis)} produtos com mojibake encontrados.\n")

    if so_ids:
        for m in mojis:
            print(f"  id={m['id']}  nome={m['nome'][:70]!r}")
        return 0

    stats = {"corrigidos_inplace": 0, "deletados_duplicata": 0,
             "precos_migrados": 0, "precos_perdidos": 0, "erros": 0}

    for m in mojis:
        nome_corr = decodificar_mojibake(m["nome"])
        marca_corr = decodificar_mojibake(m["marca"]) if m["marca"] else m["marca"]
        cat_corr = decodificar_mojibake(m["categoria"]) if m["categoria"] else m["categoria"]
        # Normaliza categoria para a canônica (ex.: "Churrasco" -> "Açougue e Peixaria")
        cat_corr = resolver_categoria(cat_corr) if cat_corr else cat_corr

        # Se a decodificação falhou (nome não mudou) E categoria também não
        # mudou, pula
        if (nome_corr == m["nome"] and marca_corr == m["marca"]
                and cat_corr == m["categoria"]):
            stats["erros"] += 1
            continue

        id_correto = _buscar_correspondente(conn, m, nome_corr)

        if id_correto:
            # Caso A: existe versão correta → migrar preços e deletar duplicata
            if not aplicar:
                # Em dry-run só conta
                c.execute("SELECT COUNT(*) AS n FROM precos WHERE produto_id = ?",
                          (m["id"],))
                n_precos = c.fetchone()["n"]
                stats["deletados_duplicata"] += 1
                stats["precos_migrados"] += n_precos
                print(f"[dry] DEL produto id={m['id']}  ({n_precos} preços p/ "
                      f"migrar ao id={id_correto})")
                print(f"     moji: {m['nome'][:60]!r}")
                print(f"     correto id={id_correto}")
                continue

            # Migra preços: UPDATE precos SET produto_id = id_correto
            # ON CONFLICT (produto_id, loja_id) → mantém o preço existente,
            # deleta o duplicata
            try:
                c.execute("""
                    UPDATE precos SET produto_id = ?
                    WHERE produto_id = ?
                      AND NOT EXISTS (
                        SELECT 1 FROM precos p2
                        WHERE p2.produto_id = ? AND p2.loja_id = precos.loja_id
                      )
                """, (id_correto, m["id"], id_correto))
                stats["precos_migrados"] += c.cursor.rowcount if hasattr(c.cursor, 'rowcount') else 0

                # Preços que colidiram (já existiam no correto para a mesma loja)
                c.execute("SELECT COUNT(*) AS n FROM precos WHERE produto_id = ?",
                          (m["id"],))
                sobras = c.fetchone()["n"]
                stats["precos_perdidos"] += sobras

                # Deleta o produto mojibakeado (preços remanescentes saem por CASCADE)
                c.execute("DELETE FROM precos WHERE produto_id = ?", (m["id"],))
                c.execute("DELETE FROM produtos WHERE id = ?", (m["id"],))
                stats["deletados_duplicata"] += 1
            except Exception as e:
                print(f"[ERRO] id={m['id']}: {e}")
                stats["erros"] += 1
                if getattr(conn, "is_postgres", False):
                    try:
                        conn.connection.rollback()
                    except Exception:
                        pass
        else:
            # Caso B: não há versão correta → corrigir in-place
            if not aplicar:
                stats["corrigidos_inplace"] += 1
                print(f"[dry] UPD produto id={m['id']}")
                print(f"     moji: {m['nome'][:60]!r}")
                print(f"     corr: {nome_corr[:60]!r}")
                continue
            try:
                busca = f"{nome_corr} {marca_corr} {cat_corr}".lower()
                c.execute("""
                    UPDATE produtos
                    SET nome = ?, marca = ?, categoria = ?, busca = ?
                    WHERE id = ?
                """, (nome_corr, marca_corr, cat_corr, busca, m["id"]))
                stats["corrigidos_inplace"] += 1
            except Exception as e:
                print(f"[ERRO] id={m['id']}: {e}")
                stats["erros"] += 1
                if getattr(conn, "is_postgres", False):
                    try:
                        conn.connection.rollback()
                    except Exception:
                        pass

    # Commit
    if aplicar:
        try:
            conn.connection.commit()
            print("\n[banco] commit OK.")
        except Exception as e:
            print(f"\n[ERRO commit] {e}")
            try:
                conn.connection.rollback()
            except Exception:
                pass
    else:
        print("\n[dry-run] NADA foi gravado.")
    conn.close()

    # Resumo
    print("\n=== RESUMO ===")
    print(f"  corrigidos_inplace:          {stats['corrigidos_inplace']}")
    print(f"  deletados_duplicata:         {stats['deletados_duplicata']}")
    print(f"  preços migrados:             {stats['precos_migrados']}")
    print(f"  preços perdidos (conflito):  {stats['precos_perdidos']}")
    print(f"  erros:                       {stats['erros']}")
    return 0


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Limpa produtos com mojibake (double-encoded UTF-8) do Neon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exemplos:
  python scraper/limpar_mojibake.py                 # detecta, não grava
  python scraper/limpar_mojibake.py --aplicar       # corrige/deleta
  python scraper/limpar_mojibake.py --ids           # só lista IDs
""",
    )
    ap.add_argument("--aplicar", action="store_true",
                    help="aplica correções (default: dry-run)")
    ap.add_argument("--ids", action="store_true",
                    help="só lista IDs dos produtos afetados (auditoria)")
    args = ap.parse_args()

    conn = abrir_conexao()
    return limpar(conn, aplicar=args.aplicar, so_ids=args.ids)


if __name__ == "__main__":
    sys.exit(main())
