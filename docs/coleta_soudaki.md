# Coleta ampliada do Soudaki

Projeto Integrador em Computação II — UNIVESP 2026.2
Despensa Planejada Santos

---

## Resumo

O comparador só mostra economia quando o mesmo produto tem preço em mais de
uma loja. O Soudaki é a menor das quatro coletas (1.539 preços) e a que menos
casa com as demais, porque **a plataforma não publica o código de barras**: o
coletor antigo extraía o EAN do nome do arquivo de imagem, um acidente que
funcionava em 22% dos casos.

Este documento registra a medição do gargalo, o novo coletor escrito para
atacá-lo e o novo integrador, com os resultados verificados até onde o
ambiente permitiu.

**Aviso de escopo:** o ambiente onde este trabalho foi feito não alcança
`soudaki.com` (apenas `github.com`, `pypi.org` e `registry.npmjs.org`). A
coleta ao vivo **não foi executada**. O que está validado é o código, contra
dados reais já no repositório e contra fixtures. Os números de ganho da
coleta nova só poderão ser medidos quando você rodar o coletor.

---

## 1. O gargalo, medido

Os 1.538 produtos em `scraper/produtos_soudaki.json` têm estas URLs de imagem:

| Padrão do arquivo | Qtd |
|---|---:|
| `small_PROD_<SKU 11 díg>_P<n>_<hash>.png` | 759 |
| `small_BR_<EAN 13 díg>_P<n>_<hash>.png` | 328 |
| `PROD_<SKU 11 díg>_P<n>_<hash>.png` | 116 |
| `small_<hash>_ext<n>_<hash>.png` | 107 |
| `small_PROD_<n>_P<n>_<hash>.png` | 94 |
| `small_PROD_<EAN 13 díg>_P<n>_<hash>.png` | 22 |

A regex do coletor antigo (`BR_(\d{13})`) acerta **340 de 1.538 (22,1%)**.
Aceitar qualquer sequência de 13 dígitos sobe para **376 (24,4%)**.

> **Conclusão que orientou o trabalho:** melhorar a regex rende ~36 produtos.
> O ganho real tem de vir dos campos do objeto do produto que o coletor
> antigo descartava — ele lia 6 de um objeto que tem dezenas.

Além disso, quando o EAN faltava, o coletor antigo gravava o **SKU interno no
campo `gtin_ean`**. Isso produz códigos como `15000004818` posando de código
de barras: nunca casam com outra loja e contaminam qualquer contagem de
"produtos com EAN".

---

## 2. O novo coletor

`scraper/soudaki/coletar_soudaki.py`

| Decisão | Motivo |
|---|---|
| Salva o objeto bruto em `raw/<secao>.json` | Permite reprocessar sem coletar de novo. Mudou a regra de extração? `--reprocessar`. |
| Varre o `__NEXT_DATA__` **inteiro** em profundidade | Produtos também aparecem em caches de estado (Apollo/Redux). Ler só `props.pageProps.preloadedProducts` ignora esses. |
| `extrair_ean()` com 3 estratégias e proveniência | (a) campo com nome de código de barras; (b) qualquer campo cujo valor passe no dígito verificador; (c) 13 dígitos dentro de texto. Grava de onde veio em `ean_origem`. |
| Valida sempre o dígito verificador | É o que separa EAN de SKU. `15000004818` tem 11 dígitos; um SKU de 13 dígitos quase nunca fecha o check digit. |
| `sku` e `gtin_ean` **nunca se misturam** | Sem EAN, o identificador vira `SKU-SOUDAKI-<sku>` — explicitamente não é código de barras. |
| `--diagnostico` imprime o schema observado | Transforma "onde está o EAN?" de adivinhação em medição. |

### Fluxo recomendado

```bash
# 1. Descobrir o que a origem expõe (1 seção, não grava nada)
python3 scraper/soudaki/coletar_soudaki.py --diagnostico --secoes bebidas
```

Isso imprime cada campo encontrado, sua frequência e um exemplo, seguido dos
campos que carregam um EAN válido:

```
CAMPO                            FREQ      %  EXEMPLO
sku                                 2   100%  15000004818
name                                2   100%  Leite Integral Piracanjuba 1L
price.amount                        2   100%  5.49
ean                                 1    50%  7898215151760
packshot1_front_grid.url            1    50%  https://a/small_BR_7898215151760_P

CANDIDATOS A EAN (campos cujo valor passa no dígito verificador):
       1 ( 50.0%)  ean (valor direto)
       1 ( 50.0%)  packshot1_front_grid.url (dentro do texto)
```

