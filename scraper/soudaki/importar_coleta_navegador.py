#!/usr/bin/env python3
"""Converte a coleta feita no navegador na saída padrão do coletor.

Caminho para quem não tem Python na própria máquina: o navegador roda
`coletor_navegador.js` e baixa `soudaki_navegador.json`; esse arquivo
entra aqui e sai do outro lado como `produtos_soudaki.json` e
`precos_soudaki.json`, idênticos aos que o coletor normal produz.

Nada de lógica nova: a leitura de EAN, preço e marca é a mesma de
`coletar_soudaki.py`, já coberta por testes. Este módulo só substitui o
transporte — em vez de buscar na rede, lê o que o navegador trouxe.

    python3 scraper/soudaki/importar_coleta_navegador.py ~/Downloads/soudaki_navegador.json
    python3 scraper/soudaki/integrar_soudaki.py --aplicar
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import coletar_soudaki as C  # noqa: E402


def carregar(caminho: pathlib.Path) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Arquivo não encontrado: {caminho}")
    except json.JSONDecodeError as e:
        sys.exit(f"{caminho} não é JSON válido: {e}")

    if not isinstance(dados, dict) or "secoes" not in dados:
        sys.exit(f"{caminho} não tem a forma esperada.\n"
                 "Esperado o arquivo gerado por coletor_navegador.js, com a\n"
                 'chave "secoes".')
    if not dados["secoes"]:
        sys.exit("A coleta veio sem nenhuma seção. Confira o console do\n"
                 "navegador: provavelmente nada foi lido.")
    return dados


def brutos_por_secao(dados: dict) -> dict[str, list]:
    """Cada seção guarda o texto do __NEXT_DATA__; aqui vira lista de produtos."""
    saida: dict[str, list] = {}
    for secao, texto in sorted(dados["secoes"].items()):
        if isinstance(texto, str):
            try:
                payload = json.loads(texto)
            except json.JSONDecodeError:
                print(f"  {secao:<28} JSON inválido, pulando")
                continue
        else:
            payload = texto  # tolera o objeto já desserializado

        produtos = list(C.varrer_produtos(payload))
        saida[secao] = produtos
        print(f"  {secao:<28} {len(produtos):>5} produtos")
    return saida


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivo", type=pathlib.Path,
                    help="soudaki_navegador.json baixado pelo navegador")
    ap.add_argument("--salvar-raw", action="store_true",
                    help="Guarda os objetos brutos por seção, como o coletor.")
    args = ap.parse_args()

    dados = carregar(args.arquivo)

    print("=" * 74)
    print("COLETA FEITA NO NAVEGADOR")
    print("=" * 74)
    print(f"  arquivo ... {args.arquivo}")
    print(f"  quando .... {dados.get('coletado_em', '?')}")
    print(f"  origem .... {dados.get('origem', '?')}")
    print(f"  seções .... {len(dados['secoes'])}\n")

    por_secao = brutos_por_secao(dados)

    if args.salvar_raw:
        C.RAW.mkdir(parents=True, exist_ok=True)
        for secao, brutos in por_secao.items():
            with open(C.RAW / f"{secao}.json", "w", encoding="utf-8") as f:
                json.dump(brutos, f, ensure_ascii=False)

    # Daqui em diante é exatamente o que coletar_soudaki.main() faz.
    registros, vistos = [], set()
    for secao, brutos in por_secao.items():
        for bruto in brutos:
            reg = C.normalizar(bruto, secao)
            if not reg:
                continue
            chave = reg["gtin_ean"] or reg["sku"] or reg["nome_completo"]
            if chave in vistos:
                continue
            vistos.add(chave)
            registros.append(reg)

    if not registros:
        sys.exit("\nNenhum produto aproveitável. O arquivo tem seções, mas\n"
                 "nenhuma delas trouxe produto reconhecível.")

    C.relatorio_coleta(registros)
    C.gravar(registros)

    print("\nPróximo passo: gravar no banco com")
    print("  python3 scraper/soudaki/integrar_soudaki.py --aplicar")


if __name__ == "__main__":
    main()
