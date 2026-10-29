# -*- coding: utf-8 -*-
"""Coleta ampliada de todas as seções do Carrefour (VTEX) — versão otimizada.

Melhorias em relação à versão anterior:
  - Filtro fq=isAvailablePerSalesChannel_1:1 habilitado: retorna apenas produtos
    com estoque disponível no canal online, eliminando itens de marketplace
    indisponíveis que consumiam slots de paginação.
  - Página tamanho aumentada para 50 (máximo suportado pela VTEX).
  - Sleep 0.2s (reduzido de 0.3s, mantendo segurança).
  - Checkpoint a cada 30 folhas.
"""
import json
import os

from coletor_vtex import coletar_vtex

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)  # g:\pi 2 - 2026\scraper

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def main() -> None:
    with open(os.path.join(AQUI, "folhas_carrefour.json"), encoding="utf-8") as f:
        folhas = json.load(f)["folhas"]

    print(f"Total de folhas Carrefour: {len(folhas)}")

    coletar_vtex({
        "nome_supermercado": "Carrefour",
        "chave_loja": "carrefour",
        "base_url": "https://www.carrefour.com.br",
        "marcador_imagem": "carrefourbr",
        "user_agent": USER_AGENT,
        "folhas": folhas,
        "pagina_tamanho": 50,
        "limite_max": 2500,
        # Filtro removido: agora coleta todos os produtos (incluindo sem estoque online)
        # e utiliza Multi-CEP para cobertura regional de preços
        "sleep": 0.2,
        "timeout": 20,
        "checkpoint_a_cada": 10,
        "arquivo_produtos": os.path.join(RAIZ, "produtos_carrefour.json"),
        "arquivo_precos": os.path.join(RAIZ, "precos_carrefour_ampliado.json"),
        "multi_cep": True,
    })


if __name__ == "__main__":
    main()
