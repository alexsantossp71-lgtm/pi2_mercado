#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 Atacadão (atacadao.com.br) — Coletor v2.0
=====================================================================
ESTRATÉGIA: API REST DIRETA da plataforma VTEX (bypass do site).

Descobertas em campo (out/2026, validadas contra a loja real):

  * O site novo é VTEX FastStore (Next.js): os produtos NÃO vêm no
    HTML nem no __NEXT_DATA__ (o navegador busca via GraphQL) =>
    raspar HTML não funciona mais (era o plano da v1).
  * O www.atacadao.com.br tem Cloudflare + proxy FastStore que
    entrega um lote FIXO cacheado da API e descarta _from/_to =>
    inútil para paginação.
  * A conta VTEX por trás da loja é "atacadaobr":
      https://atacadaobr.vtexcommercestable.com.br/api/catalog_system/...
    responde JSON puro, de qualquer IP (não testamos bloqueio).
  * PAGINAÇÃO: ?_from=N&_to=M funciona (até 50/página). MAS a VTEX
    usa CloudFront com cache de 5 min cuja chave ignora a query
    string => TODO request precisa de &_cb=<aleatório> (cache
    buster), senão a "página 2+" devolve o cache da página 1.
    [Foi exatamente isso que quebrou a paginação do coletor antigo]
  * O header de resposta "resources" traz o TOTAL da consulta:
    "0-49/542" => 542 produtos.
  * fq=isAvailablePerSalesChannel_1:1 => só produtos vendíveis no
    canal online (o resto vem com preço 0 e não serve p/ comparação).
    Padrão LIGADO; use --sem-fq para desligar.
  * Árvore de categorias: /api/catalog_system/pub/category/tree/3/
    => 515 folhas (nível 3) em 20 departamentos (out/2026).
    Há uma cópia embutida neste script como fallback.

Uso:
  python scrap_atacadao.py --probe                       # diagnóstico
  python scrap_atacadao.py --listar-categorias           # árvore
  python scrap_atacadao.py --secao padaria-e-matinais/leites/leite-integral
  python scrap_atacadao.py --secao all                   # 515 folhas
  python scrap_atacadao.py --secao all --db              # coleta + Neon
  python scrap_atacadao.py --integrar --dry-run          # simula
  python scrap_atacadao.py --integrar                    # grava no Neon

Saída (pasta output/):
  produtos_atacadao_full.json   cadastro (schema igual ao Soudaki v2)
  precos_atacadao_full.json     preços do dia
  checkpoint_atacadao.json      folhas concluídas (retomada do --secao all)
=====================================================================
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import random
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("[ERRO] Falta o requests. Rode: pip install requests")

# ---------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------
API = "https://atacadaobr.vtexcommercestable.com.br"   # plataforma VTEX
SITE = "https://www.atacadao.com.br"                    # só p/ Referer/links
LOJA_ID = 3          # Atacadão na tabela precos
OUT = Path(__file__).resolve().parent / "output"
TAM_PAGINA = 50      # VTEX: no máx. 50 itens por request
MAX_PAGINAS_PADRAO = 50   # trava: 50 págs x 50 = 2500 itens/categ. (cap VTEX)
FQ_DISPONIVEL = "isAvailablePerSalesChannel_1:1"
CHECKPOINT_A_CADA = 25    # folhas entre salvamentos parciais
HOJE = date.today().isoformat()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

RE_EAN = re.compile(r"\d{8,14}")
RE_TAG = re.compile(r"<[^>]+>")
RE_RECURSOS = re.compile(r"/(\d+)\s*$")           # "0-49/542" -> 542
RE_APRES = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|un|unid(?:ade)?s?)\b", re.I)

# departamentos (nível 1) — slug -> nome bonito
DEPTOS = {
    "mercearia": "Mercearia",
    "frios-e-congelados": "Frios e congelados",
    "bebidas": "Bebidas",
    "higiene-e-perfumaria": "Higiene e perfumaria",
    "limpeza": "Limpeza",
    "automotivo": "Automotivo",
    "pet-shop": "Pet Shop",
    "hortifruti": "Hortifrúti",
    "carnes-aves-e-peixes": "Carnes, aves e peixes",
    "jardinagem": "Jardinagem",
    "padaria-e-matinais": "Padaria e matinais",
    "utilidades-domesticas": "Utilidades domésticas",
    "eletronicos-e-eletroportateis": "Eletrônicos e eletroportáteis",
    "descartaveis-e-embalagens": "Descartáveis e embalagens",
    "papelaria": "Papelaria",
    "esporte-e-lazer": "Esporte e lazer",
    "vestuario": "Vestuário",
    "cafeteria": "Cafeteria",
    "suplementos-alimentares": "Suplementos alimentares",
    "drogaria": "Drogaria",
}

