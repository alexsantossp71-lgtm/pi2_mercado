# -*- coding: utf-8 -*-
"""
scrap_paodeacucar.py - Coletor de produtos e precos do www.paodeacucar.com
PI2 UNIVESP 2026.2 - projeto pi2_mercado  |  loja_id = 2 (Pao de Acucar)

COMO FUNCIONA (engenharia reversa em 2026-10):
  - A vitrine www.paodeacucar.com (Next.js) usa protecao Azion (desafio JS
    /az-request-verify) nas paginas HTML - mas NAO usamos HTML.
  - A camada de dados fica em api.vendas.gpa.digital e responde SEM
    bloqueio a requests comuns (verificado com curl puro).
  - Endpoint de listagem (por departamento, incluindo todos os filhos):
        POST /pa/search/category-page
        {"partner":"linx","page":1,"resultsPerPage":100,
         "multiCategory":"alimentos","sortBy":"relevance",
         "department":"ecom","storeId":461,"customerPlus":true,"filters":[]}
    * page comeca em 1; resultsPerPage aceita 100
    * subcategorias com "|" (ex.: "bebidas-alcoolicas|vinhos-e-espumantes")
      estao QUEBRADAS no proprio site (404) - use apenas departamentos de topo
  - Endpoint de detalhe (EAN + prateleiras + preco/estoque autoritativo):
        GET /pa/v4/products/ecom/{id}?storeId=461
  - A arvore do menu vem do __NEXT_DATA__ da home
    (props.initialProps.layoutProps.categories) - ja embutida abaixo.

USO (Windows: py scrap_paodeacucar.py):
  python scrap_paodeacucar.py --probe                    # diagnostico
  python scrap_paodeacucar.py --listar-departamentos
  python scrap_paodeacucar.py                            # coleta completa (5 deps.)
  python scrap_paodeacucar.py --departamentos "bebidas"  # so um
  python scrap_paodeacucar.py --sem-detalhe              # rapido, SEM EAN
  python scrap_paodeacucar.py --limite-teste 50          # teste curto

TEMPO: com detalhe (padrao, busca EAN) ~1 request por produto: rode por
departamento ou deixe rodando (5 departamentos = ~13 mil produtos, algumas
horas com delay padrao). Com --sem-detalhe: poucos minutos (sem EAN).

SAIDA: mesmo formato do scrap_carrefour.py (loja_id=2).
Dependencias: requests
"""

import argparse
import datetime
import json
import sys
import time
import unicodedata

try:
    import requests
except ImportError:
    requests = None

API_BASE = "https://api.vendas.gpa.digital"
BRAND = "pa"                 # prefixo de path da marca (BRAND = "pa")
STORE_ID = 461               # loja online padrao (DEFAULTS.STORE_ID)
FONTE = "www.paodeacucar.com"
LOJA_ID = 2
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PAGINA = 100                 # resultsPerPage
VERSAO = "v1"

# --------------------------------------------------------------------------
# DEPARTAMENTOS-ALVO (menu real de www.paodeacucar.com)
# "alimentos" inclui acougue, congelados, refrigerados, hortifruti etc.
# Desativados a pedido (mesmo criterio do Carrefour): bazar, petshop,
# descartaveis, textil, caras-do-brasil, eletro (este 404 na API).
# --------------------------------------------------------------------------
DEPARTAMENTOS = [
    ("Alimentos",      "alimentos"),
    ("Bebidas",        "bebidas"),
    ("Limpeza",        "limpeza"),
    ("Perfumaria",     "perfumaria"),
    ("Bebê e Criança", "bebe-e-crianca"),
    # ("Descartáveis",   "descartaveis"),     <- desativado
    # ("Bazar",          "bazar"),            <- desativado
    # ("PetShop",        "petshop"),          <- desativado
    # ("Têxtil",         "textil"),           <- desativado
    # ("Caras do Brasil","caras-do-brasil"),  <- desativado
    # ("Eletro",         "eletro"),           <- 404 na API
]


def log(msg):
    print(msg, flush=True)


