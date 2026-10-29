# -*- coding: utf-8 -*-
"""
Coletor Soudaki (plataforma JOKR/Daki) — captura tudo que a página expõe.

Por que reescrever
------------------
O coletor anterior (`scraper/coletar_e_integrar_soudaki.py`) lia apenas 6
campos de cada produto e tirava o EAN do nome do arquivo de imagem, com a
regex `BR_(\\d{13})`. Medido sobre os 1.538 produtos já coletados:

    imagens no padrão BR_<13 dígitos> ....  340  (22,1%)
    imagens com qualquer EAN-13 ..........  376  (24,4%)
    produtos com EAN-13 válido no banco ..  362  (23,5%)

Ou seja, o EAN vinha de um acidente do nome do arquivo. Sem EAN não há
cruzamento com as outras lojas: 76,5% do sortimento ficava sem par.

Pior, o SKU interno era gravado no campo `gtin_ean` quando o EAN faltava,
poluindo o catálogo com códigos como `15000004818` que nunca casam com nada.

O que este coletor faz de diferente
-----------------------------------
1. Guarda o objeto bruto de cada produto em `raw/`, para reprocessar sem
   precisar coletar de novo.
2. Varre o `__NEXT_DATA__` inteiro em profundidade em vez de ler só
   `props.pageProps.preloadedProducts` — produtos aparecem também em caches
   de estado (Apollo, Redux) que a versão antiga ignorava.
3. Procura o EAN em várias fontes, sempre validando o dígito verificador, e
   registra de onde veio (`ean_origem`).
4. Mantém `sku` e `gtin_ean` em campos separados. SKU interno nunca é gravado
   como EAN.
5. Emite um relatório de schema com todos os campos observados, para que o
   que existe na origem deixe de ser adivinhação.

Uso
---
    # descobre a estrutura antes de coletar tudo (1 seção, imprime o schema)
    python3 scraper/soudaki/coletar_soudaki.py --diagnostico --secoes bebidas

    # coleta completa
    python3 scraper/soudaki/coletar_soudaki.py

    # tenta enriquecer o EAN visitando a página de cada produto sem EAN
    python3 scraper/soudaki/coletar_soudaki.py --detalhe

    # reprocessa o que já está em raw/, sem rede
    python3 scraper/soudaki/coletar_soudaki.py --reprocessar

Requer `requests`. Rode da raiz do repositório.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent.parent
RAW = BASE / "raw"

BASE_URL = os.environ.get("SOUDAKI_BASE_URL", "https://soudaki.com")
HOJE = date.today().isoformat()

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

SECOES_CONHECIDAS = [
    "hortifruti", "bebidas", "laticinios", "padaria", "matinais", "saudaveis",
    "mercearia", "molhos-e-conservas", "acougue-e-peixaria", "churrasco",
    "congelados", "pratico-e-rapido", "biscoitos-e-salgadinhos",
    "chocolates-e-doces", "sorvetes-e-acai", "cervejas-e-drinks",
    "vinhos-e-espumantes", "destilados", "limpeza", "higiene-e-beleza",
    "utilidades", "pets", "bebe", "produtos-daki", "farmacia",
]

# Nomes de campo que costumam carregar o código de barras em plataformas
# de e-commerce. Verificados em ordem; o primeiro EAN-13 válido vence.
CAMPOS_EAN = (
    "ean", "ean13", "eancode", "gtin", "gtin13", "barcode", "barCode",
    "codigobarras", "globaltradeitemnumber", "upc", "externalid",
    "externalcode", "productcode", "referencecode", "codigo",
)

# Campos que identificam o produto na loja, mas NÃO são EAN.
CAMPOS_SKU = ("sku", "id", "productid", "slug", "externalid")

RE_13 = re.compile(r"\d{13}")


# --------------------------------------------------------------------------- #
# EAN
# --------------------------------------------------------------------------- #
def ean13_valido(valor) -> bool:
    """EAN-13 só vale com o dígito verificador correto.

    É isso que separa um código de barras real de um SKU interno de 13
    dígitos. Sem essa checagem o catálogo enche de código que não cruza.
    """
    s = str(valor or "").strip()
    if len(s) != 13 or not s.isdigit():
        return False
    soma = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(s[:12]))
    return (10 - soma % 10) % 10 == int(s[12])


def _chave(nome: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(nome).lower())


def extrair_ean(produto: dict) -> tuple[str | None, str | None]:
    """Procura o EAN em várias fontes. Devolve (ean, origem)."""
    plano = achatar(produto)

    # 1. Campo com nome explícito de código de barras.
    for caminho, valor in plano.items():
        folha = _chave(caminho.rsplit(".", 1)[-1])
        if folha in CAMPOS_EAN and ean13_valido(valor):
            return str(valor).strip(), f"campo:{caminho}"

    # 2. Qualquer campo cujo valor seja um EAN-13 válido, exceto os que
    #    sabidamente guardam identificador interno.
    for caminho, valor in plano.items():
        folha = _chave(caminho.rsplit(".", 1)[-1])
        if folha in CAMPOS_SKU:
            continue
        if ean13_valido(valor):
            return str(valor).strip(), f"valor:{caminho}"

    # 3. Sequência de 13 dígitos embutida em texto (URL de imagem, slug,
    #    descrição). Valida o dígito verificador antes de aceitar.
    for caminho, valor in plano.items():
        if not isinstance(valor, str) or len(valor) < 13:
            continue
        for candidato in RE_13.findall(valor):
            if ean13_valido(candidato):
                return candidato, f"texto:{caminho}"

    return None, None


# --------------------------------------------------------------------------- #
# Varredura do payload
# --------------------------------------------------------------------------- #
def achatar(obj, prefixo: str = "", saida: dict | None = None,
            profundidade: int = 0) -> dict:
    """Achata um objeto aninhado em {caminho: valor escalar}."""
    if saida is None:
        saida = {}
    if profundidade > 8:
        return saida
    if isinstance(obj, dict):
        for k, v in obj.items():
            achatar(v, f"{prefixo}.{k}" if prefixo else str(k), saida,
                    profundidade + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:12]):
            achatar(v, f"{prefixo}[{i}]", saida, profundidade + 1)
    else:
        if obj is not None and obj != "":
            saida[prefixo] = obj
    return saida


def parece_produto(obj) -> bool:
    """Identifica objetos de produto sem depender do caminho no JSON."""
    if not isinstance(obj, dict):
        return False
    chaves = {_chave(k) for k in obj}
    tem_nome = bool(chaves & {"name", "nome", "title", "productname"})
    tem_id = bool(chaves & {"sku", "productid", "id", "slug"})
    tem_preco = bool(chaves & {"price", "preco", "pricing", "amount",
                               "sellingprice", "currentprice"})
    tem_estoque = bool(chaves & {"inventory", "stock", "available",
                                 "quantity", "instock"})
    return tem_nome and tem_id and (tem_preco or tem_estoque)


def varrer_produtos(obj, profundidade: int = 0, vistos: set | None = None):
    """Percorre o payload inteiro coletando qualquer objeto de produto.

    A versão antiga lia só `props.pageProps.preloadedProducts`. Sites Next.js
    costumam repetir ou ampliar esses dados em caches de estado; varrer tudo
    pega o que estiver lá, e continua funcionando se a estrutura mudar.
    """
    if vistos is None:
        vistos = set()
    if profundidade > 12:
        return
    if isinstance(obj, dict):
        if parece_produto(obj):
            marca = id(obj)
            if marca not in vistos:
                vistos.add(marca)
                yield obj
        for v in obj.values():
            yield from varrer_produtos(v, profundidade + 1, vistos)
    elif isinstance(obj, list):
        for v in obj:
            yield from varrer_produtos(v, profundidade + 1, vistos)


def extrair_next_data(html: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                  html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Normalização
# --------------------------------------------------------------------------- #
def primeiro(plano: dict, *nomes, valido=None):
    """Primeiro valor cuja folha do caminho bate com um dos nomes."""
    alvos = {_chave(n) for n in nomes}
    for caminho, valor in plano.items():
        if _chave(caminho.rsplit(".", 1)[-1]) in alvos:
            if valido is None or valido(valor):
                return valor
    return None


# Sufixos usados quando o preço vem como objeto: {"amount": 5.49}.
SUFIXOS_VALOR = ("", ".amount", ".value", ".price", ".centamount")


def primeiro_preco(plano: dict, *nomes):
    """Valor monetário de um campo que pode ser escalar ou objeto aninhado.

    `price` tanto pode ser 5.49 quanto {"amount": 5.49, "currency": "BRL"}.
    Casar só pela folha do caminho confunde `price.amount` com
    `originalPrice.amount` — a ordem das chaves decidiria qual é o preço
    atual, o que é frágil. Aqui o caminho inteiro precisa bater.
    """
    for nome in nomes:
        alvo = _chave(nome)
        for sufixo in SUFIXOS_VALOR:
            esperado = _chave(alvo + sufixo)
            for caminho, valor in plano.items():
                if _chave(caminho) != esperado:
                    continue
                if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                    continue
                if valor <= 0:
                    continue
                # Alguns catálogos publicam o valor em centavos.
                return valor / 100 if sufixo == ".centamount" else float(valor)
    return None


def limpa_nome(texto: str) -> str:
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    return texto


def normalizar(produto: dict, secao: str) -> dict | None:
    plano = achatar(produto)

    nome = limpa_nome(primeiro(plano, "name", "nome", "title", "productName"))
    if not nome:
        return None

    preco = primeiro_preco(plano, "price", "sellingPrice", "currentPrice",
                           "salePrice", "finalPrice", "preco")
    if preco is None:
        # Último recurso: qualquer caminho com "price" que carregue um número.
        for caminho, valor in plano.items():
            if ("price" in caminho.lower() and not isinstance(valor, bool)
                    and isinstance(valor, (int, float)) and valor > 0):
                preco = float(valor)
                break

    preco_de = primeiro_preco(plano, "originalPrice", "listPrice",
                              "priceBeforeDiscount", "oldPrice",
                              "crossedPrice", "regularPrice", "fullPrice")

    quantidade = primeiro(plano, "quantity", "stock", "availableQuantity",
                          valido=lambda v: isinstance(v, (int, float)))
    disponivel = primeiro(plano, "available", "inStock", "isAvailable",
                          valido=lambda v: isinstance(v, bool))
    if disponivel is None:
        em_estoque = bool(quantidade and quantidade > 0)
    else:
        em_estoque = bool(disponivel)

    sku = primeiro(plano, "sku", "productId", "externalId")
    sku = str(sku).strip() if sku is not None else None

    ean, ean_origem = extrair_ean(produto)

    imagem = primeiro(plano, "url", "src", "imageUrl", "image",
                      valido=lambda v: isinstance(v, str)
                      and v.startswith("http")
                      and re.search(r"\.(png|jpg|jpeg|webp)", v, re.I))

    marca = primeiro(plano, "brand", "brandName", "marca", "manufacturer",
                     valido=lambda v: isinstance(v, str) and v.strip())
    categoria = primeiro(plano, "categoryName", "category", "categoria",
                         valido=lambda v: isinstance(v, str) and v.strip())

    return {
        "sku": sku,
        "gtin_ean": ean,
        "ean_origem": ean_origem,
        "nome_completo": nome,
        "marca": limpa_nome(marca) if marca else None,
        "preco_regular": preco_de if preco_de else preco,
        "preco_promocional": preco,
        "em_estoque": em_estoque,
        "quantidade_estoque": quantidade,
        "secao": secao,
        "categoria": limpa_nome(categoria) if categoria else secao,
        "imagem_url": imagem,
        "supermercado": "Soudaki",
        "data_coleta": HOJE,
        "_bruto": produto,
    }


# --------------------------------------------------------------------------- #
# Rede
# --------------------------------------------------------------------------- #
RE_LINK_SECAO = re.compile(r'/shop/([a-z0-9][a-z0-9\-]{2,60})/?["\'<\\]')

# Trechos de caminho que aparecem depois de /shop/ mas não são seção.
NAO_SECAO = {"produto", "product", "busca", "search", "carrinho", "cart",
             "checkout", "conta", "account", "login", "favoritos", "pedidos"}


def descobrir_secoes(html: str) -> list[str]:
    """Lê as seções diretamente da vitrine, em vez de confiar na lista fixa.

    A lista `SECOES_CONHECIDAS` foi herdada do coletor antigo e nunca foi
    conferida contra o site. Se uma seção foi renomeada ou criada depois,
    ela simplesmente não era coletada — e o erro é silencioso, porque a
    seção inexistente só devolve zero produtos.

    Procura em dois lugares: os objetos de categoria dentro do
    `__NEXT_DATA__` e, como rede de segurança, qualquer link /shop/<slug>/
    no HTML.
    """
    achados: list[str] = []
    vistos: set[str] = set()

    def registrar(slug) -> None:
        s = str(slug or "").strip().strip("/").lower()
        if (s and s not in vistos and s not in NAO_SECAO
                and re.fullmatch(r"[a-z0-9][a-z0-9\-]{2,60}", s)):
            vistos.add(s)
            achados.append(s)

    dados = extrair_next_data(html)
    if dados is not None:
        pilha = [dados]
        while pilha:
            no = pilha.pop()
            if isinstance(no, dict):
                # Objeto de categoria: tem slug e algo que o nomeie.
                tem_nome = any(k for k in no
                               if _chave(k) in ("name", "title", "label",
                                                "categoryname", "displayname"))
                for chave, valor in no.items():
                    if _chave(chave) in ("slug", "urlkey", "handle", "path") \
                            and isinstance(valor, str) and tem_nome:
                        registrar(valor.rsplit("/", 1)[-1])
                    pilha.append(valor)
            elif isinstance(no, list):
                pilha.extend(no)

    for slug in RE_LINK_SECAO.findall(html or ""):
        registrar(slug)
    return achados


def baixar(url: str, tentativas: int = 3, espera: float = 2.0) -> str | None:
    try:
        import requests
    except ImportError:
        sys.exit("Falta a biblioteca requests. Instale com:\n"
                 "    pip install requests")
    for n in range(tentativas):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
            print(f"    tentativa {n+1}: HTTP {r.status_code}", file=sys.stderr)
        except Exception as e:  # rede instável não deve derrubar a coleta
            print(f"    tentativa {n+1}: {type(e).__name__}: "
                  f"{str(e)[:90]}", file=sys.stderr)
        if n + 1 < tentativas:
            time.sleep(espera * (n + 1))
    return None


def coletar_secao(secao: str, salvar_raw: bool = True) -> list[dict]:
    html = baixar(f"{BASE_URL}/shop/{secao}/")
    if not html:
        return []
    dados = extrair_next_data(html)
    if not dados:
        print(f"    sem __NEXT_DATA__ em /shop/{secao}/")
        return []
    brutos = list(varrer_produtos(dados))
    if salvar_raw:
        RAW.mkdir(parents=True, exist_ok=True)
        with open(RAW / f"{secao}.json", "w", encoding="utf-8") as f:
            json.dump(brutos, f, ensure_ascii=False)
    return brutos


# --------------------------------------------------------------------------- #
# Relatórios
# --------------------------------------------------------------------------- #
def relatorio_schema(brutos: list[dict], limite: int = 45) -> None:
    """Mostra todo campo observado. É o que revela onde o EAN se esconde."""
    freq, exemplos = Counter(), {}
    for p in brutos:
        for caminho, valor in achatar(p).items():
            generico = re.sub(r"\[\d+\]", "[]", caminho)
            freq[generico] += 1
            exemplos.setdefault(generico, valor)
    total = len(brutos) or 1
    print(f"\n{'CAMPO':<52}{'FREQ':>7}{'%':>7}  EXEMPLO")
    print("-" * 110)
    for caminho, n in freq.most_common(limite):
        ex = str(exemplos[caminho])[:34].replace("\n", " ")
        print(f"{caminho[:51]:<52}{n:>7}{n/total*100:>6.0f}%  {ex}")
    print(f"\n{len(freq)} caminhos distintos em {len(brutos)} produtos.")

    print("\nCANDIDATOS A EAN (campos cujo valor passa no dígito verificador):")
    achados = Counter()
    for p in brutos:
        for caminho, valor in achatar(p).items():
            generico = re.sub(r"\[\d+\]", "[]", caminho)
            if ean13_valido(valor):
                achados[f"{generico} (valor direto)"] += 1
            elif isinstance(valor, str) and len(valor) >= 13:
                if any(ean13_valido(c) for c in RE_13.findall(valor)):
                    achados[f"{generico} (dentro do texto)"] += 1
    if achados:
        for caminho, n in achados.most_common(15):
            print(f"  {n:>6} ({n/total*100:>5.1f}%)  {caminho}")
    else:
        print("  nenhum. O EAN não está nesta página; use --detalhe.")


def relatorio_coleta(registros: list[dict]) -> dict:
    total = len(registros)
    com_ean = [r for r in registros if r["gtin_ean"]]
    origens = Counter(r["ean_origem"].split(":")[0] for r in com_ean
                      if r["ean_origem"])
    print("\n" + "=" * 74)
    print("RESULTADO DA COLETA")
    print("=" * 74)
    print(f"  produtos ................. {total:>6}")
    print(f"  com preço ................ {sum(1 for r in registros if r['preco_promocional']):>6}")
    print(f"  em estoque ............... {sum(1 for r in registros if r['em_estoque']):>6}")
    print(f"  com SKU .................. {sum(1 for r in registros if r['sku']):>6}")
    print(f"  com EAN-13 válido ........ {len(com_ean):>6}"
          f"  ({len(com_ean)/max(total,1)*100:>5.1f}%)")
    if origens:
        print("  origem do EAN:")
        for origem, n in origens.most_common():
            print(f"      {origem:<10} {n:>6}")
    print(f"  com marca ................ {sum(1 for r in registros if r['marca']):>6}")
    print(f"  com imagem ............... {sum(1 for r in registros if r['imagem_url']):>6}")
    por_secao = Counter(r["secao"] for r in registros)
    print("\n  por seção:")
    for secao, n in por_secao.most_common():
        print(f"      {secao:<28}{n:>6}")
    return {"total": total, "com_ean": len(com_ean)}


# --------------------------------------------------------------------------- #
# Gravação
# --------------------------------------------------------------------------- #
def gravar(registros: list[dict]) -> None:
    BASE.mkdir(parents=True, exist_ok=True)

    completo = BASE / "soudaki_completo.json"
    with open(completo, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=1)
    print(f"\n  completo (com objeto bruto) . {completo}")

    produtos, precos = [], []
    for r in registros:
        # Identificador do catálogo: EAN quando existe, senão SKU com prefixo
        # que deixa explícito que não é código de barras.
        ident = r["gtin_ean"] or (f"SKU-SOUDAKI-{r['sku']}" if r["sku"] else None)
        if not ident:
            continue
        produtos.append({
            "gtin_ean": r["gtin_ean"],
            "identificador": ident,
            "sku_soudaki": r["sku"],
            "nome_completo": r["nome_completo"],
            "marca": r["marca"] or "Não Informada",
            "secao": r["secao"],
            "subsecao": r["categoria"],
            "imagem_url": r["imagem_url"],
            "data_cadastro": HOJE,
        })
        precos.append({
            "identificador": ident,
            "gtin_ean": r["gtin_ean"],
            "sku_soudaki": r["sku"],
            "supermercado": "Soudaki",
            "preco_regular": r["preco_regular"],
            "preco_promocional": r["preco_promocional"],
            "em_estoque": r["em_estoque"],
            "data_coleta": HOJE,
        })

    for nome, dados in (("produtos_soudaki.json", produtos),
                        ("precos_soudaki.json", precos)):
        caminho = BASE / nome
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)
        print(f"  {nome:<28} {caminho}  ({len(dados)} registros)")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor Soudaki (JOKR/Daki).")
    ap.add_argument("--secoes", nargs="*", default=None,
                    help="Seções a coletar (padrão: as 25 conhecidas).")
    ap.add_argument("--diagnostico", action="store_true",
                    help="Imprime o schema observado e não grava os JSONs finais.")
    ap.add_argument("--detalhe", action="store_true",
                    help="Visita a página de cada produto sem EAN para tentar achá-lo.")
    ap.add_argument("--reprocessar", action="store_true",
                    help="Reprocessa o que está em raw/, sem acessar a rede.")
    ap.add_argument("--pausa", type=float, default=0.6,
                    help="Segundos entre requisições (padrão: 0.6).")
    ap.add_argument("--base-url", default=None,
                    help="Origem alternativa (espelho ou ensaio local). "
                         "Padrão: https://soudaki.com")
    args = ap.parse_args()

    if args.base_url:
        global BASE_URL
        BASE_URL = args.base_url.rstrip("/")
        print(f"Origem: {BASE_URL}")

    secoes = args.secoes
    if not secoes and not args.reprocessar:
        # Descobre as seções na própria vitrine; a lista fixa entra só como
        # complemento, para o caso de alguma não aparecer no menu.
        print(f"Descobrindo seções em {BASE_URL}/shop/ ...")
        indice = baixar(f"{BASE_URL}/shop/")
        if indice is None:
            # Sem a vitrine não há o que coletar. Abortar aqui evita insistir
            # em 25 seções, com retentativas, quando o problema é a conexão.
            sys.exit(
                f"Não foi possível acessar {BASE_URL}/shop/.\n"
                "Verifique a conexão e se o site responde no navegador.\n"
                "Para integrar as coletas que já estão no repositório:\n"
                "    python3 scraper/soudaki/atualizar_soudaki.py --sem-coleta"
            )
        descobertas = descobrir_secoes(indice)
        if descobertas:
            extras = [s for s in SECOES_CONHECIDAS if s not in descobertas]
            secoes = descobertas + extras
            print(f"  {len(descobertas)} descobertas na vitrine"
                  f" + {len(extras)} da lista fixa = {len(secoes)}")
            print(f"  {', '.join(descobertas[:12])}"
                  f"{' ...' if len(descobertas) > 12 else ''}")
        else:
            secoes = SECOES_CONHECIDAS
            print(f"  nada encontrado na vitrine; usando as {len(secoes)} "
                  "seções conhecidas")
    secoes = secoes or SECOES_CONHECIDAS

    brutos_por_secao: dict[str, list] = {}
    if args.reprocessar:
        if not RAW.exists():
            sys.exit(f"Nada em {RAW}. Rode a coleta antes de reprocessar.")
        for arq in sorted(RAW.glob("*.json")):
            with open(arq, encoding="utf-8") as f:
                brutos_por_secao[arq.stem] = json.load(f)
            print(f"  {arq.stem:<28}{len(brutos_por_secao[arq.stem]):>6} produtos (raw)")
    else:
        try:
            import requests  # noqa: F401
        except ImportError:
            sys.exit("Falta a dependência: python3 -m pip install requests")
        for i, secao in enumerate(secoes, 1):
            print(f"[{i}/{len(secoes)}] /shop/{secao}/")
            brutos = coletar_secao(secao)
            print(f"    {len(brutos)} produtos")
            brutos_por_secao[secao] = brutos
            time.sleep(args.pausa)

    todos_brutos = [p for lista in brutos_por_secao.values() for p in lista]
    if not todos_brutos:
        sys.exit("Nenhum produto coletado. Verifique acesso ao site.")

    if args.diagnostico:
        relatorio_schema(todos_brutos)
        print("\nModo diagnóstico: nenhum JSON final gravado.")
        return

    registros, vistos = [], set()
    for secao, brutos in brutos_por_secao.items():
        for bruto in brutos:
            reg = normalizar(bruto, secao)
            if not reg:
                continue
            chave = reg["gtin_ean"] or reg["sku"] or reg["nome_completo"]
            if chave in vistos:
                continue
            vistos.add(chave)
            registros.append(reg)

    if args.detalhe and not args.reprocessar:
        enriquecer_por_detalhe(registros, args.pausa)

    relatorio_coleta(registros)
    gravar(registros)

    print("\nPróximo passo: integrar ao banco com")
    print("  python3 scraper/soudaki/integrar_soudaki.py")


def enriquecer_por_detalhe(registros: list[dict], pausa: float) -> None:
    """Visita a página de cada produto sem EAN procurando o código lá."""
    alvos = [r for r in registros if not r["gtin_ean"]]
    print(f"\nEnriquecendo {len(alvos)} produtos sem EAN pela página de detalhe...")
    achados = 0
    for i, reg in enumerate(alvos, 1):
        plano = achatar(reg["_bruto"])
        slug = primeiro(plano, "slug", "urlKey", "handle",
                        valido=lambda v: isinstance(v, str) and v.strip())
        if not slug:
            continue
        html = baixar(f"{BASE_URL}/product/{slug}/", tentativas=2)
        if not html:
            html = baixar(f"{BASE_URL}/shop/{reg['secao']}/{slug}/", tentativas=1)
        if not html:
            continue
        dados = extrair_next_data(html)
        if not dados:
            continue
        for bruto in varrer_produtos(dados):
            ean, origem = extrair_ean(bruto)
            if ean:
                reg["gtin_ean"] = ean
                reg["ean_origem"] = f"detalhe/{origem}"
                achados += 1
                break
        if i % 25 == 0:
            print(f"    {i}/{len(alvos)} visitados, {achados} EANs novos")
        time.sleep(pausa)
    print(f"  EANs recuperados na página de detalhe: {achados}")


if __name__ == "__main__":
    main()
