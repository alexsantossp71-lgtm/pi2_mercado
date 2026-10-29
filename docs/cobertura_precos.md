# Avaliação da cobertura de preços

**Data da avaliação:** 29/10/2026
**Fonte medida:** `webapp/backend/dispensa.db` (124.427 produtos, 112.095 linhas de preço, 4 lojas)
**Ferramenta:** `python3 scraper/cobertura_precos.py`

---

## Resumo

A cobertura bruta é alta: **86,1% dos produtos têm algum preço**. Esse número, porém,
não descreve o que o aplicativo se propõe a fazer. O produto é um comparador, e
comparar exige o mesmo item precificado em **duas ou mais lojas**.

Por esse critério, a cobertura real é **2,98%**.

| Métrica | Valor | Leitura |
|---|---:|---|
| Produtos no catálogo | 124.427 | |
| Com algum preço | 107.124 (86,1%) | número que costuma ser reportado |
| Com preço válido (em estoque, valor > 0) | 102.292 (82,2%) | |
| **Comparáveis (≥2 lojas)** | **3.706 (2,98%)** | **o que de fato sustenta o app** |
| Comparáveis (≥3 lojas) | 379 (0,30%) | |
| Presentes nas 4 lojas | 2 | |

A diferença entre 86,1% e 2,98% é o diagnóstico central: **o catálogo está
precificado, mas quase não está sobreposto.** 79,2% dos produtos têm preço em
exatamente uma loja.

---

## 1. O relatório anterior media o arquivo errado

`scraper/relatorio_cobertura.py` lê os JSONs da raiz do repositório. Esses
arquivos são um recorte parcial:

| Arquivo | Produtos | Seções |
|---|---:|---:|
| `produtos_ampliado.json` (raiz) | 39.833 | 1 (só "Mercearia") |
| `webapp/produtos_ampliado.json` | 147.541 | 35 |
| `webapp/backend/dispensa.db` (servido pela API) | 124.427 | 36 categorias |

Como os preços de Atacadão e Pão de Açúcar foram coletados contra o catálogo
antigo e completo, apenas ~9% dos EANs deles cruzam com o recorte da raiz:

| Loja | Registros de preço | Cruzam com o catálogo da raiz |
|---|---:|---:|
| Atacadão | 20.792 | 1.958 (9,4%) |
| Pão de Açúcar | 19.496 | 1.932 (9,9%) |
| Carrefour | 4.411 | 4.411 (100%) |

O Carrefour bate 100% porque o recorte da raiz **foi gerado a partir dele**. Os
percentuais daquele relatório (2,1% Atacadão, 11,0% Carrefour) são artefato do
descasamento de arquivos, não medida do produto. O script recebeu um aviso em
tempo de execução, e a medição passou a ser feita por `scraper/cobertura_precos.py`,
direto no banco.

---

## 2. Cobertura por loja

| Loja | Linhas | Preços válidos | % do catálogo | Coleta | Idade |
|---|---:|---:|---:|---|---:|
| Carrefour – Ponta da Praia | 91.029 | 91.029 | 73,2% | 2026-09-13 | 46 dias |
| Pão de Açúcar | 15.728 | 10.418 | 8,4% | 2026-09-13 | 46 dias |
| Atacadão | 3.799 | 3.799 | 3,0% | 2026-09-13 | 46 dias |
| Soudaki | 1.539 | 1.133 | 0,9% | 2026-09-13 | 46 dias |

Duas conclusões:

1. **O catálogo é o Carrefour.** Ele responde por 81% de todas as linhas de preço.
   As outras três lojas somam 19%. Na prática, o app tem um catálogo Carrefour com
   anotações esparsas de concorrentes.
2. **Os dados estão parados há 46 dias.** Todas as lojas foram coletadas em
   13/09/2026. Existem 46 linhas do Carrefour de 28/10, mas representam 0,05% do
   lote — a `MAX(data_coleta)` sugere dados de ontem e isso é enganoso. Para
   preço de supermercado, 46 dias é tempo suficiente para a comparação perder
   validade.

---

## 3. Sobreposição entre lojas — o gargalo

Quantos produtos estão em estoque e precificados em cada par de lojas:

| Par | Em comum | % da menor loja |
|---|---:|---:|
| Carrefour × Pão de Açúcar | 2.502 | 24,0% |
| Pão de Açúcar × Atacadão | 941 | 24,8% |
| Carrefour × Atacadão | 722 | 19,0% |
| Pão de Açúcar × Soudaki | 208 | 18,4% |
| Carrefour × Soudaki | 77 | 6,8% |
| Atacadão × Soudaki | 20 | 1,8% |
| **Carrefour × PA × Atacadão** | **301** | |

Mesmo o melhor par cobre só um quarto da loja menor. Ampliar o catálogo do
Carrefour não melhora isso — **aumentar a sobreposição exige coletar os mesmos
EANs nas demais lojas**, não coletar mais EANs no Carrefour.