def sem_acento(txt):
    txt = unicodedata.normalize("NFKD", txt)
    return "".join(c for c in txt if not unicodedata.combining(c)).lower().strip()


class Coletor(object):
    """Cliente HTTP com retry (a API do GPA nao usa anti-bot)."""

    def __init__(self, delay=0.35, retries=3, store_id=STORE_ID):
        self.delay = delay
        self.retries = retries
        self.store_id = store_id
        self.sess = requests.Session()
        self.sess.headers.update({"User-Agent": UA, "Accept": "application/json",
                                  "Origin": "https://www.paodeacucar.com"})

    def get_json(self, url, silencioso=False):
        ultimo = None
        for tent in range(1, self.retries + 1):
            try:
                r = self.sess.get(url, timeout=40)
                if r.status_code == 200:
                    return r.json()
                ultimo = "HTTP %s" % r.status_code
            except Exception as e:
                ultimo = repr(e)[:120]
            if not silencioso and tent < self.retries:
                time.sleep(1.5 * tent)
        raise RuntimeError("falha GET %s (%s)" % (url[:90], ultimo))

    def post_json(self, url, corpo):
        ultimo = None
        for tent in range(1, self.retries + 1):
            try:
                r = self.sess.post(url, json=corpo, timeout=40)
                if r.status_code == 200:
                    return r.json()
                ultimo = "HTTP %s %s" % (r.status_code, (r.text or "")[:80])
            except Exception as e:
                ultimo = repr(e)[:120]
            if tent < self.retries:
                time.sleep(1.5 * tent)
        raise RuntimeError("falha POST %s (%s)" % (url[:90], ultimo))

    # ------------------------------------------------------------------ #
    def listar_categoria(self, slug, limite_teste=0):
        """Pagina 1..N do departamento. Retorna (products, total, truncado)."""
        url = "%s/%s/search/category-page" % (API_BASE, BRAND)
        corpo = {"partner": "linx", "page": 1, "resultsPerPage": PAGINA,
                 "multiCategory": slug, "sortBy": "relevance",
                 "department": "ecom", "storeId": self.store_id,
                 "customerPlus": True, "filters": []}
        prods, total, truncado = [], 0, False
        page = 1
        while True:
            corpo["page"] = page
            d = self.post_json(url, corpo)
            total = d.get("totalProducts") or 0
            pagina = d.get("products") or []
            prods.extend([p for p in pagina if isinstance(p, dict) and p.get("id")])
            page += 1
            if limite_teste and len(prods) >= limite_teste:
                break
            if len(pagina) < PAGINA:
                break
            if page > 250:          # trava de seguranca (25 mil produtos)
                truncado = True
                break
            time.sleep(self.delay)
        return prods, total, truncado

    def detalhe(self, pid):
        """GET v4 do produto: ean, shelves, sellInfos (preco/estoque)."""
        url = "%s/%s/v4/products/ecom/%s?storeId=%s" % (API_BASE, BRAND, pid, self.store_id)
        return self.get_json(url).get("content") or {}


# --------------------------------------------------------------------------- #
def montar_registro(lista, det, departamento):
    """Combina item da lista + detalhe v4 -> registro final.
    SEMANTICA DOS PRECOS (verificada no site):
      sellPrice  (v4) / price (listagem) = preco que o cliente paga ("por")
      currentPrice (v4)                  = preco de tabela ("de")
    """
    si = (det.get("sellInfos") or [{}])[0] if det else {}
    preco = si.get("sellPrice")
    if preco is None:
        preco = lista.get("price")
    preco_original = si.get("currentPrice")
    disponivel = bool(si.get("stock", lista.get("stock", False))) and (preco or 0) > 0
    shelves = det.get("shelfList") or []
    cat_chain = " / ".join(s.get("name", "") for s in shelves) if shelves else ""
    img = lista.get("productImages") or [det.get("thumbPath") or ""]
    img_url = ""
    if img:
        p = img[0] or ""
        img_url = "https://static.paodeacucar.com" + p if p.startswith("/") else p
    url_det = lista.get("urlDetails") or det.get("urlDetails") or ""
    if url_det and not url_det.startswith("http"):
        url_det = "https://www.paodeacucar.com" + url_det
    return {
        "ean": (det.get("ean") or "").strip() if det else "",
        "nome": (det.get("name") or lista.get("name") or "").strip(),
        "variante": "",
        "marca": (lista.get("brand") or det.get("brand") or "").strip(),
        "corredor": departamento,
        "categoria": cat_chain,
        "preco": preco if disponivel else None,
        "preco_original": preco_original,
        "disponivel": disponivel,
        "estoque": si.get("stockQuantity"),
        "unidade": "",
        "multiplicador": None,
        "preco_por_unidade": si.get("comparativePrice"),
        "url": url_det,
        "imagem": img_url,
        "id_site": str(lista.get("id")),
        "sku": str(lista.get("sku") or ""),
        "loja_id": LOJA_ID,
    }


