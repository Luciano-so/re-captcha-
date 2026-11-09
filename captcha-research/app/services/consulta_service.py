from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from app.browser.playwright_manager import PlaywrightManager
from app.captcha import captcha_analyzer, captcha_detector
from app.models.captcha_result import PortalReport, Viabilidade
from app.portals.base import PortalDefinition
from app.services import nfe_webservice
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
    if endpoint:
        notas.append(f"Web service oficial para {chave.uf}: {endpoint}. "
                     "Consulta com certificado: python -m app.main --diagnostico <chave>.")

    if portal.key == "nfe":
        notas.append("Download de XML/PDF sem CAPTCHA: use 'python -m app.main --lote' "
                     "(NFeDistribuicaoDFe com certificado do cliente).")

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