# Fallback embutido (out/2026): "path|Nome;path|Nome;..."
FOLHAS_RAW = "mercearia/acucar-e-adocantes/acucar|Açúcar;mercearia/acucar-e-adocantes/adocante|Adoçante;mercearia/conservas-e-enlatados/atum-e-sardinha|Atum e sardinha;mercearia/conservas-e-enlatados/azeitona|Azeitona;mercearia/conservas-e-enlatados/cogumelo|Cogumelo;mercearia/conservas-e-enlatados/demais-conservas|Demais conservas;mercearia/conservas-e-enlatados/ervilha|Ervilha;mercearia/conservas-e-enlatados/milho-verde|Milho verde;mercearia/conservas-e-enlatados/palmito|Palmito;mercearia/confeitaria/chocolate-em-po-e-granulado|Chocolate em pó e granulado;mercearia/confeitaria/fermento|Fermento;mercearia/confeitaria/leite-condensado-e-mistura-lactea|Leite condensado e mistura láctea;mercearia/confeitaria/leite-de-coco-e-coco-ralado|Leite de coco e coco ralado;mercearia/confeitaria/mistura-de-bolo-mousse-e-pudim|Mistura de bolo, mousse e pudim;mercearia/confeitaria/sagu|Sagu;mercearia/confeitaria/sorvete-e-acompanhamentos|Sorvete e acompanhamentos;mercearia/confeitaria/gelatina|Gelatina;mercearia/confeitaria/doce-para-enrolar|Doce para enrolar;mercearia/confeitaria/creme-culinario-e-de-leite|Creme culinário e de leite;mercearia/confeitaria/glicose|Glicose;mercearia/farinhas/amido-de-milho|Amido de milho;mercearia/farinhas/farinha-de-mandioca|Farinha de mandioca;mercearia/farinhas/farinha-de-milho|Farinha de milho;mercearia/farinhas/farinha-de-rosca|Farinha de rosca;mercearia/farinhas/farinha-de-trigo-integral|Farinha de trigo integral;mercearia/farinhas/farinha-de-trigo-tradicional|Farinha de trigo tradicional;mercearia/farinhas/farinha-especial|Farinha especial;mercearia/farinhas/farofa|Farofa;mercearia/farinhas/polvilho|Polvilho;mercearia/farinhas/tapioca|Tapioca;mercearia/farinhas/floco-de-arroz|Floco de arroz;mercearia/farinhas/fecula-de-mandioca|Fécula de mandioca;mercearia/farinhas/cevada|Cevada;mercearia/massas-e-molhos/macarrao-instantaneo|Macarrão instantâneo;mercearia/massas-e-molhos/massa-de-pizza|Massa de pizza;mercearia/massas-e-molhos/massa-seca|Massa seca;mercearia/massas-e-molhos/molho-de-tomate|Molho de tomate;mercearia/massas-e-molhos/molho|Molho;mercearia/massas-e-molhos/queijo-ralado|Queijo ralado;mercearia/azeites-oleos-e-vinagres/oleo-de-algodao|Óleo de algodão;mercearia/azeites-oleos-e-vinagres/oleo-de-canola|Óleo de canola;mercearia/azeites-oleos-e-vinagres/oleo-de-girassol|Óleo de girassol;mercearia/azeites-oleos-e-vinagres/oleo-de-milho|Óleo de milho;mercearia/azeites-oleos-e-vinagres/oleo-de-soja|Óleo de soja;mercearia/azeites-oleos-e-vinagres/azeite|Azeite;mercearia/azeites-oleos-e-vinagres/vinagre-e-aceto-balsamico|Vinagre e aceto balsâmico;mercearia/azeites-oleos-e-vinagres/oleo-de-coco|Óleo de coco;mercearia/azeites-oleos-e-vinagres/oleo-composto|Óleo composto;mercearia/azeites-oleos-e-vinagres/oleo-emulsificante|Óleo emulsificante;mercearia/azeites-oleos-e-vinagres/oleo-de-gergelim|Óleo de gergelim;mercearia/sopas-e-cremes/sopa-e-creme|Sopa e creme;mercearia/temperos-e-condimentos/alho-e-cebola|Alho e cebola;mercearia/temperos-e-condimentos/ervas-e-especiarias|Ervas e especiarias;mercearia/temperos-e-condimentos/ketchup|Ketchup;mercearia/temperos-e-condimentos/maionese|Maionese;mercearia/temperos-e-condimentos/molho-barbecue|Molho barbecue;mercearia/temperos-e-condimentos/molho-de-pimenta|Molho de pimenta;mercearia/temperos-e-condimentos/molho-shoyu|Molho shoyu;mercearia/temperos-e-condimentos/molho-para-salada|Molho para salada;mercearia/temperos-e-condimentos/molho-variado|Molho variado;mercearia/temperos-e-condimentos/mostarda|Mostarda;mercearia/temperos-e-condimentos/sal|Sal;mercearia/temperos-e-condimentos/tempero-pronto-e-caldo|Tempero pronto e caldo;mercearia/temperos-e-condimentos/bicarbonato|Bicarbonato;mercearia/chocolates/barra-de-chocolate|Barra de chocolate;mercearia/chocolates/bombom|Bombom;mercearia/chocolates/ovo-de-pascoa|Ovo de páscoa;mercearia/chocolates/gota-e-pedaco|Gota e pedaço;mercearia/coberturas-cremes-e-recheios/creme-de-avela|Creme de avelã;mercearia/coberturas-cremes-e-recheios/pasta-de-amendoim|Pasta de amendoim;mercearia/coberturas-cremes-e-recheios/essencias|Essências;mercearia/coberturas-cremes-e-recheios/pasta-de-chocolate|Pasta de chocolate;mercearia/coberturas-cremes-e-recheios/cobertura|Cobertura;mercearia/coberturas-cremes-e-recheios/recheio|Recheio;mercearia/doces/doce-de-leite|Doce de leite;mercearia/doces/doce-de-abobora|Doce de abóbora;mercearia/doces/doce-de-amendoim|Doce de amendoim;mercearia/doces/fruta-em-calda|Fruta em calda;mercearia/doces/doce-de-fruta|Doce de fruta;mercearia/doces/pao-de-mel|Pão de mel;mercearia/doces/doce-de-batata-doce|Doce de batata doce;mercearia/alimento-infantil/alimento-infantil-diversos|Alimento infantil diversos;mercearia/cafes-chas-e-achocolatados/achocolatado-em-po|Achocolatado em pó;mercearia/cafes-chas-e-achocolatados/cafe-soluvel|Café solúvel;mercearia/cafes-chas-e-achocolatados/cafe-torrado-e-moido|Café torrado e moído;mercearia/cafes-chas-e-achocolatados/capsula|Cápsula;mercearia/cafes-chas-e-achocolatados/cha|Chá;mercearia/cafes-chas-e-achocolatados/cappuccino|Cappuccino;mercearia/cafes-chas-e-achocolatados/filtro-de-papel|Filtro de papel;mercearia/cafes-chas-e-achocolatados/cafe-em-graos|Café em grãos;mercearia/graos/arroz-integral|Arroz integral;mercearia/graos/arroz-parboilizado|Arroz parboilizado;mercearia/graos/arroz-branco|Arroz branco;mercearia/graos/feijao|Feijão;mercearia/graos/graos-diversos|Grãos diversos;mercearia/salgadinhos-e-snacks/barra-de-cereais|Barra de cereais;mercearia/salgadinhos-e-snacks/amendoim-doce|Amendoim doce;mercearia/salgadinhos-e-snacks/amendoim|Amendoim;mercearia/salgadinhos-e-snacks/batata-palha|Batata palha;mercearia/salgadinhos-e-snacks/pipoca|Pipoca;mercearia/salgadinhos-e-snacks/salgadinho|Salgadinho;mercearia/salgadinhos-e-snacks/snack|Snack;mercearia/kits-e-cestas/cesta-de-natal|Cesta de natal;mercearia/kits-e-cestas/cesta-basica|Cesta básica;mercearia/bomboniere/bala|Bala;mercearia/bomboniere/confeito|Confeito;mercearia/bomboniere/goma-de-mascar|Goma de mascar;mercearia/bomboniere/pirulito|Pirulito;mercearia/biscoitos/biscoito-de-maizena|Biscoito de maizena;mercearia/biscoitos/biscoito-doce|Biscoito doce;mercearia/biscoitos/biscoito-integral|Biscoito integral;mercearia/biscoitos/biscoito-recheado|Biscoito recheado;mercearia/biscoitos/biscoito-salgado|Biscoito salgado;mercearia/biscoitos/biscoito-waffer|Biscoito waffer;mercearia/biscoitos/cookies|Cookies;frios-e-congelados/embutidos/apresuntado-mortadela-e-presunto|Apresuntado, mortadela e presunto;frios-e-congelados/embutidos/lanche|Lanche;frios-e-congelados/embutidos/lombo|Lombo;frios-e-congelados/embutidos/embutido|Embutido;frios-e-congelados/embutidos/afiambrado|Afiambrado;frios-e-congelados/embutidos/copa-pepperoni-e-salame|Copa, pepperoni e salame;frios-e-congelados/embutidos/peito-de-frango-e-de-peru|Peito de frango e de peru;frios-e-congelados/lacteos/bebida-lactea|Bebida láctea;frios-e-congelados/lacteos/cream-cheese-e-requeijao|Cream cheese e requeijão;frios-e-congelados/lacteos/fondue|Fondue;frios-e-congelados/lacteos/iogurte|Iogurte;frios-e-congelados/lacteos/leite-fermentado|Leite fermentado;frios-e-congelados/lacteos/sobremesa-lactea|Sobremesa láctea;frios-e-congelados/lacteos/coalhada|Coalhada;frios-e-congelados/lacteos/nata|Nata;frios-e-congelados/lacteos/cobertura-culinaria|Cobertura culinária;frios-e-congelados/lacteos/bebida-proteica|Bebida proteica;frios-e-congelados/margarinas-e-manteigas/manteiga-com-sal|Manteiga com sal;frios-e-congelados/margarinas-e-manteigas/manteiga-sem-sal|Manteiga sem sal;frios-e-congelados/margarinas-e-manteigas/creme-vegetal|Creme vegetal;frios-e-congelados/margarinas-e-manteigas/banha-e-gordura|Banha e gordura;frios-e-congelados/margarinas-e-manteigas/margarina-com-sal|Margarina com sal;frios-e-congelados/margarinas-e-manteigas/margarina-sem-sal|Margarina sem sal;frios-e-congelados/massas-frescas/capeletti|Capeletti;frios-e-congelados/massas-frescas/massa-para-lasanha|Massa para lasanha;frios-e-congelados/massas-frescas/massa-para-pastel|Massa para pastel;frios-e-congelados/massas-frescas/nhoque|Nhoque;frios-e-congelados/massas-frescas/outras-massas|Outras massas;frios-e-congelados/massas-frescas/raviolli|Raviolli;frios-e-congelados/queijos/queijo-minas-frescal-e-padrao|Queijo minas frescal e padrão;frios-e-congelados/queijos/queijo-mussarela|Queijo mussarela;frios-e-congelados/queijos/queijo-provolone|Queijo provolone;frios-e-congelados/queijos/queijo-coalho|Queijo coalho;frios-e-congelados/queijos/queijo-prato|Queijo prato;frios-e-congelados/queijos/queijo-processado|Queijo processado;frios-e-congelados/queijos/ricota-e-creme-de-ricota|Ricota e creme de ricota;frios-e-congelados/queijos/coalho-para-queijo|Coalho para queijo;frios-e-congelados/queijos/queijo-cheddar|Queijo cheddar;frios-e-congelados/queijos/queijo-especial|Queijo especial;frios-e-congelados/hamburgueres/hamburguer-bovino|Hambúrguer bovino;frios-e-congelados/hamburgueres/hamburguer-de-frango|Hambúrguer de frango;frios-e-congelados/hamburgueres/hamburguer-gourmet|Hambúrguer gourmet;frios-e-congelados/hamburgueres/hamburguer-misto|Hambúrguer misto;frios-e-congelados/hamburgueres/hamburguer-de-vegetal|Hambúrguer de vegetal;frios-e-congelados/pratos-prontos/empanado|Empanado;frios-e-congelados/pratos-prontos/lanche-congelado|Lanche congelado;frios-e-congelados/pratos-prontos/lasanha-congelada|Lasanha congelada;frios-e-congelados/pratos-prontos/pao|Pão;frios-e-congelados/pratos-prontos/pizza|Pizza;frios-e-congelados/pratos-prontos/salgado|Salgado;frios-e-congelados/pratos-prontos/sobremesa|Sobremesa;frios-e-congelados/pratos-prontos/torta-salgada|Torta salgada;frios-e-congelados/pratos-prontos/pao-de-alho|Pão de alho;frios-e-congelados/pratos-prontos/kibe-e-almondega|Kibe e almôndega;frios-e-congelados/pratos-prontos/prato-pronto|Prato pronto;frios-e-congelados/sorvetes-e-acai/acai|Açaí;frios-e-congelados/sorvetes-e-acai/sorvete|Sorvete;frios-e-congelados/sorvetes-e-acai/gelo|Gelo;frios-e-congelados/legumes-e-vegetais/batata-congelada|Batata congelada;frios-e-congelados/legumes-e-vegetais/legume-e-vegetal|Legume e vegetal;frios-e-congelados/polpas-e-frutas/polpa-de-fruta|Polpa de fruta;frios-e-congelados/polpas-e-frutas/fruta-congelada|Fruta congelada;bebidas/cervejas/cerveja-pilsen|Cerveja pilsen;bebidas/cervejas/cerveja-sem-alcool|Cerveja sem álcool;bebidas/cervejas/cerveja-artesanal|Cerveja artesanal;bebidas/cervejas/cerveja-ipa|Cerveja IPA;bebidas/cervejas/cerveja-especial|Cerveja especial;bebidas/cervejas/cerveja-puro-malte|Cerveja puro malte;bebidas/aguas/agua-de-coco|Água de coco;bebidas/aguas/agua-com-gas|Água com gás;bebidas/aguas/agua-sem-gas|Água sem gás;bebidas/aguas/tonica-e-saborizada|Tônica e saborizada;bebidas/champanhes-espumantes-e-sidras/espumante-nacional|Espumante nacional;bebidas/champanhes-espumantes-e-sidras/espumante-importado|Espumante importado;bebidas/champanhes-espumantes-e-sidras/champanhe-nacional|Champanhe nacional;bebidas/champanhes-espumantes-e-sidras/champanhe-importado|Champanhe importado;bebidas/chas-prontos/cha-verde|Chá verde;bebidas/chas-prontos/cha-mate|Chá mate;bebidas/chas-prontos/cha-preto|Chá preto;bebidas/chas-prontos/cha-de-hibisco|Chá de hibisco;bebidas/chas-prontos/cha-branco|Chá branco;bebidas/chas-prontos/cha-capim-limao|Chá capim-limão;bebidas/coqueteis/conhaque|Conhaque;bebidas/coqueteis/licor|Licor;bebidas/coqueteis/rum|Rum;bebidas/coqueteis/catuaba|Catuaba;bebidas/coqueteis/bebida-mista|Bebida mista;bebidas/destilados/aguardente|Aguardente;bebidas/destilados/corote|Corote;bebidas/destilados/gin|Gin;bebidas/destilados/saque|Saquê;bebidas/destilados/tequila|Tequila;bebidas/destilados/vermouth-e-steinhager|Vermouth e steinhäger;bebidas/destilados/vodka|Vodka;bebidas/destilados/aperitivo|Aperitivo;bebidas/destilados/ingredientes-para-drinks|Ingredientes para drinks;bebidas/energeticos-e-isotonicos/energetico|Energético;bebidas/energeticos-e-isotonicos/isotonico|Isotônico;bebidas/refrigerantes/refrigerante-sem-acucar|Refrigerante sem açúcar;bebidas/refrigerantes/refrigerante-de-sabor|Refrigerante de sabor;bebidas/refrigerantes/refrigerante-cola|Refrigerante cola;bebidas/refrigerantes/refrigerante-guarana|Refrigerante guaraná;bebidas/sucos-e-refrescos/bebida-de-soja|Bebida de soja;bebidas/sucos-e-refrescos/refresco-em-po|Refresco em pó;bebidas/sucos-e-refrescos/suco-concentrado|Suco concentrado;bebidas/sucos-e-refrescos/suco-integral|Suco integral;bebidas/sucos-e-refrescos/suco-pronto|Suco pronto;bebidas/sucos-e-refrescos/suco-refrigerado|Suco refrigerado;bebidas/sucos-e-refrescos/xarope-de-guarana-e-groselha|Xarope de guaraná e groselha;bebidas/sucos-e-refrescos/bebida-de-castanha|Bebida de castanha;bebidas/sucos-e-refrescos/bebida-de-amendoa|Bebida de amêndoa;bebidas/vinhos/vinho-importado|Vinho importado;bebidas/vinhos/vinho-nacional|Vinho nacional;bebidas/vinhos/coquetel-de-vinho|Coquetel de vinho;bebidas/vinhos/chopp-de-vinho|Chopp de vinho;bebidas/whiskies/whisky|Whisky;higiene-e-perfumaria/cabelo/condicionador|Condicionador;higiene-e-perfumaria/cabelo/creme-para-pentear|Creme para pentear;higiene-e-perfumaria/cabelo/creme-para-tratamento|Creme para tratamento;higiene-e-perfumaria/cabelo/gel-fixador|Gel fixador;higiene-e-perfumaria/cabelo/pente-e-escova|Pente e escova;higiene-e-perfumaria/cabelo/shampoo|Shampoo;higiene-e-perfumaria/cabelo/tintura-para-cabelo|Tintura para cabelo;higiene-e-perfumaria/cabelo/kit-para-cabelo|Kit para cabelo;higiene-e-perfumaria/cabelo/agua-oxigenada-e-descolorante|Água oxigenada e descolorante;higiene-e-perfumaria/cremes-de-barbear-e-barbeadores/aparelho-carga-e-lamina-de-barbear|Aparelho, carga e lâmina de barbear;higiene-e-perfumaria/cremes-de-barbear-e-barbeadores/creme-e-espuma-de-barbear|Creme e espuma de barbear;higiene-e-perfumaria/cremes-de-barbear-e-barbeadores/locao-pos-barba|Loção pós-barba;higiene-e-perfumaria/cremes-de-barbear-e-barbeadores/produtos-para-barba|Produtos para barba;higiene-e-perfumaria/desodorantes/aerossol|Aerossol;higiene-e-perfumaria/desodorantes/roll-on|Roll-On;higiene-e-perfumaria/desodorantes/liquido|Líquido;higiene-e-perfumaria/desodorantes/creme|Creme;higiene-e-perfumaria/higiene-bucal/creme-dental|Creme dental;higiene-e-perfumaria/higiene-bucal/enxaguante-bucal|Enxaguante bucal;higiene-e-perfumaria/higiene-bucal/escova-dental|Escova dental;higiene-e-perfumaria/higiene-bucal/fio-dental|Fio dental;higiene-e-perfumaria/higiene-intima/absorvente|Absorvente;higiene-e-perfumaria/higiene-intima/sabonete-intimo|Sabonete Íntimo;higiene-e-perfumaria/papel-higienico/folha-dupla|Folha dupla;higiene-e-perfumaria/papel-higienico/folha-simples|Folha simples;higiene-e-perfumaria/papel-higienico/folha-tripla|Folha tripla;higiene-e-perfumaria/sabonetes/sabonete-liquido|Sabonete líquido;higiene-e-perfumaria/sabonetes/sabonete-em-barra|Sabonete em barra;higiene-e-perfumaria/saude/alcool-gel|Álcool Gel;higiene-e-perfumaria/saude/algodao-e-curativo|Algodão e curativo;higiene-e-perfumaria/saude/hastes-flexiveis|Hastes flexíveis;higiene-e-perfumaria/saude/protetor-solar|Protetor solar;higiene-e-perfumaria/saude/preservativo|Preservativo;higiene-e-perfumaria/saude/roupa-intima|Roupa íntima;higiene-e-perfumaria/saude/fralda-geriatrica|Fralda geriátrica;higiene-e-perfumaria/corpo/bucha-e-esponja-de-banho|Bucha e esponja de banho;higiene-e-perfumaria/corpo/depilacao|Depilação;higiene-e-perfumaria/corpo/desodorante-para-os-pes|Desodorante para os pés;higiene-e-perfumaria/corpo/esmalte-e-acetona|Esmalte e acetona;higiene-e-perfumaria/corpo/locao-talco-e-hidratante|Loção, talco e hidratante;higiene-e-perfumaria/corpo/repelente|Repelente;higiene-e-perfumaria/corpo/oleo-perfumado|Óleo perfumado;higiene-e-perfumaria/bebes/fralda-rn|Fralda RN;higiene-e-perfumaria/bebes/fralda-p|Fralda P;higiene-e-perfumaria/bebes/fralda-m|Fralda M;higiene-e-perfumaria/bebes/fralda-g|Fralda G;higiene-e-perfumaria/bebes/fralda-xg|Fralda XG;higiene-e-perfumaria/bebes/fralda-xxg|Fralda XXG;higiene-e-perfumaria/bebes/lenco-de-papel-e-umedecido|Lenço de papel e umedecido;higiene-e-perfumaria/bebes/creme-para-assadura|Creme para assadura;higiene-e-perfumaria/bebes/bico-para-mamadeira|Bico para mamadeira;higiene-e-perfumaria/bebes/acessorio-para-bebe|Acessório para bebê;limpeza/limpeza-de-banheiro/agua-sanitaria-e-cloro|Água sanitária e cloro;limpeza/limpeza-de-banheiro/desinfetante-sanitario|Desinfetante sanitário;limpeza/limpeza-de-banheiro/desodorizador-e-detergente-sanitario|Desodorizador e detergente sanitário;limpeza/limpeza-de-banheiro/limpador-sanitario|Limpador sanitário;limpeza/limpeza-de-casa/alcool-e-removedor|Álcool e removedor;limpeza/limpeza-de-casa/antimofo|Antimofo;limpeza/limpeza-de-casa/aromatizante|Aromatizante;limpeza/limpeza-de-casa/cera-e-polidor|Cera e polidor;limpeza/limpeza-de-casa/inseticida|Inseticida;limpeza/limpeza-de-casa/limpador-perfumado-e-de-uso-geral|Limpador perfumado e de uso geral;limpeza/limpeza-de-casa/limpa-piso-e-vidro|Limpa piso e vidro;limpeza/limpeza-de-casa/lustra-movel|Lustra móvel;limpeza/limpeza-de-cozinha/detergente|Detergente;limpeza/limpeza-de-cozinha/esponja-e-la-de-aco|Esponja e lã de aço;limpeza/limpeza-de-cozinha/lava-louca|Lava louça;limpeza/limpeza-de-cozinha/limpador-de-forno|Limpador de forno;limpeza/limpeza-de-cozinha/limpador-e-desengordurante|Limpador e desengordurante;limpeza/limpeza-de-cozinha/sabao-em-pasta-e-saponaceo|Sabão em pasta e saponáceo;limpeza/limpeza-de-roupas/alvejante|Alvejante;limpeza/limpeza-de-roupas/amaciante|Amaciante;limpeza/limpeza-de-roupas/lava-roupa-em-po|Lava roupa em pó;limpeza/limpeza-de-roupas/lava-roupa-liquido|Lava roupa líquido;limpeza/limpeza-de-roupas/passa-roupa|Passa roupa;limpeza/limpeza-de-roupas/sabao-em-barra|Sabão em barra;limpeza/limpeza-de-roupas/tira-manchas|Tira manchas;limpeza/limpeza-de-roupas/sanitizante-em-po|Sanitizante em pó;limpeza/limpeza-de-roupas/sanitizante-liquido|Sanitizante líquido;automotivo/pneus/aro-13|Aro 13;automotivo/pneus/aro-14|Aro 14;automotivo/pneus/aro-15|Aro 15;automotivo/pneus/aro-16|Aro 16;automotivo/pneus/aro-17|Aro 17;automotivo/pneus/aro-18|Aro 18;automotivo/pneus/aro-19|Aro 19;automotivo/acessorios-automotivos/acessorio-automotivo|Acessório automotivo;automotivo/limpadores-polidores-e-oleos/oleo-para-motor|Óleo para motor;automotivo/limpadores-polidores-e-oleos/limpador-e-polidor|Limpador e polidor;pet-shop/higiene-e-limpeza/eliminador-de-odores|Eliminador de odores;pet-shop/higiene-e-limpeza/areia-para-gatos|Areia para gatos;pet-shop/higiene-e-limpeza/shampoo-e-condicionador|Shampoo e condicionador;pet-shop/higiene-e-limpeza/tapete-higienico|Tapete higiênico;pet-shop/acessorios-pet-shop/comedouro-e-bebedouro|Comedouro e bebedouro;pet-shop/acessorios-pet-shop/brinquedo-e-acessorio|Brinquedo e acessório;pet-shop/petiscos/biscoito-para-caes|Biscoito para cães;pet-shop/petiscos/biscoito-para-gatos|Biscoito para gatos;pet-shop/racao/racao-seca-para-caes|Ração seca para cães;pet-shop/racao/racao-umida-para-caes|Ração úmida para cães;pet-shop/racao/racao-seca-para-gatos|Ração seca para gatos;pet-shop/racao/racao-umida-para-gatos|Ração úmida para gatos;pet-shop/sementes/semente|Semente;hortifruti/ovos/ovo-de-codorna|Ovo de codorna;hortifruti/ovos/ovo-branco|Ovo branco;hortifruti/ovos/ovo-vermelho|Ovo vermelho;hortifruti/ovos/ovo-organico|Ovo orgânico;hortifruti/ovos/ovo-pasteurizado|Ovo pasteurizado;hortifruti/verduras-e-hortalicas/tempero-fresco|Tempero fresco;hortifruti/verduras-e-hortalicas/alga|Alga;hortifruti/verduras-e-hortalicas/verdura|Verdura;hortifruti/legumes-e-vegetais/alho-e-cebola|Alho e cebola;hortifruti/legumes-e-vegetais/legume-e-vegetal|Legume e vegetal;hortifruti/legumes-e-vegetais/batata|Batata;hortifruti/frutas/fruta-fresca|Fruta fresca;hortifruti/frutas/fruta-seca-e-processada|Fruta seca e processada;hortifruti/higienizadores-de-alimentos/higienizador-de-alimento|Higienizador de alimento;carnes-aves-e-peixes/aves/ave-natalina|Ave natalina;carnes-aves-e-peixes/aves/corte-de-frango|Corte de frango;carnes-aves-e-peixes/aves/aves-diversas|Aves diversas;carnes-aves-e-peixes/aves/miudo|Miúdo;carnes-aves-e-peixes/peixes-e-frutos-do-mar/bacalhau|Bacalhau;carnes-aves-e-peixes/peixes-e-frutos-do-mar/frutos-do-mar|Frutos do mar;carnes-aves-e-peixes/peixes-e-frutos-do-mar/peixe|Peixe;carnes-aves-e-peixes/secas-salgadas-e-defumadas/charque|Charque;carnes-aves-e-peixes/secas-salgadas-e-defumadas/bacon|Bacon;carnes-aves-e-peixes/secas-salgadas-e-defumadas/carne-de-sol|Carne de sol;carnes-aves-e-peixes/secas-salgadas-e-defumadas/ingredientes-para-feijoada|Ingredientes para feijoada;carnes-aves-e-peixes/secas-salgadas-e-defumadas/carne-seca|Carne seca;carnes-aves-e-peixes/carnes/carne-bovina|Carne bovina;carnes-aves-e-peixes/carnes/carne-suina|Carne suína;carnes-aves-e-peixes/carnes/espeto|Espeto;carnes-aves-e-peixes/carnes/ovino-e-caprino|Ovino e caprino;carnes-aves-e-peixes/linguicas-salsichas-e-chouricos/linguica|Linguiça;carnes-aves-e-peixes/linguicas-salsichas-e-chouricos/salsicha|Salsicha;carnes-aves-e-peixes/linguicas-salsichas-e-chouricos/chourico|Chouriço;carnes-aves-e-peixes/linguicas-salsichas-e-chouricos/linguicinha|Linguicinha;jardinagem/solo/terra-vegetal|Terra vegetal;jardinagem/plantas/planta|Planta;jardinagem/plantas/cacto-e-suculenta|Cacto e suculenta;jardinagem/flores/flor|Flor;jardinagem/acessorios-para-jardim/acessorio-para-jardim|Acessório para jardim;padaria-e-matinais/aveias-e-cereais/aveia|Aveia;padaria-e-matinais/aveias-e-cereais/cereal-matinal|Cereal matinal;padaria-e-matinais/aveias-e-cereais/granola|Granola;padaria-e-matinais/leites/leite-0--lactose|Leite 0% lactose;padaria-e-matinais/leites/leite-desnatado|Leite desnatado;padaria-e-matinais/leites/leite-integral|Leite integral;padaria-e-matinais/leites/leite-semidesnatado|Leite semidesnatado;padaria-e-matinais/leites/leite-em-po|Leite em pó;padaria-e-matinais/leites/composto-lacteo-e-suplemento|Composto lácteo e suplemento;padaria-e-matinais/bolos-e-tortas/bolo|Bolo;padaria-e-matinais/bolos-e-tortas/minibolo|Minibolo;padaria-e-matinais/bolos-e-tortas/torta|Torta;padaria-e-matinais/paes-e-torradas/pao-de-forma|Pão de forma;padaria-e-matinais/paes-e-torradas/pao-de-hamburguer|Pão de hambúrguer;padaria-e-matinais/paes-e-torradas/pao-de-hot-dog|Pão de hot dog;padaria-e-matinais/paes-e-torradas/pao-especial|Pão especial;padaria-e-matinais/paes-e-torradas/pao-de-coco|Pão de coco;padaria-e-matinais/paes-e-torradas/pao-de-milho|Pão de milho;padaria-e-matinais/paes-e-torradas/pao-sem-gluten|Pão sem glúten;padaria-e-matinais/paes-e-torradas/pao-sovado|Pão sovado;padaria-e-matinais/paes-e-torradas/pao-integral|Pão integral;padaria-e-matinais/paes-e-torradas/torrada|Torrada;padaria-e-matinais/paes-e-torradas/bisnaguinha|Bisnaguinha;padaria-e-matinais/paes-e-torradas/colomba-pascal|Colomba pascal;padaria-e-matinais/paes-e-torradas/pao-salgado|Pão salgado;padaria-e-matinais/paes-e-torradas/pao-doce|Pão doce;padaria-e-matinais/paes-e-torradas/pao-de-mel-2|Pão de mel 2;padaria-e-matinais/mel-geleias-e-pates/pate|Patê;padaria-e-matinais/mel-geleias-e-pates/geleia|Geleia;padaria-e-matinais/mel-geleias-e-pates/mel|Mel;padaria-e-matinais/panetones-e-chocotones/panetone|Panetone;padaria-e-matinais/panetones-e-chocotones/chocotone|Chocotone;padaria-e-matinais/doceria/donut-e-bomba|Donut e bomba;padaria-e-matinais/doceria/sonho|Sonho;padaria-e-matinais/doceria/petit-four|Petit four;padaria-e-matinais/salgados/assado|Assado;padaria-e-matinais/salgados/pastel|Pastel;utilidades-domesticas/cozinha/acessorio-para-pia-de-cozinha|Acessório para pia de cozinha;utilidades-domesticas/cozinha/conjunto-de-jantar|Conjunto de jantar;utilidades-domesticas/cozinha/copo-caneca-e-taca|Copo, caneca e taça;utilidades-domesticas/cozinha/demais-acessorios-para-cozinha|Demais acessórios para cozinha;utilidades-domesticas/cozinha/faca-de-cozinha-e-faqueiro|Faca de cozinha e faqueiro;utilidades-domesticas/cozinha/garrafa-termica|Garrafa térmica;utilidades-domesticas/cozinha/panela|Panela;utilidades-domesticas/cozinha/pote-tigela-e-jarra|Pote, tigela e jarra;utilidades-domesticas/cozinha/cadeira-banqueta-e-mesa|Cadeira, banqueta e mesa;utilidades-domesticas/cozinha/assadeira|Assadeira;utilidades-domesticas/velas-e-acendedores/fosforo-carvao-e-lenha|Fósforo, carvão e lenha;utilidades-domesticas/velas-e-acendedores/vela|Vela;utilidades-domesticas/utilidades-domesticas-diversas/lampada|Lâmpada;utilidades-domesticas/utilidades-domesticas-diversas/pilha-e-bateria|Pilha e bateria;utilidades-domesticas/utilidades-domesticas-diversas/acessorio-para-manicure|Acessório para manicure;utilidades-domesticas/utilidades-domesticas-diversas/luva-de-procedimento|Luva de procedimento;utilidades-domesticas/utilidades-domesticas-diversas/verniz-para-calcados|Verniz para calçados;utilidades-domesticas/utilidades-domesticas-diversas/colchao|Colchão;utilidades-domesticas/utilidades-domesticas-diversas/escova|Escova;utilidades-domesticas/utilidades-domesticas-diversas/adaptador-ferramenta-extensao-e-lanterna|Adaptador, ferramenta, extensão e lanterna;utilidades-domesticas/utilidades-domesticas-diversas/bomba-de-ar|Bomba de ar;utilidades-domesticas/utilidades-domesticas-diversas/arvore-de-natal|Árvore de natal;utilidades-domesticas/utilidades-domesticas-diversas/espelho|Espelho;utilidades-domesticas/utilidades-domesticas-diversas/guarda-chuva|Guarda-chuva;utilidades-domesticas/utilidades-domesticas-diversas/mala|Mala;utilidades-domesticas/utilidades-domesticas-diversas/corante|Corante;utilidades-domesticas/utilidades-domesticas-diversas/churrasqueira-e-acessorios|Churrasqueira e acessórios;utilidades-domesticas/banheiro-e-lavanderia/assento-sanitario|Assento sanitário;utilidades-domesticas/banheiro-e-lavanderia/escova-sanitaria|Escova sanitária;utilidades-domesticas/banheiro-e-lavanderia/pregador-de-roupa-e-varal|Pregador de roupa e varal;utilidades-domesticas/banheiro-e-lavanderia/resistencia|Resistência;utilidades-domesticas/banheiro-e-lavanderia/cantoneira|Cantoneira;utilidades-domesticas/banheiro-e-lavanderia/saboneteira|Saboneteira;utilidades-domesticas/banheiro-e-lavanderia/acessorio|Acessório;utilidades-domesticas/organizacao-e-limpeza/pano-e-toalha-de-limpeza|Pano e toalha de limpeza;utilidades-domesticas/organizacao-e-limpeza/saco-de-lixo|Saco de Lixo;utilidades-domesticas/organizacao-e-limpeza/vassoura-rodo-e-acessorio|Vassoura, rodo e acessório;utilidades-domesticas/organizacao-e-limpeza/balde|Balde;utilidades-domesticas/organizacao-e-limpeza/desentupidor|Desentupidor;utilidades-domesticas/organizacao-e-limpeza/caixa-organizadora|Caixa organizadora;utilidades-domesticas/organizacao-e-limpeza/cesto-de-roupa|Cesto de roupa;utilidades-domesticas/organizacao-e-limpeza/lixeira|Lixeira;utilidades-domesticas/organizacao-e-limpeza/carrinho|Carrinho;utilidades-domesticas/organizacao-e-limpeza/escada|Escada;utilidades-domesticas/artigos-para-festa/caixa-termica|Caixa térmica;utilidades-domesticas/artigos-para-festa/artigo-para-festa|Artigo para festa;utilidades-domesticas/cama-mesa-e-banho/cama-mesa-e-banho-diversos|Cama, mesa e banho diversos;eletronicos-e-eletroportateis/eletroportateis/cozinha|Cozinha;eletronicos-e-eletroportateis/eletroportateis/casa|Casa;eletronicos-e-eletroportateis/eletroportateis/beleza|Beleza;eletronicos-e-eletroportateis/eletronicos/som|Som;eletronicos-e-eletroportateis/eletronicos/celular|Celular;descartaveis-e-embalagens/descartaveis/copo-plastico|Copo plástico;descartaveis-e-embalagens/descartaveis/guardanapo|Guardanapo;descartaveis-e-embalagens/descartaveis/papel-filme|Papel filme;descartaveis-e-embalagens/descartaveis/prato|Prato;descartaveis-e-embalagens/descartaveis/talher|Talher;descartaveis-e-embalagens/descartaveis/papel-toalha|Papel toalha;descartaveis-e-embalagens/descartaveis/mascara|Máscara;descartaveis-e-embalagens/descartaveis/palito-de-dente|Palito de dente;descartaveis-e-embalagens/embalagens/embalagem-para-uso-geral|Embalagem para uso geral;descartaveis-e-embalagens/embalagens/embalagem-para-pizza|Embalagem para pizza;papelaria/material-escolar/caneta-giz-de-cera-e-lapis|Caneta, giz de cera e lápis;papelaria/material-escolar/papel-sulfite|Papel sulfite;papelaria/material-escolar/agenda-e-cadernos|Agenda e cadernos;papelaria/material-escolar/tesoura-e-estilete|Tesoura e estilete;papelaria/material-escolar/cola|Cola;papelaria/material-escolar/apontador|Apontador;papelaria/material-escolar/corretivo|Corretivo;papelaria/material-escolar/borracha|Borracha;papelaria/material-escolar/bobina|Bobina;papelaria/material-escolar/estojo|Estojo;papelaria/material-escolar/mochila|Mochila;papelaria/material-escolar/fita-adesiva|Fita adesiva;esporte-e-lazer/jogos-diversos/baralho|Baralho;esporte-e-lazer/jogos-diversos/domino|Dominó;esporte-e-lazer/jogos-diversos/uno|Uno;esporte-e-lazer/barracas-e-acessorios/manta|Manta;esporte-e-lazer/barracas-e-acessorios/travesseiro|Travesseiro;esporte-e-lazer/barracas-e-acessorios/barraca|Barraca;esporte-e-lazer/barracas-e-acessorios/tenda|Tenda;esporte-e-lazer/brinquedos/brinquedo|Brinquedo;esporte-e-lazer/esporte-e-lazer-diversos/piscina|Piscina;esporte-e-lazer/esporte-e-lazer-diversos/bicicleta-adulto|Bicicleta adulto;esporte-e-lazer/esporte-e-lazer-diversos/bicicleta-infantil|Bicicleta infantil;vestuario/roupas-e-calcados/roupa-e-calcado|Roupa e calçado;vestuario/roupas-e-calcados/chinelo|Chinelo;cafeteria/bebidas--cafeteria-/diversos|Diversos;cafeteria/bomboniere/diversos|Diversos;cafeteria/doces/diversos|Diversos;cafeteria/salgados/diversos|Diversos;suplementos-alimentares/vitaminas/suplementos-e-vitaminas|Suplementos e vitaminas;suplementos-alimentares/vitaminas/kit-de-vitaminas-e-suplementos|Kit de vitaminas e suplementos;suplementos-alimentares/massa-muscular/creatina-e-proteinas|Creatina e proteínas;suplementos-alimentares/massa-muscular/pre-e-pos-treino|Pré e pós-treino;suplementos-alimentares/massa-muscular/colageno|Colágeno;suplementos-alimentares/suplementos-alimentares-e-vitaminicos/suplementos-alimentares|Suplementos alimentares;suplementos-alimentares/suplementos-alimentares-e-vitaminicos/suplementos-vitaminicos|Suplementos vitamínicos;drogaria/medicamentos/dor-e-febre|Dor e febre;drogaria/medicamentos/anti-inflamatorios|Anti-inflamatórios;drogaria/medicamentos/estomago-e-digestao|Estômago e digestão;drogaria/medicamentos/relaxantes-musculares|Relaxantes musculares;drogaria/medicamentos/dermatologicos|Dermatológicos;drogaria/medicamentos/garganta|Garganta;drogaria/suplementos-vitaminicos/multivitaminico|Multivitamínico;drogaria/suplementos-vitaminicos/omega|Ômega"

