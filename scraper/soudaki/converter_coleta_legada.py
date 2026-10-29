# -*- coding: utf-8 -*-
"""
Converte as coletas antigas do Soudaki para o formato do coletor novo.

Motivo
------
As coletas do Soudaki que existem no repositório foram gravadas pelo coletor
antigo, que misturava SKU e EAN no mesmo campo `gtin_ean`. Antes de passá-las
pelo integrador novo é preciso separar os dois:

  - `15000001840`  -> SKU interno da plataforma (11 dígitos, não é EAN)
  - `7898215151760` -> EAN-13 de verdade (dígito verificador fecha)

Também recupera EANs que estavam escondidos na URL da imagem, que é de onde o
coletor antigo os tirava — mas com uma regex (`BR_(\\d{13})`) que só pegava um
dos padrões de nome de arquivo.

Fontes lidas (a mais recente prevalece por código):
  scraper/produtos_soudaki.json        + scraper/precos_soudaki_ampliado.json
  scraper/produtos_daki_bebidas.json   + scraper/precos_daki_bebidas_ampliado.json
  webapp/precos_soudaki_ampliado.json

Saída: scraper/soudaki/produtos_soudaki.json e precos_soudaki.json, no
formato que `integrar_soudaki.py` espera.

Uso
---
    python3 scraper/soudaki/converter_coleta_legada.py
    python3 scraper/soudaki/integrar_soudaki.py --aplicar
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent.parent
sys.path.insert(0, str(RAIZ / "scraper"))

from parear_soudaki_pa import ean13_valido  # noqa: E402

RE_13 = re.compile(r"(?<!\d)(\d{13})(?!\d)")

# (arquivo de produtos, arquivo de preços). O de produtos pode ser None
# quando o de preços já traz nome, marca e seção.
FONTES = [
    ("scraper/produtos_soudaki.json", "scraper/precos_soudaki_ampliado.json"),
    ("scraper/produtos_daki_bebidas.json",
     "scraper/precos_daki_bebidas_ampliado.json"),
    (None, "webapp/precos_soudaki_ampliado.json"),
]


def carregar(rel: str):
    caminho = RAIZ / rel
    if not caminho.exists():
        return None
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def para_float(v):
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def extrair_ean(codigo: str, imagem: str) -> str | None:
    """EAN só quando o dígito verificador fecha. SKU nunca vira EAN."""
    if ean13_valido(codigo):
        return codigo
    for achado in RE_13.findall(imagem or ""):
        if ean13_valido(achado):
            return achado
    return None


def main() -> None:
    registros: dict[str, dict] = {}
    origem = Counter()

    for arq_prod, arq_prec in FONTES:
        precos = carregar(arq_prec)
        if not isinstance(precos, list):
            continue
        prods = {}
        if arq_prod:
            lista = carregar(arq_prod)
            if isinstance(lista, list):
                prods = {str(p.get("gtin_ean")).strip(): p for p in lista}

        novos = atualizados = 0
        for pr in precos:
            codigo = str(pr.get("gtin_ean") or "").strip()
            if not codigo:
                continue
            meta = prods.get(codigo, {})
            nome = (pr.get("nome_completo") or meta.get("nome_completo")
                    or "").strip()
            if not nome:
                continue
            imagem = pr.get("imagem_url") or meta.get("imagem_url") or ""
            data = str(pr.get("data_coleta") or "")[:10]

            anterior = registros.get(codigo)
            if anterior and anterior["_data"] >= data:
                continue
            if anterior:
                atualizados += 1
            else:
                novos += 1

            ean = extrair_ean(codigo, imagem)
            registros[codigo] = {
                "_data": data,
                "gtin_ean": ean,
                "identificador": ean or f"SKU-SOUDAKI-{codigo}",
                "sku_soudaki": codigo,
                "nome_completo": nome,
                "marca": (pr.get("marca") or meta.get("marca")
                          or "Não Informada"),
                "secao": pr.get("secao") or meta.get("secao"),
                "subsecao": (pr.get("categoria") or meta.get("subsecao")
                             or pr.get("secao")),
                "imagem_url": imagem or None,
                "preco_regular": para_float(pr.get("preco_regular")),
                "preco_promocional": para_float(pr.get("preco_promocional")),
                "em_estoque": str(pr.get("em_estoque")).strip().lower()
                in ("true", "1", "sim"),
            }
        origem[arq_prec] = (len(precos), novos, atualizados)

    print(f"{'ARQUIVO':<48}{'REG':>7}{'NOVOS':>8}{'MAIS RECENTES':>15}")
    print("-" * 78)
    for arq, (total, novos, atu) in origem.items():
        print(f"{arq:<48}{total:>7}{novos:>8}{atu:>15}")

    produtos, precos_out = [], []
    for codigo in sorted(registros):
        r = registros[codigo]
        produtos.append({
            "gtin_ean": r["gtin_ean"],
            "identificador": r["identificador"],
            "sku_soudaki": r["sku_soudaki"],
            "nome_completo": r["nome_completo"],
            "marca": r["marca"],
            "secao": r["secao"],
            "subsecao": r["subsecao"],
            "imagem_url": r["imagem_url"],
            "data_cadastro": r["_data"],
        })
        precos_out.append({
            "identificador": r["identificador"],
            "gtin_ean": r["gtin_ean"],
            "sku_soudaki": r["sku_soudaki"],
            "supermercado": "Soudaki",
            "preco_regular": r["preco_regular"],
            "preco_promocional": r["preco_promocional"],
            "em_estoque": r["em_estoque"],
            "data_coleta": r["_data"],
        })

    BASE.mkdir(parents=True, exist_ok=True)
    for nome, dados in (("produtos_soudaki.json", produtos),
                        ("precos_soudaki.json", precos_out)):
        with open(BASE / nome, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)

    com_ean = sum(1 for p in produtos if p["gtin_ean"])
    datas = Counter(p["data_cadastro"][:7] for p in produtos)
    print(f"\n  {len(produtos)} produtos convertidos")
    print(f"  com EAN-13 válido: {com_ean} ({com_ean/max(len(produtos),1)*100:.1f}%)")
    print(f"  sem EAN (vão como SKU-SOUDAKI-*): {len(produtos)-com_ean}")
    print(f"  por mês de coleta: {dict(sorted(datas.items()))}")
    print(f"\n  gravado em {BASE}")
    print("  próximo: python3 scraper/soudaki/integrar_soudaki.py --aplicar")


if __name__ == "__main__":
    main()