def departamentos_selecionados(filtro):
    if not filtro:
        return list(DEPARTAMENTOS)
    pedidos = [sem_acento(x) for x in filtro.split(",") if x.strip()]
    sel, usados = [], set()
    for pedido in pedidos:
        achou = False
        for i, (nome, slug) in enumerate(DEPARTAMENTOS):
            if i in usados:
                continue
            n = sem_acento(nome)
            if pedido == n or pedido in n or pedido == slug:
                sel.append((nome, slug))
                usados.add(i)
                achou = True
        if not achou:
            raise SystemExit("Departamento desconhecido: %s\nUse --listar-departamentos." % pedido)
    return sel


def mode_probe(args):
    log("== PROBE www.paodeacucar.com (loja_id=%d) ==" % LOJA_ID)
    if requests is None:
        log("[X] requests nao instalado. Rode: pip install requests")
        return 1
    col = Coletor(delay=args.delay, store_id=args.store_id)
    log("[*] API: %s (store_id=%s)" % (API_BASE, args.store_id))
    log("[*] Totais por departamento:\n")
    log("    %-22s %10s  %s" % ("DEPARTAMENTO", "TOTAL", "EXEMPLO / PRECO"))
    ok = 0
    for nome, slug in departamentos_selecionados(args.departamentos):
        try:
            prods, total, trunc = col.listar_categoria(slug, limite_teste=3)
            if prods:
                p = prods[0]
                log("    %-22s %10s  %s | R$ %s"
                    % (nome[:22], total, (p.get("name") or "")[:32], p.get("price")))
                ok += 1
            else:
                log("    %-22s %10s  %s" % (nome[:22], total or 0, "(vazio)"))
        except Exception as e:
            log("    %-22s      ERR  %s" % (nome[:22], str(e)[:60]))
        time.sleep(col.delay)
    log("\n[*] Testando detalhe v4 (EAN) com o 1o produto...")
    try:
        prods, total, _ = col.listar_categoria("alimentos", limite_teste=1)
        det = col.detalhe(prods[0]["id"])
        _si = (det.get("sellInfos") or [{}])[0]
        log("    [OK] %s | EAN=%s | por=R$ %s (tabela R$ %s)"
            % ((det.get("name") or "?")[:40], det.get("ean"),
               _si.get("sellPrice"), _si.get("currentPrice")))
    except Exception as e:
        log("    [X] detalhe v4 falhou: %s" % str(e)[:90])
    log("\n[OK] Probe concluido: %d/%d departamentos respondendo."
        % (ok, len(departamentos_selecionados(args.departamentos))))
    return 0


def mode_listar():
    log("Departamentos-alvo (menu de www.paodeacucar.com):")
    log("%-24s %s" % ("NOME", "SLUG"))
    for nome, slug in DEPARTAMENTOS:
        log("%-24s %s" % (nome, slug))
    log("\nDesativados (mesmo criterio do Carrefour): Descartaveis, Bazar,")
    log("PetShop, Textil, Caras do Brasil, Eletro (reativar: descomente")
    log("na lista DEPARTAMENTOS).")
    return 0


