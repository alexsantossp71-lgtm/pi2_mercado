# -*- coding: utf-8 -*-
"""
Pipeline completa: roda todos os scrapers + consolidação.
Executa em sequência, retoma de checkpoints, e reporta status final.
Com logs melhorados a cada 10 segundos no máximo.
"""

import os
import sys
import time
import json
import traceback
import threading
from datetime import datetime


BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(BASE))
os.chdir(PROJECT)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

LOG_FILE = os.path.join(BASE, "pipeline_log.txt")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_with_heartbeat(name, func, interval=10):
    log(f"=== INICIO: {name} ===")
    t0 = time.time()
    done = threading.Event()

    def heartbeat():
        while not done.is_set():
            elapsed = time.time() - t0
            log(f"[ANDAMENTO] {name} ainda rodando... ({elapsed:.0f}s decorridos)")
            done.wait(interval)

    hb_thread = threading.Thread(target=heartbeat, daemon=True)
    hb_thread.start()

    try:
        func()
        done.set()
        elapsed = time.time() - t0
        log(f"=== FIM: {name} ({elapsed:.0f}s) ===")
        return True
    except Exception as e:
        done.set()
        elapsed = time.time() - t0
        log(f"=== ERRO: {name} ({elapsed:.0f}s) - {e} ===")
        traceback.print_exc()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        return False


# --- Step 1: Gerar folhas ---
def step_gerar_folhas():
    from gerar_folhas import main as gerar
    gerar()


# --- Step 2: Carrefour ---
def step_carrefour():
    from coletar_carrefour import main as coletar
    coletar()


# --- Step 3: Atacadão ---
def step_atacadao():
    from coletar_atacadao import main as coletar
    coletar()


# --- Step 4: Pão de Açúcar ---
def step_pa():
    from coletar_pa import main as coletar
    coletar()


# --- Step 5: Soudaki bebidas ---
def step_soudaki():
    sys.path.insert(0, BASE)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "coletar_daki_bebidas",
        os.path.join(BASE, "coletar_daki_bebidas.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, 'main'):
        mod.main()
    elif hasattr(mod, 'coletar'):
        mod.coletar()
    else:
        log("coletar_daki_bebidas: funcao main/coletar nao encontrada, executando direto")
        exec(open(os.path.join(BASE, "coletar_daki_bebidas.py"), encoding="utf-8").read())


# --- Step 6: Consolidação ---
def step_consolidar():
    from consolidar import main as consolidar
    consolidar()


# --- Step 7: Verificação ---
def step_verificar():
    import glob as globmod
    log("=== VERIFICACAO FINAL ===")

    files = {
        "Carrefour precos": os.path.join(PROJECT, "scraper", "precos_carrefour_ampliado.json"),
        "Carrefour produtos": os.path.join(PROJECT, "scraper", "produtos_ampliado.json"),
        "Atacadão precos": os.path.join(PROJECT, "scraper", "precos_atacadao_ampliado.json"),
        "Atacadão produtos": os.path.join(PROJECT, "scraper", "produtos_atacadao.json"),
        "PA precos": os.path.join(PROJECT, "scraper", "precos_pao_de_acucar_ampliado.json"),
        "PA produtos": os.path.join(PROJECT, "scraper", "produtos_pao_de_acucar.json"),
        "Soudaki precos": os.path.join(PROJECT, "scraper", "precos_daki_bebidas_ampliado.json"),
        "Soudaki produtos": os.path.join(PROJECT, "scraper", "produtos_daki_bebidas.json"),
        "Consolidado precos": os.path.join(PROJECT, "scraper", "precos_unificados.json"),
        "Consolidado produtos": os.path.join(PROJECT, "scraper", "produtos_consolidados.json"),
    }

    total_precos = 0
    total_produtos = 0
    for name, path in files.items():
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    count = len(data) if isinstance(data, (list, dict)) else 0
                    log(f"  [OK] {name}: {count} registros ({os.path.getsize(path)/1024:.1f} KB)")
                    if "precos" in name.lower():
                        total_precos += count
                    elif "produtos" in name.lower():
                        total_produtos += count
            except Exception as e:
                log(f"  [ERRO] {name}: falha ao ler JSON - {e}")
        else:
            log(f"  [AVISO] {name}: arquivo nao encontrado ({path})")

    log(f"  TOTAL precos unicos: {total_precos}")
    log(f"  TOTAL produtos unicos: {total_produtos}")

    parciais = globmod.glob(os.path.join(PROJECT, "scraper", "*.parcial"))
    if parciais:
        log(f"  ATENCAO: {len(parciais)} arquivo(s) .parcial restante(s)")
        for p in parciais:
            log(f"    {os.path.basename(p)}: {os.path.getsize(p):,} bytes")
    else:
        log("  Nenhum arquivo .parcial restante (limpo)")

    progressos = globmod.glob(os.path.join(PROJECT, "scraper", "*.progresso.json"))
    if progressos:
        log(f"  ATENCAO: {len(progressos)} arquivo(s) .progresso.json restante(s)")

    log("=== PIPELINE COMPLETA ===")


def main():
    log("==================================================")
    log("INICIANDO PIPELINE COMPLETA DE POPULACAO DO BANCO")
    log("==================================================")

    steps = [
        ("Gerar folhas", step_gerar_folhas),
        ("Carrefour VTEX", step_carrefour),
        ("Atacadão VTEX", step_atacadao),
        ("Pão de Açúcar GPA", step_pa),
        ("Soudaki bebidas", step_soudaki),
        ("Consolidação", step_consolidar),
        ("Verificação", step_verificar),
    ]

    success_count = 0
    start_total = time.time()

    for name, func in steps:
        ok = run_with_heartbeat(name, func, interval=10)
        if ok:
            success_count += 1
        else:
            log(f"AVISO: {name} falhou ou gerou erro. Prosseguindo...")

    elapsed_total = time.time() - start_total
    log("")

    log("=" * 60)
    log(f"RESUMO FINAL ({elapsed_total/60:.1f} minutos)")
    log("=" * 60)
    for name, ok in steps:
        status = "OK" if ok else "FALHOU"
        log(f"  {name}: {status}")

    log("=" * 60)
    log(f"Tempo total: {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")
    log("Pipeline concluída.")


if __name__ == "__main__":
    main()