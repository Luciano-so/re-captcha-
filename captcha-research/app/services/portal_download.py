"""Download ASSISTIDO do XML pelo Portal Nacional da NF-e ("Consulta Completa" → "Download do documento").

Caminho oficial para o EMITENTE (a NFeDistribuicaoDFe não distribui ao emitente, cStat 641).
- O CAPTCHA é resolvido por uma PESSOA no navegador visível. O programa não interage com ele.
- O certificado A1 do cliente é apresentado pelo navegador (TLS cliente) só para o portal oficial.
- Depois do CAPTCHA, o programa clica em "Download do documento", salva o XML, valida e gera o DANFE.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import TimeoutError as PWTimeout
from playwright.async_api import async_playwright

from app.services import armazenamento, danfe
from app.services.certificados import pfx_moderno
from app.services.clientes import Cliente

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
ORIGEM = "https://www.nfe.fazenda.gov.br"
URL_COMPLETA = ORIGEM + "/portal/consultaRecaptcha.aspx?tipoConsulta=completa"
CAMPO_CHAVE = ["#ctl00_ContentPlaceHolder1_txtChaveAcessoCompleta", "input[id*='ChaveAcesso']",
               "input[name*='ChaveAcesso']"]
BOTAO_DOWNLOAD = ("input[value*='Download do documento'], a:has-text('Download do documento'), "
                  "button:has-text('Download do documento')")


async def baixar_assistido(chave: str, cliente: Cliente, espera_captcha_seg: int = 300,
                           pasta_base: Path = armazenamento.PASTA_PADRAO) -> dict:
    senha = os.getenv(cliente.senha_env)
    if senha is None:
        raise ValueError(f"Variável {cliente.senha_env} não definida")
    pasta = armazenamento.pasta_cliente(cliente.cnpj_cpf, pasta_base)
    destino = armazenamento.caminho_xml(pasta, chave)
    shots = ROOT / "screenshots"
    shots.mkdir(exist_ok=True)

    pfx_bytes, pfx_senha = pfx_moderno(cliente.pfx, senha)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(
            locale="pt-BR", accept_downloads=True,
            client_certificates=[{"origin": ORIGEM, "pfx": pfx_bytes, "passphrase": pfx_senha}],
        )
        page = await ctx.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        try:
            await page.goto(URL_COMPLETA, wait_until="domcontentloaded")
            for sel in CAMPO_CHAVE:
                if await page.locator(sel).count():
                    await page.locator(sel).first.fill(chave)
                    break
            else:
                raise RuntimeError("Campo da chave não encontrado na página do portal")

            print("\n>>> No navegador: resolva o CAPTCHA e clique em 'Continuar'. "
                  f"Aguardando até {espera_captcha_seg // 60} min...\n")
            botao = page.locator(BOTAO_DOWNLOAD).first
            await botao.wait_for(state="visible", timeout=espera_captcha_seg * 1000)

            erro = page.locator("#ctl00_ContentPlaceHolder1_bltMensagensErro, .indisponivel")
            if await erro.count() and (await erro.first.inner_text()).strip():
                raise RuntimeError("Portal: " + (await erro.first.inner_text()).strip()[:200])

            async with page.expect_download(timeout=90000) as dl_info:
                await botao.click()
                # Algumas versões do portal mostram uma página intermediária com novo botão de confirmação
                try:
                    confirmar = page.locator(BOTAO_DOWNLOAD + ", input[value*='Continuar']").first
                    await confirmar.wait_for(state="visible", timeout=8000)
                    await confirmar.click()
                except PWTimeout:
                    pass
            dl = await dl_info.value
            tmp = pasta / f"{chave}-portal.tmp"
            await dl.save_as(tmp)
        except Exception:
            shot = shots / f"assistido_{chave}_{datetime.now():%H%M%S}.png"
            await page.screenshot(path=str(shot), full_page=True)
            log.error("Falha no download assistido; tela salva em %s", shot)
            raise
        finally:
            await browser.close()

    xml = tmp.read_bytes().decode("utf-8", "replace")
    tmp.unlink()
    if chave not in xml or "<infNFe" not in xml:
        bad = pasta / f"{chave}-resposta-portal.html"
        bad.write_text(xml, encoding="utf-8")
        raise RuntimeError(f"O arquivo baixado não é o XML desta NF-e (salvo em {bad})")
    if "<protNFe" not in xml:
        log.warning("XML sem protNFe (protocolo): validade jurídica exige nfeProc completo")
    destino.write_text(xml, encoding="utf-8")
    out = {"xml": str(destino), "tem_protocolo": "<protNFe" in xml}
    try:
        out["pdf"] = str(danfe.gerar_danfe(xml, destino.with_name(f"{chave}-danfe.pdf")))
    except Exception as e:
        out["pdf_erro"] = str(e)
    return out


def info_xml(xml_path: str) -> str:
    x = Path(xml_path).read_text(encoding="utf-8")
    get = lambda t: (re.search(rf"<{t}>([^<]*)</{t}>", x) or [None, "-"])[1]
    return f"nº {get('nNF')} | emissão {get('dhEmi')} | valor {get('vNF')} | protocolo {get('nProt')}"
