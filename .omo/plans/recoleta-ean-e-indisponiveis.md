# Plano: Recoleta por EAN com CEP + produtos indisponíveis na economia máxima

## Contexto
Carrefour e Atacadão descartam silenciosamente produtos sem estoque no canal online
(filtro `isAvailablePerSalesChannel_1:1` + `preco <= 0`). O app então sugere que o
produto "só existe" numa loja. Validado ao vivo: Feijão Preto Camil 1kg
(EAN 7896006751113) existe na VTEX do Atacadão mas com `IsAvailable:false`;
a simulação de checkout com `postalCode` retorna preço/estoque por região
(Santos 11060-002, SP 01310-100).

## Técnica validada
1. `GET {base}/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{ean}` → sku itemId, sellerId
2. `POST {base}/api/checkout/pub/orderForms/simulation` body
   `{"items":[{"id":<itemId>,"quantity":1,"seller":"<sellerId>"}],"country":"BRA","postalCode":"<cep>"}`
   → items[0].availability ("available"|"withoutStock"), price em centavos.
3. Tentar CEP Santos (11060-002), depois São Paulo (01310-100); se nenhum disponível,
   registrar registro com `preco_regular: null, em_estoque: false`.

## TODOs
- [x] 1. Criar `scraper/recoletar_por_ean.py` — recoleta pontual por EAN com CEPs de fallback para Atacadão, Carrefour e Pão de Açúcar; grava em `precos_<loja>_ampliado.json` registros inclusive indisponíveis (`preco_regular: null, em_estoque: false, cep_coleta`)
- [x] 2. Rodar a recoleta para garantir `7896006751113` presente nas 3 lojas
- [x] 3. Webapp: `priceCalculator.js` + `ui.js` — lista economia máxima mostra TODOS os produtos; falta de preço em alguma loja renderiza "indisponível" por loja (usar array `em_estoque` que já vem do backend)
- [x] 4. Verificação: feijão nas 3 lojas nos JSONs; app mostrando indisponível; backend `:8000` respondendo

## Success Criteria
- `Select-String "7896006751113"` encontra registro nos 3 precos_*_ampliado.json
- Lista economia máxima renderiza produto com loja sem preço como "indisponível" sem escondê-lo
