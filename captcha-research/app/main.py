"""Uso:
  python -m app.main --portal nfe [--portal sefaz-mt] [--headless] [--ai]   # pesquisa de portal/CAPTCHA
  python -m app.main --lote input/chaves.txt                                 # baixa XML/PDF de uma lista
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from app.agents.research_agent import run
from app.portals import PORTALS
from app.services.consulta_service import ROOT

DEFAULT_CHAVE = "3526 0353 5656 6300 0209 5542 0000 0189 1811 1548 5768"


def executar_lote(arquivo: Path) -> None:
    from app.services.nfe_lote import NfeConfig, buscar_notas, ler_chaves

    try:
        cfg = NfeConfig.from_env()
    except ValueError as e:
        raise SystemExit(f"Erro: {e}")
    resultados = buscar_notas(ler_chaves(arquivo), cfg)
    saida = ROOT / "reports" / f"lote_{datetime.now():%Y%m%d_%H%M%S}.json"
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps([r.model_dump(mode="json") for r in resultados],
                                ensure_ascii=False, indent=2), encoding="utf-8")
    for r in resultados:
        print(f"{r.chave}  {r.status.value:<15} {r.c_stat or '':<4} {r.mensagem}")
    print(f"\nResumo salvo em {saida}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Pesquisa de CAPTCHA e consulta oficial de NF-e")
    p.add_argument("--lote", type=Path, help="arquivo com uma chave por linha (ou CSV, 1ª coluna)")
    p.add_argument("--portal", action="append", choices=sorted(PORTALS), help="repetível")
    p.add_argument("--chave", default=os.getenv("NFE_CHAVE", DEFAULT_CHAVE))
    p.add_argument("--headless", action="store_true", help="padrão: navegador visível")
    p.add_argument("--ai", action="store_true", help="usar Browser Use (requer chave de LLM)")
    a = p.parse_args()

    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(ROOT / "logs" / "run.log", encoding="utf-8"), logging.StreamHandler()],
    )
    if a.lote:
        executar_lote(a.lote)
        return
    for path in asyncio.run(run(a.chave, a.portal or ["nfe"], a.headless, a.ai)):
        print(f"\n===== {path.name} =====\n{path.read_text(encoding='utf-8')}")


if __name__ == "__main__":
    main()
