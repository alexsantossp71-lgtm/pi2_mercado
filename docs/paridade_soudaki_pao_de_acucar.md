# Paridade Soudaki × Pão de Açúcar

**Data:** 29/10/2026
**Ferramenta:** `python3 scraper/parear_soudaki_pa.py`
**Objetivo pedido:** compatibilizar ao máximo os produtos com preço no Soudaki
com os produtos já cadastrados e à venda no Pão de Açúcar, buscando paridade de 100%.

---

## Resultado

| | Produtos | Paridade |
|---|---:|---:|
| Antes | 261 / 1.539 | 17,0% |
| **Depois** | **593 / 1.539** | **38,5%** |
| Ganho | +332 | +21,5 p.p. |

Efeito no app: produtos comparáveis em 2 ou mais lojas passaram de **3.706 para
3.864**, e o catálogo perdeu **332 fichas duplicadas** (124.427 → 124.095).

Exemplo real agora funcionando:

```
Apresuntado Fatiado Perdigão 200g
  Soudaki        R$  6,99
  Pão de Açúcar  R$  9,19     economia de R$ 6,60 em 3 unidades
```

---

## Por que não dá para chegar a 100%

A meta de 100% não é alcançável, e a razão é estrutural — não é falha de coleta
nem de código.

**O Soudaki não publica EAN para a maior parte do sortimento.** A loja roda na
plataforma JOKR/Daki, que expõe SKU interno em vez de código de barras:

| Formato do código | Produtos | % |
|---|---:|---:|
| EAN-13 válido (`7891515435134`) | 362 | 23,5% |
| SKU interno Daki (`15000004818`, `20000000533`) | 1.177 | 76,5% |

Como o cruzamento entre lojas é feito por EAN, **1.177 produtos (76,5%) nunca
encontrariam par por código**. Daí os 17,0% iniciais.

### Teto por faixa

| Caminho | Produtos | Paridade acumulada |
|---|---:|---:|
| EAN-13 idêntico (faixa A) | 261 | 17,0% |
| **+ marca + tamanho + nome (faixa B)** | **+332** | **38,5%** |
| + faixa C, após revisão manual | +46 | ~41,5% |
| + coleta dirigida dos 100 EANs faltantes no PA | +100 | ~48,0% |
| Restante: SKU interno sem equivalente no PA | 798 | — |

Os 798 restantes concentram-se em categorias que o Pão de Açúcar vende sob
código próprio ou simplesmente não têm equivalente de catálogo:

| Categoria | Produtos sem par |
|---|---:|
| Padaria (pães, ovos a granel) | 403 |
| Laticínios | 186 |
| Bebidas | 134 |
| Limpeza | 108 |
| Hortifruti (produto solto, pesado) | 98 |

Pão fresco, ovos a granel e hortifruti pesado não têm EAN de fabricante em
loja nenhuma — cada rede usa PLU interno. Esses itens só seriam comparáveis com
uma tabela de equivalência mantida à mão, produto a produto.

---

## Como o pareamento funciona

Quando o EAN falha, o par é buscado por **marca + tamanho + núcleo descritivo**.

```
Soudaki  "Maggi Sopa Cebola 68g"
PA       "Sopa Cebola Maggi Pacote 68g"
         marca=maggi  tamanho=(68,g)  Jaccard=1.00  -> faixa B
```

### Faixas de confiança

| Faixa | Critério | Produtos | Uso |
|---|---|---:|---|
| A | EAN-13 idêntico | 261 | aplicada |
| B | marca + tamanho + Jaccard ≥ 0,60 | 332 | aplicada |
| C | marca + tamanho + Jaccard ≥ 0,40 | 46 | revisar antes de aplicar |
| D | sem candidato | 898 | coleta dirigida |

### Guardas contra falso positivo

Cada guarda nasceu de um erro real encontrado na auditoria:

1. **Polaridade de atributo.** `Margarina COM SAL` casava com `Margarina SEM SAL`
   com escore 1,00, porque "com" e "sem" estavam na lista de palavras ignoradas.
   Hoje os eixos sal, gás, açúcar, lactose, cafeína e álcool precisam concordar.
   O mesmo vale para teor: integral ≠ desnatado ≠ semidesnatado ≠ light.

2. **Marca precisa ser marca.** `Café 3 Corações` casava com `Café Brasileiro`
   porque "café" aparece no campo marca de algumas fichas. Um token só é aceito
   como marca quando é predominantemente marca — razão entre uso como marca e
   uso total no nome ≥ 0,5. Isso separa `quaker` (1,00) de `cafe` (0,07).

3. **Variantes mútuas.** `Queijo PRATO Vigor` casava com `Queijo CHEDDAR Vigor`.
   Quando cada lado tem um descritivo exclusivo que o outro não tem, o par é
   recusado. Um lado só com tokens extras continua válido — é apenas um nome
   mais descritivo do mesmo item.

