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


def test_salvar_e_recuperar_lista_api():
    with TestClient(app) as client:
        # 1. Salvar nova lista
        payload = {
            "nome": "Compras do Fim de Semana",
            "itens": [
                {"id": 1, "qtd": 2, "produto": {"id": 1, "nome": "Arroz 5kg"}},
                {"id": 2, "qtd": 1, "produto": {"id": 2, "nome": "Feijão 1kg"}},
            ],
        }
        res_save = client.post("/api/listas", json=payload)
        assert res_save.status_code == 200
        saved_data = res_save.json()
        codigo = saved_data["codigo"]
        assert codigo
        assert saved_data["nome"] == "Compras do Fim de Semana"
        assert saved_data["total_itens"] == 3
        assert len(saved_data["itens"]) == 2

        # 2. Recuperar lista pelo código
        res_get = client.get(f"/api/listas/{codigo}")
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["codigo"] == codigo
        assert get_data["nome"] == "Compras do Fim de Semana"
        assert len(get_data["itens"]) == 2

        # 3. Listar listas recentes
        res_list = client.get("/api/listas")
        assert res_list.status_code == 200
        list_data = res_list.json()
        assert any(item["codigo"] == codigo for item in list_data)

        # 4. Atualizar lista existente
        payload_update = {
            "codigo": codigo,
            "nome": "Compras do Fim de Semana (Atualizado)",
            "itens": [
                {"id": 1, "qtd": 5, "produto": {"id": 1, "nome": "Arroz 5kg"}},
            ],
        }
        res_up = client.post("/api/listas", json=payload_update)
        assert res_up.status_code == 200
        assert res_up.json()["nome"] == "Compras do Fim de Semana (Atualizado)"
        assert res_up.json()["total_itens"] == 5

        # 5. Excluir lista
        res_del = client.delete(f"/api/listas/{codigo}")
        assert res_del.status_code == 200

        # 6. Confirmar 404 após exclusão
        res_404 = client.get(f"/api/listas/{codigo}")
        assert res_404.status_code == 404



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
