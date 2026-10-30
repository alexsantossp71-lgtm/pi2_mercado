#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes offline do scrap_atacadao.py v2 (não faz rede).

Rode na pasta do script:  python teste_parser_atacadao.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrap_atacadao as s  # noqa: E402

OK = 0
FALHAS = []


def teste(nome, cond, extra=""):
    global OK
    if cond:
        OK += 1
        print(f"  ✔ {nome} {extra}")
    else:
        FALHAS.append(nome)
        print(f"  ✘ {nome} {extra}")


# --- produto VTEX REAL (Açúcar Bulnez, coletado da API em out/2026) ---
PROD_VTEX = {
    "productId": "171471",
    "productName": "Açúcar Refinado Bulnez 1kg",
    "brand": "Bulnez",
    "linkText": "acucar-refinado-bulnez-14485",
    "link": "https://atacadaobr.vtexcommercestable.com.br/acucar-refinado-bulnez-14485/p",
    "categories": ["/Mercearia/Açúcar e adoçantes/Açúcar/"],
    "items": [{
        "itemId": "63231",
        "name": "Açúcar Refinado Bulnez 1kg",
        "ean": "7896534405779",
        "images": [{"imageUrl": "https://atacadaobr.vteximg.com.br/arquivos/ids/2237110/g.jpg.png"}],
        "sellers": [{
            "sellerId": "1",
            "sellerName": "ATACADAO SA",
            "sellerDefault": True,
            "commertialOffer": {
                "Price": 3.19, "ListPrice": 3.19, "PriceWithoutDiscount": 3.19,
                "IsAvailable": True, "AvailableQuantity": 99999,
            },
        }],
    }],
}

# mesmo produto com promoção: Price < PriceWithoutDiscount
PROD_PROMO = {
    "productId": "1", "productName": "Produto X 500g", "brand": "Y",
    "items": [{
        "itemId": "9", "ean": "7891000000012",
        "images": [],
        "sellers": [{"commertialOffer": {
            "Price": 4.50, "ListPrice": 6.90, "PriceWithoutDiscount": 6.90,
            "IsAvailable": True, "AvailableQuantity": 10}}],
    }],
}

# sem preço (ex.: indisponível — aparece quando --sem-fq)
PROD_ZERADO = {
    "productId": "2", "productName": "Produto Z", "brand": "W",
    "items": [{
        "itemId": "8", "ean": "7891000000029",
        "images": [],
        "sellers": [{"commertialOffer": {
            "Price": 0.0, "ListPrice": 0.0, "IsAvailable": False, "AvailableQuantity": 0}}],
    }],
}

print("== teste_parser_atacadao (v2) ==")

# 1. mapa da consulta a partir do caminho
teste("map 3 níveis", s.FOLHAS_RAW.split(";")[0].split("|")[0].count("/") + 1 == 3)

# 2. header resources
class R:  # faux resposta
    def __init__(self, valor):
        self.headers = {"resources": valor}

teste("resources '0-49/542' -> 542", s.total_do_header(R("0-49/542")) == 542)
teste("resources '5-5/8' -> 8", s.total_do_header(R("5-5/8")) == 8)
teste("resources ausente -> None", s.total_do_header(R("")) is None)

# 3. EAN
teste("EAN 13 dígitos", s._ean_limpo("7896534405779") == "7896534405779")
teste("EAN vazio", s._ean_limpo(None) == "")
teste("EAN sujo (ref com EAN dentro)", s._ean_limpo("EAN:7896051111016") == "7896051111016")

# 4. apresentação
teste("apresentacao '1kg' no nome",
      s._apresentacao("Açúcar Refinado Bulnez 1kg", "") == "1 kg")
teste("apresentacao '400g'",
      s._apresentacao("Leite em Pó 400g", "") == "400 g")
teste("apresentacao '1,5L'",
      s._apresentacao("Vinho 1,5L", "") == "1.5 l")
teste("apresentacao sem medida -> descrição",
      s._apresentacao("Produto Genérico", "<p>Descrição <b>limpa</b>  aqui</p>") == "Descrição limpa aqui")

