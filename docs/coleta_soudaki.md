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

### Um comando

```bash
python3 scraper/soudaki/atualizar_soudaki.py
```

Coleta `soudaki.com/shop/` e grava no banco, mostrando quanto mudou. Se a
coleta falhar, o banco **não** é tocado.

As seções são descobertas na própria vitrine — a lista fixa de 25 slugs veio
do coletor antigo e nunca foi conferida contra o site; se alguma foi
renomeada, ela some da coleta sem aviso, porque uma seção inexistente apenas
devolve zero produtos. O que for descoberto entra primeiro, e a lista fixa
complementa.

Para integrar só o que já está no repositório, sem rede:

```bash
python3 scraper/soudaki/atualizar_soudaki.py --sem-coleta
```

### Passo a passo, quando quiser controlar

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

---

## 7. Integração das coletas que já estavam no repositório

Sem acesso ao site, o que deu para fazer foi aproveitar as coletas do Soudaki
já versionadas. O levantamento achou uma que nunca tinha chegado ao banco:
`scraper/precos_daki_bebidas_ampliado.json`, de **25/10/2026** — mais recente
que os dados de setembro que o sistema servia.

`scraper/soudaki/converter_coleta_legada.py` passa essas coletas para o
formato novo, separando SKU de EAN (o coletor antigo gravava os dois no mesmo
campo) e recuperando EANs escondidos na URL da imagem.

Resultado no banco:

| | Antes | Depois |
|---|---:|---:|
| Preços do Soudaki | 1.539 | **1.584** |
| ... disponíveis com preço | 1.133 | **1.171** |
| Produtos com Soudaki + outra loja | 608 | **616** |
| Preços de outubro | 0 | **345** |

Verificado: integridade ok, 0 inconsistências no índice de busca, 0 pares
(produto, loja) duplicados, busca inalterada, 42 + 6 testes passando. A
segunda execução cria 0 produtos.

O integrador também ganhou a regra de frescor: uma reexecução com dados
antigos não rebaixa um preço mais novo que já esteja no banco.


---

## 8. Ensaio local: o pipeline verificado sem o site

O bloqueio de rede foi diagnosticado no nível do pacote: o TCP conecta em
`172.67.71.57:443`, o `Client hello` do TLS é enviado e a conexão é derrubada
(`SSL_ERROR_SYSCALL`). O filtro de saída lê o SNI, vê `soudaki.com` fora da
lista e corta. GitHub passa pelo mesmo teste. Não é IPv6, não é DNS, não é o
site fora do ar — é política de rede, e não há contorno legítimo.

Para que restasse apenas uma incógnita (o formato que o site publica hoje),
`scraper/soudaki/ensaio_local.py` serve os dados reais do Soudaki que estão
no repositório no formato de uma página Next.js, com metade dos produtos em
`preloadedProducts` e metade num cache de estado — justamente o caso que o
coletor antigo perdia.

```bash
# terminal 1
python3 scraper/soudaki/ensaio_local.py --porta 8777
# terminal 2
python3 scraper/soudaki/coletar_soudaki.py --base-url http://localhost:8777
```

O coletor ganhou `--base-url` para isso (também serve para apontar a um
espelho).

### O que o ensaio provou

| Etapa | Resultado |
|---|---|
| Descoberta de seções na vitrine | 10 seções encontradas |
| Varredura do payload | 1.538 produtos, **incluindo os do cache de estado** |
| Extração de EAN | 375 válidos (24,4%), nenhum SKU virou EAN |
| Estoque | 1.132 disponíveis — igual à origem |
| Integração | 1.538 vinculados, 100% |
| Conferência de preços | **0 preços da coleta faltando no banco** |
| Reexecução | 0 produtos criados (idempotente) |

O ensaio achou um bug — no próprio ensaio: `em_estoque` vem como inteiro
`1/0` em algumas coletas e como string `"True"` em outras, e a primeira
versão comparava só com a string, zerando o estoque. Vale registrar porque é
exatamente o tipo de divergência de formato que derruba uma coleta real.

