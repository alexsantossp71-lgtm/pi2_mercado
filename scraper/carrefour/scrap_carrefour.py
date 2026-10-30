# -*- coding: utf-8 -*-
"""
scrap_carrefour.py - Coletor de produtos e precos do mercado.carrefour.com.br
PI2 UNIVESP 2026.2 - projeto pi2_mercado  |  loja_id = 1 (Carrefour Mercado)

COMO FUNCIONA (descoberto por engenharia reversa em 2026-10):
  - A vitrine mercado.carrefour.com.br e um app React Router 7 com backend VTEX
    (conta "carrefourbrfood"), protegido por Cloudflare/CAPTCHA na vitrine.
  - POREM a API classica da VTEX responde SEM captcha em:
        https://carrefourbrfood.myvtex.com/api/catalog_system/...
  - Endpoint usado:
        /pub/products/search/?fq=C:/{categoria_id}/&_from=0&_to=49
        -> JSON com nome, marca, EAN, preco (commertialOffer.Price), estoque,
           categoria, imagem e link.
  - O preco da API e IGUAL ao preco exibido no site (verificado).
  - Paginacao VTEX: passos de 50; limite pratico de _from ~2500. Quando um
    corredor atinge o limite, o script desce para as subcategorias e coleta
    cada uma separadamente (com deduplicacao por id de produto + EAN).

USO (Windows: py scrap_carrefour.py OU python scrap_carrefour.py):
  python scrap_carrefour.py --probe                      # diagnostico rapido
  python scrap_carrefour.py --listar-corredores          # mostra os corredores-alvo
  python scrap_carrefour.py                              # coleta completa (11 corredores-alvo)
  python scrap_carrefour.py --corredores "Mercearia,Bebidas"
  python scrap_carrefour.py --limite-teste 100           # teste: 100 produtos por categoria
  python scrap_carrefour.py --saida coleta_carrefour.json --delay 0.6

SAIDA: arquivo JSON com:
  {
    "fonte": "mercado.carrefour.com.br", "loja_id": 1,
    "coleta_em": "...", "total": N, "por_corredor": {...},
    "avisos": [...],
    "produtos": [ { ean, nome, variante, marca, corredor, categoria,
                    preco, preco_original, disponivel, estoque, unidade,
                    multiplicador, url, imagem, id_site, loja_id }, ... ]
  }
  Registros com ean "" (ex.: hortifruti a granel) ficam com o campo vazio
  de proposito - o import pode filtra-los.

Dependencias: requests  (opcional: cloudscraper, usado so como plano B
se a VTEX ligar bloqueio; pip install cloudscraper)
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
try:
    import cloudscraper
except ImportError:
    cloudscraper = None

API_BASE = "https://carrefourbrfood.myvtex.com/api/catalog_system"
STOREFRONT = "https://mercado.carrefour.com.br"
LOJA_ID = 1
FONTE = "mercado.carrefour.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PAGINA = 50          # produtos por pagina (_from.._to)
MAX_FROM = 2450      # limite pratico da paginacao VTEX
VERSAO = "v1"

# ---------------------------------------------------------------------------
# CORREDORES-ALVO (menu real do mercado.carrefour.com.br -> IDs VTEX)
# Fora desta lista = NAO e alvo (marketplace: automotivo, audio, TVs, moveis...)
# Desativados a pedido (2026-10): Drogaria, Utilidades Domesticas, Pet Care
# ---------------------------------------------------------------------------
CORREDORES = [
    ("Mercearia",              3002077),
    ("Açougue e Peixaria",     2300000),
    ("Hortifruti",             2500000),
    ("Frios e Laticínios",     3002063),
    ("Padaria e Matinais",     3002068),
    ("Congelados",             3002075),
    ("Bebidas",                4599),
    ("Pratos Prontos e Massas Frescas", 3002078),
    ("Bebê e Infantil",        10021),
    ("Limpeza e Lavanderia",   26),
    ("Higiene e Perfumaria",   35),
    # ("Drogaria",              17),      <- desativado
    # ("Utilidades Domésticas", 45),      <- desativado
    # ("Pet Care",              36),      <- desativado
]


def log(msg):
    print(msg, flush=True)


def sem_acento(txt):
    txt = unicodedata.normalize("NFKD", txt)
    return "".join(c for c in txt if not unicodedata.combining(c)).lower().strip()


class Coletor(object):
    """Cliente HTTP com retry e plano B (cloudscraper)."""

    def __init__(self, delay=0.4, retries=3):
        self.delay = delay
        self.retries = retries
        self.usando_scraper = False
        self.scraper = None
        if requests:
            self.sess = requests.Session()
            self.sess.headers.update({"User-Agent": UA, "Accept": "application/json"})
        else:
            self.sess = None
        self._trocar_para_scraper()

    def _trocar_para_scraper(self):
        if cloudscraper is None:
            return
        if self.scraper is None:
            self.scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False})
            self.scraper.headers.update({"Accept": "application/json"})
            self.usando_scraper = True

    def get_json(self, url, silencioso=False):
        ultimo_erro = None
        for tent in range(1, self.retries + 1):
            try:
                if self.usando_scraper and self.scraper is not None:
                    r = self.scraper.get(url, timeout=40)
                elif self.sess is not None:
                    r = self.sess.get(url, timeout=40)
                else:
                    raise RuntimeError("requests nao instalado (pip install requests)")
                # VTEX responde 206 (Partial Content) nas buscas _from/_to
                if r.status_code in (200, 203, 206):
                    return r.json()
                txt = (r.text or "")[:200].lower()
                if r.status_code in (403, 429, 503) or "captcha" in txt or "challenge" in txt:
                    self._trocar_para_scraper()
                ultimo_erro = "HTTP %s" % r.status_code
            except Exception as e:
                ultimo_erro = repr(e)[:120]
                self._trocar_para_scraper()
            if not silencioso and tent < self.retries:
                time.sleep(1.5 * tent)
        raise RuntimeError("falha ao acessar %s (%s)" % (url[:90], ultimo_erro))

    # ------------------------------------------------------------------ #
    def baixar_arvore(self):
        """Arvore completa de categorias -> {root_id: [(cat_id, nome), ...]}"""
        url = "%s/pub/category/tree/15/" % API_BASE
        arvore = self.get_json(url)
        filhos = {}
        nomes = {}

        def walk(no):
            nomes[no["id"]] = no["name"]
            for c in no.get("children") or []:
                walk(c)

        for raiz in arvore:
            walk(raiz)
        for nome_root, rid in CORREDORES:
            lista = []
            for raiz in arvore:
                if raiz["id"] == rid:
                    for c in raiz.get("children") or []:
                        lista.append((c["id"], c["name"]))
                    break
            filhos[rid] = lista
        return filhos, nomes

    def buscar_categoria(self, cat_path, limite_teste=0, aviso=None):
        """Pagina produtos de uma categoria (inclui descendentes).
        cat_path: id da raiz ('3002077') ou caminho completo '4599/3744'.
        IMPORTANTE: nesta conta o filtro so funciona com caminho COMPLETO
        a partir da raiz (fq=C:/4599/3744/), nao com o id do filho sozinho.
        Retorna (lista_de_products, truncado)."""
        prods = []
        offset = 0
        while True:
            url = ("%s/pub/products/search/?fq=C:/%s/&_from=%d&_to=%d"
                   % (API_BASE, cat_path, offset, offset + PAGINA - 1))
            try:
                pagina = self.get_json(url)
            except RuntimeError as e:
                if aviso is not None:
                    aviso.append("categoria %s: falha em _from=%d (%s)"
                                 % (cat_path, offset, e))
                break
            if not isinstance(pagina, list):
                if aviso is not None and offset > 0:
                    aviso.append("categoria %s: resposta invalida em _from=%d"
                                 % (cat_path, offset))
                break
            prods.extend([p for p in pagina if isinstance(p, dict) and p.get("productId")])
            offset += PAGINA
            if limite_teste and len(prods) >= limite_teste:
                break
            if len(pagina) < PAGINA:
                break
            if offset > MAX_FROM:
                return prods, True          # truncado -> chamar subcategorias
            time.sleep(self.delay)
        return prods, False


# --------------------------------------------------------------------------- #
def escolher_seller(item):
    """Preferencia: sellerDefault disponivel -> qualquer disponivel -> default."""
    sellers = item.get("sellers") or []
    melhor_disp = None
    for s in sellers:
        co = s.get("commertialOffer") or {}
        if co.get("IsAvailable") and (co.get("Price") or 0) > 0:
            if s.get("sellerDefault"):
                return s
            if melhor_disp is None:
                melhor_disp = s
    if melhor_disp is not None:
        return melhor_disp
    for s in sellers:
        if s.get("sellerDefault"):
            return s
    return sellers[0] if sellers else None


def extrair_registros(p, corredor):
    """Um product VTEX -> um ou mais registros (1 por EAN distinto)."""
    pid = str(p.get("productId") or "")
    nome = (p.get("productName") or "").strip()
    marca = (p.get("brand") or "").strip()
    cats = p.get("categories") or []
    cat_path = (cats[0] if cats else "").strip()
    link_text = (p.get("linkText") or "").strip()
    url = "%s/produto/%s-%s" % (STOREFRONT, link_text, pid) if link_text else ""
    items = p.get("items") or []
    multi_item = len(items) > 1

    registros = []
    eans_vistos = set()
    reserva_sem_ean = None
    reserva_qualquer = None

    for it in items:
        ean = (it.get("ean") or "").strip()
        seller = escolher_seller(it)
        co = (seller or {}).get("commertialOffer") or {}
        disp = bool(co.get("IsAvailable")) and (co.get("Price") or 0) > 0
        preco = co.get("Price") if disp else None
        preco_orig = co.get("ListPrice")
        if preco_orig is None or (preco is not None and preco_orig < preco):
            preco_orig = preco
        imgs = it.get("images") or []
        img = ""
        if imgs:
            img = (imgs[0].get("imageUrl") or "").strip()
        variante = ""
        if multi_item:
            iname = (it.get("name") or "").strip()
            if iname and iname != nome:
                variante = iname
        rec = {
            "ean": ean,
            "nome": nome,
            "variante": variante,
            "marca": marca,
            "corredor": corredor,
            "categoria": cat_path,
            "preco": preco,
            "preco_original": preco_orig,
            "disponivel": disp,
            "estoque": co.get("AvailableQuantity"),
            "unidade": (it.get("measurementUnit") or "").strip(),
            "multiplicador": it.get("unitMultiplier"),
            "url": url,
            "imagem": img,
            "id_site": pid,
            "loja_id": LOJA_ID,
        }
        if ean:
            if ean in eans_vistos:
                continue
            eans_vistos.add(ean)
            if disp:
                registros.append(rec)
            else:
                if reserva_sem_ean is None:
                    reserva_sem_ean = rec  # placeholder; ver no fim
                registros.append(rec)      # indisponivel com EAN: mantem (preco None)
        else:
            if reserva_qualquer is None:
                reserva_qualquer = rec

    if not registros and reserva_qualquer is not None:
        registros.append(reserva_qualquer)
    return registros


# --------------------------------------------------------------------------- #
def corredores_selecionados(filtro):
    if not filtro:
        return list(CORREDORES)
    pedidos = [sem_acento(x) for x in filtro.split(",") if x.strip()]
    sel = []
    usados = set()
    for pedido in pedidos:
        achou = False
        for i, (nome, cid) in enumerate(CORREDORES):
            n = sem_acento(nome)
            if i in usados:
                continue
            if pedido == n or pedido in n:   # casa exata ou parcial
                sel.append((nome, cid))
                usados.add(i)
                achou = True
        if not achou:
            raise SystemExit("Corredor desconhecido: %s\nUse --listar-corredores."
                             % pedido)
    return sel


def mode_probe(args):
    log("== PROBE mercado.carrefour.com.br (%s) ==" % FONTE)
    if requests is None:
        log("[X] requests nao instalado. Rode: pip install requests")
        return 1
    col = Coletor(delay=args.delay)
    log("[*] Testando API VTEX: %s" % API_BASE)
    try:
        filhos, nomes = col.baixar_arvore()
        log("[OK] Arvore de categorias baixada (%d nos)." % len(nomes))
    except Exception as e:
        log("[X] API inacessivel: %s" % e)
        if cloudscraper is None:
            log("    Dica: pip install cloudscraper  (plano B contra bloqueio)")
        return 2
    log("[*] Consultando 1a pagina de cada corredor-alvo:\n")
    log("    %-34s %6s  %s" % ("CORREDOR", "PAG1", "EXEMPLO / PRECO"))
    ok = 0
    for nome, cid in corredores_selecionados(args.corredores):
        try:
            prods, trunc = col.buscar_categoria(str(cid), limite_teste=5)
            if prods:
                p = prods[0]
                it = (p.get("items") or [{}])[0]
                preco = None
                for s in it.get("sellers") or []:
                    co = s.get("commertialOffer") or {}
                    if co.get("IsAvailable"):
                        preco = co.get("Price")
                        break
                ex = (p.get("productName") or "")[:34]
                log("    %-34s %6d  %s | R$ %s" % (nome[:34], len(prods), ex, preco))
                ok += 1
            else:
                log("    %-34s %6d  %s" % (nome[:34], 0, "(vazio)"))
        except Exception as e:
            log("    %-34s   ERR  %s" % (nome[:34], str(e)[:60]))
        time.sleep(col.delay)
    log("\n[*] PAG1 = produtos na 1a pagina (50 = pagina cheia).")
    log("[OK] Probe concluido: %d/%d corredores respondendo."
        % (ok, len(corredores_selecionados(args.corredores))))
    log("     Proximo passo: python scrap_carrefour.py")
    return 0


def mode_listar():
    log("Corredores-alvo (do menu do mercado.carrefour.com.br):")
    log("%-36s %s" % ("NOME", "ID VTEX"))
    for nome, cid in CORREDORES:
        log("%-36s %s" % (nome, cid))
    log("\nFora do alvo (nao coletar): Automotivo, Audio, TVs, Informatica,")
    log("Moveis, Moda, Brinquedos, Papelaria + desativados: Drogaria,")
    log("Utilidades Domesticas, Pet Care (reativar: descomente na lista CORREDORES).")
    return 0


def mode_coleta(args):
    sel = corredores_selecionados(args.corredores)
    col = Coletor(delay=args.delay)
    avisos = []
    log("== Coleta Carrefour Mercado (loja_id=%d) - %s ==" % (LOJA_ID, VERSAO))
    log("[*] Corredores: %s" % ", ".join(n for n, _ in sel))
    log("[*] Baixando arvore de categorias...")
    filhos, _ = col.baixar_arvore()
    log("[OK] Arvore ok.")

    vistos = set()
    produtos = []
    por_corredor = {}
    t0 = time.time()
    for nome, cid in sel:
        log("[*] %-34s " % (nome + " ..."), )
        prods, truncado = col.buscar_categoria(str(cid), args.limite_teste, avisos)
        n_antes = len(prods)
        if truncado and not args.limite_teste:
            subcats = filhos.get(cid) or []
            for scid, snome in subcats:
                mais, tr2 = col.buscar_categoria("%s/%s" % (cid, scid),
                                                 args.limite_teste, avisos)
                prods.extend(mais)
                time.sleep(col.delay)
            log("(root=%d, +%d subcategorias)" % (n_antes, len(subcats)))
        elif truncado:
            log("(truncado em %d p/ teste)" % n_antes)
        else:
            log("(%d products pag.)" % n_antes)

        novos = 0
        for p in prods:
            registros = extrair_registros(p, nome)
            for rec in registros:
                chave = "%s::%s" % (rec["id_site"], rec["ean"])
                if chave in vistos:
                    continue
                vistos.add(chave)
                if not rec["disponivel"] and not args.incluir_indisponiveis:
                    continue
                if args.so_com_ean and not rec["ean"]:
                    continue
                produtos.append(rec)
                novos += 1
        por_corredor[nome] = novos
        log("      -> %d registros novos" % novos)

    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saida = {
        "fonte": FONTE,
        "loja_id": LOJA_ID,
        "coleta_em": agora,
        "api": "carrefourbrfood.myvtex.com",
        "versao_script": VERSAO,
        "total": len(produtos),
        "por_corredor": por_corredor,
        "avisos": avisos,
        "produtos": produtos,
    }
    caminho = args.saida
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)
    dt = time.time() - t0
    log("\n== RESUMO ==")
    for n, q in por_corredor.items():
        log("  %-34s %6d" % (n, q))
    log("  TOTAL: %d produtos em %.1fs" % (len(produtos), dt))
    if avisos:
        log("  Avisos: %d" % len(avisos))
        for a in avisos[:10]:
            log("   - %s" % a)
    log("[OK] Salvo em: %s" % caminho)
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="Coletor mercado.carrefour.com.br (loja_id=1) - PI2 pi2_mercado")
    ap.add_argument("--probe", action="store_true",
                    help="diagnostico: testa API e mostra amostra por corredor")
    ap.add_argument("--listar-corredores", action="store_true",
                    help="lista os corredores-alvo e sai")
    ap.add_argument("--corredores", default="",
                    help='subset, ex: "Mercearia,Bebidas" (sem acento ok)')
    ap.add_argument("--saida", default="carrefour_produtos.json",
                    help="arquivo JSON de saida (padrao: carrefour_produtos.json)")
    ap.add_argument("--delay", type=float, default=0.4,
                    help="pausa entre chamadas em segundos (padrao 0.4)")
    ap.add_argument("--limite-teste", type=int, default=0,
                    help="para testes: no max N produtos por categoria")
    ap.add_argument("--incluir-indisponiveis", action="store_true",
                    help="mantem produtos sem preco/estoque (padrao: descarta)")
    ap.add_argument("--so-com-ean", action="store_true",
                    help="descarta registros sem EAN (ex.: hortifruti a granel)")
    args = ap.parse_args()

    if args.listar_corredores:
        return mode_listar()
    if args.probe:
        return mode_probe(args)
    if requests is None:
        log("[X] requests nao instalado. Rode: pip install requests cloudscraper")
        return 1
    return mode_coleta(args)


if __name__ == "__main__":
    sys.exit(main())
