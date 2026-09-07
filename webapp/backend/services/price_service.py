"""
Price Service for Dispensa Planejada FastAPI Backend
Calculates single-store totals and performs multi-store optimization via SQL SGBD.
"""

from typing import List, Dict, Optional
from models import (
    CalculoRequest,
    CalculoResponse,
    ItemDivisao,
    LojaDivisao,
    LojaTotal,
    MultilojaResumo,
)
from services.product_service import get_product_by_id

LOJAS = {
    "carrefour": {"nome": "Carrefour - Ponta da Praia", "icone": "🛍️", "index": 0},
    "pao_de_acucar": {"nome": "Pão de Açúcar", "icone": "🥐", "index": 1},
    "atacadao": {"nome": "Atacadão", "icone": "🏬", "index": 2},
}

CHAVES_LOJA = ["carrefour", "pao_de_acucar", "atacadao"]


def calculate_basket_prices(request: CalculoRequest) -> CalculoResponse:
    # Resolve items from SGBD
    itens_resolvidos = []
    for item_in in request.itens:
        prod = get_product_by_id(item_in.id)
        if prod:
            itens_resolvidos.append({"produto": prod, "qtd": item_in.qtd})

    if not itens_resolvidos:
        return CalculoResponse(
            melhor_loja_unica=None,
            pior_loja_unica=None,
            economia_loja_unica=0.0,
            totais_lojas=[],
            multiloja=MultilojaResumo(total=0.0, economia_vs_pior=0.0, distribuicao=[]),
        )

    # 1. Single Store Totals
    totais_por_loja: Dict[str, float] = {k: 0.0 for k in CHAVES_LOJA}
    disponiveis_por_loja: Dict[str, int] = {k: 0 for k in CHAVES_LOJA}
    totais_itens = len(itens_resolvidos)

    for item in itens_resolvidos:
        prod = item["produto"]
        qtd = item["qtd"]
        precos = prod.get("preco", [])

        for idx, key in enumerate(CHAVES_LOJA):
            p_val = precos[idx] if idx < len(precos) else None
            estoque = prod.get("em_estoque", [])
            disponivel = not isinstance(estoque, list) or idx >= len(estoque) or estoque[idx] is not False
            if p_val is not None and disponivel:
                totais_por_loja[key] += p_val * qtd
                disponiveis_por_loja[key] += 1

    totais_lojas_list: List[LojaTotal] = []
    for key in CHAVES_LOJA:
        totais_lojas_list.append(
            LojaTotal(
                loja_key=key,
                loja_nome=LOJAS[key]["nome"],
                icone=LOJAS[key]["icone"],
                total=round(totais_por_loja[key], 2),
                itens_disponiveis=disponiveis_por_loja[key],
                itens_totais=totais_itens,
            )
        )

    # Filter stores that have at least one price
    lojas_com_preco = [lt for lt in totais_lojas_list if lt.total > 0]
    melhor_loja: Optional[LojaTotal] = None
    pior_loja: Optional[LojaTotal] = None
    economia_unica = 0.0

    if lojas_com_preco:
        lojas_ordenadas_unica = sorted(lojas_com_preco, key=lambda x: x.total)
        melhor_loja = lojas_ordenadas_unica[0]
        pior_loja = lojas_ordenadas_unica[-1]
        economia_unica = round(pior_loja.total - melhor_loja.total, 2)

    # 2. Multi-Store Optimization
    distribuicao_dict: Dict[str, List[ItemDivisao]] = {k: [] for k in CHAVES_LOJA}
    total_multiloja = 0.0

    for item in itens_resolvidos:
        prod = item["produto"]
        qtd = item["qtd"]
        precos = prod.get("preco", [])

        opcoes = []
        for idx, key in enumerate(CHAVES_LOJA):
            p_val = precos[idx] if idx < len(precos) else None
            estoque = prod.get("em_estoque", [])
            disponivel = not isinstance(estoque, list) or idx >= len(estoque) or estoque[idx] is not False
            if p_val is not None and disponivel:
                opcoes.append((key, p_val))

        if not opcoes:
            continue

        opcoes.sort(key=lambda x: x[1])
        melhor_loja_key, menor_preco = opcoes[0]
        custo = menor_preco * qtd
        total_multiloja += custo

        distribuicao_dict[melhor_loja_key].append(
            ItemDivisao(
                produto_id=prod["id"],
                nome=prod["nome"],
                gtin_ean=prod.get("gtin_ean"),
                qtd=qtd,
                preco_unitario=menor_preco,
                custo_total=round(custo, 2),
            )
        )

    distribuicao_list: List[LojaDivisao] = []
    for key in CHAVES_LOJA:
        itens_loja = distribuicao_dict[key]
        if itens_loja:
            subtotal = sum(i.custo_total for i in itens_loja)
            distribuicao_list.append(
                LojaDivisao(
                    loja_key=key,
                    loja_nome=LOJAS[key]["nome"],
                    icone=LOJAS[key]["icone"],
                    total=round(subtotal, 2),
                    itens=itens_loja,
                )
            )

    distribuicao_list.sort(key=lambda x: x.total, reverse=True)

    total_multiloja_rounded = round(total_multiloja, 2)
    economia_vs_pior = round((pior_loja.total - total_multiloja_rounded) if pior_loja else 0.0, 2)

    return CalculoResponse(
        melhor_loja_unica=melhor_loja,
        pior_loja_unica=pior_loja,
        economia_loja_unica=economia_unica,
        totais_lojas=totais_lojas_list,
        multiloja=MultilojaResumo(
            total=total_multiloja_rounded,
            economia_vs_pior=economia_vs_pior,
            distribuicao=distribuicao_list,
        ),
    )