def mode_coleta(args):
    sel = departamentos_selecionados(args.departamentos)
    col = Coletor(delay=args.delay, store_id=args.store_id)
    avisos = []
    log("== Coleta Pao de Acucar (loja_id=%d) - %s ==" % (LOJA_ID, VERSAO))
    log("[*] Departamentos: %s" % ", ".join(n for n, _ in sel))
    log("[*] store_id=%s | detalhe v4: %s" % (args.store_id, "SIM (com EAN)" if not args.sem_detalhe else "NAO (--sem-detalhe)"))

    vistos = set()
    produtos = []
    por_dep = {}
    t0 = time.time()
    for nome, slug in sel:
        log("[*] %s ..." % nome)
        prods, total, trunc = col.listar_categoria(slug, args.limite_teste)
        if trunc:
            avisos.append("%s: paginacao truncada em 250 paginas" % nome)
        novos = 0
        for i, p in enumerate(prods):
            pid = str(p.get("id"))
            if pid in vistos:
                continue
            det = {}
            if not args.sem_detalhe:
                try:
                    det = col.detalhe(pid)
                    time.sleep(col.delay)
                except Exception as e:
                    avisos.append("%s: detalhe %s falhou (%s)" % (nome, pid, str(e)[:50]))
                    det = {}
            rec = montar_registro(p, det, nome)
            vistos.add(pid)
            if not rec["disponivel"] and not args.incluir_indisponiveis:
                continue
            if args.so_com_ean and not rec["ean"]:
                continue
            produtos.append(rec)
            novos += 1
            if novos % 100 == 0:
                log("      %d produtos... (%.0fs)" % (novos, time.time() - t0))
        por_dep[nome] = novos
        log("    -> %d registros novos (api total=%d)" % (novos, total))

    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saida = {
        "fonte": FONTE,
        "loja_id": LOJA_ID,
        "coleta_em": agora,
        "api": "api.vendas.gpa.digital",
        "store_id": args.store_id,
        "versao_script": VERSAO,
        "total": len(produtos),
        "por_corredor": por_dep,
        "avisos": avisos,
        "produtos": produtos,
    }
    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)
    dt = time.time() - t0
    log("\n== RESUMO ==")
    for n, q in por_dep.items():
        log("  %-24s %6d" % (n, q))
    log("  TOTAL: %d produtos em %.1fs" % (len(produtos), dt))
    if avisos:
        log("  Avisos: %d" % len(avisos))
        for a in avisos[:10]:
            log("   - %s" % a)
    log("[OK] Salvo em: %s" % args.saida)
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="Coletor www.paodeacucar.com (loja_id=2) - PI2 pi2_mercado")
    ap.add_argument("--probe", action="store_true",
                    help="diagnostico: testa API e mostra totais por departamento")
    ap.add_argument("--listar-departamentos", action="store_true",
                    help="lista os departamentos-alvo e sai")
    ap.add_argument("--departamentos", default="",
                    help='subset, ex: "bebidas,limpeza" (sem acento ok)')
    ap.add_argument("--saida", default="paodeacucar_produtos.json",
                    help="arquivo JSON de saida (padrao: paodeacucar_produtos.json)")
    ap.add_argument("--delay", type=float, default=0.35,
                    help="pausa entre chamadas em segundos (padrao 0.35)")
    ap.add_argument("--store-id", type=int, default=STORE_ID,
                    help="storeId da API (padrao 461 = loja online)")
    ap.add_argument("--limite-teste", type=int, default=0,
                    help="para testes: no max N produtos por departamento")
    ap.add_argument("--sem-detalhe", action="store_true",
                    help="pula o GET v4 por produto (rapido, mas SEM EAN)")
    ap.add_argument("--incluir-indisponiveis", action="store_true",
                    help="mantem produtos sem preco/estoque (padrao: descarta)")
    ap.add_argument("--so-com-ean", action="store_true",
                    help="descarta registros sem EAN")
    args = ap.parse_args()

    if args.listar_departamentos:
        return mode_listar()
    if args.probe:
        return mode_probe(args)
    if requests is None:
        log("[X] requests nao instalado. Rode: pip install requests")
        return 1
    return mode_coleta(args)


if __name__ == "__main__":
    sys.exit(main())