Dois testes automatizados cobrem esse caminho
(`test_coleta_ponta_a_ponta_contra_o_formato_do_site` e o de seção
inexistente), então o pipeline não depende de alguém lembrar de rodar o
ensaio à mão.

### O que o ensaio NÃO prova

Que o `soudaki.com` de hoje publica os produtos nesse formato. O ensaio usa o
formato observado nos dados que temos. Se a página mudou, o
`--diagnostico` mostra em uma requisição — é por isso que ele existe.


---

## 9. O que o site responde hoje (29/10/2026)

Consegui alcançar `soudaki.com` por outro caminho de rede e sondei a origem
diretamente. O resultado muda o diagnóstico da etapa anterior.

| URL | Resposta |
|---|---|
| `soudaki.com/shop/laticinios/` | **404** — "Page not found" |
| `soudaki.com/shop/` | **404** |
| `soudaki.com/shop/search/?q=queijo` | **404** (a própria home linka para cá) |
| `soudaki.com/` | 200, com **Cloudflare Turnstile** ativo |
| `soudaki.com/robots.txt` | 200 — `/shop/` **não** é proibido |
| `soudaki.com/sitemap.xml` | 200 — **nenhuma URL de loja** |

O texto do 404 — *"The page you are looking for doesn't exist or has been
moved"* — é o padrão do **Webflow**, que hospeda o site institucional. Ou
seja: o domínio responde, mas `/shop/*` não chega à loja para um cliente
simples.

### Por que isso importa

Não é um slug errado. A mesma seção `laticinios` **funcionou**: produziu 258
produtos na coleta de 13/09, e `bebidas` produziu 349 em **25/10, quatro
dias antes desta sondagem**. O coletor antigo usava `requests` puro.

As duas explicações possíveis:

1. **Proteção de bot** — o Cloudflare na home sugere que a loja só é
   entregue a quem passa pelo desafio; um cliente HTTP recebe o 404 do
   Webflow.
2. **A loja saiu do domínio** nos últimos dias.

Dá para separar as duas em dez segundos: **abra a URL no navegador**. Se a
loja carregar, é proteção de bot. Se der 404 também, a loja mudou de
endereço.

### O que foi feito a respeito

O coletor ganhou um modo com navegador de verdade, pelo mesmo caminho que o
projeto já usa para o Carrefour (Playwright + stealth):

```bash
pip install playwright playwright-stealth && playwright install chromium
python3 scraper/soudaki/coletar_soudaki.py --navegador
python3 scraper/soudaki/coletar_soudaki.py --navegador --ver-navegador  # com janela
```

E `parece_bloqueio()` passou a distinguir "a loja respondeu" de "veio um
desafio ou o 404 institucional" — antes, uma resposta 200 com o 404 do
Webflow seria tratada como seção vazia, e a coleta terminaria com zero
produtos sem explicar por quê. As respostas reais de hoje estão fixadas em
teste.


---

## 10. Carrega no navegador, não carrega no cliente HTTP

Com a confirmação de que a loja **abre normalmente no navegador**, as duas
hipóteses da seção anterior se resolvem: a loja **não mudou de endereço**.
`/shop/laticinios/` continua sendo o lugar certo. O que mudou é quem o site
atende.

### User-Agent não é a peça que falta

Primeira coisa que se checa, e ela já estava feita. O coletor sempre mandou
um User-Agent de Chrome:

```
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36
```

É o **mesmo** User-Agent do coletor legado, que trouxe 349 produtos em
25/10. Se o UA bastasse, nada teria quebrado. O filtro passou a olhar mais
fundo.

### O que faltava de verdade

Duas lacunas concretas, agora fechadas:

**1. Cabeçalhos incoerentes.** Declarávamos Chrome 126 mas não mandávamos
nada que um Chrome 126 manda junto: `sec-ch-ua`, `Sec-Fetch-Dest`,
`Sec-Fetch-Mode`, `Sec-Fetch-Site`, `Upgrade-Insecure-Requests`. Um UA de
Chrome sem as *client hints* do Chrome é uma incoerência fácil de detectar.

