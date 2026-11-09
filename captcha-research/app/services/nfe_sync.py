"""Sincronização por NSU: baixa todos os documentos novos de cada cliente, sem precisar das chaves.

Regras do Ambiente Nacional respeitadas:
- Continua do último NSU salvo (state/nsu_<cnpj>.json).
- Ao alcançar maxNSU ou receber cStat 137 (nenhum documento), aguarda 1h para o próximo ciclo.
- cStat 656 (consumo indevido): para o cliente e aguarda 1h.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from app.services import armazenamento, nfe_distribuicao
from app.services.clientes import Cliente, Clientes

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "state"
ESPERA = timedelta(hours=1)


class Estado(BaseModel):
    ult_nsu: str = "0"
    proxima_consulta: datetime | None = None


class SyncResultado(BaseModel):
    cliente: str
    cnpj_cpf: str
    documentos: int = 0
    xml_completos: int = 0
    ult_nsu: str = "0"
    c_stat: str | None = None
    mensagem: str = ""


def _arq(c: Cliente) -> Path:
    return STATE / f"nsu_{c.cnpj_cpf}.json"


def ler_estado(c: Cliente) -> Estado:
    p = _arq(c)
    return Estado.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else Estado()


def gravar_estado(c: Cliente, e: Estado) -> None:
    STATE.mkdir(exist_ok=True)
    _arq(c).write_text(e.model_dump_json(indent=2), encoding="utf-8")


def sincronizar_cliente(c: Cliente, clientes: Clientes, tp_amb: str = "1",
                        intervalo_seg: float = 2, max_lotes: int = 50,
                        pasta_base: Path = armazenamento.PASTA_PADRAO) -> SyncResultado:
    est = ler_estado(c)
    r = SyncResultado(cliente=c.nome, cnpj_cpf=c.cnpj_cpf, ult_nsu=est.ult_nsu)
    agora = datetime.now(timezone.utc)
    if est.proxima_consulta and agora < est.proxima_consulta:
        r.mensagem = f"Aguardando intervalo da SEFAZ até {est.proxima_consulta.astimezone():%H:%M}."
        return r
    try:
        ctx = clientes.ssl_context(c)
    except Exception as e:
        r.mensagem = str(e)
        return r
    pasta = armazenamento.pasta_cliente(c.cnpj_cpf, pasta_base)

    for _ in range(max_lotes):
        res = nfe_distribuicao.enviar(
            nfe_distribuicao.envelope_nsu(est.ult_nsu, c.cnpj_cpf, c.cuf, tp_amb), ctx, tp_amb)
        r.c_stat, r.mensagem = res.c_stat, res.erro or res.x_motivo or ""
        if res.erro:
            break
        for d in res.docs:
            armazenamento.salvar(d, pasta)
            r.documentos += 1
            r.xml_completos += d.tipo == "procNFe"
        if res.ult_nsu:
            est.ult_nsu = res.ult_nsu
        if res.c_stat in ("137", "656") or (res.max_nsu and res.ult_nsu and int(res.ult_nsu) >= int(res.max_nsu)):
            est.proxima_consulta = datetime.now(timezone.utc) + ESPERA
            break
        if res.c_stat != "138":
            break
        gravar_estado(c, est)
        time.sleep(intervalo_seg)
    gravar_estado(c, est)
    r.ult_nsu = est.ult_nsu
    return r


def sincronizar(clientes: Clientes, cnpj: str | None = None, max_lotes: int = 50) -> list[SyncResultado]:
    alvo = [clientes.por_documento(cnpj)] if cnpj else clientes.lista
    if cnpj and alvo == [None]:
        raise ValueError(f"Cliente {cnpj} não cadastrado")
    tp_amb = os.getenv("NFE_TP_AMB", "1")
    intervalo = float(os.getenv("NFE_INTERVALO_SEG", "2"))
    out = []
    for c in alvo:
        res = sincronizar_cliente(c, clientes, tp_amb, intervalo, max_lotes)
        log.info("Sync %s: %d docs (%d XML) NSU=%s cStat=%s %s", c.nome, res.documentos,
                 res.xml_completos, res.ult_nsu, res.c_stat, res.mensagem)
        out.append(res)
    return out
