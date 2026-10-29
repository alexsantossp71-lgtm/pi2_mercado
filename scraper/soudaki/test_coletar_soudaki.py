# -*- coding: utf-8 -*-
"""
Testes do parser do coletor Soudaki.

O coletor não pode ser testado contra o site em CI, então o que é testável
sem rede — validação de EAN, varredura do payload, normalização — é coberto
aqui com payloads sintéticos no formato que o soudaki.com publica.

    python3 -m pytest -q scraper/soudaki/test_coletar_soudaki.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coletar_soudaki import (  # noqa: E402
    achatar, ean13_valido, extrair_ean, extrair_next_data, normalizar,
    parece_produto, varrer_produtos,
)


# --------------------------------------------------------------------------- #
# Validação de EAN
# --------------------------------------------------------------------------- #
def test_aceita_ean13_real():
    # EANs retirados do catálogo real do Pão de Açúcar.
    for ean in ("7891515435134", "7896036090244", "7894900300017",
                "7891000102640"):
        assert ean13_valido(ean), ean


def test_rejeita_sku_interno_da_daki():
    """O ponto central: SKU interno não pode passar por EAN.

    Era isso que enchia o catálogo de códigos como 15000004818, que nunca
    cruzam com outra loja.
    """
    for sku in ("15000004818", "20000000533", "30000000335", "50000000889"):
        assert not ean13_valido(sku), sku


def test_rejeita_formatos_invalidos():
    for ruim in ("", None, "123", "789151543513", "78915154351345",
                 "789151543513a", "0000000000000_exp", 7891515435134.0):
        assert not ean13_valido(ruim), repr(ruim)


def test_rejeita_digito_verificador_errado():
    assert ean13_valido("7891515435134")
    assert not ean13_valido("7891515435135")


# --------------------------------------------------------------------------- #
# Extração de EAN
# --------------------------------------------------------------------------- #
def test_ean_de_campo_explicito_vence():
    produto = {
        "sku": "15000004818",
        "name": "Leite Integral Piracanjuba 1L",
        "ean": "7898215151760",
        "packshot1_front_grid": {"url": "https://x/small_PROD_15000004818_P1.png"},
    }
    ean, origem = extrair_ean(produto)
    assert ean == "7898215151760"
    assert origem.startswith("campo:")


def test_ean_dentro_da_url_da_imagem():
    produto = {
        "sku": "ABC123",
        "name": "Iogurte",
        "packshot1_front_grid": {
            "url": "https://assets.jokrtech.com/small_BR_7896051167006_P1_a1b2.png"
        },
    }
    ean, origem = extrair_ean(produto)
    assert ean == "7896051167006"
    assert origem.startswith("texto:")


def test_sku_de_13_digitos_nao_vira_ean():
    """Um SKU com 13 dígitos não deve ser confundido com código de barras."""
    produto = {"sku": "1500000481800", "name": "Ovos", "price": {"amount": 9.9}}
    ean, origem = extrair_ean(produto)
    assert ean is None
    assert origem is None


def test_sem_ean_em_lugar_nenhum():
    produto = {"sku": "15000004818", "name": "Pão francês",
               "price": {"amount": 1.5}}
    assert extrair_ean(produto) == (None, None)


# --------------------------------------------------------------------------- #
# Varredura do payload
# --------------------------------------------------------------------------- #
def _next_data_padrao():
    """Formato que o coletor antigo lia: props.pageProps.preloadedProducts."""
    return {
        "props": {
            "pageProps": {
                "preloadedProducts": {
                    "Leites": [{
                        "sku": "15000004818",
                        "name": "Leite Integral Piracanjuba 1L",
                        "ean": "7898215151760",
                        "price": {"amount": 5.49, "currency": "BRL"},
                        "originalPrice": {"amount": 6.99},
                        "inventory": {"quantity": 12},
                        "category": {"categoryName": "Laticínios"},
                        "brand": {"brandName": "Piracanjuba"},
                        "packshot1_front_grid": {
                            "url": "https://assets.jokrtech.com/small_PROD_x.png"},
                    }],
                    "Ovos": [{
                        "sku": "20000000533",
                        "name": "Ovos Tipo Extra Branco com 20",
                        "price": {"amount": 18.9},
                        "inventory": {"quantity": 0},
                        "category": {"categoryName": "Padaria"},
                    }],
                }
            }
        }
    }


def test_varre_estrutura_conhecida():
    achados = list(varrer_produtos(_next_data_padrao()))
    assert len(achados) == 2
    assert {p["sku"] for p in achados} == {"15000004818", "20000000533"}


def test_varre_produto_fora_do_caminho_conhecido():
    """Produtos em cache de estado também devem ser capturados.

    A versão antiga lia só preloadedProducts e perdia o resto.
    """
    payload = _next_data_padrao()
    payload["props"]["pageProps"]["__APOLLO_STATE__"] = {
        "Product:999": {
            "sku": "99999999999",
            "name": "Produto só no cache Apollo",
            "price": {"amount": 3.5},
            "inventory": {"quantity": 2},
        }
    }
    skus = {p["sku"] for p in varrer_produtos(payload)}
    assert "99999999999" in skus
    assert len(skus) == 3


def test_nao_confunde_objeto_qualquer_com_produto():
    assert not parece_produto({"name": "Bebidas", "slug": "bebidas"})
    assert not parece_produto({"id": 1, "title": "Banner"})
    assert not parece_produto("texto")
    assert parece_produto({"sku": "1", "name": "X", "price": {"amount": 1}})


def test_extrai_next_data_do_html():
    payload = _next_data_padrao()
    html = ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload) + "</script></body></html>")
    assert extrair_next_data(html) == payload


def test_html_sem_next_data_nao_quebra():
    assert extrair_next_data("<html><body>nada</body></html>") is None
    assert extrair_next_data(
        '<script id="__NEXT_DATA__">{json quebrado</script>') is None


# --------------------------------------------------------------------------- #
# Normalização
# --------------------------------------------------------------------------- #
def test_normaliza_produto_com_ean():
    bruto = _next_data_padrao()["props"]["pageProps"]["preloadedProducts"]["Leites"][0]
    reg = normalizar(bruto, "laticinios")
    assert reg["gtin_ean"] == "7898215151760"
    assert reg["sku"] == "15000004818"
    assert reg["nome_completo"] == "Leite Integral Piracanjuba 1L"
    assert reg["preco_promocional"] == 5.49
    assert reg["preco_regular"] == 6.99
    assert reg["em_estoque"] is True
    assert reg["marca"] == "Piracanjuba"
    assert reg["secao"] == "laticinios"


def test_normaliza_produto_sem_ean_mantem_sku_separado():
    """gtin_ean fica vazio; o SKU não migra para o campo de EAN."""
    bruto = _next_data_padrao()["props"]["pageProps"]["preloadedProducts"]["Ovos"][0]
    reg = normalizar(bruto, "padaria")
    assert reg["gtin_ean"] is None
    assert reg["sku"] == "20000000533"
    assert reg["em_estoque"] is False


def test_estoque_por_booleano():
    reg = normalizar({"sku": "1", "name": "X", "price": {"amount": 2.0},
                      "available": True}, "mercearia")
    assert reg["em_estoque"] is True
    reg = normalizar({"sku": "2", "name": "Y", "price": {"amount": 2.0},
                      "available": False}, "mercearia")
    assert reg["em_estoque"] is False


def test_produto_sem_nome_e_descartado():
    assert normalizar({"sku": "1", "price": {"amount": 1.0}}, "x") is None


def test_preco_em_campo_alternativo():
    reg = normalizar({"sku": "1", "name": "X", "sellingPrice": 7.25,
                      "inventory": {"quantity": 1}}, "mercearia")
    assert reg["preco_promocional"] == 7.25


def test_preco_nao_depende_da_ordem_das_chaves():
    """Com originalPrice declarado antes de price, o atual ainda é o atual."""
    reg = normalizar({
        "originalPrice": {"amount": 9.99},
        "price": {"amount": 4.99},
        "sku": "1", "name": "X", "inventory": {"quantity": 3},
    }, "mercearia")
    assert reg["preco_promocional"] == 4.99
    assert reg["preco_regular"] == 9.99


def test_preco_escalar_e_objeto_funcionam_igual():
    escalar = normalizar({"sku": "1", "name": "X", "price": 3.5,
                          "inventory": {"quantity": 1}}, "x")
    objeto = normalizar({"sku": "2", "name": "Y", "price": {"amount": 3.5},
                         "inventory": {"quantity": 1}}, "x")
    assert escalar["preco_promocional"] == objeto["preco_promocional"] == 3.5


def test_preco_em_centavos():
    reg = normalizar({"sku": "1", "name": "X", "inventory": {"quantity": 1},
                      "price": {"centAmount": 1299, "currency": "BRL"}}, "x")
    assert reg["preco_promocional"] == 12.99


def test_sem_preco_nao_inventa_valor():
    reg = normalizar({"sku": "1", "name": "X", "inventory": {"quantity": 1}}, "x")
    assert reg["preco_promocional"] is None


def test_guarda_o_objeto_bruto():
    """Sem o bruto, cada mudança de campo exigiria coletar tudo de novo."""
    bruto = _next_data_padrao()["props"]["pageProps"]["preloadedProducts"]["Ovos"][0]
    reg = normalizar(bruto, "padaria")
    assert reg["_bruto"] == bruto


# --------------------------------------------------------------------------- #
# Achatamento
# --------------------------------------------------------------------------- #
def test_achatar_aninhado():
    plano = achatar({"a": {"b": {"c": 1}}, "d": [10, 20]})
    assert plano["a.b.c"] == 1
    assert plano["d[0]"] == 10
    assert plano["d[1]"] == 20


def test_achatar_ignora_vazios():
    plano = achatar({"a": None, "b": "", "c": 0})
    assert "a" not in plano and "b" not in plano
    assert plano["c"] == 0


# --------------------------------------------------------------------------- #
# Guarda de variante dietética (integrador)
# --------------------------------------------------------------------------- #
from integrar_soudaki import (  # noqa: E402
    marcadores_dieteticos, variante_dietetica_assimetrica,
)

import pytest  # noqa: E402


@pytest.mark.parametrize("a,b", [
    # Casos reais que a auditoria pegou passando indevidamente.
    ("Energético Red Bull Pomelo Lata 250ml",
     "Energético Red Bull Pomelo Sem Açúcar 250ml"),
    ("Refrigerante Coca-cola Sem Açúcar Pet 200ml",
     "Refrigerante Coca-Cola Original Pet 200 ml"),
    ("Geleia diet amora Linea 230g", "Geleia Amora Linea Vidro 230g"),
    ("Café Pilão Descafeinado 500g", "Café Torrado e Moído Pilão 500g"),
    ("Cerveja Heineken Zero Álcool 330ml", "Cerveja Heineken 330ml"),
])
def test_rejeita_variante_dietetica_assimetrica(a, b):
    assert variante_dietetica_assimetrica(a, b)


@pytest.mark.parametrize("a,b", [
    # 'integral' é descritor que o Soudaki omite; rejeitar aqui perdia pares
    # corretos. Fica a cargo do eixo de teor, que é simétrico.
    ("Aveia flocos finos Nestle 170g",
     "Aveia em Flocos Finos Integral Nestlé Caixa 170g"),
    ("Farinha de aveia Quaker 165g",
     "Farinha De Aveia Integral Quaker Caixa 165G"),
    ("Suco Xandô Laranja 1,5L", "Suco Integral Laranja Xandô Garrafa 1,5l"),
    # 'zero lactose' não pode disparar o eixo do açúcar.
    ("Leite Zero Lactose Piracanjuba 1L",
     "Leite Sem Lactose Piracanjuba Caixa 1l"),
    ("Pão de forma sem glúten e sem lactose Wickbold 300g",
     "Pão de Forma Original sem Glúten Zero Lactose Wickbold 300g"),
    ("Manteiga com sal Aviação 200g", "Manteiga com Sal Aviação Pote 200g"),
])
def test_aceita_quando_nao_ha_divergencia_dietetica(a, b):
    assert not variante_dietetica_assimetrica(a, b)


def test_zero_lactose_nao_e_lido_como_zero_acucar():
    assert marcadores_dieteticos("Leite Zero Lactose") == {"semlactose"}
    assert marcadores_dieteticos("Refrigerante Zero") == {"semacucar"}
