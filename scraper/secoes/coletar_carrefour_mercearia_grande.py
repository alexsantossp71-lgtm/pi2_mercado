# -*- coding: utf-8 -*-
"""Coleta de todas as folhas de mercearia do Carrefour sem filtro.

O filtro `isAvailablePerSalesChannel_1:1` foi removido dos coletores, e a
filtragem de preços já acontece internamente (`extrair_preco`).  Esta
versão simplesmente itera sobre **todas** as folhas de mercearia e
executa `coletar_vtex` sem nenhum `filtro_fq`.

Caso alguma folha realmente ultrapasse o limite de offset da VTEX (2 500
itens), ela será truncada automaticamente – o número de folhas que
ultrapassam esse limite é muito pequeno, portanto a perda de itens será
mínima.
"""
import io, sys, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from coletor_vtex import coletar_vtex

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))

# Carrega folhas e filtra mercearia
folhas = json.load(open(os.path.join(BASE_DIR, 'folhas_carrefour.json'), encoding='utf-8'))['folhas']
mercearia = [f for f in folhas if f['slug'].startswith('mercearia/')]

print(f'Coletando {len(mercearia)} folhas de mercearia (sem filtro)')

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

coletar_vtex({
    "nome_supermercado": "Carrefour",
    "chave_loja": "carrefour",
    "base_url": "https://mercado.carrefour.com.br",
    "marcador_imagem": "carrefourbr",
    "user_agent": USER_AGENT,
    "folhas": mercearia,
    "pagina_tamanho": 50,
    "limite_max": 2500,
    # sem filtro_fq – a filtragem de preço é feita internamente
    "sleep": 0.3,
    "timeout": 20,
    "checkpoint_a_cada": 25,
    "arquivo_produtos": os.path.join(RAIZ, "produtos_ampliado.json"),
    "arquivo_precos": os.path.join(RAIZ, "precos_carrefour_ampliado.json"),
})

print('\nColeta Carrefour mercearia concluída.')
