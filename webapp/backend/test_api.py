"""
Unit & Integration Tests for Dispensa Planejada FastAPI SGBD Backend
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from main import app
def test_read_root():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert "app" in data
        assert data["sgbd"] == "SQLite3 + FTS5 (Relacional)"


def test_list_categories():
    with TestClient(app) as client:
        response = client.get("/api/categorias")
        assert response.status_code == 200
        cats = response.json()
        assert isinstance(cats, list)
        assert len(cats) > 0
        assert "nome" in cats[0]
        assert "quantidade_produtos" in cats[0]


def test_list_brands():
    with TestClient(app) as client:
        response = client.get("/api/marcas")
        assert response.status_code == 200
        brands = response.json()
        assert isinstance(brands, list)
        assert len(brands) > 0


def test_search_products_sql():
    with TestClient(app) as client:
        response = client.get("/api/produtos?q=arroz&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0
        assert len(data["produtos"]) > 0
        assert "arroz" in data["produtos"][0]["nome"].lower()


def test_calculate_prices_sql():
    with TestClient(app) as client:
        search_res = client.get("/api/produtos?q=leite&limit=1")
        assert search_res.status_code == 200
        prod_id = search_res.json()["produtos"][0]["id"]

        calc_res = client.post("/api/calcular", json={"itens": [{"id": prod_id, "qtd": 2}]})
        assert calc_res.status_code == 200
        calc_data = calc_res.json()
        assert "totais_lojas" in calc_data
        assert "multiloja" in calc_data


def test_calculate_prices_ignores_out_of_stock():
    product = {
        "id": 99,
        "nome": "Produto sem estoque no Carrefour",
        "gtin_ean": None,
        "preco": [1.0, 5.0, None],
        "preco_regular": [None, None, None],
        "em_estoque": [False, True, False],
    }
    with patch("services.price_service.get_product_by_id", return_value=product), \
         patch("services.price_service.get_products_by_ids", return_value={}):
        with TestClient(app) as client:
            response = client.post("/api/calcular", json={"itens": [{"id": 99, "qtd": 1}]})

    assert response.status_code == 200
    data = response.json()
    totais = {item["loja_key"]: item for item in data["totais_lojas"]}
    assert totais["carrefour"]["total"] == 0
    assert totais["pao_de_acucar"]["total"] == 5
    assert data["multiloja"]["total"] == 5


def test_produtos_lote():
    """POST /api/produtos/lote retorna produtos por ID em uma chamada só."""
    with TestClient(app) as client:
        busca = client.get("/api/produtos?q=arroz&limit=3")
        assert busca.status_code == 200
        ids = [p["id"] for p in busca.json()["produtos"][:3]]
        assert ids

        resposta = client.post("/api/produtos/lote", json={"ids": ids})
        assert resposta.status_code == 200
        produtos = resposta.json()
        retornados = {p["id"] for p in produtos}
        assert retornados == set(ids)
        for p in produtos:
            assert "nome" in p and "preco" in p and len(p["preco"]) == 4

    # Lote vazio -> lista vazia
    with TestClient(app) as client:
        resposta = client.post("/api/produtos/lote", json={"ids": []})
        assert resposta.status_code == 200
        assert resposta.json() == []
