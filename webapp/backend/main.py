"""
Dispensa Planejada Santos — FastAPI Application Entrypoint
PI em Computação II - UNIVESP 2026.2
Powered by SQLite SGBD Relacional + FTS5
"""

from contextlib import asynccontextmanager
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Vercel importa este arquivo com o repo-root como cwd; garantir que webapp/backend/
# esteja no sys.path para que os modulos locais (models, services, db) importem.
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models import (
    BuscaResponse,
    CalculoRequest,
    CalculoResponse,
    CategoriaOut,
    LojaMeta,
    MarcaOut,
    MetaResponse,
    ProdutoOut,
)
from services.product_service import (
    get_brands,
    get_categories,
    get_product_by_id,
    search_products,
)
from services.price_service import calculate_basket_prices

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("dispensa.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando backend Dispensa Planejada FastAPI (Turso/LibSQL)...")
    
    # We can perform a quick connection test here
    try:
        from db import get_db_connection
        conn = get_db_connection()
        conn.close()
        logger.info("Conexão com Turso LibSQL bem sucedida!")
    except Exception as e:
        logger.error(f"Erro ao conectar ao Turso: {e}")
        
    yield
    logger.info("Encerrando backend...")


app = FastAPI(
    title="Dispensa Planejada Santos API (SGBD SQL)",
    description="API de alta performance alimentada por SGBD Relacional SQLite3 + FTS5 para comparação de preços em Santos/SP",
    version="2.0.0",
    lifespan=lifespan,
)

# Same-origin deployment needs no CORS; local development uses port 8080.
cors_origins = [origin.strip() for origin in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080",
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def read_root():
    return {
        "status": "online",
        "app": "Dispensa Planejada Santos API",
        "sgbd": "SQLite3 + FTS5 (Relacional)",
        "versao": "2.0.0",
        "docs": "/docs",
    }


@app.get("/api/produtos", response_model=BuscaResponse)
def api_search_products(
    q: Optional[str] = Query(None, description="Termo de busca (Full-Text Search FTS5)"),
    categoria: Optional[str] = Query(None, description="Filtro de categoria"),
    marca: Optional[str] = Query(None, description="Filtro de marca"),
    page: int = Query(1, ge=1, description="Número da página"),
    limit: int = Query(20, ge=1, le=100, description="Itens por página"),
):
    total, current_page, page_limit, total_pages, items = search_products(
        q=q, categoria=categoria, marca=marca, page=page, limit=limit
    )
    return BuscaResponse(
        total=total,
        page=current_page,
        limit=page_limit,
        total_pages=total_pages,
        produtos=items,
    )


@app.get("/api/produtos/{product_id}", response_model=ProdutoOut)
def api_get_product(product_id: int):
    prod = get_product_by_id(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    logger.info(f"DEBUG api_get_product({product_id}): preco={prod.get('preco')} len={len(prod.get('preco',[]))}")
    return prod


@app.get("/api/categorias", response_model=list[CategoriaOut])
def api_list_categories():
    return get_categories()


@app.get("/api/marcas", response_model=list[MarcaOut])
def api_list_brands(categoria: Optional[str] = Query(None, description="Filtrar por categoria")):
    return get_brands(categoria=categoria)


@app.post("/api/calcular", response_model=CalculoResponse)
def api_calculate(request: CalculoRequest):
    return calculate_basket_prices(request)


@app.get("/api/meta", response_model=MetaResponse)
def api_meta():
    """Metadados do sistema: lojas cadastradas e data da última coleta de preços."""
    from db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()

    # Garante que a coluna data_coleta existe (ALTER TABLE incremental, sem DROP)
    try:
        cursor.execute(
            "ALTER TABLE precos ADD COLUMN data_coleta TEXT DEFAULT NULL"
        )
    except Exception:
        pass  # coluna já existe

    # Lojas cadastradas (fonte de verdade: tabela lojas)
    cursor.execute("SELECT chave, nome, icone FROM lojas ORDER BY id")
    lojas = [LojaMeta(chave=r["chave"], nome=r["nome"], icone=r["icone"]) for r in cursor.fetchall()]

    # Última coleta: maior data_coleta registrada na tabela de preços
    max_date = None
    ultima_fmt = None
    try:
        cursor.execute("SELECT MAX(data_coleta) AS ultima FROM precos WHERE data_coleta IS NOT NULL")
        row = cursor.fetchone()
        if row:
            max_date = row.get("ultima") or row.get("MAX(data_coleta)")
        if max_date:
            parts = str(max_date).split(" ")[0].split("-")
            if len(parts) == 3:
                ano, mes, dia = parts
                ultima_fmt = f"{int(dia)}/{int(mes)}/{ano}"
    except Exception:
        pass  # coluna data_coleta pode não existir ainda no Turso

    conn.close()

    return MetaResponse(
        lojas=lojas,
        ultima_coleta=max_date,
        ultima_coleta_fmt=ultima_fmt,
    )


# Vercel ASGI fallback handler (Mangum). If mangum is unavailable, the module
# still imports cleanly and the app runs under uvicorn locally.
try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except Exception:
    pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