# 5. normalização produto real
reg = s.normalizar_produto(PROD_VTEX, "mercearia/acucar-e-adocantes/acucar", "Açúcar")
teste("sku do item", reg and reg["sku"] == "63231")
teste("gtin_ean", reg["gtin_ean"] == "7896534405779")
teste("categoria bonita", reg["categoria"] == "Mercearia")
teste("subsecao", reg["subsecao"] == "Açúcar")
teste("preco_regular", reg["preco_regular"] == 3.19)
teste("sem promoção quando Price==regular", reg["preco_promocional"] is None)
teste("em_estoque", reg["em_estoque"] is True)
teste("link trocado p/ www", reg["link"].startswith("https://www.atacadao.com.br/"))
teste("imagem", reg["imagem_url"].startswith("https://atacadaobr.vteximg.com.br/"))

# 6. promoção
reg2 = s.normalizar_produto(PROD_PROMO, "bebidas/cervejas/cerveja-pilsen", "Cerveja Pilsen")
teste("promo detectada", reg2["preco_promocional"] == 4.50)
teste("regular mantido", reg2["preco_regular"] == 6.90)

# 7. produto sem preço é descartado
teste("sem preço -> None", s.normalizar_produto(PROD_ZERADO, "x/y/z", "Z") is None)

# 8. regular menor que preço é corrigido
PROD_INVERT = {"productId": "3", "productName": "P", "brand": "B", "items": [{
    "itemId": "7", "ean": "7891000000036", "images": [],
    "sellers": [{"commertialOffer": {
        "Price": 10.0, "ListPrice": 8.0, "IsAvailable": True, "AvailableQuantity": 1}}]}]}
reg3 = s.normalizar_produto(PROD_INVERT, "x/y/z", "Z")
teste("regular<preço corrigido", reg3["preco_regular"] == 10.0)

# 9. fallback embutido
folhas = [i for i in s.FOLHAS_RAW.split(";") if "|" in i]
teste("fallback tem 515 folhas", len(folhas) == 515)
l1s = {f.split("|")[0].split("/")[0] for f in folhas}
teste("todos os deptos mapeados", l1s <= set(s.DEPTOS),
      extra=f"(deptos nas folhas: {len(l1s)})")
teste("paths com 3 níveis", all(f.split("|")[0].count("/") == 2 for f in folhas))

# 10. guarda anti-path-fantasma
teste("_norm_cat acentos/hífen",
      s._norm_cat("Padaria e matinais") == s._norm_cat("padaria-e-matinais") ==
      "padaria e matinais")
teste("_norm_cat VÍRGULA (Carnes, Aves e Peixes)",
      s._norm_cat("Carnes, Aves e Peixes") == s._norm_cat("carnes-aves-e-peixes") ==
      "carnes aves e peixes",
      extra=f"(obtive {s._norm_cat('Carnes, Aves e Peixes')!r})")
PROD_CERVA = {"categories": ["/Bebidas/Cervejas/Cerveja pilsen/", "/Bebidas/"]}
teste("cerveja pertence a bebidas", s._depto_bate(PROD_CERVA, "bebidas"))
teste("cerveja NÃO pertence a drogaria", not s._depto_bate(PROD_CERVA, "drogaria"))
PROD_ACUCAR = {"categories": ["/Mercearia/Açúcar e adoçantes/Açúcar/"]}
teste("açúcar pertence a mercearia", s._depto_bate(PROD_ACUCAR, "mercearia"))
teste("produto sem categories não trava", not s._depto_bate({}, "mercearia"))
teste("drogaria está na lista de exclusão",
      any("drogaria/medicamentos/x".startswith(p) for p in s.EXCLUIR_FOLHAS_PREFIXOS))

# 11. REGRA do fantasma (proporcional — categorias pequenas legítimas passam)
cat_pequena = [PROD_ACUCAR, {"categories": ["/Mercearia/Sopas/Sopa/"]}]
teste("categoria pequena 2/2 legítima NÃO é fantasma",
      not s._eh_fantasma(cat_pequena, "mercearia"))
teste("categoria 1/1 legítima NÃO é fantasma",
      not s._eh_fantasma([PROD_CERVA], "bebidas"))
fantasma10 = [PROD_CERVA, PROD_ACUCAR] * 5   # nada de drogaria
teste("amostra sem nenhum do depto É fantasma",
      s._eh_fantasma(fantasma10, "drogaria"))
mista = [PROD_CERVA] + [{"categories": ["/Bebidas/Águas/Água/"]}] * 9
teste("amostra com maioria do depto NÃO é fantasma",
      not s._eh_fantasma(mista, "bebidas"))
teste("amostra vazia não é fantasma", not s._eh_fantasma([], "mercearia"))

print()
if FALHAS:
    print(f"✘ {len(FALHAS)} FALHA(S): {FALHAS}")
    sys.exit(1)
print(f"✔ {OK} testes OK")