```bash
# 2. Coleta completa das 25 seções
python3 scraper/soudaki/coletar_soudaki.py

# 3. Se ainda faltar EAN, visitar a página de cada produto sem EAN
python3 scraper/soudaki/coletar_soudaki.py --detalhe
```

Saídas em `scraper/soudaki/`: `raw/<secao>.json` (bruto),
`soudaki_completo.json` (normalizado + bruto), `produtos_soudaki.json` e
`precos_soudaki.json`.

---

## 3. O novo integrador

`scraper/soudaki/integrar_soudaki.py` — vincula a coleta ao catálogo em cinco
regras, nesta ordem:

| # | Situação | Ação |
|---|---|---|
| 1 | EAN-13 válido já no catálogo | Usa o produto existente — comparável na hora |
| 2 | EAN-13 válido inédito | Cria produto com EAN real, pronto para casar depois |
| 3 | SKU já no catálogo | Atualiza no lugar (é o que torna a reexecução segura) |
| 4 | Sem EAN, equivalente encontrado | Casa por marca + tamanho + núcleo do nome |
| 5 | Sem EAN e sem par | Cria como `SKU-SOUDAKI-<sku>`, sem fingir ser EAN |

A regra 4 reaproveita o pareador validado na etapa anterior
(`scraper/parear_soudaki_pa.py`), agora aplicado ao **catálogo inteiro**, não
só ao Pão de Açúcar.

```bash
python3 scraper/soudaki/integrar_soudaki.py            # simula, não grava
python3 scraper/soudaki/integrar_soudaki.py --aplicar  # grava (faz backup)
```

### Três correções que a auditoria exigiu

**Variante dietética assimétrica.** O pareador só acusa conflito quando os
dois lados declaram o mesmo eixo. Isso deixava passar:

```
Energético Red Bull Pomelo 250ml   ×  Energético Red Bull Pomelo Sem Açúcar 250ml
Coca-cola Sem Açúcar Pet 200ml     ×  Coca-Cola Original Pet 200 ml
```

Mesma marca, mesmo tamanho, preços diferentes. A nova guarda trata a
**omissão** como divergência, para os eixos açúcar, lactose, cafeína, álcool
e glúten.

Ela foi deliberadamente limitada. A primeira versão incluía `integral` e
`desnatado`, e rejeitou 15 pares — **12 deles corretos**: "Aveia em Flocos
Nestlé" × "Aveia em Flocos *Integral* Nestlé", "Farinha de Aveia Quaker" ×
"Farinha de Aveia *Integral* Quaker", "Suco Xandô Laranja" × "Suco
*Integral* Laranja Xandô". `integral` é descritor que o Soudaki costuma
omitir. Esse eixo voltou ao tratamento simétrico, que não erra assim.

A versão final rejeita **3** pares, todos de fato errados. Os 12 casos —
5 que devem ser rejeitados, 7 que não podem — estão fixados em teste.

**Colisões.** 29 itens do Soudaki apontavam para o mesmo produto do catálogo
(o catálogo tem 103 códigos com sufixo `_exp`, lote a vencer, que duplicam o
item base). Antes, o último gravado sobrescrevia o primeiro conforme a ordem
do arquivo. Agora a escolha é explícita: em estoque primeiro, depois menor
preço, depois código sem `_exp`.

**Idempotência.** Rodar duas vezes criava 455 produtos duplicados. Duas
causas, ambas corrigidas:

- o script não reconhecia os `SKU-SOUDAKI-*` que ele mesmo criara;
- o vocabulário de marcas era montado sobre a tabela inteira, então os
  produtos recém-criados deslocavam as razões marca/nome e mudavam o
  pareamento a cada rodada.

Hoje o vocabulário e o índice de alvos saem **apenas do catálogo de
referência** (produtos com preço de alguma loja que não o Soudaki) — o que
também é mais correto: casar Soudaki com Soudaki não gera comparação alguma.

---

## 4. Resultados verificados

### Reexecutando o fluxo inteiro sobre os dados atuais

Teste honesto: removi o Soudaki de uma cópia do banco e reintegrei os mesmos
1.538 produtos pelo caminho novo.