EXCLUIR_PREFIXOS = ("institucional", "atendimento", "fale-conosco", "sobre")

# Fora do escopo do projeto (decisão de out/2026):
#   1. Medicamentos não são comparados num app de compras de supermercado
#      (a folha "dor-e-febre" sozinha teria ~4.9 mil itens).
#   2. Descobrimos em campo que TODOS os slugs de drogaria/ são "fantasma":
#      a árvore lista, mas a busca ignora o path e devolve o catálogo
#      inteiro (~4.873 itens de qualquer departamento). O guarda anti-
#      fantasma abaixo descartaria mesmo assim; excluímos na origem.
# Suplementos de verdade ficam no depto "suplementos-alimentares" (coletado OK).
EXCLUIR_FOLHAS_PREFIXOS = ("drogaria/",)


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _sleep(base: float = 0.35):
    time.sleep(base + random.uniform(0, 0.35))


def criar_sessao():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
        "Referer": SITE + "/",
    })
    log("[sessão] requests puro -> API VTEX direta "
        "(atacadaobr.vtexcommercestable.com.br — sem Cloudflare)")
    return s


# ---------------------------------------------------------------------
# Camada HTTP com retry/backoff + cache-buster obrigatório
# ---------------------------------------------------------------------
def api_get(sess, rota: str, params: dict | None = None, tentativas: int = 3):
    """GET {API}{rota} com _cb (cache-buster), retry e backoff.

    O _cb é OBRIGATÓRIO em toda consulta paginada: o CloudFront da
    VTEX cacheia 5 min por CAMINHO (ignora query string) e, sem ele,
    a página 2+ devolve o corpo da página 1.
    """
    p = dict(params or {})
    p["_cb"] = random.randint(10_000_000, 99_999_999)
    url = API + rota
    for t in range(1, tentativas + 1):
        try:
            r = sess.get(url, params=p, timeout=30)
        except requests.RequestException as e:
            log(f"  [{t}/{tentativas}] rede: {e}")
            time.sleep(3 * t)
            continue
        if r.status_code == 200 or r.status_code == 206:  # 206 = página parcial (normal)
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            esp = min(5 * (2 ** (t - 1)), 60)
            log(f"  [{t}/{tentativas}] HTTP {r.status_code} — backoff {esp}s")
            time.sleep(esp + random.uniform(0, 2))
            continue
        log(f"  [HTTP {r.status_code}] {rota[:100]}")
        if r.status_code in (401, 403):
            log("      acesso negado — improvável neste domínio; "
                "aguarde alguns minutos e rode de novo")
        return None
    return None