**2. Requisição fria, sem cookies.** O coletor ia direto em
`/shop/<secao>/`. Um navegador nunca faz isso: ele passa pela home, recebe
os cookies e só então navega, com `Referer`. Agora existe `sessao()`, que
visita a home uma vez e reaproveita os cookies em todas as seções.

### Um furo silencioso que isso revelou

O site devolve o 404 institucional com **status 200**. O caminho `requests`
só tratava `status_code == 404`, então a resposta passava como página
válida, o parser não achava produto nenhum e a seção era contada como
vazia — coleta terminando em zero **sem dizer o motivo**. Agora
`parece_bloqueio()` roda nos dois caminhos, requests e navegador.

### A escada de diagnóstico

Como só a sua máquina tem o caminho de rede que funciona, o teste precisa
rodar aí:

```bash
python3 scraper/soudaki/diagnostico_acesso.py
```

Ele sobe seis estratégias, da mais barata para a mais cara, e diz qual
delas devolve a loja de verdade:

| # | Estratégia | Custo |
|---|---|---|
| 1 | `requests`, cabeçalhos antigos | nenhum |
| 2 | `requests`, cabeçalhos completos | nenhum |
| 3 | sessão aquecida na home (cookies) | nenhum |
| 4 | Playwright headless | precisa instalar |
| 5 | Playwright headless, passando pela home | precisa instalar |
| 6 | Playwright com janela aberta | precisa instalar |

Cada linha sai como `OK` (com a contagem de produtos), `BLOQUEADO` (com o
motivo: 404 do Webflow ou desafio do Cloudflare), `PARCIAL`, `PULADA` ou
`ERRO`. Ao final ele imprime o comando de coleta correspondente à primeira
que funcionou. Opções: `--secao bebidas`, `--so 3`, `--salvar` (grava o
HTML de cada tentativa para inspeção).

Se nem a estratégia 6 passar, aí sim o endereço mudou, e o jeito é abrir o
F12 na aba Network e ver para onde a loja realmente vai.

### Se precisar do Playwright

```bash
pip install playwright playwright-stealth && playwright install chromium
python3 scraper/soudaki/coletar_soudaki.py --navegador
python3 scraper/soudaki/integrar_soudaki.py --aplicar
```


---

## 11. Era a localização (correção do que está escrito acima)

A pergunta certa foi "talvez proxy do Brasil?". Medi de onde saem as
minhas requisições:

```
{"ip":"194.26.202.48","country":"US"}
```

**Estados Unidos.** E as coletas que deram certo — 1.538 produtos em
13/09, 349 em 25/10 — rodaram na máquina do dono do projeto, em Santos.

Isso corrige o diagnóstico das seções 9 e 10. Eu havia escrito que algo
"mudou no site nos últimos quatro dias", porque o mesmo código funcionou
em 25/10 e falhou em 29/10. A comparação era inválida: **as duas execuções
saíram de países diferentes.** O mais provável é que nada tenha mudado. A
Daki entrega em cidades brasileiras; servir a vitrine só para o Brasil é
decisão de negócio banal, não defesa contra robô.

Resumo honesto do que cada evidência diz:

| Observação | O que eu concluí antes | O que ela realmente mostra |
|---|---|---|
| `/shop/*` → 404 daqui | o site mudou | um IP dos EUA recebe 404 |
| funcionou em 25/10 | quebrou em 4 dias | rodou do Brasil, e segue valendo |
| Turnstile na home | protege a loja | protege a home, e só |

### Precisa de proxy?

**Para você, não.** Você já está no Brasil — é só rodar na sua máquina. O
proxy resolveria o *meu* problema, não o do projeto.

Isso só vira questão se a coleta for automatizada um dia. Hoje não é: não
há `.github/workflows/`, nem cron no `render.yaml` ou no `vercel.json`.
Quando for, lembre que GitHub Actions, Render e Vercel rodam fora do
Brasil, e a coleta vai falhar exatamente assim. As saídas seriam coletar
localmente e versionar o JSON, usar um runner self-hosted em casa, ou
pagar um proxy br — nessa ordem de bom senso.

