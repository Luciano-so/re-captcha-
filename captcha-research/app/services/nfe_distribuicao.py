"""Cliente do web service oficial NFeDistribuicaoDFe (Ambiente Nacional).

Caminho AUTORIZADO, sem CAPTCHA, com certificado ICP-Brasil do ATOR da NF-e
(emitente, destinatário, transportador ou autorizado em autXML).
- consChNFe: busca uma NF-e pela chave.
- distNSU: devolve, em sequência, todos os documentos novos do CNPJ.
Destinatário: o procNFe (XML completo) só vem após a manifestação; antes, vem resNFe.
"""
from __future__ import annotations

import base64
import gzip
import re
import ssl
from dataclasses import dataclass, field

import httpx

ENDPOINTS = {
    "1": "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    "2": "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}
NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"


def _envelope(cnpj_cpf: str, cuf_autor: str, tp_amb: str, corpo: str) -> str:
    tag = "CNPJ" if len(cnpj_cpf) == 14 else "CPF"
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope"><soap12:Body>'
        f'<nfeDistDFeInteresse xmlns="{NS_WSDL}"><nfeDadosMsg>'
        '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
        f"<tpAmb>{tp_amb}</tpAmb><cUFAutor>{cuf_autor}</cUFAutor><{tag}>{cnpj_cpf}</{tag}>"
        f"{corpo}</distDFeInt></nfeDadosMsg></nfeDistDFeInteresse></soap12:Body></soap12:Envelope>"
    )


def envelope_chave(chave: str, cnpj_cpf: str, cuf_autor: str, tp_amb: str = "1") -> str:
    return _envelope(cnpj_cpf, cuf_autor, tp_amb, f"<consChNFe><chNFe>{chave}</chNFe></consChNFe>")


def envelope_nsu(ult_nsu: str, cnpj_cpf: str, cuf_autor: str, tp_amb: str = "1") -> str:
    return _envelope(cnpj_cpf, cuf_autor, tp_amb, f"<distNSU><ultNSU>{int(ult_nsu):015d}</ultNSU></distNSU>")


@dataclass
class Documento:
    nsu: str
    schema: str
    xml: str

    @property
    def tipo(self) -> str:
        return self.schema.split("_")[0]  # procNFe, resNFe, procEventoNFe, resEvento

    @property
    def chave(self) -> str | None:
        m = re.search(r"<chNFe>(\d{44})</chNFe>", self.xml) or re.search(r'Id="NFe(\d{44})"', self.xml)
        return m.group(1) if m else None


@dataclass
class DistResult:
    c_stat: str | None
    x_motivo: str | None
    docs: list[Documento] = field(default_factory=list)
    ult_nsu: str | None = None
    max_nsu: str | None = None
    erro: str | None = None

    @property
    def proc_nfe(self) -> str | None:
        return next((d.xml for d in self.docs if d.tipo == "procNFe"), None)


def _tag(xml: str, nome: str) -> str | None:
    m = re.search(rf"<{nome}>([^<]*)</{nome}>", xml)
    return m.group(1) if m else None


def parse_response(xml: str) -> DistResult:
    docs = []
    for attrs, b64 in re.findall(r"<docZip([^>]*)>([^<]+)</docZip>", xml):
        nsu = re.search(r'NSU="(\d+)"', attrs)
        schema = re.search(r'schema="([^"]+)"', attrs)
        docs.append(Documento(nsu.group(1) if nsu else "", schema.group(1) if schema else "",
                              gzip.decompress(base64.b64decode(b64)).decode("utf-8")))
    return DistResult(_tag(xml, "cStat"), _tag(xml, "xMotivo"), docs,
                      _tag(xml, "ultNSU"), _tag(xml, "maxNSU"))


def enviar(envelope: str, ssl_ctx: ssl.SSLContext, tp_amb: str = "1", timeout: float = 30) -> DistResult:
    try:
        r = httpx.post(ENDPOINTS[tp_amb], content=envelope.encode(),
                       headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                       verify=ssl_ctx, timeout=timeout)
    except httpx.HTTPError as e:
        return DistResult(None, None, erro=f"{type(e).__name__}: {str(e)[:200]}")
    res = parse_response(r.text)
    if res.c_stat is None:
        res.erro = f"HTTP {r.status_code} sem cStat"
    return res