---

## 4. A cauda longa distorce o número global

O catálogo tem uma faixa de relevância curada e uma massa residual:

| Faixa de relevância | Produtos | % catálogo | Com preço | Comparáveis ≥2 |
|---|---:|---:|---:|---:|
| 90–100 (curado forte) | 804 | 0,7% | 99,5% | **48,4%** |
| 70–89 (curado) | 8.219 | 6,6% | 89,1% | 9,1% |
| 50–69 (médio) | 17.910 | 14,4% | 86,0% | 4,5% |
| 20–49 (fraco) | 2.593 | 2,1% | 71,3% | 7,9% |
| 9–19 (residual) | 1.625 | 1,3% | 99,4% | **95,9%** |
| 0–8 (cauda longa) | 93.276 | **75,0%** | 85,9% | **0,0%** |

Três quartos do catálogo (93.276 produtos) têm relevância ≤ 8 e **comparabilidade
praticamente nula (3 produtos)**. É essa massa que puxa a média global para 2,98%.

A faixa 9–19 é uma anomalia útil: 1.585 produtos com relevância 16 e 95,9% de
comparabilidade — são itens da lista curada de cesta básica (laticínios, bebidas
lácteas, matinais), coletados deliberadamente em várias lojas. É a prova de que
coleta dirigida funciona.

### O que o usuário realmente encontra

Simulação de 300 cestas com 8 itens típicos de cesta básica (arroz, feijão, leite,
óleo, açúcar, café, macarrão, farinha, sabão, papel higiênico, ovos, manteiga,
detergente, molho de tomate, biscoito), tomando o produto mais relevante de cada
busca — exatamente como o app ordena:

| Resultado | Itens | % |
|---|---:|---:|
| Sem preço em nenhuma loja | 0 | 0,0% |
| Preço em 1 loja só | 489 | 20,4% |
| **Preço em ≥2 lojas** | **1.911** | **79,6%** |

**O núcleo curado funciona bem.** Para o uso típico, 4 de cada 5 itens são
comparáveis. O 2,98% global mede o catálogo inteiro, inclusive 93 mil produtos
que nenhum usuário vai buscar.

Mas há um problema sério na outra ponta:

| Loja consegue cobrir 100% dos 8 itens | Cestas | % |
|---|---:|---:|
| Pão de Açúcar | 52/300 | 17,3% |
| Carrefour | 11/300 | 3,7% |
| Atacadão | 0/300 | 0,0% |
| Soudaki | 0/300 | 0,0% |

**Em 82,7% das cestas, nenhuma loja cobre a lista inteira.** O cálculo de
"melhor loja única" (`price_service.py`) soma totais de conjuntos de itens
diferentes entre lojas. O código mitiga isso ordenando primeiro por
`itens_disponiveis` e comparando "pior loja" dentro da mesma completude, mas o
usuário vê um total por loja que não corresponde à mesma cesta.

---

## 5. Cobertura por categoria

| Categoria | Produtos | Com preço | Comparáveis ≥2 | % |
|---|---:|---:|---:|---:|
| Utilidades Domésticas | 51.539 | 81,6% | 22 | 0,0% |
| Geral | 19.755 | 100,0% | 0 | 0,0% |
| Alimentos | 10.555 | 98,4% | 1.477 | 14,0% |
| Higiene e Perfumaria | 10.431 | 75,1% | 135 | 1,3% |
| Limpeza e Lavanderia | 5.806 | 59,7% | 18 | 0,3% |
| Mercearia | 5.271 | 81,2% | 51 | 1,0% |
| Bebidas | 5.185 | 92,1% | 461 | 8,9% |
| Perfumaria | 1.118 | 97,8% | 623 | **55,7%** |
| Limpeza | 1.329 | 98,1% | 327 | 24,6% |
| Bebê e Criança | 303 | 98,3% | 162 | **53,5%** |
| Descartáveis | 338 | 99,4% | 121 | 35,8% |
| Petshop | 232 | 100,0% | 101 | 43,5% |

Note o padrão: as categorias **pequenas** têm a melhor comparabilidade
(Perfumaria 55,7%, Bebê e Criança 53,5%, Petshop 43,5%), porque vieram de coleta
dirigida. As categorias **gigantes** vieram de varredura ampla do Carrefour e
quase não têm par (Utilidades Domésticas: 51.539 produtos, 22 comparáveis).

### Categorias fragmentadas

Quatro categorias existem em duas grafias, dividindo o catálogo e os filtros da
interface:

- `Higiene e Perfumaria` (10.431) × `Higiene e perfumaria` (299)
- `Utilidades Domésticas` (51.539) × `Utilidades domésticas` (202)
- `Padaria e Matinais` (273) × `Padaria e matinais` (127)
- `Hortifruti` (263) × `Hortifrúti` (55)

