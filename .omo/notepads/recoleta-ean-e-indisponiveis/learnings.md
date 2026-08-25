
## Indispon�veis no frontend (priceCalculator.js/ui.js)
- Novo helper disponivelEm(produto, i) = preco[i] != null && (em_estoque ausente || em_estoque[i] !== false). �ndices: 0=carrefour, 1=pao_de_acucar, 2=atacadao.
- itensIndisponiveisPorLoja(lista) conta faltas por loja; melhorLojaUnica desempata por total asc, depois menos indispon�veis (retorna tamb�m indisponiveis).
- divisaoMultiLoja agora retorna indisponiveis: [{nome, qtd}] para itens sem pre�o em nenhuma loja � nunca descarta silenciosamente.
- renderLista: c�lula "Menor pre�o" mostra badges price-unavailable por loja faltante dentro de .price-missing-stores; renderResultados mostra nota "N itens indispon�veis nesta loja" (classe .store-missing) nos cards OP��O 1 e Comparativo, e card "?? Indispon�veis" na divis�o multi-loja.
- Teste l�gico validado com node (EAN 7896006751113 Feij�o: 2 faltas C/A, 1 PdA; divis�o inclui produto sem pre�o algum).

## [2026-08-24] Sessão QA — execução das tasks 2 e 4
- T2: `python scraper/recoletar_por_ean.py 7896006751113` rodou com sucesso. Atacadão R$ 6,55 (estoque True, cep_coleta 11060-002) e Pão de Açúcar R$ 8,29 (estoque True). Carrefour gravou indisponível (observacao: erro_catalogo:HTTPError — catálogo devolve erro HTTP na busca por EAN; registrar-se como dado e não como falha fatal foi correto).
- T4 verificação completa: EAN presente e parseável nos 3 precos_*_ampliado.json; backend FastAPI local :8000 200 em /api/marcas, /api/categorias, /api/produtos; UI validada em browser (Playwright, frontend :8080 + backend :8000): linha do produto mostra "R$ 8,29 | indisponível em Carrefour - Ponta da Praia | indisponível em Atacadão"; cards OPÇÃO 1/Comparativo com "1 item indisponível nesta loja". Evidência: playwright .playwright-mcp/qa-indisponivel-task4.png.
- Processos QA encerrados (uvicorn PID 5664, http.server PID 8412) — portas 8000/8080 liberadas.

## Armadilhas encontradas (IMPORTANTE)
- Porta 8000 estava ocupada por processo zumbi `python run_api.py` (PID 16900) de sessão antiga respondendo 404 nas rotas novas. Checar `Get-NetTCPConnection -LocalPort <porta> -State Listen` antes de assumir que um backend subiu.
- FTS5 do backend faz busca de FRASE para termos adjacentes: "feijao camil" retorna 0 enquanto "feijao" retorna 195. Acentuação OK (feijão ≈ feijao). Melhoria futura: OR/AND explícito ou prefix matching em product_service.search_products (fora do escopo deste plano).
- recoletar_por_ean.py tem HOJE = "2026-08-23" fixo (linha 32) — grava data errada; corrigir para `date.today().isoformat()` quando for executar em lote.
