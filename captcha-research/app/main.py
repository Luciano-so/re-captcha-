"""Uso: python -m app.main --portal nfe [--portal sefaz-mt] [--headless] [--ai]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv

from app.agents.research_agent import run
from app.portals import PORTALS
from app.services.consulta_service import ROOT

DEFAULT_CHAVE = "3526 0353 5656 6300 0209 5542 0000 0189 1811 1548 5768"


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Pesquisa de CAPTCHA e alternativas oficiais (NF-e)")
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
    for path in asyncio.run(run(a.chave, a.portal or ["nfe"], a.headless, a.ai)):
        print(f"\n===== {path.name} =====\n{path.read_text(encoding='utf-8')}")


if __name__ == "__main__":
    main()
