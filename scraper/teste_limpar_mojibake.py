#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes unitários das funções puras (sem banco) do limpar_mojibake.py.

Cobre:
  - tem_mojibake: detecta double-encoding sem falsos positivos
    ("São", "Coração", "Âmbar" são legítimos)
  - decodificar_mojibake: reverte UTF-8→Latin-1→UTF-8
  - _norm_nome: normalização para match por nome

Roda offline (sem banco, sem dependências).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import limpar_mojibake as mod


def test_tem_mojibake():
    # --- Verdadeiros positivos (mojibake real) ---
    # "LinguiÃ§a" (Ã + § como 2 chars Unicode)
    assert mod.tem_mojibake("LinguiÃ§a Toscana Seara 600Gr") is True
    # "orgÃ¢nico" (Ã + ¢)
    assert mod.tem_mojibake("Tomate pelati orgÃ¢nico La Pastina 400g") is True
    # "AÃ§Ãºcar" (Ã + §, Ã + º)
    assert mod.tem_mojibake("Iogurte com AÃ§Ãºcar") is True
    # "TÃ´nica" (Ã + ´)
    assert mod.tem_mojibake("Gin TÃ´nica") is True
    # "ParmesÃ£o" (Ã + £)
    assert mod.tem_mojibake("Torrada ParmesÃ£o 100Gr") is True

    # --- Falsos positivos (NÃO é mojibake) ---
    # "São" (S + ã — ã é 1 char U+00E3, não 2)
    assert mod.tem_mojibake("São Paulo") is False
    # "Coração" (1 char ã)
    assert mod.tem_mojibake("Coração de Frango") is False
    # "Não" (1 char ã)
    assert mod.tem_mojibake("Não Informado") is False
    # "ESPORÃO" (1 char Ã em maiúscula — mas isolado, sem 2o char)
    assert mod.tem_mojibake("Vinho ESPORÃO Alentejo") is False
    # "Âmbar" (1 char Â seguido de m, que está fora do range U+00A0..U+00BF)
    assert mod.tem_mojibake("Taça Âmbar Wolff") is False
    # "Caminhão" (1 char ã)
    assert mod.tem_mojibake("Caminhão de Carga") is False

    # --- Casos vazios ---
    assert mod.tem_mojibake("") is False
    assert mod.tem_mojibake(None) is False
    assert mod.tem_mojibake("Texto sem acento") is False

    print("✔ tem_mojibake")


def test_decodificar_mojibake():
    # Mojibake → texto correto
    assert mod.decodificar_mojibake("LinguiÃ§a") == "Linguiça"
    assert mod.decodificar_mojibake("orgÃ¢nico") == "orgânico"
    assert mod.decodificar_mojibake("AÃ§Ãºcar") == "Açúcar"
    assert mod.decodificar_mojibake("TÃ´nica") == "Tônica"
    assert mod.decodificar_mojibake("ParmesÃ£o") == "Parmesão"
    # Composto: nome + marca + categoria
    assert mod.decodificar_mojibake("LinguiÃ§a Toscana 600Gr") == "Linguiça Toscana 600Gr"

    # Texto SEM mojibake → devolve intacto
    assert mod.decodificar_mojibake("Linguiça Toscana 600g") == "Linguiça Toscana 600g"
    assert mod.decodificar_mojibake("Coração de Frango") == "Coração de Frango"
    assert mod.decodificar_mojibake("São Paulo") == "São Paulo"

    # Vazio
    assert mod.decodificar_mojibake("") == ""
    assert mod.decodificar_mojibake(None) is None

    print("✔ decodificar_mojibake")


def test_norm_nome():
    # Trim + lower + colapsa espaços
    assert mod._norm_nome("  Linguiça  Toscana  ") == "linguiça toscana"
    assert mod._norm_nome("Coração de Frango") == "coração de frango"
    assert mod._norm_nome("") == ""
    assert mod._norm_nome(None) == ""
    # "Coca   Cola   2L" → "coca cola 2l"
    assert mod._norm_nome("Coca   Cola   2L") == "coca cola 2l"

    # IMPORTANTE: o nome CORRETO e o mojibakeado têm a mesma normalização
    # só se o mojibake for decodificado ANTES de normalizar.
    # "LinguiÃ§a" (moji) normaliza para "linguiÃÂ§a" — DIFERENTE de "linguiça"
    # Por isso o script decodifica antes de buscar por nome.
    assert mod._norm_nome("LinguiÃ§a") != mod._norm_nome("Linguiça"), \
        "mojibake e correto devem ter nomes normalizados diferentes"
    # Após decodificar, ficam iguais:
    assert mod._norm_nome(mod.decodificar_mojibake("LinguiÃ§a")) == \
           mod._norm_nome("Linguiça")

    print("✔ _norm_nome")


if __name__ == "__main__":
    test_tem_mojibake()
    test_decodificar_mojibake()
    test_norm_nome()
    print("\n[TODOS OS TESTES] ✔ 3/3 passaram")
