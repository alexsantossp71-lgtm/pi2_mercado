# -*- coding: utf-8 -*-
"""
Configuração das seções-alvo do Dispensa Planejada (coleta ampliada de mercado).

Define, por loja, quais seções de nível 0 entram na coleta (supermercado:
mercearia, bebidas, hortifruti, açougue, frios, congelados, padaria, limpeza,
higiene, pet, bebê, suplementos etc.) e quais subseções atípicas são EXCLUÍDAS
(marketplace: maquiagem, perucas, roupas de pet/bebê, puericultura, cabeleireiro
etc.), conforme decisão do projeto.

A lista de folhas-alvo é materializada por `gerar_folhas.py` nos arquivos
`folhas_carrefour.json` e `folhas_atacadao.json`.
"""

# ---------------------------------------------------------------------------
# Seções de nível 0 incluídas por loja
# ---------------------------------------------------------------------------
SECOES_CARREFOUR = [
    "mercearia",
    "bebidas",
    "hortifruti",
    "acougue-e-peixaria",
    "frios-e-laticinios",
    "congelados",
    "padaria-e-matinais",
    "pratos-prontos-e-massas-frescas",
    "higiene-e-perfumaria",
    "limpeza-e-lavanderia",
    "bebe-e-infantil",
    "pet-care",
    "suplementos-alimentares",
    "cuidados-sexuais",
    "utilidades-domesticas",  # equivalente ao "bazar" do Pão de Açúcar
]

# Drogaria (medicamentos/farmácia) fica de fora: não é supermercado e não
# existe nas outras lojas. Eletrônicos/moda/brinquedos/toy etc. também ficam
# de fora (decisão do projeto).

SECOES_ATACADAO = [
    "mercearia",
    "frios-e-congelados",
    "bebidas",
    "higiene-e-perfumaria",
    "limpeza",
    "pet-shop",
    "hortifruti",
    "carnes-aves-e-peixes",
    "padaria-e-matinais",
    "descartaveis-e-embalagens",
    "cafeteria",
    "utilidades-domesticas",
    "bebe-e-infantil",
]

# ---------------------------------------------------------------------------
# Subseções atípicas de marketplace a EXCLUIR (substring do slug/ramo)
# ---------------------------------------------------------------------------
EXCLUIR_SUBSTRING = [
    # --- Higiene e perfumaria: maquiagem / unhas / cabelo / salão / depilação ---
    "maquiagem",
    "unhas",
    "perucas",
    "apliques",
    "acessorios-e-elasticos",
    "elasticos-para-cabelo",
    "presilhas",
    "grampos",
    "tiaras",
    "bobs-para-cabelo",
    "bancada-para-salao",
    "kits-e-tesouras-para-cabeleireiros",
    "cabeleireiro",
    "depilador",
    "depilacao",
    "ceras-e-cremes-depilatorios",
    "aparador-de-pelos",
    "aparelhos-eletricos",
    "lixa-de-pe",
    "descolorante",
    "tintura",
    "alisantes",
    "aquecedor-de-cera",
    "escova-de-higiene-corporal",
    "capas-e-protetores-de-roupa-para-cabeleireiro",
    "folha-e-lenco-falso-para-depilacao",
    "espremedor-de-tubos-de-tintas",
    "navalhas-e-laminas-para-pelos-faciais",
    "adesivos-para-seios",
    "adesivos-para-orelhas",
    "luneta-de-aumento",
    "saia-de-leve-e-leve",
    # --- Pet care: acessórios / roupas / transporte / aquário / equip. veterinário ---
    "roupas-para-pets",
    "roupas-de-pet",
    "bijuterias-e-joias-para-pets",
    "maquina-de-tosa",
    "secadores-e-sopradores-para-pet",
    "capas-protetoras-para-animais",
    "coleiras",
    "guias-para-pets",
    "brinquedos-para-pets",
    "arranhadores",
    "acessorios-pet",
    "acessorios-para-pets",
    "transporte-pet",
    "transporte-para-pets",
    "aquarios-e-acessorios",
    "casas-e-gaiolas",
    "gaiolas",
    "canis-e-cercas",
    "bolsas-e-caixas-para-transporte",
    "mantas-e-cobertas-para-pets",
    "canguru-e-sling-para-pet",
    "barreira-automotiva",
    "tela-de-protecao-para-pets",
    "adestramento",
    "montaria",
    "modelos-anatomicos",
    "mesas-veterinarias",
    "ultrassom-veterinario",
    "agulhas-descartaveis-para-pets",
    "bracadeira-para-medidor",
    "simuladores-medicos",
    "aparelhos-pet",
    # --- Bebê e infantil: puericultura / roupas / passeio / berço ---
    "roupas-para-bebe",
    "roupas-de-bebe",
    "roupas-para-criancas",
    "carrinhos",
    "cadeirinhas",
    "bercos",
    "passeio",
    "banheiras",
    "trocador-de-fraldas",
    "andador-para-bebes",
    "jumpers-para-bebes",
    "tapete-ginasio",
    "mobile",
    "cadeira-de-alimentacao",
    "bomba-de-tirar-leite",
    "baba-eletronica",
    "seguranca-do-bebe",
    "fraldas-de-pano",
    "cercados",
]

# Limite de paginação da VTEX (offset máximo 2.500): folhas maiores truncam
LIMITE_MAX_FOLHA = 2500
