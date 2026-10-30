#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Teste do parser do scrap_soudaki.py com fixture sintético fiel à estrutura real."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrap_soudaki as s

# Fixture: estrutura exata que o v1 lia com sucesso (props.pageProps.preloadedProducts)
FIXTURE = {
    "buildId": "test-build-123",
    "props": {"pageProps": {
        "preloadedProducts": {
            "leites": [
                {"name": "Leite Integral Caixa* 1L", "sku": "SKU001",
                 "price": {"amount": 5.49}, "sku_id": 1,
                 "category": {"categoryName": "Laticínios"},
                 "packshot1_front_grid": {"url": "https://img.daki/BR_7894900011517.jpg"},
                 "inventory": {"quantity": 10}},
                {"name": "Leite Desnatado Caixa* 1L", "sku": "SKU002",
                 "price": {"amount": 5.29},
                 "category": {"categoryName": "Laticínios"},
                 "packshot1_front_grid": {"url": "https://img.daki/BR_7894900011524.jpg"},
                 "inventory": {"quantity": 0}},
            ],
            "queijos": [
                {"name": "Queijo Mussarela Fatiado 500g", "sku": "SKU003",
                 "price": {"amount": 24.90},
                 "category": {"categoryName": "Laticínios"},
                 "packshot1_front_grid": {"url": "https://img.daki/BR_7894900011531.jpg"},
                 "inventory": {"quantity": 3}},
                # sem preço -> deve ser descartado
                {"name": "Item sem preço", "sku": "SKU004",
                 "category": {"categoryName": "Laticínios"}, "inventory": {"quantity": 5}},
            ],
        },
        "outraChave": "não é produto",
    }}
}

html_fake = ('<html><head><script id="__NEXT_DATA__" type="application/json">'
             + json.dumps(FIXTURE) + '</script></head>'
             '<body><a href="/shop/laticinios/leites/">leites</a>'
             '<a href="/shop/laticinios/queijos/">queijos</a></body></html>')

falhas = []

# 1. extração do __NEXT_DATA__
nd = s.extrair_next_data(html_fake)
assert nd and nd.get("buildId") == "test-build-123", "extrair_next_data falhou"
print("✔ extrair_next_data ok (buildId lido)")

# 2. descoberta de subcategorias pelos links
subs = sorted({m.group(3) for m in s.RE_LINK_SUB.finditer(html_fake)
               if m.group(2) == "laticinios"})
assert subs == ["leites", "queijos"], f"subcategorias erradas: {subs}"
print(f"✔ subcategorias descobertas: {subs}")

# 3. colheita de produtos (varredura recursiva + normalização)
itens = s.colher_produtos(nd, "laticinios")
assert len(itens) == 3, f"esperava 3 produtos válidos, veio {len(itens)}"
skus = {i["sku"] for i in itens}
assert skus == {"SKU001", "SKU002", "SKU003"}, f"skus errados: {skus}"
print(f"✔ colher_produtos ok: {len(itens)} itens válidos (sem-preço descartado)")

# 4. campo a campo
i1 = next(i for i in itens if i["sku"] == "SKU001")
assert i1["gtin_ean"] == "7894900011517", f"EAN errado: {i1['gtin_ean']}"
assert i1["marca"] == "Leite" and i1["categoria"] == "Laticínios"
assert i1["apresentacao"] == "1l" and i1["em_estoque"] is True and i1["preco"] == 5.49
i2 = next(i for i in itens if i["sku"] == "SKU002")
assert i2["em_estoque"] is False, "estoque 0 deveria dar False"
print("✔ normalizar_item ok (EAN da imagem, marca, apresentação, estoque)")

# 5. dedup e merge de saída
s.OUT = Path("/tmp/teste_soudaki_out")
import shutil
shutil.rmtree(s.OUT, ignore_errors=True)
f_prod, f_prec = s.salvar_saida({"laticinios": itens})
p1 = json.loads(f_prod.read_text())
assert len(p1) == 3
# segunda execução: mesmas coisas -> 0 novos, atualização em vez de duplicar
s.salvar_saida({"laticinios": itens})
p2 = json.loads(f_prod.read_text())
assert len(p2) == 3, f"merge duplicou! {len(p2)}"
print("✔ salvar_saida ok (merge sem duplicar)")

# 6. geração de padrões de data-route
pats = s.padroes_data_route("bld123", "laticinios", ["leites", "queijos"])
assert any("/shop/laticinios.json?page={p}" in p for p in pats)
assert any("/shop/laticinios/leites.json?page={p}" in p for p in pats)
assert all(p.format(p=2).startswith("https://") is False for p in pats)
print(f"✔ padroes_data_route ok ({len(pats)} padrões gerados)")

print("\n" + "=" * 50)
print("TODOS OS TESTES PASSARAM ✔")
print("=" * 50)
