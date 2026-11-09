"""Gera o DANFE (PDF) localmente a partir do XML procNFe, com a biblioteca open source brazilfiscalreport."""
from __future__ import annotations

from pathlib import Path


def gerar_danfe(xml: str, destino: Path) -> Path:
    try:
        from brazilfiscalreport.danfe import Danfe
    except ImportError as e:
        raise RuntimeError("Instale: pip install brazilfiscalreport") from e
    destino.parent.mkdir(parents=True, exist_ok=True)
    Danfe(xml=xml.encode("utf-8")).output(str(destino))
    return destino
