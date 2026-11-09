"""Busca de XML/PDF de uma lista de NF-e via NFeDistribuicaoDFe (caminho oficial, com certificado).

Ponto de integração com outras aplicações:

    from app.services.nfe_lote import NfeConfig, buscar_notas
    resultados = buscar_notas(["3526...", ...], NfeConfig.from_env())

Proteções:
- Chaves validadas e deduplicadas; inválidas não são enviadas à SEFAZ.
- Notas já baixadas são puladas (sem nova requisição).
- Intervalo entre requisições (NFE_INTERVALO_SEG) e parada imediata em
  cStat 656 (consumo indevido), conforme regra do Ambiente Nacional.
"""
from __future__ import annotations

import logging
import os
import time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from app.services import danfe, nfe_distribuicao
from app.services.key_validator import validar_chave

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


class NfeConfig(BaseModel):
    cert_pem: str
    key_pem: str
    cnpj_cpf: str
    cuf_autor: str
    tp_amb: str = "1"
    ca_bundle: str | None = None
    intervalo_seg: float = 2.0
    pasta_saida: Path = ROOT / "downloads"
    gerar_pdf: bool = True

    @classmethod
    def from_env(cls) -> "NfeConfig":
        faltando = [v for v in ("NFE_CERT_PEM", "NFE_KEY_PEM", "NFE_CNPJ_CPF", "NFE_CUF_AUTOR")
                    if not os.getenv(v)]
        if faltando:
            raise ValueError("Configure no .env: " + ", ".join(faltando))
        return cls(
            cert_pem=os.environ["NFE_CERT_PEM"], key_pem=os.environ["NFE_KEY_PEM"],
            cnpj_cpf=os.environ["NFE_CNPJ_CPF"], cuf_autor=os.environ["NFE_CUF_AUTOR"],
            tp_amb=os.getenv("NFE_TP_AMB", "1"), ca_bundle=os.getenv("NFE_CA_BUNDLE") or None,
            intervalo_seg=float(os.getenv("NFE_INTERVALO_SEG", "2")),
        )


class Status(str, Enum):
    BAIXADA = "baixada"            # XML completo (+ PDF)
    JA_EXISTIA = "ja_existia"      # já estava na pasta de saída
    SOMENTE_RESUMO = "somente_resumo"  # precisa de manifestação do destinatário
    NAO_ENCONTRADA = "nao_encontrada"  # SEFAZ não retornou documento para este ator
    CHAVE_INVALIDA = "chave_invalida"
    ERRO = "erro"
    INTERROMPIDA = "interrompida"  # não processada por bloqueio (656)


class NotaResultado(BaseModel):
    chave: str
    status: Status
    c_stat: str | None = None
    mensagem: str = ""
    xml_path: str | None = None
    pdf_path: str | None = None


def ler_chaves(arquivo: Path) -> list[str]:
    """Uma chave por linha (espaços permitidos). Linhas vazias e iniciadas por # são ignoradas.
    Aceita CSV: usa a primeira coluna."""
    chaves = []
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#"):
            chaves.append(linha.split(";")[0].split(",")[0].strip())
    return chaves


def buscar_nota(chave: str, cfg: NfeConfig) -> NotaResultado:
    info = validar_chave(chave)
    if not info.valida:
        return NotaResultado(chave=chave, status=Status.CHAVE_INVALIDA, mensagem="; ".join(info.erros))
    ch = info.normalizada
    xml_path = cfg.pasta_saida / f"{ch}-procNFe.xml"
    pdf_path = cfg.pasta_saida / f"{ch}-danfe.pdf"
    if xml_path.exists():
        return NotaResultado(chave=ch, status=Status.JA_EXISTIA, xml_path=str(xml_path),
                             pdf_path=str(pdf_path) if pdf_path.exists() else None)

    res = nfe_distribuicao.baixar_xml(ch, cfg.cnpj_cpf, cfg.cuf_autor, cfg.cert_pem, cfg.key_pem,
                                      cfg.tp_amb, cfg.ca_bundle or True)
    if res.erro:
        return NotaResultado(chave=ch, status=Status.ERRO, mensagem=res.erro)
    base = dict(chave=ch, c_stat=res.c_stat, mensagem=res.x_motivo or "")
    cfg.pasta_saida.mkdir(parents=True, exist_ok=True)

    if res.proc_nfe:
        xml_path.write_text(res.proc_nfe, encoding="utf-8")
        r = NotaResultado(**base, status=Status.BAIXADA, xml_path=str(xml_path))
        if cfg.gerar_pdf:
            try:
                r.pdf_path = str(danfe.gerar_danfe(res.proc_nfe, pdf_path))
            except Exception as e:
                r.mensagem += f" | DANFE não gerado: {e}"
        return r
    if res.docs:  # resNFe / eventos
        for schema, xml in res.docs:
            (cfg.pasta_saida / f"{ch}-{schema.split('_')[0]}.xml").write_text(xml, encoding="utf-8")
        return NotaResultado(**base, status=Status.SOMENTE_RESUMO,
                             mensagem=(res.x_motivo or "") + " | Registre a Ciência da Operação e repita.")
    return NotaResultado(**base, status=Status.NAO_ENCONTRADA)


def buscar_notas(chaves: list[str], cfg: NfeConfig) -> list[NotaResultado]:
    vistos: set[str] = set()
    resultados: list[NotaResultado] = []
    bloqueado = False
    for chave in chaves:
        norm = "".join(chave.split())
        if norm in vistos:
            continue
        vistos.add(norm)
        if bloqueado:
            resultados.append(NotaResultado(chave=norm, status=Status.INTERROMPIDA,
                                            mensagem="Não consultada: SEFAZ sinalizou consumo indevido (656)."))
            continue
        r = buscar_nota(norm, cfg)
        log.info("%s -> %s %s", r.chave, r.status.value, r.mensagem)
        resultados.append(r)
        if r.c_stat == "656":
            bloqueado = True
            log.warning("cStat 656: interrompendo lote. Aguarde ~1h antes de nova tentativa.")
        if r.status not in (Status.CHAVE_INVALIDA, Status.JA_EXISTIA):
            time.sleep(cfg.intervalo_seg)
    return resultados
