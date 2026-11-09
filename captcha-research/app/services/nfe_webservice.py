"""Cliente do web service oficial NFeConsultaProtocolo4 (SOAP 1.2, TLS mútuo).

Caminho AUTORIZADO, sem CAPTCHA: exige certificado digital ICP-Brasil do usuário.
O certificado A1 (.pfx) deve ser convertido para PEM (cert + chave), ex.:
  openssl pkcs12 -in cert.pfx -out cert.pem -clcerts -nokeys
  openssl pkcs12 -in cert.pfx -out key.pem -nocerts -nodes
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeConsultaProtocolo4"


def build_envelope(chave: str, tp_amb: str = "1") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
        f'<soap12:Body><nfeDadosMsg xmlns="{NS_WSDL}">'
        '<consSitNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
        f"<tpAmb>{tp_amb}</tpAmb><xServ>CONSULTAR</xServ><chNFe>{chave}</chNFe>"
        "</consSitNFe></nfeDadosMsg></soap12:Body></soap12:Envelope>"
    )


@dataclass
class WsResult:
    ok: bool
    c_stat: str | None = None
    x_motivo: str | None = None
    detalhe: str = ""
    n_prot: str | None = None
    dh_recbto: str | None = None
    c_stat_nota: str | None = None
    eventos: int = 0
    raw: str = ""


def parse_response(xml: str) -> WsResult:
    """O cStat/xMotivo do retorno é o primeiro; o da nota fica dentro de <protNFe>."""
    c_stat = re.search(r"<cStat>(\d+)</cStat>", xml)
    x_motivo = re.search(r"<xMotivo>([^<]*)</xMotivo>", xml)
    prot = re.search(r"<protNFe.*?</protNFe>", xml, re.S)
    p = prot.group(0) if prot else ""
    return WsResult(
        ok=bool(c_stat),
        c_stat=c_stat.group(1) if c_stat else None,
        x_motivo=x_motivo.group(1) if x_motivo else None,
        detalhe="" if c_stat else "Resposta sem cStat",
        n_prot=(re.search(r"<nProt>(\d+)</nProt>", p) or [None, None])[1],
        dh_recbto=(re.search(r"<dhRecbto>([^<]+)</dhRecbto>", p) or [None, None])[1],
        c_stat_nota=(re.search(r"<cStat>(\d+)</cStat>", p) or [None, None])[1],
        eventos=len(re.findall(r"<procEventoNFe", xml)),
    )


def probe(endpoint: str, timeout: float = 15) -> str:
    """Verifica apenas se o endpoint responde (sem certificado). Não consulta nada."""
    try:
        r = httpx.get(endpoint + "?wsdl", timeout=timeout)
        return f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        return f"{type(e).__name__} (esperado sem certificado cliente): {str(e)[:120]}"


def consultar(endpoint: str, chave: str, ssl_ctx, tp_amb: str = "1", timeout: float = 30) -> WsResult:
    """ssl_ctx: SSLContext com o certificado do cliente (app.services.certificados)."""
    try:
        r = httpx.post(
            endpoint,
            content=build_envelope(chave, tp_amb).encode(),
            headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            verify=ssl_ctx,
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        return WsResult(ok=False, detalhe=f"{type(e).__name__}: {str(e)[:200]}")
    res = parse_response(r.text)
    res.raw = r.text
    if not res.ok:
        res.detalhe = f"HTTP {r.status_code}: {r.text[:300]}"
    return res
