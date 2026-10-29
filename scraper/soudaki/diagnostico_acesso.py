#!/usr/bin/env python3
"""Descobre qual estratégia consegue ler a loja do Soudaki.

Em 29/10/2026 `soudaki.com/shop/*` passou a responder 200 com o corpo do
404 do site institucional (Webflow) para cliente HTTP simples, enquanto a
loja carrega normalmente num navegador comum. O mesmo endereço funcionou
com `requests` puro quatro dias antes.

Este script sobe uma escada de estratégias, da mais barata para a mais
cara, e diz qual delas devolve a loja de verdade. Rode na máquina onde o
site abre no navegador:

    python3 scraper/soudaki/diagnostico_acesso.py
    python3 scraper/soudaki/diagnostico_acesso.py --secao bebidas
    python3 scraper/soudaki/diagnostico_acesso.py --salvar

Depois é só informar qual linha deu OK: ela define como a coleta roda.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

BASE_URL = "https://soudaki.com"
AQUI = pathlib.Path(__file__).resolve().parent

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Exatamente o que o coletor mandava até agora.
HEADERS_SIMPLES = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Conjunto coerente com o User-Agent declarado.
HEADERS_COMPLETOS = {
    "User-Agent": UA,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": ('"Google Chrome";v="126", "Chromium";v="126", '
                  '"Not-A.Brand";v="24"'),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

def onde_estou() -> str:
    """País de saída desta máquina. Best-effort: sem rede, não atrapalha."""
    try:
        import requests
        r = requests.get("https://api.country.is/", timeout=6)
        d = r.json()
        return f"{d.get('country', '?')} (IP {d.get('ip', '?')})"
    except Exception:
        return "indeterminado"


PADRAO_NEXT = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def conta_produtos(html: str) -> int:
    """Quantos produtos dá para ler do __NEXT_DATA__ da página."""
    if not html:
        return 0
    m = PADRAO_NEXT.search(html)
    if not m:
        return 0
    try:
        dados = json.loads(m.group(1))
    except Exception:
        return 0

    total = 0
    pre = (dados.get("props", {}).get("pageProps", {})
           .get("preloadedProducts"))
    if isinstance(pre, dict):
        for v in pre.values():
            if isinstance(v, list):
                total += len(v)
    elif isinstance(pre, list):
        total = len(pre)

    if total == 0:  # a loja também já apareceu via cache do Apollo
        texto = m.group(1)
        total = texto.count('"__typename":"Product"')
    return total


def avalia(html: str | None, status: int | str) -> tuple[str, str]:
    """Devolve (veredito, observação) para uma resposta."""
    if html is None:
        return "FALHOU", "sem resposta"
    baixo = html[:4000].lower()
    if "__next_data__" in html.lower():
        n = conta_produtos(html)
        if n:
            return "OK", f"{n} produtos"
        return "PARCIAL", "veio __NEXT_DATA__, mas sem produtos"
    if "page not found" in baixo or "doesn't exist or has been moved" in baixo:
        return "BLOQUEADO", "404 do site institucional (Webflow)"
    if ("challenges.cloudflare.com" in baixo or "checking your browser" in baixo
            or "just a moment" in baixo):
        return "BLOQUEADO", "desafio do Cloudflare"
    return "?", f"HTTP {status}, {len(html)} bytes, sem __NEXT_DATA__"


# --------------------------------------------------------------------------- #
# Estratégias
# --------------------------------------------------------------------------- #
def e1_requests_simples(url: str):
    import requests
    r = requests.get(url, headers=HEADERS_SIMPLES, timeout=30)
    return r.text, r.status_code


def e2_requests_completo(url: str):
    import requests
    r = requests.get(url, headers=HEADERS_COMPLETOS, timeout=30)
    return r.text, r.status_code


def e3_sessao_aquecida(url: str):
    """Visita a home antes, como um navegador, e reaproveita os cookies."""
    import requests
    s = requests.Session()
    s.headers.update(HEADERS_COMPLETOS)
    inicial = s.get(f"{BASE_URL}/", timeout=30)
    time.sleep(1.0)
    r = s.get(url, timeout=30, headers={
        "Referer": f"{BASE_URL}/", "Sec-Fetch-Site": "same-origin"})
    cookies = len(s.cookies)
    return r.text, f"{inicial.status_code}/{r.status_code} ({cookies} cookies)"


def _playwright(url: str, headless: bool, aquecer: bool):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        nav = pw.chromium.launch(headless=headless)
        ctx = nav.new_context(user_agent=UA, locale="pt-BR",
                              viewport={"width": 1366, "height": 900})
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(ctx)
        except Exception:
            pass
        pag = ctx.new_page()
        try:
            if aquecer:
                pag.goto(f"{BASE_URL}/", wait_until="domcontentloaded",
                         timeout=45000)
                pag.wait_for_timeout(3000)
            resp = pag.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                pag.wait_for_selector("script#__NEXT_DATA__", timeout=15000)
            except Exception:
                pag.wait_for_timeout(5000)
            html = pag.content()
            status = resp.status if resp else "?"
            return html, status
        finally:
            ctx.close()
            nav.close()


def e4_playwright_headless(url: str):
    return _playwright(url, headless=True, aquecer=False)


def e5_playwright_aquecido(url: str):
    return _playwright(url, headless=True, aquecer=True)


def e6_playwright_janela(url: str):
    return _playwright(url, headless=False, aquecer=True)


ESCADA = [
    ("1 requests, cabeçalhos atuais", e1_requests_simples),
    ("2 requests, cabeçalhos completos", e2_requests_completo),
    ("3 sessão aquecida na home", e3_sessao_aquecida),
    ("4 Playwright headless", e4_playwright_headless),
    ("5 Playwright headless + home", e5_playwright_aquecido),
    ("6 Playwright com janela", e6_playwright_janela),
]


def main() -> None:
    global BASE_URL
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secao", default="laticinios")
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--salvar", action="store_true",
                    help="Grava o HTML de cada tentativa para inspeção.")
    ap.add_argument("--so", type=int, default=None, metavar="N",
                    help="Roda apenas a estratégia N.")
    args = ap.parse_args()
    BASE_URL = args.base_url.rstrip("/")
    url = f"{BASE_URL}/shop/{args.secao}/"

    pais = onde_estou()
    print(f"Alvo:   {url}")
    print(f"Saindo de: {pais}")
    if pais.startswith("BR"):
        print("Você está no Brasil, que é o caso que interessa.")
    elif pais != "indeterminado":
        print("ATENÇÃO: fora do Brasil. A loja da Daki pode simplesmente\n"
              "não ser servida para este país, e aí o teste não vale.")
    print()
    print(f"{'estratégia':<34} {'veredito':<11} observação")
    print("-" * 78)

    vencedora = None
    for rotulo, func in ESCADA:
        if args.so and not rotulo.startswith(str(args.so)):
            continue
        try:
            html, status = func(url)
        except ImportError as e:
            print(f"{rotulo:<34} {'PULADA':<11} falta {e.name}")
            continue
        except Exception as e:
            print(f"{rotulo:<34} {'ERRO':<11} "
                  f"{type(e).__name__}: {str(e)[:40]}")
            continue

        veredito, obs = avalia(html, status)
        print(f"{rotulo:<34} {veredito:<11} {obs}")

        if args.salvar and html:
            destino = AQUI / f"tentativa_{rotulo[0]}.html"
            destino.write_text(html, encoding="utf-8")

        if veredito == "OK" and vencedora is None:
            vencedora = rotulo
        time.sleep(1.5)

    print("-" * 78)
    if vencedora:
        print(f"\nFunciona: {vencedora}")
        if vencedora.startswith("1"):
            print("\nLeitura: a estratégia 1 é exatamente o que o coletor\n"
                  "sempre fez. Se ela passa daqui, nunca houve nada quebrado\n"
                  "no coletor - o que decidia era de onde partia a requisição.\n"
                  "Nada de proxy, nada de Playwright.")
            print("\n    python3 scraper/soudaki/atualizar_soudaki.py")
        elif vencedora.startswith(("2", "3")):
            print("\nLeitura: cabeçalhos coerentes e/ou cookies da home\n"
                  "resolvem. Já é o padrão do coletor.")
            print("\n    python3 scraper/soudaki/atualizar_soudaki.py")
        else:
            print("\nLeitura: só com navegador de verdade. Há proteção\n"
                  "ativa de bot além da localização.")
            print("\n    python3 scraper/soudaki/coletar_soudaki.py --navegador\n"
                  "    python3 scraper/soudaki/integrar_soudaki.py --aplicar")
    else:
        print("\nNenhuma estratégia leu a loja.")
        print("Se o endereço abre no seu navegador mas nem a estratégia 6\n"
              "funciona, confira no navegador (F12, aba Network) para qual\n"
              "URL a loja realmente vai — pode ter mudado de lugar.")
        sys.exit(1)


if __name__ == "__main__":
    main()
