"""Gravação dos documentos em downloads/<cnpj_cliente>/ e geração do DANFE."""
from __future__ import annotations

import logging
from pathlib import Path

from app.services import danfe
from app.services.nfe_distribuicao import Documento

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
PASTA_PADRAO = ROOT / "downloads"


def pasta_cliente(cnpj_cpf: str, base: Path = PASTA_PADRAO) -> Path:
    p = base / cnpj_cpf
    p.mkdir(parents=True, exist_ok=True)
    return p


def caminho_xml(pasta: Path, chave: str) -> Path:
    return pasta / f"{chave}-procNFe.xml"


def salvar(doc: Documento, pasta: Path, gerar_pdf: bool = True) -> dict[str, str]:
    """Salva um documento; para procNFe também gera o PDF. Retorna os caminhos gravados."""
    chave = doc.chave or f"nsu{doc.nsu}"
    if doc.tipo == "procNFe":
        xml_path = caminho_xml(pasta, chave)
    elif doc.tipo == "resNFe":
        xml_path = pasta / f"{chave}-resNFe.xml"
    else:  # eventos: vários por nota
        xml_path = pasta / "eventos" / f"{chave}-{doc.tipo}-{doc.nsu}.xml"
        xml_path.parent.mkdir(exist_ok=True)
    xml_path.write_text(doc.xml, encoding="utf-8")
    out = {"xml": str(xml_path)}
    if doc.tipo == "procNFe" and gerar_pdf:
        try:
            out["pdf"] = str(danfe.gerar_danfe(doc.xml, pasta / f"{chave}-danfe.pdf"))
        except Exception as e:
            log.warning("DANFE não gerado para %s: %s", chave, e)
            out["pdf_erro"] = str(e)
    return out
