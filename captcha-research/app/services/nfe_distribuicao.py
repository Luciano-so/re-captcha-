"""Download do XML da NF-e pelo web service oficial NFeDistribuicaoDFe (Ambiente Nacional).

Caminho AUTORIZADO, sem CAPTCHA. Requisitos:
- Certificado ICP-Brasil (PEM) do CNPJ/CPF que é ATOR da NF-e
  (emitente, destinatário, transportador ou autorizado em autXML).
- Destinatário: o XML completo (procNFe) só vem após a manifestação
  (ex.: Ciência da Operação). Antes disso o retorno é apenas resNFe (resumo).
"""
from __future__ import annotations

import base64
import gzip
import re
from dataclasses import dataclass, field

import httpx

ENDPOINTS = {
    "1": "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    "2": "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}
NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"


def build_envelope(chave: str, cnpj_cpf: str, cuf_autor: str, tp_amb: str = "1") -> str:
    doc_tag = "CNPJ" if len(cnpj_cpf) == 14 else "CPF"
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope"><soap12:Body>'
        f'<nfeDistDFeInteresse xmlns="{NS_WSDL}"><nfeDadosMsg>'
        '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
        f"<tpAmb>{tp_amb}</tpAmb><cUFAutor>{cuf_autor}</cUFAutor>"
        f"<{doc_tag}>{cnpj_cpf}</{doc_tag}>"
        f"<consChNFe><chNFe>{chave}</chNFe></consChNFe>"
        "</distDFeInt></nfeDadosMsg></nfeDistDFeInteresse></soap12:Body></soap12:Envelope>"
    )


@dataclass
class DistResult:
    c_stat: str | None
    x_motivo: str | None
    docs: list[tuple[str, str]] = field(default_factory=list)  # (schema, xml)
    erro: str | None = None

    @property
    def proc_nfe(self) -> str | None:
        return next((x for s, x in self.docs if s.startswith("procNFe")), None)


def parse_response(xml: str) -> DistResult:
    c_stat = re.search(r"<cStat>(\d+)</cStat>", xml)
    x_motivo = re.search(r"<xMotivo>([^<]*)</xMotivo>", xml)
    docs = [
        (schema, gzip.decompress(base64.b64decode(b64)).decode("utf-8"))
        for schema, b64 in re.findall(r'<docZip[^>]*schema="([^"]+)"[^>]*>([^<]+)</docZip>', xml)
    ]
    return DistResult(c_stat.group(1) if c_stat else None,
                      x_motivo.group(1) if x_motivo else None, docs)


def baixar_xml(chave: str, cnpj_cpf: str, cuf_autor: str, cert_pem: str, key_pem: str,
               tp_amb: str = "1", verify: str | bool = True, timeout: float = 30) -> DistResult:
    try:
        r = httpx.post(
            ENDPOINTS[tp_amb],
            content=build_envelope(chave, cnpj_cpf, cuf_autor, tp_amb).encode(),
            headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            cert=(cert_pem, key_pem), verify=verify, timeout=timeout,
        )
    except httpx.HTTPError as e:
        return DistResult(None, None, erro=f"{type(e).__name__}: {str(e)[:200]}")
    res = parse_response(r.text)
    if res.c_stat is None:
        res.erro = f"HTTP {r.status_code} sem cStat"
    return res