def total_do_header(r) -> int | None:
    """Header 'resources' no formato '0-49/542' => 542 (total da consulta)."""
    if r is None:
        return None
    m = RE_RECURSOS.search(r.headers.get("resources", "") or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------
# Árvore de categorias (API pública VTEX) + fallback embutido
# ---------------------------------------------------------------------
def _path_da_url(url: str):
    if not url:
        return None
    path = url.split("://", 1)[-1]
    path = path.split("/", 1)[1] if "/" in path else ""
    path = path.split("?")[0].strip("/")
    segs = [s for s in path.split("/") if s]
    if not segs or any(segs[0].startswith(x) for x in EXCLUIR_PREFIXOS):
        return None
    return "/".join(segs)


def obter_folhas(sess):
    """[(path, nome, id)] das categorias-folha. Live; fallback embutido."""
    r = api_get(sess, "/api/catalog_system/pub/category/tree/3/")
    if r is not None and "json" in r.headers.get("Content-Type", ""):
        try:
            tree = r.json()
        except ValueError:
            tree = None
        if isinstance(tree, list) and tree:
            folhas, vistos = [], set()

            def walk(nodes):
                for n in nodes:
                    filhos = n.get("children") or []
                    if filhos:
                        walk(filhos)
                        continue
                    path = _path_da_url(n.get("url") or "")
                    if path and path not in vistos:
                        vistos.add(path)
                        folhas.append((path, n.get("name") or "", str(n.get("id") or "")))

            walk(tree)
            if folhas:
                return folhas, "árvore ao vivo"
    # fallback embutido (out/2026)
    folhas = []
    for item in FOLHAS_RAW.split(";"):
        if "|" not in item:
            continue
        path, nome = item.split("|", 1)
        folhas.append((path, nome, ""))
    return folhas, "fallback embutido (out/2026)"


# ---------------------------------------------------------------------
# Normalização VTEX -> schema do pi2_mercado (igual Soudaki v2)
# ---------------------------------------------------------------------
def _ean_limpo(v) -> str:
    if not v:
        return ""
    m = RE_EAN.search(str(v))
    return m.group(0) if m else ""


def _apresentacao(nome: str, descricao: str) -> str:
    m = RE_APRES.search(nome or "")
    if m:
        qtd = m.group(1).replace(",", ".")
        try:
            q = float(qtd)
            qtd = str(int(q)) if q.is_integer() else qtd
        except ValueError:
            pass
        un = m.group(2).lower()
        un = {"unid": "un", "unidade": "un", "unidades": "un"}.get(un, un)
        return f"{qtd} {un}"
    desc = re.sub(RE_TAG, " ", descricao or "")
    desc = htmllib.unescape(" ".join(desc.split()))
    return desc[:120]


def _oferta_do_item(it: dict):
    """(preco, regular, disp) do melhor seller do item, ou None."""
    for sl in it.get("sellers") or []:
        off = sl.get("commertialOffer") or {}
        try:
            preco = float(off.get("Price") or 0)
        except (TypeError, ValueError):
            continue
        if preco <= 0:
            continue
        try:
            regular = float(off.get("PriceWithoutDiscount") or off.get("ListPrice") or 0)
        except (TypeError, ValueError):
            regular = 0.0
        if regular <= 0 or regular < preco:
            regular = preco
        disp = bool(off.get("IsAvailable")) or float(off.get("AvailableQuantity") or 0) > 0
        return preco, regular, disp
    return None


# ---------------------------------------------------------------------
# Guarda anti-path-fantasma
# ---------------------------------------------------------------------
def _norm_cat(s: str) -> str:
    """'Carnes, Aves e Peixes'/'carnes-aves-e-peixes' -> 'carnes aves e peixes'.

    Minúsculas, sem acentos, sem pontuação (a VÍRGULA do nome oficial
    'Carnes, aves e peixes' quebraria a comparação com o slug)."""
    s = (s or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9\s]", " ", s)   # hífen/vírgula/ponto -> espaço
    return " ".join(s.split())


def _depto_bate(prod: dict, l1_path: str) -> bool:
    """O produto pertence (em alguma categoria) ao depto do path da folha?"""
    alvo = _norm_cat(l1_path)
    for c in prod.get("categories") or []:
        segs = [x for x in (c or "").split("/") if x]
        if segs and _norm_cat(segs[0]) == alvo:
            return True
    return False


def _eh_fantasma(amostra: list, l1_path: str) -> bool:
    """Folha é path-fantasma se MENOS DA METADE dos produtos pertence
    ao departamento pedido (a VTEX devolve o catálogo geral quando o
    slug não resolve). Categorias pequenas legítimas (1-2 itens que
    pertencem) NÃO são fantasma — por isso a regra é proporcional."""
    if not amostra:
        return False
    batem = sum(1 for pr in amostra if _depto_bate(pr, l1_path))
    return batem * 2 < len(amostra)


def normalizar_produto(prod: dict, folha_path: str, folha_nome: str):
    """Produto VTEX -> registro do schema pi2 (ou None se sem preço)."""
    l1 = folha_path.split("/")[0]
    categoria = DEPTOS.get(l1, l1.replace("-", " ").title())
    nome = (prod.get("productName") or "").strip()
    marca = (prod.get("brand") or "").strip() or "Não Informada"

    escolhido = None   # (item, oferta)
    for it in prod.get("items") or []:
        oferta = _oferta_do_item(it)
        if not oferta:
            continue
        escolhido = (it, oferta)
        if _ean_limpo(it.get("ean")):
            break    # prefere item com EAN

    if not escolhido:
        return None   # sem preço válido (normal quando --sem-fq)
    it, (preco, regular, disp) = escolhido

    promo = round(preco, 2) if preco < regular else None
    img = ""
    for im in it.get("images") or []:
        if isinstance(im, dict) and im.get("imageUrl"):
            img = im["imageUrl"]
            break
    link = (prod.get("link") or "").replace(
        "atacadaobr.vtexcommercestable.com.br", "www.atacadao.com.br")

    return {
        "sku": str(it.get("itemId") or prod.get("productId") or ""),
        "gtin_ean": _ean_limpo(it.get("ean")),
        "nome": nome,
        "marca": marca,
        "categoria": categoria,
        "subsecao": folha_nome,
        "secao": folha_path,
        "apresentacao": _apresentacao(nome, prod.get("description") or ""),
        "imagem_url": img,
        "link": link,
        "preco_regular": round(regular, 2),
        "preco_promocional": promo,
        "em_estoque": disp,
    }


# ---------------------------------------------------------------------
# Coleta de uma folha (paginação _from/_to + total via header)
# ---------------------------------------------------------------------
def buscar_pagina(sess, path: str, offset: int, fq: bool, tamanho: int = TAM_PAGINA):
    params = {
        "map": ",".join(["c"] * (path.count("/") + 1)),
        "_from": offset,
        "_to": offset + tamanho - 1,
    }
    if fq:
        params["fq"] = FQ_DISPONIVEL
    r = api_get(sess, f"/api/catalog_system/pub/products/search/{path}", params)
    if r is None:
        return None, None
    try:
        data = r.json()
    except ValueError:
        return None, None
    if not isinstance(data, list):
        return None, None
    return data, total_do_header(r)


def coletar_folha(sess, path: str, nome: str, max_paginas: int, fq: bool):
    """-> (itens, total, skus) — itens=None indica FALHA de rede/API;
    lista vazia = categoria realmente sem produtos."""
    vistos: dict[str, dict] = {}
    total = None
    offset = 0
    for pag in range(1, max_paginas + 1):
        data, tot = buscar_pagina(sess, path, offset, fq)
        if data is None:
            if pag == 1:
                log(f"  [folha] FALHA na pág 1 de {path} — pulando")
                return None, None, 0
            break
        if total is None:
            total = tot
        if not data:
            break
        if pag == 1:
            # GUARDA ANTI-PATH-FANTASMA: se a maioria dos produtos não
            # pertence ao departamento pedido, o slug não resolveu na busca
            # (a VTEX então devolve o catálogo inteiro). Descarta a folha.
            amostra = data[:10]
            l1 = path.split("/")[0]
            if _eh_fantasma(amostra, l1):
                batem = sum(1 for pr in amostra if _depto_bate(pr, l1))
                log(f"  [folha] ✘ PATH FANTASMA: só {batem}/{len(amostra)} produtos "
                    f"pertencem a '{l1}' — a API devolveu o catálogo geral. "
                    f"Folha descartada.")
                return "FANTASMA", total, 0
        novos = 0
        for prod in data:
            if not isinstance(prod, dict):
                continue
            reg = normalizar_produto(prod, path, nome)
            if reg and reg["sku"] and reg["sku"] not in vistos:
                vistos[reg["sku"]] = reg
                novos += 1
        if pag == 1:
            log(f"  [{path}] total API: {total if total is not None else '?'}"
                f" | pág 1: {len(data)} itens")
        offset += TAM_PAGINA
        if total is not None and offset >= total:
            break
        _sleep()
    return list(vistos.values()), total, len(vistos)


# ---------------------------------------------------------------------
# Saída JSON (merge com execuções anteriores — igual Soudaki v2)
# ---------------------------------------------------------------------
def _carregar(caminho: Path):
    if caminho.exists():
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
    return []


def salvar_saida(todos_por_cat: dict):
    OUT.mkdir(exist_ok=True)
    f_prod = OUT / "produtos_atacadao_full.json"
    f_prec = OUT / "precos_atacadao_full.json"
    prods = {p.get("sku"): p for p in _carregar(f_prod)}
    precs = {p.get("sku"): p for p in _carregar(f_prec)}

    novos_p = novos_c = 0
    for cat, itens in todos_por_cat.items():
        for it in itens:
            sku = it["sku"]
            reg_prod = {
                "sku": sku, "gtin_ean": it["gtin_ean"], "nome": it["nome"],
                "marca": it["marca"], "categoria": it["categoria"],
                "subsecao": it["subsecao"], "secao": it["secao"],
                "apresentacao": it["apresentacao"], "imagem_url": it["imagem_url"],
                "link": it.get("link", ""),
                "relevancia": 10, "data_cadastro": HOJE,
            }
            if sku in prods:
                prods[sku].update({k: v for k, v in reg_prod.items() if v})
            else:
                prods[sku] = reg_prod
                novos_p += 1

            reg_prec = {
                "sku": sku, "gtin_ean": it["gtin_ean"], "nome": it["nome"],
                "preco_regular": it["preco_regular"],
                "preco_promocional": it["preco_promocional"],
                "em_estoque": it["em_estoque"], "data_coleta": HOJE,
            }
            precs[sku] = reg_prec
            novos_c += 1

    f_prod.write_text(json.dumps(list(prods.values()), ensure_ascii=False),
                      encoding="utf-8")
    f_prec.write_text(json.dumps(list(precs.values()), ensure_ascii=False),
                      encoding="utf-8")
    log(f"JSON salvo: {f_prod.name} ({len(prods)} produtos, +{novos_p} novos)")
    log(f"JSON salvo: {f_prec.name} ({len(precs)} preços)")
    com_ean = sum(1 for p in prods.values() if p.get("gtin_ean"))
    if prods:
        log(f"Cobertura EAN: {com_ean}/{len(prods)} ({100.0 * com_ean / len(prods):.1f}%)")
    return f_prod, f_prec


def _checkpoint_ler():
    arq = OUT / "checkpoint_atacadao.json"
    if not arq.exists():
        return set()
    try:
        return set(json.loads(arq.read_text(encoding="utf-8")).get("concluidas", []))
    except (ValueError, OSError):
        return set()


def _checkpoint_gravar(concluidas: set):
    OUT.mkdir(exist_ok=True)
    arq = OUT / "checkpoint_atacadao.json"
    arq.write_text(json.dumps(
        {"quando": HOJE, "concluidas": sorted(concluidas)},
        ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------
# Probe (diagnóstico)
# ---------------------------------------------------------------------
def probe(sess):
    log("== PROBE Atacadão (API VTEX direta) ==")

    folhas, origem = obter_folhas(sess)
    log(f"  categorias-folha: {len(folhas)} ({origem})")

    cat = "padaria-e-matinais/leites/leite-integral"
    log(f"  [paginação] teste em /{cat}/ (catálogo bruto, janelas adjacentes)")
    d1, _ = buscar_pagina(sess, cat, 0, fq=False, tamanho=3)    # itens 1-3
    d2, _ = buscar_pagina(sess, cat, 3, fq=False, tamanho=3)    # itens 4-6
    if d1 is None:
        log("  ❌ API não respondeu — me mande a saída acima")
        return
    ids1 = {p.get("productId") for p in (d1 or [])}
    ids2 = {p.get("productId") for p in (d2 or [])}
    log(f"    _from=0 (itens 1-3): {len(d1 or [])} itens {sorted(ids1)}")
    log(f"    _from=3 (itens 4-6): {len(d2 or [])} itens {sorted(ids2)}")
    if ids1 and ids2 and not (ids1 & ids2):
        log("    ✔ PAGINAÇÃO FUNCIONANDO (lotes distintos + cache-buster OK)")
    elif ids1 and not ids2:
        log("    ✔ paginação OK (2º lote vazio — categoria pequena)")
    else:
        log("    ✘ lotes repetidos — me mande esta saída")

    totais = {}
    for rotulo, fqb in (("com filtro de disponibilidade", True), ("catálogo bruto", False)):
        _, t = buscar_pagina(sess, cat, 0, fq=fqb)
        totais[rotulo] = t
        log(f"    total {rotulo}: {t}")

    itens, total, _ = coletar_folha(sess, cat, "Leite integral", 3, fq=True)
    if itens == "FANTASMA":
        log("  ✘ PATH FANTASMA até em categoria conhecida — me mande esta saída")
    elif itens:
        a = itens[0]
        log(f"  amostra: ean={a['gtin_ean'] or '—'} | regular={a['preco_regular']} | "
            f"promo={a['preco_promocional']} | {a['nome'][:48]}")
        com_ean = sum(1 for i in itens if i["gtin_ean"])
        log(f"  ✔ COLETA OK: {len(itens)} produtos | EAN: {com_ean}/{len(itens)} "
            f"({100.0 * com_ean / len(itens):.0f}%)")
    else:
        log("  ❌ nenhum produto normalizado — me mande esta saída")
    log("== FIM PROBE ==")


def listar_categorias(sess):
    folhas, origem = obter_folhas(sess)
    OUT.mkdir(exist_ok=True)
    destino = OUT / "categorias_atacadao.json"
    destino.write_text(json.dumps(
        [{"path": p, "nome": n, "id": i} for p, n, i in folhas],
        ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{len(folhas)} folhas ({origem}) salvas em {destino.name}:")
    for p, n, _ in folhas:
        print(f"  {p}   ({n})")


# ---------------------------------------------------------------------
# Integração Neon (mesma lógica do Soudaki v2, com LOJA_ID=3)
# ---------------------------------------------------------------------
def integrar_neon(f_prod: Path, f_prec: Path, dry_run: bool):
    raiz_repo = Path(__file__).resolve().parents[2]
    caminho_db = raiz_repo / "webapp" / "backend"
    if not (caminho_db / "db.py").exists():
        log("[ERRO] Este script precisa estar em <repo>/scraper/atacadao/ para "
            "achar webapp/backend/db.py.")
        return
    sys.path.insert(0, str(caminho_db))
    try:
        from db import get_db_connection  # type: ignore
    except ImportError as e:
        log(f"[ERRO] não consegui importar db.py: {e}")
        return

    conn = get_db_connection()
    c = conn.cursor()
    pg = getattr(conn, "is_postgres", True)
    motor = "Neon/Postgres" if pg else "SQLite local"
    log(f"[banco] conectado ({motor})")
    # Nota: os SQLs usam placeholders "?" — o db.py traduz para "?"/%s
    # conforme o motor (funciona no Neon e no SQLite local).

    c.execute("SELECT id, gtin_ean FROM produtos WHERE gtin_ean IS NOT NULL")
    ean_to_id = {r["gtin_ean"]: r["id"] for r in c.fetchall()}
    c.execute("SELECT id, LOWER(TRIM(nome)) AS n FROM produtos")
    nome_to_id = {r["n"]: r["id"] for r in c.fetchall()}

    prods = json.loads(f_prod.read_text(encoding="utf-8"))
    precs = {p.get("sku"): p for p in json.loads(f_prec.read_text(encoding="utf-8"))}

    st = {"match_ean": 0, "match_nome": 0, "novos": 0, "precos": 0}
    for p in prods:
        ean = p.get("gtin_ean")
        nome = (p.get("nome") or "").lower().strip()
        prod_id = ean_to_id.get(ean) if ean else None
        if prod_id:
            st["match_ean"] += 1
        else:
            prod_id = nome_to_id.get(nome)
            if prod_id:
                st["match_nome"] += 1
                if ean and ean not in ean_to_id:
                    if not dry_run:
                        c.execute("UPDATE produtos SET gtin_ean = ? WHERE id = ? "
                                  "AND gtin_ean IS NULL", (ean, prod_id))
                    ean_to_id[ean] = prod_id
        if not prod_id:
            st["novos"] += 1
            if dry_run:
                continue
            busca = f"{p['nome']} {p['marca']} {p['categoria']}".lower()
            c.execute(
                "INSERT INTO produtos (gtin_ean, nome, categoria, marca, relevancia, "
                "imagem_url, apresentacao, busca) VALUES (?,?,?,?,10,?,?,?) "
                "RETURNING id",
                (ean, p["nome"], p["categoria"], p["marca"], p.get("imagem_url"),
                 p.get("apresentacao"), busca))
            prod_id = c.fetchone()["id"]
            nome_to_id[nome] = prod_id
            if ean:
                ean_to_id[ean] = prod_id

        pc = precs.get(p["sku"])
        if not pc:
            continue
        st["precos"] += 1
        if dry_run:
            continue
        c.execute("SELECT id FROM precos WHERE produto_id = ? AND loja_id = ? LIMIT 1",
                  (prod_id, LOJA_ID))
        row = c.fetchone()
        vals = (pc["preco_promocional"], pc["preco_regular"], pc["em_estoque"], HOJE)
        if row:
            c.execute("UPDATE precos SET preco_promocional=?, preco_regular=?, "
                      "em_estoque=?, data_coleta=? WHERE id=?", vals + (row["id"],))
        else:
            c.execute("INSERT INTO precos (produto_id, loja_id, preco_promocional, "
                      "preco_regular, em_estoque, data_coleta) VALUES (?,?,?,?,?,?)",
                      (prod_id, LOJA_ID) + vals)

    if dry_run:
        log(f"[dry-run] nada gravado. Match EAN: {st['match_ean']} | "
            f"Match nome: {st['match_nome']} | Novos: {st['novos']} | "
            f"Preços a gravar: {st['precos']}")
    else:
        conn.connection.commit()
        log(f"[banco] OK — match EAN: {st['match_ean']} | match nome: "
            f"{st['match_nome']} | produtos novos: {st['novos']} | "
            f"preços gravados: {st['precos']}")
    conn.close()


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Coletor Atacadão (API VTEX) v2")
    ap.add_argument("--secao", default=None,
                    help="folha no formato 'mercearia/acucar-e-adocantes/acucar' "
                         "(ou lista separada por vírgula), 'all' para todas")
    ap.add_argument("--max-paginas", type=int, default=MAX_PAGINAS_PADRAO,
                    help=f"trava de páginas de 50 itens por folha "
                         f"(padrão {MAX_PAGINAS_PADRAO})")
    ap.add_argument("--sem-fq", action="store_true",
                    help="desliga o filtro de disponibilidade (mais lento; "
                         "itens sem preço são descartados de qualquer forma)")
    ap.add_argument("--probe", action="store_true",
                    help="só diagnóstico (não salva)")
    ap.add_argument("--listar-categorias", action="store_true",
                    help="lista a árvore de categorias e sai")
    ap.add_argument("--db", action="store_true",
                    help="grava no Neon após coletar")
    ap.add_argument("--integrar", action="store_true",
                    help="não coleta; só integra JSONs existentes no Neon")
    ap.add_argument("--dry-run", action="store_true",
                    help="com --db/--integrar: mostra o que faria, sem gravar")
    args = ap.parse_args()

    sess = criar_sessao()

    if args.probe:
        probe(sess)
        return
    if args.listar_categorias:
        listar_categorias(sess)
        return
    if args.integrar:
        f_prod = OUT / "produtos_atacadao_full.json"
        f_prec = OUT / "precos_atacadao_full.json"
        if not f_prod.exists():
            sys.exit("[ERRO] JSONs não encontrados. Rode uma coleta primeiro.")
        integrar_neon(f_prod, f_prec, args.dry_run)
        return
    if not args.secao:
        ap.print_help()
        sys.exit("\n[ERRO] informe --secao (ex.: padaria-e-matinais/leites/leite-integral), "
                 "'all' ou use --probe / --listar-categorias")

    fq = not args.sem_fq

    if args.secao.strip().lower() == "all":
        folhas, origem = obter_folhas(sess)
        log(f"[árvore] {len(folhas)} folhas ({origem})")
        antes = len(folhas)
        folhas = [f for f in folhas
                  if not f[0].startswith(EXCLUIR_FOLHAS_PREFIXOS)]
        if antes != len(folhas):
            log(f"[escopo] {antes - len(folhas)} folhas excluídas "
                f"({', '.join(EXCLUIR_FOLHAS_PREFIXOS)} — fora do escopo)")
        concluidas = _checkpoint_ler()
        if concluidas:
            log(f"[retomada] {len(concluidas)} folhas já concluídas — pulando")
    else:
        # nomes bonitos das folhas embutidas (quando o path existir lá)
        nomes_embutidos = {}
        for item in FOLHAS_RAW.split(";"):
            if "|" in item:
                pth, nm = item.split("|", 1)
                nomes_embutidos[pth] = nm
        folhas = []
        for c in args.secao.split(","):
            c = c.strip().strip("/")
            if not c:
                continue
            nome = nomes_embutidos.get(c) or c.split("/")[-1].replace("-", " ")
            folhas.append((c, nome, ""))
        concluidas = set()

    pendentes = [(p, n) for p, n, _ in folhas if p not in concluidas]
    log(f"[plano] {len(pendentes)} folhas para coletar | fq={'ON' if fq else 'OFF'} | "
        f"{TAM_PAGINA} itens/página")
    if not pendentes:
        sys.exit("[FIM] todas as folhas já estão no checkpoint. Para recolerar do "
                 "zero, apague output/checkpoint_atacadao.json (e os JSONs, se quiser).")

    resultado: dict[str, list] = {}
    feitas_agora: set[str] = set()
    falhas = []
    fantasmas = []
    try:
        for i, (path, nome) in enumerate(pendentes, 1):
            log(f"[{i}/{len(pendentes)}] {path}")
            try:
                itens, total, _ = coletar_folha(sess, path, nome,
                                                args.max_paginas, fq)
            except Exception as e:
                log(f"  [ERRO] {type(e).__name__}: {e} — seguindo")
                itens = None
            if itens == "FANTASMA":
                fantasmas.append(path)          # não transiente: concluída
                feitas_agora.add(path)
            elif itens is None:
                falhas.append(path)             # falha de rede: NÃO concluída
            else:
                if itens:
                    resultado[path] = itens
                feitas_agora.add(path)          # vazia tb é conclusão (0 produtos)
            if i % CHECKPOINT_A_CADA == 0:
                salvar_saida(resultado)
                _checkpoint_gravar(concluidas | feitas_agora)
                log(f"  [checkpoint] {i}/{len(pendentes)} folhas | "
                    f"falhas até aqui: {len(falhas)}")
            _sleep(0.15)
    except KeyboardInterrupt:
        log("[INTERRUPÇÃO] salvando o que já foi coletado...")
        salvar_saida(resultado)
        _checkpoint_gravar(concluidas | feitas_agora)
        sys.exit("[FIM parcial] rode o mesmo comando depois para retomar.")

    if not resultado and not feitas_agora:
        sys.exit("[FIM] Nada coletado. Rode --probe para diagnosticar.")
    f_prod, f_prec = salvar_saida(resultado)
    _checkpoint_gravar(concluidas | feitas_agora)
    if falhas:
        log(f"[aviso] {len(falhas)} folhas falharam (não marcadas como concluídas): "
            f"{falhas[:5]}{'...' if len(falhas) > 5 else ''}")
    if fantasmas:
        log(f"[aviso] {len(fantasmas)} folha(s) com PATH FANTASMA descartada(s) "
            f"(marcadas como concluídas p/ não repetir): {fantasmas[:5]}")
    if args.db:
        integrar_neon(f_prod, f_prec, args.dry_run)
    log("[FIM] ✔")


if __name__ == "__main__":
    main()
