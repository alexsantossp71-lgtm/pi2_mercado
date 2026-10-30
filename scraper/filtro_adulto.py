# -*- coding: utf-8 -*-
"""
Filtro de produtos adultos / sex shop — Dispensa Planejada.

O comparador de preços é um projeto acadêmico de mercado popular: produtos de
sex shop não fazem sentido no catálogo e poluem a busca (ex.: buscar "gel"
retornava "Gel Excitante"). Este módulo centraliza o bloqueio usado em TODA a
pipeline:

  - scraper/secoes/coletor_vtex.py  (coleta Carrefour / Atacadão)
  - webapp/backend/importar_json_para_sqlite.py  (ETL SQLite -> Neon)

Critérios, em duas camadas:
  1. SEÇÃO adulta ("Cuidados Sexuais", "Sex Shop"...) -> bloqueia qualquer
     produto da seção, mesmo com nome neutro ("Gel Comestível Morango");
  2. NOME/MARCA com termo ou marca inequivocamente adulta -> bloqueia o item
     mesmo quando ele foi alocado em seção comum (ex.: gel Intt em Higiene).

Lições aprendidas com falsos positivos REAIS da base (não bloquear):
  - "Abelha Rainha" é marca de COSMÉTICOS populares (sabonete, creme de pés,
    protetor solar, desodorante). Só a linha adulta dela é bloqueada, pelo
    nome "Secret Sexy";
  - "sexua" em NOME pega "Bissexual" (bandeira LGBT) e o perfume "Sexual"
    (Michel Germain) — por isso 'sexua' só vale para SEÇÃO;
  - "nipple" pega protetor de mamilo para AMAMENTAÇÃO (Mam Nipple Shields,
    Bella B Nipple Nurture Butter) — adultos já caem por "pasties";
  - "sexy" genérico: Sexyhair (shampoo), vinho Sexy Fish, gel de banho
    Playboy "Play It Sexy" — legítimos;
  - "lubrificante", "prazer", "sensual": camisinha Jontex/Blowtex, lubrificantes
    de farmácia, perfumes "Sensual" — itens normais;
  - "algema" com fronteira de palavra: preserva o gel de banho "Algemarin"
    (algas marinhas);
  - "sexo" em nome pega o livro "As Willis - Sexo, Morte E Escaravelhos".
"""

import re
import unicodedata

# --- Camada 1: seções/categorias inequivocamente adultas -------------------
_PADROES_SECAO = [
    r"sexua",        # Cuidados Sexuais / Sexuais (plural perde o L) / Sex Shop
    r"sex shop",
    r"sexshop",
    r"erot",         # seção "Eróticos"
]

# --- Camada 2: nome/marca inequivocamente adultos ---------------------------
_PADROES_NOME = [
    r"secret sexy",               # linha adulta da Abelha Rainha
    r"hot flowers",               # marca adulta (sprays e geis)
    r"intt",                      # marca adulta Intt (Inttimus, Eros Intt, Wellness)
    r"lovetoy",                   # Lovetoy / Lovetoys (exceto coletor menstrual, abaixo)
    r"la pimienta",               # marca adulta
    r"adao e eva",                # marca adulta (rede de sex shops)
    r"erot",                      # erótico/erótica em nome de produto
    r"vibrador",
    r"excitante",                 # gel excitante feminino/masculino
    r"despedida de solteiro",
    r"\balgemas?\b",              # algema/algemas — NÃO pega "Algemarin"
    r"vela beij",                 # vela beijável
    r"beijavel",                  # gel/vela beijável
    r"pasties",                   # adesivo para mamilos
    r"orgastic",
    r"pussy",
    r"penian",                    # anel/bomba/aumento peniano
    r"\bpenis\b",                 # pênis (normalizado sem acento)
    r"plug anal",
    r"dildo",
]

_RE_SECAO = re.compile("|".join(_PADROES_SECAO), re.IGNORECASE)
_RE_NOME = re.compile("|".join(_PADROES_NOME), re.IGNORECASE)

# Exceções: marca adulta, mas produto de higiene/saúde que deve PERMANECER
# (avaliado antes do bloqueio).
_EXCECOES_HIGIENE = re.compile(r"coletores? menstrua", re.IGNORECASE)


def _normalizar(texto: str) -> str:
    """Minúsculas + remove acentos (NFD), para casar 'Erótico' == 'erotico'."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def eh_produto_bloqueado(nome: str = "", marca: str = "", secao: str = "") -> bool:
    """True se a seção for adulta ou se nome/marca indicarem produto sex shop."""
    if _EXCECOES_HIGIENE.search(_normalizar(nome)):
        return False
    if _RE_SECAO.search(_normalizar(secao)):
        return True
    return bool(_RE_NOME.search(" ".join((_normalizar(nome), _normalizar(marca)))))
