#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes unitários das funções puras (sem banco) do integrar_carrefour_pa.py.

Cobre:
  - ean_valido: EANs reais (Carrefour/PA) vs códigos placeholder do GPA
  - _split_preco: regras de preco_promocional/preco_regular (com/sem promo)
  - _em_estoque: disponivel + estoque (incluindo 99999 do Carrefour)
  - _apresentacao: unidade + multiplicador (campo não vem pronto no JSON v2)
  - resolver_categoria: path do site -> categoria canônica (Carrefour + PA)

Roda sem dependência de banco (não importa db.py nem filtro_adulto).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Importa o módulo alvo: scraper/integrar_carrefour_pa.py
RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import integrar_carrefour_pa as mod


def test_ean_valido():
    # EAN-13 reais das amostras
    assert mod.ean_valido("7891079000229") == "7891079000229"  # Carrefour, Nissin
    assert mod.ean_valido("7891103221057") == "7891103221057"  # Carrefour, Leite Cond.
    assert mod.ean_valido("7896196061009") == "7896196061009"  # PA, La Pastina
    # Códigos internos do GPA (0000000*) são ACEITOS pelo integrador —
    # o catálogo já os usa como chave (1.700+ produtos). Decisão do projeto.
    assert mod.ean_valido("0000000339087") == "0000000339087"
    # Tudo zeros — rejeitado
    assert mod.ean_valido("0000000000000") is None
    # Tipos inválidos
    assert mod.ean_valido(None) is None
    assert mod.ean_valido("") is None
    assert mod.ean_valido("abc") is None
    assert mod.ean_valido("123") is None  # muito curto
    assert mod.ean_valido(7896196061009) == "7896196061009"  # int funciona
    print("✔ ean_valido")


def test_split_preco():
    # Sem promoção: preco == preco_original
    p1 = {"preco": 3.19, "preco_original": 3.19}
    promo, reg = mod._split_preco(p1)
    assert promo is None, f"esperava None, veio {promo}"
    assert reg == 3.19

    # Com promoção: preco < original (item 2 do Carrefour: 5.57 vs 7.29)
    p2 = {"preco": 5.57, "preco_original": 7.29}
    promo, reg = mod._split_preco(p2)
    assert promo == 5.57
    assert reg == 7.29

    # Sem preco_original: assume preço regular, sem promo
    p3 = {"preco": 10.0, "preco_original": None}
    promo, reg = mod._split_preco(p3)
    assert promo is None
    assert reg == 10.0

    # Sem nada — ambos None
    p4 = {"preco": None, "preco_original": None}
    promo, reg = mod._split_preco(p4)
    assert promo is None
    assert reg is None

    # Tolerância de 1 centavo (3.19 vs 3.1900001 float)
    p5 = {"preco": 3.19, "preco_original": 3.1900001}
    promo, reg = mod._split_preco(p5)
    assert promo is None
    assert abs(reg - 3.19) < 0.001

    # Strings numéricas (algumas APIs retornam como string)
    p6 = {"preco": "2.99", "preco_original": "4.99"}
    promo, reg = mod._split_preco(p6)
    assert promo == 2.99
    assert reg == 4.99

    print("✔ _split_preco")


def test_em_estoque():
    # Disponível com estoque finito (PA item 1: estoque=11)
    assert mod._em_estoque({"disponivel": True, "estoque": 11}) is True
    # Carrefour usa 99999 como "infinito"
    assert mod._em_estoque({"disponivel": True, "estoque": 99999}) is True
    # Indisponível
    assert mod._em_estoque({"disponivel": False, "estoque": 99999}) is False
    # Estoque zero
    assert mod._em_estoque({"disponivel": True, "estoque": 0}) is False
    # Sem flag disponivel — confia no estoque
    assert mod._em_estoque({"estoque": 5}) is True
    assert mod._em_estoque({"estoque": 0}) is False
    # Sem nada
    assert mod._em_estoque({}) is False
    print("✔ _em_estoque")


def test_apresentacao():
    # Sem multiplicador (ou =1) -> só unidade
    assert mod._apresentacao({"unidade": "un", "multiplicador": 1.0}) == "un"
    assert mod._apresentacao({"unidade": "kg", "multiplicador": None}) == "kg"
    # Com multiplicador > 1 -> "X und" (formato %g elimina .0)
    assert mod._apresentacao({"unidade": "un", "multiplicador": 6.0}) == "6 un"
    assert mod._apresentacao({"unidade": "un", "multiplicador": 12.0}) == "12 un"
    # Vazio
    assert mod._apresentacao({}) is None
    print("✔ _apresentacao")


def test_resolver_categoria():
    # Carrefour: path raiz->folha "/Mercearia/Massas e Molhos/Massas Instantâneas/"
    c = mod.resolver_categoria("/Mercearia/Massas e Molhos/Massas Instantâneas/", "Mercearia")
    assert c == "Mercearia", f"esperava Mercearia, veio {c}"

    # Carrefour promo: "/Açougue e Peixaria/Frios e Laticínios/"
    c = mod.resolver_categoria("/Açougue e Peixaria/Frios e Laticínios/", "Açougue e Peixaria")
    assert c == "Açougue e Peixaria"

    # PA: path folha->raiz "Melão e Melância / Frutas / Hortifruti / Alimentos"
    c = mod.resolver_categoria("Melão e Melância / Frutas / Hortifruti / Alimentos", "Alimentos")
    assert c == "Hortifruti", f"esperava Hortifruti, veio {c}"

    # PA: "Patês e Antepastos / Laticínios / Alimentos Refrigerados / Alimentos"
    # Nenhum dos segmentos intermediários casa, cai em "Alimentos" (raiz, que é canônica)
    c = mod.resolver_categoria("Patês e Antepastos / Laticínios / Alimentos Refrigerados / Alimentos", "Alimentos")
    assert c == "Alimentos", f"esperava Alimentos, veio {c}"

    # PA departamento "Limpeza" (alias) -> "Limpeza e Lavanderia"
    c = mod.resolver_categoria("Limpeza", "Limpeza")
    assert c == "Limpeza e Lavanderia", f"esperava 'Limpeza e Lavanderia', veio {c}"

    # PA "Perfumaria" (alias) -> "Higiene e Perfumaria"
    c = mod.resolver_categoria("Perfumaria", "Perfumaria")
    assert c == "Higiene e Perfumaria", f"esperava 'Higiene e Perfumaria', veio {c}"

    # Sem casamento -> fallback no corredor
    c = mod.resolver_categoria("/Seção Inexistente/", "Geral")
    assert c == "Geral", f"esperava Geral, veio {c}"

    print("✔ resolver_categoria")


def test_data_da_coleta():
    # Formato do JSON v2: "2026-10-29 21:15:30"
    d = mod.data_da_coleta({"coleta_em": "2026-10-29 21:15:30"})
    assert d == "2026-10-29"

    # ISO sem hora
    d = mod.data_da_coleta({"coleta_em": "2026-10-29T21:15:30"})
    assert d == "2026-10-29"

    # Só data
    d = mod.data_da_coleta({"coleta_em": "2026-10-29"})
    assert d == "2026-10-29"

    # Vazio -> hoje
    d = mod.data_da_coleta({})
    from datetime import date
    assert d == date.today().isoformat()

    print("✔ data_da_coleta")


if __name__ == "__main__":
    test_ean_valido()
    test_split_preco()
    test_em_estoque()
    test_apresentacao()
    test_resolver_categoria()
    test_data_da_coleta()
    print("\n[TODOS OS TESTES] ✔ 6/6 passaram")
