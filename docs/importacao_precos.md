# Importação de preços: o que estava parado no repositório

Projeto Integrador em Computação II — UNIVESP 2026.2
Despensa Planejada Santos

---

## Resumo

O pedido era popular o banco com preços. A coleta nova do Soudaki não foi
possível (o ambiente não alcança `soudaki.com`), mas o levantamento das
coletas já existentes no repositório revelou um problema maior: **havia
coletas de outubro nos arquivos JSON que nunca chegaram ao banco**, que
continuava servindo preços de setembro.

Resultado da importação:

| Métrica | Antes | Depois |
|---|---:|---:|
| Produtos comparáveis (≥2 lojas, preço válido) | 3.864 | **5.794** |
| ... em % do catálogo | 3,11% | **4,67%** |
| Núcleo útil (relevância ≥50) comparável | 7,2% | **11,2%** |
| Linhas de preço | 112.095 | **117.008** |
| Idade da coleta (Carrefour, PA, Atacadão) | 46 dias | **4 dias** |
| Produtos no catálogo | 124.095 | 124.095 (inalterado) |

O catálogo não cresceu e o arquivo do banco passou de 66,7 para 67,2 MB.

---

## 1. O que estava fora do banco

Levantamento de todas as coletas de preço do repositório:

| Arquivo | Loja | Registros | Com preço | Período |
|---|---|---:|---:|---|
| `scraper/precos_carrefour_ampliado.json` | Carrefour | 99.687 | 99.253 | 2026-10 |
| `webapp/precos_carrefour_ampliado.json` | Carrefour | 99.687 | 99.253 | 2026-10 |
| `precos_atacadao_ampliado.json` (raiz) | Atacadão | 20.792 | 5.306 | 2026-08 |
| `precos_pao_de_acucar_ampliado.json` (raiz) | PA | 19.496 | 12.197 | 2026-08 |
| `scraper/precos_pao_de_acucar_ampliado.json` | PA | 12.791 | 12.791 | 2026-10 |
| `precos_carrefour_ampliado.json` (raiz) | Carrefour | 4.411 | 4.407 | 2026-10 |
| `scraper/precos_atacadao_ampliado.json` | Atacadão | 3.843 | 3.839 | 2026-10 |
| `scraper/precos_soudaki_ampliado.json` | Soudaki | 1.538 | 361 | 2026-09 |

O banco, porém, tinha **99% dos preços datados de setembro**. Os JSONs de
outubro já estavam no disco e nunca haviam sido carregados.

A razão é estrutural: `webapp/backend/importar_json_para_sqlite.py` **apaga o
banco e reconstrói tudo** a cada execução. Rodá-lo desfaria a consolidação do
Soudaki feita na etapa anterior, então ele não vinha sendo usado.

### Os arquivos grandes de agosto rendem menos do que parecem

O arquivo do Atacadão na raiz tem 20.792 registros contra 3.799 no banco — à
primeira vista, 5× mais dados. Mas **15.483 deles não têm preço**: são itens
fora de estoque, marcados com `observacao: "sem_estoque"`. Sobram 5.306
preços reais. O mesmo no PA: 19.496 registros, 12.197 com preço.

Vale registrar porque a primeira estimativa, feita só sobre EANs válidos,
apontava +15.026 comparáveis. Medindo com o filtro de preço, o ganho real
ficou em +1.930.

---

## 2. Como a importação decide

`scraper/importar_precos.py` é incremental: nunca apaga o banco.

**Regra de frescor.** Um preço só é gravado quando é mais novo que o que já
está lá. Coleta antiga nunca sobrescreve coleta recente — serve apenas para
preencher buracos. A `data_coleta` real é preservada, então a idade de cada
preço continua auditável (e aparece no relatório de cobertura).

Na execução aplicada: 92.015 preços atualizados (outubro sobre setembro),
4.913 inseridos, **3.114 ignorados** por o banco já ter dado igual ou mais
recente.

