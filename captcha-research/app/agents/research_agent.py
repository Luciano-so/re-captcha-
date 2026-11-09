"""Coordena: valida chave -> analisa portais -> (opcional) Browser Use -> relatórios."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.browser.browser_use_manager import BrowserUseManager
from app.models.captcha_result import PortalReport
from app.portals import PORTALS
from app.services.consulta_service import ROOT, analisar_portal
from app.services.key_validator import validar_chave


def render_report(r: PortalReport) -> str:
    c = r.captcha
    tipos = ", ".join(t.value for t in c.types) if c and c.types else "-"
    lines = [
        f"PORTAL: {r.portal}",
        f"URL: {r.url}",
        f"CAPTCHA IDENTIFICADO: {'Sim' if c and c.captcha_found else ('Não' if c else 'Não verificado')}",
        f"TIPO: {tipos}",
        f"CONSULTA: {'Concluída' if r.consulta_concluida else 'Pendente'}",
        f"ALTERNATIVA OFICIAL: {'Encontrada' if r.alternativas else 'Não encontrada'}",
        f"AUTOMAÇÃO SEM INTERVENÇÃO: {r.automacao.value}",
        f"JUSTIFICATIVA: {r.justificativa}",
    ]
    if c:
        lines.append(f"ANÁLISE CAPTCHA: {c.analysis} (detectado em {c.detected_at.isoformat()})")
        lines += [f"  - {e.type.value}: {e.element}" for e in c.evidences]
    lines.append("ALTERNATIVAS:")
    lines += [f"  - {a.nome} | {a.requisitos} | {a.url_documentacao}" for a in r.alternativas]
    if r.erro:
        lines.append(f"ERRO: {r.erro}")
    lines.append("EVIDÊNCIAS: " + (", ".join(r.evidencias) or "-") + ", logs/run.log")
    return "\n".join(lines) + "\n"


async def run(chave_raw: str, portal_keys: list[str], headless: bool, use_ai: bool) -> list[Path]:
    chave = validar_chave(chave_raw)
    if not chave.valida:
        raise ValueError("Chave inválida: " + "; ".join(chave.erros))

    out: list[Path] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for key in portal_keys:  # sequencial: uma consulta por portal, sem massa
        portal = PORTALS[key]
        rep = await analisar_portal(portal, chave, headless)
        if use_ai and portal.url_consulta:
            bu = BrowserUseManager()  # sessão própria, após Playwright fechar
            rep.justificativa += " [Browser Use] " + await bu.describe_page(portal.url_consulta)
        base = ROOT / "reports" / f"{key}_{ts}"
        base.parent.mkdir(exist_ok=True)
        base.with_suffix(".txt").write_text(render_report(rep), encoding="utf-8")
        base.with_suffix(".json").write_text(
            json.dumps(rep.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        out.append(base.with_suffix(".txt"))
    return out
