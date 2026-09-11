"""
Data Loader Module for Dispensa Planejada FastAPI Backend
Loads JSON datasets into memory and builds fast search indices.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("dispensa.data_loader")

LOJAS = {
    "carrefour": {"nome": "Carrefour - Ponta da Praia", "icone": "🛍️", "index": 0},
    "pao_de_acucar": {"nome": "Pão de Açúcar", "icone": "🥐", "index": 1},
    "atacadao": {"nome": "Atacadão", "icone": "🏬", "index": 2},
    "soudaki": {"nome": "Soudaki", "icone": "🛒", "index": 3},
}

CHAVES_LOJA = ["carrefour", "pao_de_acucar", "atacadao", "soudaki"]

ARQUIVOS_PRECOS = {
    "carrefour": "precos_carrefour_ampliado.json",
    "pao_de_acucar": "precos_pao_de_acucar_ampliado.json",
    "atacadao": "precos_atacadao_ampliado.json",
    "soudaki": "precos_soudaki_ampliado.json",
}

# Global in-memory storage (mutated in-place to preserve references across imports)
PRODUTOS_MAP: Dict[int, dict] = {}
PRODUTOS_LIST: List[dict] = []
INDEX_BUSCA: List[dict] = []


def find_data_dir() -> Path:
    candidates = [
        Path(__file__).parent.parent,  # webapp/
        Path.cwd() / "webapp",
        Path.cwd(),
    ]
    for c in candidates:
        if (c / "produtos_ampliado.json").exists():
            return c
    raise FileNotFoundError("produtos_ampliado.json não foi encontrado nos caminhos buscados.")


def format_apresentacao(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        qtd = raw.get("quantidade")
        unid = raw.get("unidade_medida") or ""
        if qtd is not None:
            return f"{qtd}{unid}"
    return str(raw)


def load_dataset():
    data_dir = find_data_dir()
    logger.info(f"Carregando base de dados a partir de: {data_dir}")

    # Load main products file
    with open(data_dir / "produtos_ampliado.json", "r", encoding="utf-8") as f:
        produtos_raw = json.load(f)

    # Load prices for each store
    precos_por_ean: Dict[str, Dict[str, dict]] = {}

    for loja_key, filename in ARQUIVOS_PRECOS.items():
        filepath = data_dir / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                precos_list = json.load(f)
                for p in precos_list:
                    gtin = p.get("gtin_ean")
                    if not gtin:
                        continue
                    if gtin not in precos_por_ean:
                        precos_por_ean[gtin] = {}
                    precos_por_ean[gtin][loja_key] = p
        else:
            logger.warning(f"Arquivo de preços {filename} não encontrado.")

    # Unify dataset
    produtos_list = []
    produtos_map = {}
    index_busca = []

    for i, prod in enumerate(produtos_raw, start=1):
        gtin = prod.get("gtin_ean")
        precos_dict = precos_por_ean.get(gtin, {}) if gtin else {}

        precos = []
        precos_reg = []
        estoque = []

        for loja_key in CHAVES_LOJA:
            p_info = precos_dict.get(loja_key)
            if p_info:
                precos.append(p_info.get("preco_promocional"))
                precos_reg.append(p_info.get("preco_regular"))
                estoque.append(bool(p_info.get("em_estoque", False)))
            else:
                precos.append(None)
                precos_reg.append(None)
                estoque.append(False)

        item = {
            "id": i,
            "gtin_ean": gtin,
            "nome": prod.get("nome_completo") or prod.get("nome") or "Produto sem nome",
            "categoria": prod.get("secao") or prod.get("categoria") or "Geral",
            "marca": prod.get("marca") or "Não Informada",
            "relevancia": prod.get("relevancia", 0),
            "imagem_url": prod.get("imagem_url"),
            "apresentacao": format_apresentacao(prod.get("apresentacao")),
            "preco": precos,
            "preco_regular": precos_reg,
            "em_estoque": estoque,
        }

        produtos_list.append(item)
        produtos_map[i] = item
        index_busca.append({
            "nome_lower": item["nome"].lower(),
            "cat_lower": item["categoria"].lower(),
            "marca_lower": item["marca"].lower(),
        })

    # Mutate in-place
    PRODUTOS_LIST.clear()
    PRODUTOS_LIST.extend(produtos_list)

    PRODUTOS_MAP.clear()
    PRODUTOS_MAP.update(produtos_map)

    INDEX_BUSCA.clear()
    INDEX_BUSCA.extend(index_busca)

    no_estoque = sum(1 for p in PRODUTOS_LIST if any(p["preco"][idx] is not None and p["em_estoque"][idx] for idx in range(len(CHAVES_LOJA))))
    logger.info(f"Dataset carregado com sucesso: {len(PRODUTOS_LIST)} produtos total | {no_estoque} produtos com preço em estoque.")
