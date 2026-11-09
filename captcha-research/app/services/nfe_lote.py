"""Busca de XML/PDF de uma lista de chaves, escolhendo o certificado de cada cliente.

Integração:
    from app.services.clientes import Clientes
    from app.services.nfe_lote import buscar_notas
    resultados = buscar_notas([("3526...", None), ("5126...", "12345678000199")], Clientes.carregar())

Cada item é (chave, cnpj_do_cliente_opcional). Sem CNPJ, usa o emitente da chave
(nota emitida por um cliente) ou o único cliente cadastrado. Para notas RECEBIDAS,
informe o CNPJ do cliente destinatário.
"""
from __future__ import annotations

import logging
import os
import time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from app.services import armazenamento, nfe_distribuicao
from app.services.clientes import Clientes
from app.services.key_validator import validar_chave

log = logging.getLogger(__name__)


class Status(str, Enum):
    BAIXADA = "baixada"
    SITUACAO_CONSULTADA = "situacao_consultada"  # emitente: SEFAZ não distribui o XML; só situação/protocolo
    JA_EXISTIA = "ja_existia"
    SOMENTE_RESUMO = "somente_resumo"   # destinatário precisa manifestar
    NAO_ENCONTRADA = "nao_encontrada"   # SEFAZ não retornou documento para este CNPJ
    CHAVE_INVALIDA = "chave_invalida"
    SEM_CLIENTE = "sem_cliente"         # nenhum certificado cadastrado serve para a nota
    ERRO = "erro"
    INTERROMPIDA = "interrompida"       # não processada após cStat 656


class NotaResultado(BaseModel):
    chave: str
    status: Status
    cliente: str | None = None
    c_stat: str | None = None
    mensagem: str = ""
    xml_path: str | None = None
    pdf_path: str | None = None
    situacao: str | None = None    # AUTORIZADA, CANCELADA, DENEGADA...
    protocolo: str | None = None


SITUACOES = {"100": "AUTORIZADA", "150": "AUTORIZADA", "101": "CANCELADA", "151": "CANCELADA",
             "110": "DENEGADA", "301": "DENEGADA", "302": "DENEGADA", "217": "NAO CONSTA NA SEFAZ"}


def consultar_situacao(ch: str, uf: str | None, ctx, tp_amb: str) -> tuple[str | None, str | None, str]:
    """NFeConsultaProtocolo4 na UF autorizadora -> (situacao, protocolo, mensagem)."""
    from app.portals.nfe_portal import WS_CONSULTA_PROTOCOLO
    from app.services import nfe_webservice
    endpoint = WS_CONSULTA_PROTOCOLO.get(uf or "")
    if not endpoint:
        return None, None, f"consulta de situação da UF {uf} não configurada"
    r = nfe_webservice.consultar(endpoint, ch, ctx, tp_amb)
    if not r.ok:
        return None, None, f"consulta de situação falhou: {r.detalhe[:150]}"
    return SITUACOES.get(r.c_stat, r.x_motivo), r.n_prot, f"situação: cStat {r.c_stat} {r.x_motivo}"


def ler_itens(arquivo: Path) -> list[tuple[str, str | None]]:
    """Formato: 'chave' ou 'chave;cnpj_cliente' (também aceita vírgula). # = comentário."""
    itens = []
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = [p.strip() for p in linha.replace(",", ";").split(";")]
        itens.append((partes[0], partes[1] if len(partes) > 1 and partes[1] else None))
    return itens