Há ainda sobreposição conceitual não resolvida: `Alimentos` × `Mercearia`,
`Limpeza` × `Limpeza e Lavanderia`, `Perfumaria` × `Higiene e Perfumaria`,
`Bebê e Criança` × `Bebê e Infantil`.

---

## 6. Qualidade do catálogo

| Problema | Produtos | % |
|---|---:|---:|
| Placeholder `Produto EAN <número>` | 19.755 | 15,9% |
| Sem marca identificada | 95.594 | 76,8% |
| Sem imagem | 19.755 | 15,9% |
| EAN-13 com dígito verificador inválido | 1.540 | 1,2% |

Os 19.755 placeholders são a categoria "Geral" inteira. São preços órfãos que o
importador cadastrou automaticamente: o EAN apareceu na coleta sem ficha no
catálogo, então virou um produto sem nome, marca ou imagem. Exemplos de EAN:
`0000000000243`, `0000000000391` — nem são EAN-13 válidos. Ocupam 15,9% do
catálogo, são 100% precificados (só pelo Carrefour) e **nunca são comparáveis**.

Excluindo os placeholders, o catálogo útil é de **104.672 produtos**, com 83,5%
precificados e 3,54% comparáveis.

**Pontos positivos da integridade:** zero EANs duplicados, zero preços órfãos sem
produto, zero preços com valor nulo ou negativo. O modelo relacional está
consistente; o problema é de cobertura e de curadoria, não de corrupção.

**Ponto negativo:** 100% das linhas de preço estão sem `cep_coleta` (exceto 46).
Não há como auditar a que unidade/região um preço se refere, o que é relevante
porque o app se anuncia como específico de Santos.

---

## 7. Conclusões

1. **A cobertura anunciável não é 86%.** Para um comparador, a métrica honesta é
   2,98% de catálogo comparável — ou 79,6% de itens comparáveis no uso típico
   de cesta básica. São números muito diferentes e ambos verdadeiros; o relatório
   precisa dizer qual está usando.

2. **O gargalo é sobreposição, não volume.** Coletar mais produtos no Carrefour
   não melhora a comparação. Só aumentam a comparabilidade coletas dos **mesmos
   EANs** nas outras lojas.

3. **Os dados estão vencidos.** 46 dias para preço de supermercado inviabiliza a
   recomendação de compra. É o problema mais urgente e o mais barato de resolver.

4. **A cauda longa prejudica mais do que ajuda.** 93 mil produtos sem par e 20 mil
   placeholders inflam o catálogo, degradam a busca e derrubam todas as métricas.

5. **A coleta dirigida comprovadamente funciona.** As faixas curadas atingem
   48%–96% de comparabilidade. O caminho já está validado dentro do próprio projeto.

---

## 8. Recomendações, em ordem de retorno

| # | Ação | Esforço | Efeito |
|---|---|---|---|
| 1 | Recoletar os 3.706 EANs já comparáveis nas lojas em que existem | Baixo | Devolve validade aos dados; resolve os 46 dias no que importa |
| 2 | Definir uma **lista-núcleo** (300–500 itens de cesta básica) e coletar os mesmos EANs nas 4 lojas | Médio | Leva o núcleo de 7,2% para perto de 100% de comparabilidade |
| 3 | Excluir ou ocultar os 19.755 placeholders da busca | Baixo | Limpa 15,9% do catálogo e melhora a relevância |
| 4 | Normalizar as 4 categorias duplicadas e unificar os pares conceituais | Baixo | Corrige filtros da interface |
| 5 | Exibir na interface em quantas lojas o item é comparável e a data da coleta | Baixo | Honestidade com o usuário; já há ressalva no README |
| 6 | Gravar `cep_coleta` em toda coleta | Baixo | Torna o recorte "Santos" auditável |
| 7 | Rodar `cobertura_precos.py --kpi` no CI após cada coleta | Baixo | Impede regressão silenciosa |

---

## Como reproduzir

```bash
# Banco local (SQLite)
python3 scraper/cobertura_precos.py

# Banco de produção (Neon)
DATABASE_URL="postgresql://..." python3 scraper/cobertura_precos.py

# Com validação de metas (sai != 0 se falhar)
python3 scraper/cobertura_precos.py --kpi

# Opções
python3 scraper/cobertura_precos.py --relevancia-min 70 --top-categorias 30
```

Saída estruturada em `scraper/cobertura_precos.json`.

### Estado do gate `--kpi` em 29/10/2026

```
[KPI FALHOU]
  - núcleo comparável 7.2% < meta 60.0%
  - Carrefour - Ponta da Praia: coleta com 46 dias > limite 30
  - Pão de Açúcar: coleta com 46 dias > limite 30
  - Atacadão: coleta com 46 dias > limite 30
  - Soudaki: coleta com 46 dias > limite 30
```

As metas (`KPI` no topo do script) são alvos de projeto, não descrição do estado
atual. O gate passa a fazer sentido como critério de aceite depois das ações 1 e 2.
