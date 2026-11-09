"""Diagnóstico ponta a ponta de UMA nota, etapa por etapa (uma requisição por serviço).

Etapas:
 1. Chave (formato, DV, UF, emitente)
 2. Cliente/certificado escolhido, senha, validade, cadeia
 3. TLS mútuo com a SEFAZ autorizadora (handshake)
 4. NFeConsultaProtocolo4 na UF autorizadora: situação e protocolo
 5. NFeDistribuicaoDFe consChNFe: XML (respeita bloqueio 656 registrado)
 6. XML local já existente / geração do DANFE (PDF)
"""
from __future__ import annotations

import socket
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from app.portals.nfe_portal import WS_CONSULTA_PROTOCOLO
from app.services import armazenamento, danfe, nfe_distribuicao, nfe_webservice
from app.services.certificados import carregar_pfx
from app.services.clientes import Clientes
from app.services.key_validator import validar_chave


class Etapa(BaseModel):
    nome: str
    ok: bool | None  # None = não executada / não se aplica
    detalhe: str
    ms: int = 0


def _etapa(nome, fn) -> Etapa:
    t = time.perf_counter()
    try:
        ok, det = fn()
    except Exception as e:
        ok, det = False, f"{type(e).__name__}: {str(e)[:300]}"
    return Etapa(nome=nome, ok=ok, detalhe=det, ms=int((time.perf_counter() - t) * 1000))


def diagnosticar(chave_raw: str, clientes: Clientes, cnpj_cliente: str | None = None,
                 tp_amb: str = "1", consultar_distribuicao: bool = True) -> list[Etapa]:
    etapas: list[Etapa] = []
    info = validar_chave(chave_raw)
    etapas.append(Etapa(
        nome="1. Chave", ok=info.valida,
        detalhe=(f"{info.normalizada} | UF {info.uf} | {info.ano_mes[2:]}/{info.ano_mes[:2]} | "
                 f"emitente {info.cnpj} | modelo {info.modelo} | nº {int(info.numero)} série {int(info.serie)}"
                 if info.valida else "; ".join(info.erros))))
    if not info.valida:
        return etapas
    ch = info.normalizada

    escolha = clientes.escolher(ch, cnpj_cliente)
    if not escolha:
        etapas.append(Etapa(nome="2. Certificado", ok=False, detalhe="Nenhum cliente cadastrado serve para esta nota"))
        return etapas
    cliente, doc = escolha
    papel = "EMITENTE" if ch[6:20][:8] == cliente.raiz else "destinatário/terceiro"

    def cert():
        import os
        senha = os.getenv(cliente.senha_env)
        if senha is None:
            return False, f"Variável {cliente.senha_env} não definida"
        _, c, extras = carregar_pfx(cliente.pfx, senha)
        restante = (c.not_valid_after_utc - datetime.now(timezone.utc)).days
        clientes.ssl_context(cliente)
        return restante > 0, (f"{cliente.nome} ({doc}) como {papel} | válido até "
                              f"{c.not_valid_after_utc:%d/%m/%Y} ({restante} dias) | cadeia no pfx: {len(extras)}")
    etapas.append(_etapa("2. Certificado", cert))
    if not etapas[-1].ok:
        return etapas
    ctx = clientes.ssl_context(cliente)

    endpoint = WS_CONSULTA_PROTOCOLO.get(info.uf)

    def tls():
        if not endpoint:
            return None, f"Endpoint de consulta da UF {info.uf} não cadastrado em nfe_portal.py"
        host = urlparse(endpoint).hostname
        with socket.create_connection((host, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            peer = t.getpeercert()
            emissor = dict(x[0] for x in peer.get("issuer", ()))
            return True, f"{host} | {t.version()} | servidor emitido por {emissor.get('commonName', '?')}"
    etapas.append(_etapa("3. TLS com SEFAZ-" + (info.uf or "?"), tls))

    def protocolo():
        if not endpoint:
            return None, "sem endpoint"
        r = nfe_webservice.consultar(endpoint, ch, ctx, tp_amb)
        if not r.ok:
            return False, r.detalhe
        situacao = {"100": "AUTORIZADA", "101": "CANCELADA", "110": "DENEGADA", "150": "AUTORIZADA (fora de prazo)",
                    "151": "CANCELADA (fora de prazo)"}.get(r.c_stat_nota or r.c_stat, r.x_motivo)
        return r.c_stat in ("100", "101", "110", "150", "151"), (
            f"cStat {r.c_stat} {r.x_motivo} | situação: {situacao} | protocolo {r.n_prot or '-'} "
            f"em {r.dh_recbto or '-'} | eventos: {r.eventos}")
    if etapas[-1].ok:
        etapas.append(_etapa("4. Consulta situação (NFeConsultaProtocolo4)", protocolo))

    pasta = armazenamento.pasta_cliente(cliente.cnpj_cpf)
    xml_local = armazenamento.caminho_xml(pasta, ch)

    def distribuicao():
        if xml_local.exists():
            return True, f"XML já existe: {xml_local}"
        if not consultar_distribuicao:
            return None, "pulada (--sem-distribuicao)"
        from app.services.nfe_sync import ler_estado
        est = ler_estado(cliente)
        if est.proxima_consulta and datetime.now(timezone.utc) < est.proxima_consulta:
            aviso = f" (sync NSU bloqueado até {est.proxima_consulta.astimezone():%H:%M}; consChNFe é independente)"
        else:
            aviso = ""
        r = nfe_distribuicao.enviar(nfe_distribuicao.envelope_chave(ch, doc, cliente.cuf, tp_amb), ctx, tp_amb)
        if r.erro:
            return False, r.erro
        for d in r.docs:
            armazenamento.salvar(d, pasta, gerar_pdf=False)
        explic = {
            "641": "a SEFAZ não distribui ao emitente as notas que ele emitiu",
            "656": "consumo indevido: aguarde 1h (outro sistema pode estar usando este CNPJ)",
            "137": "nenhum documento para este CNPJ",
            "632": "solicitação fora de prazo (mais de 90 dias)",
            "640": "CNPJ não é ator desta NF-e",
        }.get(r.c_stat, "")
        tipos = ", ".join(d.tipo for d in r.docs) or "nenhum"
        return bool(r.proc_nfe), f"cStat {r.c_stat} {r.x_motivo}{' — ' + explic if explic else ''} | docs: {tipos}{aviso}"
    etapas.append(_etapa("5. Download XML (NFeDistribuicaoDFe)", distribuicao))

    def pdf():
        if not xml_local.exists():
            return None, "sem XML completo para gerar o DANFE"
        p = danfe.gerar_danfe(xml_local.read_text(encoding="utf-8"), xml_local.with_name(f"{ch}-danfe.pdf"))
        return True, f"{p} ({p.stat().st_size // 1024} KB)"
    etapas.append(_etapa("6. DANFE (PDF)", pdf))
    return etapas


def imprimir(etapas: list[Etapa]) -> None:
    simb = {True: "OK  ", False: "FALHA", None: "--  "}
    for e in etapas:
        print(f"[{simb[e.ok]}] {e.nome} ({e.ms} ms)\n        {e.detalhe}")