def buscar_nota(chave: str, cnpj_cliente: str | None, clientes: Clientes,
                tp_amb: str = "1", pasta_base: Path = armazenamento.PASTA_PADRAO,
                gerar_pdf: bool = True) -> NotaResultado:
    info = validar_chave(chave)
    if not info.valida:
        return NotaResultado(chave=chave, status=Status.CHAVE_INVALIDA, mensagem="; ".join(info.erros))
    ch = info.normalizada
    escolha = clientes.escolher(ch, cnpj_cliente)
    if not escolha:
        return NotaResultado(chave=ch, status=Status.SEM_CLIENTE,
                             mensagem="Emitente não é cliente cadastrado; informe 'chave;cnpj_do_cliente'.")
    cliente, doc_pedido = escolha
    pasta = armazenamento.pasta_cliente(cliente.cnpj_cpf, pasta_base)
    xml = armazenamento.caminho_xml(pasta, ch)
    if xml.exists():
        pdf = xml.with_name(f"{ch}-danfe.pdf")
        return NotaResultado(chave=ch, status=Status.JA_EXISTIA, cliente=cliente.nome,
                             xml_path=str(xml), pdf_path=str(pdf) if pdf.exists() else None)
    try:
        ctx = clientes.ssl_context(cliente)
    except Exception as e:
        return NotaResultado(chave=ch, status=Status.ERRO, cliente=cliente.nome, mensagem=str(e))

    # Emitente: a distribuição sempre responde 641 (não distribui ao emitente). Não gasta cota.
    if ch[6:14] == cliente.raiz and cnpj_cliente is None:
        situacao, prot, msg = consultar_situacao(ch, info.uf, ctx, tp_amb)
        return NotaResultado(chave=ch, cliente=cliente.nome, status=Status.SITUACAO_CONSULTADA if situacao
                             else Status.ERRO, situacao=situacao, protocolo=prot,
                             mensagem=msg + " | XML não distribuído ao emitente: obter no sistema emissor.")

    res = nfe_distribuicao.enviar(nfe_distribuicao.envelope_chave(ch, doc_pedido, cliente.cuf, tp_amb),
                                  ctx, tp_amb)
    base = dict(chave=ch, cliente=cliente.nome, c_stat=res.c_stat, mensagem=res.x_motivo or "")
    if res.erro:
        return NotaResultado(**base | {"mensagem": res.erro}, status=Status.ERRO)
    if not res.proc_nfe and res.c_stat != "656":
        base["situacao"], base["protocolo"], msg = consultar_situacao(ch, info.uf, ctx, tp_amb)
        base["mensagem"] += f" | {msg}"

    salvos = [armazenamento.salvar(d, pasta, gerar_pdf) for d in res.docs]
    if res.proc_nfe:
        s = next(x for d, x in zip(res.docs, salvos) if d.tipo == "procNFe")
        return NotaResultado(**base, status=Status.BAIXADA, xml_path=s["xml"], pdf_path=s.get("pdf"))
    if res.docs:
        return NotaResultado(**base | {"mensagem": base["mensagem"] + " | Registre a Ciência da Operação e repita."},
                             status=Status.SOMENTE_RESUMO)
    return NotaResultado(**base, status=Status.NAO_ENCONTRADA)


def buscar_notas(itens: list[tuple[str, str | None]], clientes: Clientes,
                 intervalo_seg: float | None = None, **kw) -> list[NotaResultado]:
    intervalo = float(os.getenv("NFE_INTERVALO_SEG", "2")) if intervalo_seg is None else intervalo_seg
    kw.setdefault("tp_amb", os.getenv("NFE_TP_AMB", "1"))
    vistos: set[str] = set()
    resultados: list[NotaResultado] = []
    bloqueado = False
    for chave, cnpj in itens:
        norm = "".join(chave.split())
        if norm in vistos:
            continue
        vistos.add(norm)
        if bloqueado:
            resultados.append(NotaResultado(chave=norm, status=Status.INTERROMPIDA,
                                            mensagem="Não consultada: SEFAZ sinalizou consumo indevido (656)."))
            continue
        r = buscar_nota(norm, cnpj, clientes, **kw)
        log.info("%s [%s] -> %s %s", r.chave, r.cliente, r.status.value, r.mensagem)
        resultados.append(r)
        if r.c_stat == "656":
            bloqueado = True
            log.warning("cStat 656: lote interrompido. Aguarde ~1h.")
        if r.c_stat is not None or r.status == Status.ERRO:
            time.sleep(intervalo)
    return resultados