4. **Tamanho normalizado.** 1 litro, 1l e 1000ml são o mesmo; 500g e 1kg não.

5. **Embalagem múltipla.** `Bipack Coca-Cola 2L` não é `Kit Coca-Cola + Fanta`.

6. **Par exclusivo.** Um produto do PA só serve de par para um item do Soudaki,
   o de maior escore. Sem isso, quatro sabores de iogurte da mesma marca e
   tamanho colapsariam todos no mesmo registro.

### Determinismo

A primeira versão produzia resultados diferentes a cada execução — 322, 334 e
337 pares sobre o mesmo banco. A causa era `max()` sobre um `set` de strings:
a ordem de iteração muda a cada processo por causa do hash randomizado do
Python, e com ela a marca escolhida e todo o pareamento. Todos os desempates
passaram a ser explícitos (maior escore, depois menor `produto_id`). Verificado:
cinco execuções consecutivas produzem exatamente 334 pares na faixa B.

---

## O que foi gravado no banco

Um item do Soudaki com SKU interno é, na prática, uma **ficha duplicada** do
mesmo produto que o PA já tem com EAN. A API cruza preços por `produto_id`, então
manter dois registros impede a comparação. A consolidação:

1. move o preço do Soudaki para o `produto_id` do PA;
2. apaga a linha de preço antiga do Soudaki;
3. remove a ficha duplicada de `produtos` e de `produtos_fts`.

Backup automático antes de gravar, em `webapp/backend/dispensa.bak-<timestamp>.db`.

### Verificação pós-consolidação

| Checagem | Resultado |
|---|---|
| Preços órfãos | 0 |
| EANs duplicados | 0 |
| Produtos sem entrada no FTS | 0 |
| Entradas no FTS sem produto | 0 |
| Violações de `UNIQUE(produto_id, loja_id, cep_coleta)` | 0 |
| Testes da API (`webapp/backend/test_api.py`) | 6 passaram |
| `/api/produtos`, `/api/produtos/{id}`, `/api/calcular` | validados manualmente |

> O banco consolidado é o SQLite local de desenvolvimento, que não é versionado.
> Em produção (Neon), rode a mesma ferramenta apontando para o banco de destino
> ou reaplique após a próxima importação — a consolidação não sobrevive a um
> `importar_json_para_sqlite.py`, que recria as tabelas do zero.

---

## Arquivos gerados

| Arquivo | Conteúdo |
|---|---|
| `scraper/pareamento_soudaki_pa.csv` | 380 pares das faixas B e C, com escore e coluna `conferido` para revisão manual |
| `scraper/gap_soudaki_pa.txt` | 100 EANs válidos presentes no Soudaki e ausentes da coleta do PA — entrada direta para coleta dirigida |
| `scraper/pareamento_soudaki_pa.json` | mapa completo com motivo de cada decisão (regenerável, não versionado) |

---

## Próximos passos para subir a paridade

| # | Ação | Ganho estimado | Esforço |
|---|---|---:|---|
| 1 | Revisar os 46 pares da faixa C no CSV e aplicar os aprovados | +46 (~41,5%) | baixo |
| 2 | Coletar no PA os 100 EANs de `gap_soudaki_pa.txt` | +100 (~48,0%) | baixo, precisa de rede |
| 3 | Mapear à mão os itens de Padaria e Hortifruti sem EAN | até +501 | alto, manual |
| 4 | Pedir o EAN ao Soudaki/Daki via API de detalhe do produto | até +798 | médio, depende da API expor o campo |

A ação 4 é a única que resolveria o problema na raiz: enquanto o Soudaki
publicar SKU interno, 76,5% do sortimento depende de heurística de nome.

### Observação sobre os itens `_exp`

103 produtos do Soudaki têm sufixo `_exp` no código (`20000000533_exp`). São
variantes de **próximo vencimento**, com preço promocional, e 71 deles duplicam
um produto que já existe sem o sufixo. Não geram par novo com o PA, mas inflam
o catálogo e, se comparados, mostram um preço que não corresponde ao produto
regular. Recomenda-se tratá-los como oferta, não como item de catálogo.

---

## Como reproduzir

```bash
# Analisa e gera os arquivos, sem tocar no banco
python3 scraper/parear_soudaki_pa.py

# Inclui a faixa C como par válido
python3 scraper/parear_soudaki_pa.py --incluir-c

# Grava a consolidação (faz backup antes)
python3 scraper/parear_soudaki_pa.py --aplicar

# Aponta para outro banco
python3 scraper/parear_soudaki_pa.py --db /caminho/dispensa.db --aplicar
```

Depois de aplicar, confira o efeito com:

```bash
python3 scraper/cobertura_precos.py
```
