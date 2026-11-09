from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from app.browser.playwright_manager import PlaywrightManager
from app.captcha import captcha_analyzer, captcha_detector
from app.models.captcha_result import PortalReport, Viabilidade
from app.portals.base import PortalDefinition
from app.services import danfe, nfe_distribuicao, nfe_webservice
from app.services.key_validator import ChaveInfo

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


async def analisar_portal(portal: PortalDefinition, chave: ChaveInfo, headless: bool) -> PortalReport:
    rep = PortalReport(portal=portal.nome, url=portal.url_consulta or "-",
                       alternativas=[a.model_copy() for a in portal.alternativas])
    notas: list[str] = [portal.observacoes] if portal.observacoes else []

    if portal.ufs_atendidas and chave.uf not in portal.ufs_atendidas:
        notas.append(f"A chave é de {chave.uf}; este portal atende {sorted(portal.ufs_atendidas)} "
                     "e não retornará esta NF-e.")

    # 1) Navegador: identificar campos e CAPTCHA (sem enviar formulário)
    if portal.url_consulta:
        try:
            async with PlaywrightManager(headless=headless) as pm:
                status = await pm.goto(portal.url_consulta)
                log.info("%s carregado (HTTP %s)", portal.url_consulta, status)
                campo = await pm.fill_first(portal.campo_chave, chave.normalizada)
                notas.append(f"Campo da chave: {campo}" if campo else "Campo da chave não localizado.")
                snap = await pm.snapshot()
                rep.captcha = captcha_analyzer.analyze(
                    portal.nome, pm.page.url, captcha_detector.detect(snap))
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shot = await pm.screenshot(ROOT / "screenshots" / f"{portal.key}_{ts}.png")
                rep.evidencias.append(str(shot.relative_to(ROOT)))
        except Exception as e:  # rede, timeout, bloqueio
            log.exception("Falha ao acessar %s", portal.url_consulta)
            rep.erro = f"{type(e).__name__}: {str(e)[:200]}"

    # 2) Alternativa oficial: web service com certificado
    endpoint = portal.ws_consulta.get(chave.uf or "")
    cert, key = os.getenv("NFE_CERT_PEM"), os.getenv("NFE_KEY_PEM")
    if endpoint:
        notas.append(f"Web service oficial para {chave.uf}: {endpoint} -> "
                     f"{nfe_webservice.probe(endpoint)}")
        if cert and key:
            res = nfe_webservice.consultar(endpoint, chave.normalizada, cert, key,
                                           tp_amb=os.getenv("NFE_TP_AMB", "1"))
            rep.alternativas[0].implementado = True
            if res.ok:
                rep.consulta_concluida = True
                notas.append(f"Consulta via web service: cStat={res.c_stat} {res.x_motivo}")
            else:
                notas.append(f"Consulta via web service falhou: {res.detalhe}")
        else:
            notas.append("NFE_CERT_PEM/NFE_KEY_PEM não configurados: consulta via web service não executada.")

    # 2b) XML + PDF via NFeDistribuicaoDFe (somente no portal nacional)
    if portal.key == "nfe":
        notas.append(baixar_xml_pdf(chave, rep))

    # 3) Conclusão
    if rep.consulta_concluida:
        rep.automacao = Viabilidade.VIAVEL
        notas.append("Automação sem intervenção humana comprovada via web service com certificado "
                     "(CAPTCHA do portal não foi resolvido nem contornado).")
    elif endpoint or portal.alternativas:
        rep.automacao = Viabilidade.NAO_COMPROVADA
        notas.append("Existe caminho oficial documentado, mas depende de certificado digital ICP-Brasil; "
                     "sem ele a consulta automatizada não foi executada.")
    else:
        rep.automacao = Viabilidade.NAO_DISPONIVEL
    rep.justificativa = " ".join(notas)
    return rep


def baixar_xml_pdf(chave: ChaveInfo, rep: PortalReport) -> str:
    cert, key = os.getenv("NFE_CERT_PEM"), os.getenv("NFE_KEY_PEM")
    doc, cuf = os.getenv("NFE_CNPJ_CPF"), os.getenv("NFE_CUF_AUTOR")
    if not all((cert, key, doc, cuf)):
        return ("Download XML/PDF não executado: configure NFE_CERT_PEM, NFE_KEY_PEM, "
                "NFE_CNPJ_CPF e NFE_CUF_AUTOR no .env.")
    verify = os.getenv("NFE_CA_BUNDLE") or True
    res = nfe_distribuicao.baixar_xml(chave.normalizada, doc, cuf, cert, key,
                                      os.getenv("NFE_TP_AMB", "1"), verify)
    if res.erro:
        return f"NFeDistribuicaoDFe falhou: {res.erro}"
    msg = f"NFeDistribuicaoDFe: cStat={res.c_stat} {res.x_motivo}."
    out = ROOT / "downloads"
    out.mkdir(exist_ok=True)
    for schema, xml in res.docs:
        nome = "procNFe" if schema.startswith("procNFe") else schema.split("_")[0]
        p = out / f"{chave.normalizada}-{nome}.xml"
        p.write_text(xml, encoding="utf-8")
        rep.evidencias.append(str(p.relative_to(ROOT)))
    if not res.proc_nfe:
        return msg + (" XML completo não retornado (apenas resumo ou nada). Se for destinatário, "
                      "registre a manifestação (Ciência da Operação) e repita.")
    rep.consulta_concluida = True
    try:
        pdf = danfe.gerar_danfe(res.proc_nfe, out / f"{chave.normalizada}-danfe.pdf")
        rep.evidencias.append(str(pdf.relative_to(ROOT)))
        return msg + " XML completo salvo e DANFE (PDF) gerado."
    except Exception as e:
        return msg + f" XML salvo; falha ao gerar DANFE: {e}"