**Preço de outra praça não entra.** O arquivo de agosto do Atacadão traz 6
registros com `cep_coleta` da capital (01310-100). O comparador é de Santos;
foram descartados.

**Produtos novos não são criados por padrão.** 21.982 EANs têm preço em
alguma coleta mas não existem no catálogo. Criá-los foi medido numa execução
de teste:

| | Com `--criar-produtos` | Padrão |
|---|---:|---:|
| Produtos no catálogo | 146.077 | 124.095 |
| Comparáveis | 6.639 | 6.611 |
| Arquivo do banco | 81,0 MB | 67,2 MB |

Dos 21.982 produtos criados, **28 (0,1%) ficaram comparáveis**. Os outros
21.954 entram com uma loja só, inflando o catálogo em 18% e o arquivo em
14 MB para capturar 28 comparações a mais. O padrão é não criar; a flag
existe para quem quiser o catálogo mais amplo.

---

## 3. Uso

```bash
python3 scraper/importar_precos.py              # simula e mostra o plano
python3 scraper/importar_precos.py --aplicar    # grava (faz backup antes)
```

O script imprime o inventário das coletas, o plano e, ao aplicar, o estado
final do banco com a distribuição de idade dos preços.

---

## 4. Verificações após aplicar

| Verificação | Resultado |
|---|---|
| `PRAGMA integrity_check` | ok |
| Produtos sem linha no índice de busca | 0 |
| Linhas órfãs no índice | 0 |
| Preços órfãos | 0 |
| EANs duplicados | 0 |
| Pares (produto, loja) duplicados | 0 |
| Preços ≤ 0 | 0 |
| Busca por "arroz" | 677 resultados (inalterado) |
| Paridade do Soudaki | 606 → 608 |
| Testes da API | 6 passaram |
| Testes do coletor Soudaki | 37 passaram |

Teste de ponta a ponta com a API no ar:

```
GET /api/meta        -> ultima_coleta 2026-10-28
GET /api/produtos?q=capeletti
   Capeletti Recheio Queijo Massa Leve 400g  [18.44, 13.29, 10.50, null]
POST /api/calcular   -> melhor Atacadão R$ 10,50 | pior Carrefour R$ 18,44
                        economia R$ 7,94
```

---

## 5. O que melhorou e o que não

**Melhorou.** Comparáveis +1.930 (+49,9%). Núcleo útil de 7,2% para 11,2% —
é a métrica que mais importa, porque é onde estão os produtos que o usuário
realmente procura. Preços de 4 dias em vez de 46.

**Não melhorou.** O gate de KPI continua reprovando:

```
[KPI FALHOU]
  - núcleo comparável 11.22% < meta 60.0%
  - Soudaki: coleta com 46 dias > limite 30
```

As causas são as já documentadas em `docs/cobertura_precos.md` e não se
resolvem importando o que já existe:

- **19.755 produtos placeholder** (`Produto EAN <número>`, 15,9% do
  catálogo), todos do Carrefour, sem nome e sem imagem;
- **77% dos produtos sem marca identificada**;
- **`cep_coleta` nulo em 100%** das linhas — só o arquivo de agosto do
  Atacadão traz CEP, e de forma parcial (4.740 de 20.792), então preencher o
  resto seria inventar dado;
- **sortimento que não se sobrepõe**: 51.539 produtos em "Utilidades
  Domésticas" com 0,1% de comparabilidade;
- **Soudaki parado em setembro**, porque a coleta nova depende de acesso ao
  site.

---

## Arquivos

| Caminho | Conteúdo |
|---|---|
| `scraper/importar_precos.py` | Importador incremental com regra de frescor |
| `scraper/cobertura_precos.py` | Relatório de cobertura (mede o resultado) |
| `docs/cobertura_precos.md` | Diagnóstico de cobertura |
| `docs/coleta_soudaki.md` | Coletor e integrador do Soudaki |
| `webapp/backend/importar_json_para_sqlite.py` | ETL original, recria tudo do zero |