| | Banco atual | Fluxo novo, do zero |
|---|---:|---:|
| Pares Soudaki × outra loja | 606 | **601** |
| Produtos comparáveis (≥2 lojas) | 4.687 | **4.693** |
| Produtos no catálogo | 124.095 | 124.070 |

**O fluxo novo não aumenta a paridade com os dados antigos — fica 5 abaixo.**
Isso é esperado e não é defeito: esses dados têm apenas 375 EANs válidos em
1.538, e a diferença vem justamente das guardas mais rigorosas (variante
dietética, colisões), que trocam alguns pares por pares corretos.

O ganho da etapa depende da **coleta nova**, que não pude executar.

### Aplicando sobre o banco atual

Cenário real de uso, numa cópia:

```
  1. EAN já no catálogo .............  371  (24,1%)
  2. EAN novo .......................    4  ( 0,3%)
  3. SKU já no catálogo .............  837  (54,4%)   <- atualizados no lugar
  4. Sem EAN, casado por atributos ..  294  (19,1%)
  5. Sem EAN e sem par ..............   32  ( 2,1%)

  produtos criados ... 36      preços atualizados . 1494
```

Paridade **606 → 614**. Segunda execução: 0 produtos criados.

### Verificações

| Verificação | Resultado |
|---|---|
| `PRAGMA integrity_check` | ok |
| Produtos sem linha no índice de busca | 0 |
| Linhas órfãs no índice | 0 |
| Preços órfãos | 0 |
| EANs duplicados | 0 |
| Pares (produto, loja) duplicados | 0 |
| Busca por "arroz" | 677 resultados (inalterado) |
| Determinismo | 3 processos separados, resultado idêntico |
| Idempotência | 2ª e 3ª execução criam 0 produtos |
| Testes | 37 do coletor/integrador + 6 da API |

O determinismo foi verificado em processos separados de propósito: na etapa
anterior, desempates implícitos sobre conjuntos de strings faziam o resultado
mudar a cada execução por causa do hash randomizado do Python.

---

## 5. O que esperar da coleta nova

Não dá para prometer número. O que se sabe:

- **Piso:** 376 EANs (24,4%), o que a extração por imagem já alcança.
- Se o objeto do produto tiver um campo de código de barras — comum em
  plataformas de e-commerce, mesmo sem aparecer na interface — o salto é
  grande, porque hoje 1.162 produtos vão para o catálogo sem EAN.
- **Teto realista:** 501 dos 1.539 itens são de Padaria e Hortifruti, frescos
  e granel, que **não têm EAN de fabricante**. Excluindo-os, o universo
  pareável é de 1.038 itens.

O `--diagnostico` responde isso em uma requisição. Rode-o primeiro.

---

## 6. Limitações

- **A coleta não foi executada.** Sem acesso a `soudaki.com`, o coletor está
  validado contra fixtures e contra os dados já coletados, não contra o site.
  Se a estrutura da página mudou, `--diagnostico` vai mostrar.
- **O seletor de seções é herdado.** As 25 seções vieram do coletor antigo e
  não foram reconferidas no site.
- **`--detalhe` é lento** — uma requisição por produto sem EAN, ~1.100
  requisições com pausa de 0,6 s (cerca de 11 minutos). Use depois de ver no
  diagnóstico se vale a pena.
- **Os 29 itens descartados por colisão perdem o preço.** São duplicatas
  (`_exp` e embalagens repetidas); o item escolhido é o de melhor
  disponibilidade e preço, mas o descarte é silencioso no banco.
- **Paridade de 100% continua inatingível**, pelo motivo registrado em
  `docs/paridade_soudaki_pao_de_acucar.md`: produtos frescos sem EAN e
  sortimentos que simplesmente não se sobrepõem.

---

## Arquivos

| Caminho | Conteúdo |
|---|---|
| `scraper/soudaki/coletar_soudaki.py` | Coletor (581 linhas) |
| `scraper/soudaki/integrar_soudaki.py` | Integrador (412 linhas) |
| `scraper/soudaki/test_coletar_soudaki.py` | 37 testes, sem rede |
| `scraper/coletar_e_integrar_soudaki.py` | Coletor antigo, mantido para referência |
| `docs/paridade_soudaki_pao_de_acucar.md` | Etapa anterior: pareamento e paridade |
| `docs/cobertura_precos.md` | Diagnóstico de cobertura das quatro lojas |