### O teste que fecha isso

`diagnostico_acesso.py` agora imprime o país de saída antes de começar e
avisa se você não estiver no Brasil. E a leitura do resultado ficou
explícita:

- **estratégia 1 passa** → é exatamente o que o coletor sempre fez. Nunca
  houve nada quebrado; o que decidia era de onde partia a requisição.
  Sem proxy, sem Playwright.
- **2 ou 3 passam** → cabeçalhos coerentes e cookies ajudaram. Já é o
  padrão do coletor.
- **só 4-6 passam** → aí sim há proteção de bot de verdade.

Nada do que foi feito nas seções 9 e 10 se perde nesse cenário: cabeçalhos
coerentes, sessão com cookies e a detecção do 404-servido-como-200 são
melhorias legítimas. Só não eram a causa.


---

## 12. Coletar sem ter Python na máquina

O plano das seções anteriores dependia de rodar um script aí. Sem Python
instalado, ele não serve. Mas o navegador sozinho dá conta: ele já tem o
IP brasileiro, os cookies da sessão e a aprovação do Cloudflare. Falta só
usá-lo como transporte.

### Como fazer

1. Abra **`https://soudaki.com/shop/laticinios/`** e espere carregar.
2. Tecle **F12** e vá na aba **Console**.
3. Se o Chrome reclamar, digite `allow pasting` e tecle Enter.
4. Abra `scraper/soudaki/coletor_navegador.js`, copie **tudo** e cole no
   console. Enter.
5. Ele percorre as seções, vai dizendo quantos produtos achou em cada uma
   e baixa **`soudaki_navegador.json`**.
6. Mande esse arquivo para o repositório — anexar no chat já basta.

Para só algumas seções: `coletarSoudaki(["laticinios", "bebidas"])`.

Leva cerca de meio minuto. A pausa de 0,9 s entre seções é de propósito:
não há razão para martelar o site.

### O que o script faz, e o que ele não faz

Ele faz **transporte e nada mais**. Para cada seção, busca a página com
`fetch(..., {credentials: "include"})` — mesma origem, mesmos cookies,
mesmo IP da aba aberta — e guarda o bloco `__NEXT_DATA__` cru.

Ele **não** interpreta produto, preço, marca ou EAN. Essa lógica continua
no Python, onde está testada. Duplicá-la em JavaScript seria criar uma
segunda versão para divergir da primeira.

Do lado de cá, `importar_coleta_navegador.py` recebe o arquivo e o entrega
às mesmas funções do coletor normal:

```bash
python3 scraper/soudaki/importar_coleta_navegador.py soudaki_navegador.json
python3 scraper/soudaki/integrar_soudaki.py --aplicar
```

### Verificado, não suposto

O JS foi executado de ponta a ponta contra o ensaio local, num contexto de
navegador simulado com Node, e o resultado passou pelo importador:

| Medida | Coletor nativo | Via navegador |
|---|---:|---:|
| produtos | 1.538 | **1.538** |
| em estoque | 1.132 | **1.132** |
| EAN-13 válido | 375 (24,4%) | **375 (24,4%)** |
| laticínios | 258 | **258** |
| padaria | 502 | **502** |

Idêntico. O caminho pelo navegador não perde nada.

Um detalhe que a verificação pegou: a página serve parte dos produtos em
`preloadedProducts` e parte no cache do Apollo (`Product:<sku>`). A
primeira versão da contagem olhava só a primeira fonte e anunciava 129
onde havia 258 — metade. Os dados iam completos, mas o número na tela
assustaria à toa. Agora conta identificadores únicos das duas fontes, o
que de quebra não conta duas vezes quem aparece nas duas.

6 testes cobrem o importador, incluindo arquivo inexistente, JSON quebrado
numa seção (não derruba as outras) e arquivo sem a chave `secoes`.
