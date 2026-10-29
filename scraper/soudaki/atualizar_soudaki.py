# -*- coding: utf-8 -*-
"""
Atualiza os preços do Soudaki no banco, em um comando.

    python3 scraper/soudaki/atualizar_soudaki.py

Faz, em sequência:

  1. coleta https://soudaki.com/shop/ (descobrindo as seções na própria
     vitrine) e grava os JSONs em scraper/soudaki/;
  2. integra ao banco, vinculando por EAN, por SKU e por atributos;
  3. mostra quanto mudou.

Se a coleta falhar — site fora do ar, estrutura mudada, sem rede — o banco
não é tocado. Nesse caso rode o diagnóstico para ver o que a página expõe:

    python3 scraper/soudaki/coletar_soudaki.py --diagnostico --secoes bebidas

Para integrar as coletas antigas que já estão no repositório, sem acessar o
site:

    python3 scraper/soudaki/atualizar_soudaki.py --sem-coleta
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent.parent
DB_PADRAO = RAIZ / "webapp" / "backend" / "dispensa.db"
PY = sys.executable


def medir(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    db = sqlite3.connect(str(caminho))
    try:
        q = lambda s: db.execute(s).fetchone()[0]  # noqa: E731
        return {
            "precos_soudaki": q("SELECT COUNT(*) FROM precos WHERE loja_id = 4"),
            "em_estoque": q("SELECT COUNT(*) FROM precos WHERE loja_id = 4 "
                            "AND em_estoque = 1 AND preco_promocional > 0"),
            "paridade": q("SELECT COUNT(*) FROM (SELECT produto_id FROM precos "
                          "WHERE loja_id = 4 INTERSECT SELECT produto_id "
                          "FROM precos WHERE loja_id <> 4)"),
            "comparaveis": q("SELECT COUNT(*) FROM (SELECT produto_id FROM precos "
                             "GROUP BY produto_id HAVING "
                             "COUNT(DISTINCT loja_id) >= 2)"),
            "mais_recente": q("SELECT MAX(data_coleta) FROM precos "
                              "WHERE loja_id = 4") or "-",
        }
    finally:
        db.close()


def rodar(titulo: str, comando: list[str]) -> bool:
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70, flush=True)
    return subprocess.run(comando, cwd=str(RAIZ)).returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Coleta o Soudaki e grava os preços no banco.")
    ap.add_argument("--db", type=Path, default=DB_PADRAO)
    ap.add_argument("--sem-coleta", action="store_true",
                    help="Pula a coleta e integra o que já está em "
                         "scraper/soudaki/ (ou converte as coletas antigas).")
    ap.add_argument("--detalhe", action="store_true",
                    help="Visita a página de cada produto sem EAN. Lento, mas "
                         "é o que mais aumenta a paridade entre lojas.")
    ap.add_argument("--pausa", type=float, default=0.6,
                    help="Segundos entre requisições (padrão: 0.6).")
    args = ap.parse_args()

    if not args.db.exists():
        sys.exit(f"Banco não encontrado: {args.db}")

    antes = medir(args.db)

    if args.sem_coleta:
        if not (BASE / "produtos_soudaki.json").exists():
            if not rodar("CONVERTENDO AS COLETAS ANTIGAS DO REPOSITÓRIO",
                         [PY, str(BASE / "converter_coleta_legada.py")]):
                sys.exit("Falha ao converter as coletas antigas.")
    else:
        cmd = [PY, str(BASE / "coletar_soudaki.py"), "--pausa", str(args.pausa)]
        if args.detalhe:
            cmd.append("--detalhe")
        if not rodar("1/2  COLETANDO soudaki.com/shop/", cmd):
            print("\nA coleta falhou. O banco NÃO foi alterado.")
            print("Para ver o que a página está expondo hoje:")
            print("  python3 scraper/soudaki/coletar_soudaki.py "
                  "--diagnostico --secoes bebidas")
            sys.exit(1)

    if not rodar("2/2  GRAVANDO NO BANCO",
                 [PY, str(BASE / "integrar_soudaki.py"),
                  "--db", str(args.db), "--aplicar"]):
        sys.exit("Falha ao integrar. Há backup ao lado do banco.")

    depois = medir(args.db)
    print("\n" + "=" * 70)
    print("RESULTADO")
    print("=" * 70)
    rotulos = [
        ("precos_soudaki", "preços do Soudaki"),
        ("em_estoque", "  ... disponíveis com preço"),
        ("paridade", "produtos com Soudaki + outra loja"),
        ("comparaveis", "produtos comparáveis (>=2 lojas)"),
    ]
    for chave, rotulo in rotulos:
        a, d = antes.get(chave, 0), depois.get(chave, 0)
        seta = f"{d - a:+d}" if d != a else "="
        print(f"  {rotulo:<38}{a:>8} -> {d:>8}   {seta}")
    print(f"  {'coleta mais recente':<38}{antes.get('mais_recente','-'):>8}"
          f" -> {depois.get('mais_recente','-'):>8}")
    print("\nVeja o quadro completo com:")
    print("  python3 scraper/cobertura_precos.py")


if __name__ == "__main__":
    main()
