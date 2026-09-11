"""
Pydantic Models for Dispensa Planejada FastAPI Backend
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class ProdutoOut(BaseModel):
    id: int
    gtin_ean: Optional[str] = None
    nome: str
    categoria: str
    marca: str
    relevancia: int = 0
    imagem_url: Optional[str] = None
    apresentacao: Optional[str] = None
    preco: List[Optional[float]] = Field(default_factory=list, description="Preço por loja: [Carrefour, Pão de Açúcar, Atacadão, Soudaki]")
    preco_regular: List[Optional[float]] = Field(default_factory=list)
    em_estoque: List[bool] = Field(default_factory=list)


class BuscaResponse(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    produtos: List[ProdutoOut]


class CategoriaOut(BaseModel):
    nome: str
    quantidade_produtos: int


class MarcaOut(BaseModel):
    nome: str
    quantidade_produtos: int


class ItemListaInput(BaseModel):
    id: int
    qtd: int = Field(gt=0, default=1)


class CalculoRequest(BaseModel):
    itens: List[ItemListaInput]


class LojaTotal(BaseModel):
    loja_key: str
    loja_nome: str
    icone: str
    total: float
    itens_disponiveis: int
    itens_totais: int


class ItemDivisao(BaseModel):
    produto_id: int
    nome: str
    gtin_ean: Optional[str] = None
    qtd: int
    preco_unitario: float
    custo_total: float


class LojaDivisao(BaseModel):
    loja_key: str
    loja_nome: str
    icone: str
    total: float
    itens: List[ItemDivisao]


class MultilojaResumo(BaseModel):
    total: float
    economia_vs_pior: float
    distribuicao: List[LojaDivisao]


class CalculoResponse(BaseModel):
    melhor_loja_unica: Optional[LojaTotal] = None
    pior_loja_unica: Optional[LojaTotal] = None
    economia_loja_unica: float = 0.0
    totais_lojas: List[LojaTotal] = Field(default_factory=list)
    multiloja: MultilojaResumo
