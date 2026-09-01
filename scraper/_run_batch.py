# -*- coding: utf-8 -*-
"""
Driver resiliente para coleta CEP-fallback (1 preco/loja) do universo completo
de EANs em Atacadao, Carrefour e Pao de Acucar.

Reutiliza a logica de store do modulo recoletar_por_ean (coletar_loja), mas:
  - Desativa o Playwright do Carrefour (DISABLE_CARREFOUR_PLAYWRIGHT=1).
  - Aplica timeout por loja (nao existe no script original).
  - Grava em arquivos atomicos (temp + os.replace) para evitar corrupcao.
  - Processa em lotes retomaveis: pula EANs ja presentes nas 3 lojas.
  - Faz a "early coverage probe" apos o 1o lote e para se cobertura < 2%.
  - Escreve progress log e, ao fim, _scrape_done.json.

Escrito por: worker da Task 5.
"""
import os
import sys
import json
import time
import datetime
import tempfile
import concurrent.futures

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# Kill-switch: nunca dispara Playwright no bulk.
os.environ["DISABLE_CARREFOUR_PLAYWRIGHT"] = "1"

import recoletar_por_ean as recoleta

recoleta.HOJE = datetime.date.today().isoformat()
recoleta.TIMEOUT = int(os.environ.get("RECOLETA_TIMEOUT", "12"))

LOJAS = tuple(recoleta.ARQUIVOS.keys())

# Saidas no ROOT do projeto (mesmo do script original)
ARQUIVOS = recoleta.ARQUIVOS

UNIVERSO = os.environ.get("UNIVERSO_FILE") or os.path.join(BASE, "eans_todas.txt")
PROGRESS_LOG = os.path.join(BASE, "_scrape_progress.log")
DONE_FILE = os.path.join(BASE, "_scrape_done.json")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))
FLUSH = int(os.environ.get("FLUSH", "25"))
STORE_TIMEOUT = int(os.environ.get("EAN_STORE_TIMEOUT", "40"))
DELAY = float(os.environ.get("SCRAPE_DELAY", "0.3"))
MAX_EANS = int(os.environ.get("MAX_EANS", "0"))  # 0 = todos
PROBE_THRESHOLD = float(os.environ.get("PROBE_THRESHOLD", "2.0"))  # % minima


# ---------------------------------------------------------------------------
# Escrita atomica (evita corromper JSON se o processo for morto)
# ---------------------------------------------------------------------------
def _atomic_salvar(caminho, dados):
    d = os.path.dirname(caminho) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
        os.replace(tmp, caminho)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def carregar_todos():
    return {l: recoleta.carregar_por_ean(ARQUIVOS[l]) for l in LOJAS}


def salvar_todos(atual):
    for l in LOJAS:
        _atomic_salvar(ARQUIVOS[l], list(atual[l].values()))


# ---------------------------------------------------------------------------
# Coleta com timeout por loja
# ---------------------------------------------------------------------------
def coletar_com_timeout(loja, ean):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(recoleta.coletar_loja, loja, ean)
        try:
            return fut.result(timeout=STORE_TIMEOUT)
        except concurrent.futures.TimeoutError:
            return recoleta.registro_indisponivel(loja, ean, "timeout_coleta")
        except Exception as err:  # noqa
            return recoleta.registro_indisponivel(loja, ean, f"erro:{type(err).__name__}")


# ---------------------------------------------------------------------------
# Probe de conectividade
# ---------------------------------------------------------------------------
def rede_bloqueada():
    import requests
    headers = recoleta.HEADERS
    ok = False
    for host in ("https://www.atacadao.com.br", "https://www.paodeacucar.com"):
        try:
            r = requests.get(host, timeout=12, headers=headers)
            if r.status_code < 500:
                ok = True
        except Exception:
            pass
    return not ok


