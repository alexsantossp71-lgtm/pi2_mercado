# -*- coding: utf-8 -*-
"""
Ensaio local: serve páginas no formato do soudaki.com, para testar o coletor.

Para que serve
--------------
O coletor só pode ser exercitado de verdade contra o site, e nem sempre há
acesso a ele (em ambiente restrito, o filtro de saída derruba o handshake
TLS). Este servidor reproduz o formato das páginas — HTML com um
`__NEXT_DATA__` contendo os produtos — usando os dados reais do Soudaki que
já estão no repositório.

Com isso dá para verificar o caminho inteiro sem rede externa: descoberta de
seções, varredura do payload, extração de EAN, normalização, gravação dos
JSONs e integração no banco. O que fica por confirmar é só o formato que o
site publica hoje, que o `--diagnostico` responde em uma requisição.

Uso
---
    # terminal 1
    python3 scraper/soudaki/ensaio_local.py --porta 8777

    # terminal 2
    python3 scraper/soudaki/coletar_soudaki.py --base-url http://localhost:8777
    python3 scraper/soudaki/integrar_soudaki.py --db /tmp/ensaio.db --aplicar
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent

CATALOGO: dict[str, list] = {}
SECOES: list[dict] = []
POR_SLUG: dict[str, dict] = {}


def slugificar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = t.encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t)).strip("-")


def carregar() -> None:
    """Monta o catálogo do ensaio a partir das coletas reais do repositório."""
    prods = json.load(open(RAIZ / "scraper/produtos_soudaki.json",
                           encoding="utf-8"))
    precos = {str(p.get("gtin_ean")): p for p in json.load(
        open(RAIZ / "scraper/precos_soudaki_ampliado.json", encoding="utf-8"))}

    por_secao = defaultdict(list)
    for p in prods:
        codigo = str(p.get("gtin_ean") or "")
        pr = precos.get(codigo, {})
        nome = p.get("nome_completo") or ""
        if not nome:
            continue
        slug = f"{slugificar(nome)[:60]}-{codigo}"

        def num(v):
            try:
                return float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                return None

        # em_estoque aparece como int (1/0), bool e string conforme a coleta.
        bruto = pr.get("em_estoque")
        disponivel = str(bruto).strip().lower() in ("1", "true", "sim", "yes")

        # Formato de produto equivalente ao que a plataforma publica.
        item = {
            "sku": codigo,
            "name": nome,
            "slug": slug,
            "price": {"amount": num(pr.get("preco_promocional")),
                      "currency": "BRL"},
            "originalPrice": {"amount": num(pr.get("preco_regular"))},
            "inventory": {"quantity": 10 if disponivel else 0},
            "category": {"categoryName": p.get("subsecao") or "Geral"},
            "brand": {"brandName": p.get("marca") or ""},
            "packshot1_front_grid": {"url": p.get("imagem_url") or ""},
        }
        secao = slugificar(p.get("secao") or "geral")
        por_secao[secao].append(item)
        POR_SLUG[slug] = item

    CATALOGO.update(por_secao)
    for secao in sorted(por_secao):
        SECOES.append({"slug": secao, "name": secao.replace("-", " ").title()})


def pagina(payload: dict) -> bytes:
    return (
        "<!DOCTYPE html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
        "<title>Soudaki (ensaio)</title></head><body><div id=\"__next\"></div>"
        "<script id=\"__NEXT_DATA__\" type=\"application/json\">"
        + json.dumps(payload, ensure_ascii=False)
        + "</script></body></html>"
    ).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencia o log por requisição
        pass

    def _responder(self, corpo: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):  # noqa: N802
        caminho = self.path.split("?")[0].strip("/")
        partes = [p for p in caminho.split("/") if p]

        if partes == ["shop"]:
            return self._responder(pagina({"props": {"pageProps": {
                "categories": SECOES,
                "banners": [{"id": 1, "title": "Ofertas"}],  # ruído proposital
            }}}))

        if len(partes) == 2 and partes[0] == "shop":
            secao = partes[1]
            if secao not in CATALOGO:
                return self._responder(b"nao encontrado", 404)
            itens = CATALOGO[secao]
            # Metade em preloadedProducts, metade num cache de estado: é assim
            # que aparecem os produtos que o coletor antigo deixava escapar.
            meio = len(itens) // 2
            return self._responder(pagina({"props": {"pageProps": {
                "preloadedProducts": {secao: itens[:meio]},
                "__APOLLO_STATE__": {
                    f"Product:{i['sku']}": i for i in itens[meio:]},
            }}}))

        if len(partes) == 2 and partes[0] == "product":
            item = POR_SLUG.get(partes[1])
            if not item:
                return self._responder(b"nao encontrado", 404)
            return self._responder(pagina(
                {"props": {"pageProps": {"product": item}}}))

        return self._responder(b"nao encontrado", 404)


def main() -> None:
    ap = argparse.ArgumentParser(description="Servidor de ensaio do Soudaki.")
    ap.add_argument("--porta", type=int, default=8777)
    args = ap.parse_args()

    carregar()
    total = sum(len(v) for v in CATALOGO.values())
    print(f"Ensaio com {total} produtos em {len(CATALOGO)} seções")
    print(f"  http://localhost:{args.porta}/shop/")
    print("\nColete com:")
    print(f"  python3 scraper/soudaki/coletar_soudaki.py "
          f"--base-url http://localhost:{args.porta}")
    HTTPServer(("0.0.0.0", args.porta), Handler).serve_forever()


if __name__ == "__main__":
    main()
