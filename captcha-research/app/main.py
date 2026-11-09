"""Uso:
  python -m app.main --portal nfe [--portal sefaz-mt] [--headless] [--ai]   # pesquisa de portal/CAPTCHA
  python -m app.main --lote input/chaves.txt     # XML/PDF de uma lista (chave ou chave;cnpj_cliente)
  python -m app.main --sincronizar               # todas as notas novas de todos os clientes (NSU)
  python -m app.main --sincronizar 12345678000199
  python -m app.main --clientes                  # confere cadastro e validade dos certificados
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from app.agents.research_agent import run
from app.portals import PORTALS
from app.services.consulta_service import ROOT

DEFAULT_CHAVE = "3526 0353 5656 6300 0209 5542 0000 0189 1811 1548 5768"


def _clientes():
    from app.services.clientes import Clientes
    try:
        return Clientes.carregar()
    except ValueError as e:
        raise SystemExit(f"Erro: {e}")


def _salvar_json(prefixo: str, dados: list) -> Path:
    saida = ROOT / "reports" / f"{prefixo}_{datetime.now():%Y%m%d_%H%M%S}.json"
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps([d.model_dump(mode="json") for d in dados], ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return saida


def _eh_planilha(arquivo: Path) -> bool:
    if arquivo.suffix.lower() in (".csv", ".xlsx", ".xlsm"):
        return True
    with arquivo.open("rb") as f:
        primeira = f.readline().decode("utf-8", "ignore").lower()
    return "chave" in primeira and any(d in primeira for d in ";\t,")


def executar_lote(arquivo: Path, limite: int | None = None) -> None:
    from app.services.nfe_lote import buscar_notas, ler_itens
    from app.services.planilha import PlanilhaInvalida, gravar_resultados, ler_planilha
    clientes = _clientes()
    planilha = _eh_planilha(arquivo)
    if planilha:
        try:
            linhas = ler_planilha(arquivo, clientes)[:limite]
        except PlanilhaInvalida as e:
            raise SystemExit(f"Erro na planilha {arquivo.name}: {e}")
        itens = [(i.chave, i.cnpj_cliente) for i in linhas]
    else:
        itens = ler_itens(arquivo)[:limite]
    print(f"{len(itens)} nota(s) para consultar.")
    resultados = buscar_notas(itens, clientes)
    if planilha:
        try:
            print(f"Planilha atualizada: {gravar_resultados(arquivo, linhas, resultados)} "
                  f"(original em {arquivo.name}.bak)")
        except PermissionError:
            print(f"Não foi possível alterar {arquivo.name}: feche o arquivo no Excel e rode de novo "
                  "(as notas já baixadas não serão consultadas outra vez).")
    for r in resultados:
        print(f"{r.chave}  {r.status.value:<15} {r.c_stat or '':<4} {r.cliente or '-':<20} {r.mensagem}")
    print(f"\nResumo salvo em {_salvar_json('lote', resultados)}")


def executar_sync(cnpj: str | None, limite: int | None = None) -> None:
    from app.services.nfe_sync import sincronizar
    try:
        resultados = sincronizar(_clientes(), cnpj, limite or 50)
    except ValueError as e:
        raise SystemExit(f"Erro: {e}")
    for r in resultados:
        print(f"{r.cliente:<25} docs={r.documentos:<4} xml={r.xml_completos:<4} NSU={r.ult_nsu} "
              f"cStat={r.c_stat} {r.mensagem}")
    print(f"\nResumo salvo em {_salvar_json('sync', resultados)}")


def listar_clientes() -> None:
    from app.services.certificados import validade
    for c in _clientes().lista:
        senha = os.getenv(c.senha_env)
        try:
            info = f"válido até {validade(c.pfx, senha):%d/%m/%Y}" if senha else f"defina {c.senha_env}"
        except Exception as e:
            info = f"ERRO: {e}"
        print(f"{c.nome:<25} {c.cnpj_cpf:<15} UF {c.cuf}  {info}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Pesquisa de CAPTCHA e consulta oficial de NF-e")
    p.add_argument("--lote", type=Path, help="arquivo: 'chave' ou 'chave;cnpj_cliente' por linha")
    p.add_argument("--limite", type=int,
                   help="lote: só as N primeiras notas | sincronizar: no máximo N consultas à SEFAZ")
    p.add_argument("--sincronizar", nargs="?", const="*", metavar="CNPJ", help="sync por NSU")
    p.add_argument("--clientes", action="store_true", help="confere o cadastro de certificados")
    p.add_argument("--diagnostico", metavar="CHAVE", help="testa todas as etapas para UMA nota")
    p.add_argument("--assistido", metavar="CHAVE",
                   help="baixa XML+PDF pelo Portal Nacional (você resolve o CAPTCHA; o resto é automático)")
    p.add_argument("--cliente", metavar="CNPJ", help="com --diagnostico: CNPJ do cliente destinatário")
    p.add_argument("--sem-distribuicao", action="store_true", help="com --diagnostico: não chama a distribuição")
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
    if a.clientes:
        return listar_clientes()
    if a.assistido:
        from app.services.key_validator import validar_chave
        from app.services.portal_download import baixar_assistido, info_xml
        info = validar_chave(a.assistido)
        if not info.valida:
            raise SystemExit("Chave inválida: " + "; ".join(info.erros))
        esc = _clientes().escolher(info.normalizada, a.cliente)
        if not esc:
            raise SystemExit("Nenhum certificado cadastrado serve para esta nota (use --cliente CNPJ)")
        try:
            out = asyncio.run(baixar_assistido(info.normalizada, esc[0]))
        except Exception as e:
            raise SystemExit(f"Download assistido falhou: {e}")
        print(f"XML: {out['xml']}  ({info_xml(out['xml'])})")
        print(f"PDF: {out.get('pdf') or 'não gerado: ' + out.get('pdf_erro', '')}")
        return
    if a.diagnostico:
        from app.services.diagnostico import diagnosticar, imprimir
        etapas = diagnosticar(a.diagnostico, _clientes(), a.cliente, os.getenv("NFE_TP_AMB", "1"),
                              not a.sem_distribuicao)
        imprimir(etapas)
        print(f"\nRelatório: {_salvar_json('diagnostico', etapas)}")
        return
    if a.lote:
        return executar_lote(a.lote, a.limite)
    if a.sincronizar:
        return executar_sync(None if a.sincronizar == "*" else a.sincronizar, a.limite)
    for path in asyncio.run(run(a.chave, a.portal or ["nfe"], a.headless, a.ai)):
        print(f"\n===== {path.name} =====\n{path.read_text(encoding='utf-8')}")


if __name__ == "__main__":
    main()