# ---------------------------------------------------------------------------
# Log de progresso
# ---------------------------------------------------------------------------
def append_log(linha):
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Reset log no inicio de um run fresco (so se vazio/inexistente)
    if not os.path.exists(PROGRESS_LOG):
        with open(PROGRESS_LOG, "w", encoding="utf-8") as f:
            f.write("# scrape progress log\n")

    # Carrega universo
    with open(UNIVERSO, "r", encoding="utf-8") as f:
        universo = [l.strip() for l in f if l.strip()]
    # mantem apenas validos e unicos; EANs realistas (7/8/9) primeiro p/ probe valido
    seen = set()
    eans = []
    for e in universo:
        if recoleta.ean_valido(e) and e not in seen:
            seen.add(e)
            eans.append(e)
    eans.sort(key=lambda e: (0 if e[0] in "789" else 1, e))
    if MAX_EANS:
        eans = eans[:MAX_EANS]

    total_eans = len(eans)
    append_log(f"[{_ts()}] INICIO run: {total_eans} EANs no universo | batch={BATCH_SIZE} flush={FLUSH} store_timeout={STORE_TIMEOUT}s delay={DELAY}s")

    if rede_bloqueada():
        msg = "REDE BLOQUEADA: homepages dos supermercados inalcanzaveis. Encerrando."
        append_log(f"[{_ts()}] {msg}")
        write_done(stopped=True, motivo="rede_bloqueada", total_eans=total_eans,
                   com_preco=0, per_store={}, coverage=0.0,
                   observacoes=[msg])
        return

    atual = carregar_todos()
    total_com_preco = 0
    per_store_cum = {l: 0 for l in LOJAS}
    ja_existentes = 0
    processados = 0
    probe_feito = False
    erros_conexao = 0
    tentativas_loja = 0
    inicio = time.time()

    n_batches = (total_eans + BATCH_SIZE - 1) // BATCH_SIZE
    universo_set = set(eans)

    def em_estoque_any(ean):
        return any(atual[l].get(ean, {}).get("em_estoque") for l in LOJAS)

    def cobertura_sobre(lista):
        if not lista:
            return 0, 0
        c = sum(1 for e in lista if em_estoque_any(e))
        return c, len(lista)

    for bi in range(n_batches):
        start = bi * BATCH_SIZE
        end = min(start + BATCH_SIZE, total_eans)
        lote = eans[start:end]
        lote_erros = 0
        lote_tent = 0
        for ean in lote:
            # pula se ja tem registro nas 3 lojas (retomabilidade)
            if all(ean in atual[l] for l in LOJAS):
                ja_existentes += 1
                continue
            for l in LOJAS:
                existente = atual[l].get(ean)
                # preserva preco real ja existente; so recoleta se faltar ou indisponivel
                if existente and existente.get("em_estoque"):
                    continue
                reg = coletar_com_timeout(l, ean)
                atual[l][ean] = reg
                lote_tent += 1
                obs = reg.get("observacao", "")
                if obs.startswith("erro:") or obs == "timeout_coleta":
                    lote_erros += 1
            processados += 1
            # flush periodico
            if processados % FLUSH == 0:
                salvar_todos(atual)

        salvar_todos(atual)
        c_lote, n_lote = cobertura_sobre(lote)
        cobertura_lote = (c_lote / n_lote * 100.0) if n_lote else 0.0
        erros_conexao += lote_erros
        tentativas_loja += lote_tent
        cum_proc = processados + ja_existentes
        append_log(
            f"[{_ts()}] batch {bi+1}/{n_batches} | lote={len(lote)} "
            f"| lote_com_preco={c_lote} ({cobertura_lote:.1f}%) "
            f"| cum_processados={cum_proc}/{total_eans} "
            f"| lote_erros={lote_erros}"
        )

        # EARLY COVERAGE PROBE apos o 1o lote (lote realista, por ordem)
        if not probe_feito:
            probe_feito = True
            pc, pn = cobertura_sobre(lote)
            probe_cov = (pc / pn * 100.0) if pn else 0.0
            if probe_cov < PROBE_THRESHOLD:
                motivo = (f"EARLY PROBE: cobertura {probe_cov:.1f}% < {PROBE_THRESHOLD:.0f}% "
                          f"apos 1o lote. Universo de EANs aparenta ser placeholder/nao-real "
                          f"(ex.: 0000000000352). Encerrando para troca de fonte de EAN.")
                append_log(f"[{_ts()}] {motivo}")
                elapsed = time.time() - inicio
                write_done(stopped=True, motivo="early_probe_cobertura_baixa",
                           total_eans=total_eans, processados=processados,
                           ja_existentes=ja_existentes,
                           com_preco=pc, per_store={l: 0 for l in LOJAS},
                           coverage=probe_cov, elapsed=elapsed,
                           observacoes=[motivo,
                                        f"erros_conexao_total={erros_conexao}",
                                        f"tentativas_loja_total={tentativas_loja}"])
                return

    # Totais finais computados a partir dos arquivos (inclui preservados)
    per_store_final = {l: sum(1 for r in atual[l].values() if r.get("em_estoque")) for l in LOJAS}
    com_preco_final = sum(1 for e in universo_set if em_estoque_any(e))
    elapsed = time.time() - inicio
    coverage = (com_preco_final / total_eans * 100.0) if total_eans else 0.0
    append_log(f"[{_ts()}] FIM run: processados={processados} ja_existentes={ja_existentes} "
               f"com_preco={com_preco_final} coverage={coverage:.1f}% elapsed={elapsed:.0f}s")
    write_done(stopped=False, motivo="concluido",
               total_eans=total_eans, processados=processados,
               ja_existentes=ja_existentes, com_preco=com_preco_final,
               per_store=per_store_final, coverage=coverage, elapsed=elapsed,
               observacoes=[f"erros_conexao_total={erros_conexao}",
                            f"tentativas_loja_total={tentativas_loja}"])


def _ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_done(stopped, motivo, total_eans, com_preco=0, per_store=None,
               coverage=0.0, elapsed=0.0, observacoes=None, processados=0,
               ja_existentes=0):
    per_store = per_store or {l: 0 for l in LOJAS}
    done = {
        "total_eans_attempted": total_eans,
        "total_processed_this_run": processados,
        "total_already_present": ja_existentes,
        "total_with_at_least_one_real_price": com_preco,
        "per_store_em_estoque_counts": per_store,
        "coverage_pct": round(coverage, 2),
        "early_probe_triggered_stop": stopped and motivo.startswith("early_probe"),
        "stopped": stopped,
        "motivo": motivo,
        "elapsed_seconds": round(elapsed, 1),
        "observacoes": observacoes or [],
        "finished_at": datetime.datetime.now().isoformat(),
    }
    with open(DONE_FILE, "w", encoding="utf-8") as f:
        json.dump(done, f, indent=2, ensure_ascii=False)
    append_log(f"[{_ts()}] ESCREVEU {os.path.basename(DONE_FILE)}: stopped={stopped} cov={coverage:.1f}%")


if __name__ == "__main__":
    main()
