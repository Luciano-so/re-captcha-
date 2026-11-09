import base64
import gzip
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

from app.services import nfe_distribuicao, nfe_lote, nfe_sync
from app.services.certificados import criar_ssl_context, validade
from app.services.clientes import Cliente, Clientes
from app.services.key_validator import calcular_dv
from app.services.nfe_distribuicao import DistResult, Documento
from app.services.nfe_lote import Status, buscar_notas, ler_itens

CHAVE = "35260353565663000209554200000189181115485768"  # emitente 53565663000209


def _chave(cnpj_emit: str) -> str:
    base = CHAVE[:6] + cnpj_emit + CHAVE[20:43]
    return base + calcular_dv(base)


def _proc(chave):
    return Documento("1", "procNFe_v4.00.xsd", f'<nfeProc><infNFe Id="NFe{chave}"/></nfeProc>')


@pytest.fixture
def clientes():
    return Clientes([
        Cliente(nome="Emitente", cnpj_cpf="53565663000209", cuf="35", pfx="a.pfx", senha_env="X"),
        Cliente(nome="Outro", cnpj_cpf="11111111000191", cuf="51", pfx="b.pfx", senha_env="Y"),
    ])


def test_ler_itens(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("# c\n\n3526 0353;11.111.111/0001-91\n123,\n456\n", encoding="utf-8")
    assert ler_itens(f) == [("3526 0353", "11.111.111/0001-91"), ("123", None), ("456", None)]


def test_escolha_de_cliente(clientes):
    assert clientes.escolher(CHAVE)[0].nome == "Emitente"
    filial = _chave("53565663000390")  # mesma raiz
    assert clientes.escolher(filial) == (clientes.lista[0], "53565663000390")
    assert clientes.escolher(_chave("22222222000100")) is None
    assert clientes.escolher(_chave("22222222000100"), "11.111.111/0001-91")[0].nome == "Outro"


def test_lote(tmp_path, monkeypatch, clientes):
    monkeypatch.setattr(Clientes, "ssl_context", lambda self, c: None)
    enviados, situacoes = [], []
    recebida_ok = _chave("44444444000100")
    recebida_656 = _chave("33333333000100")

    def fake(env, ctx, tp_amb):
        enviados.append(env)
        if recebida_ok in env:
            return DistResult("138", "Documento localizado", [_proc(recebida_ok)])
        return DistResult("656", "Consumo indevido")

    def fake_sit(ch, uf, ctx, tp_amb):
        situacoes.append(ch)
        return "AUTORIZADA", "135260000000001", "situação: cStat 100"

    monkeypatch.setattr(nfe_lote.nfe_distribuicao, "enviar", fake)
    monkeypatch.setattr(nfe_lote, "consultar_situacao", fake_sit)
    itens = [(recebida_ok, "11111111000191"), (CHAVE, None), (CHAVE, None), ("123", None),
             (_chave("22222222000100"), None), (recebida_656, "11111111000191"), (_chave("53565663000390"), None)]
    res = buscar_notas(itens, clientes, intervalo_seg=0, pasta_base=tmp_path, gerar_pdf=False)

    assert [r.status for r in res] == [Status.BAIXADA, Status.SITUACAO_CONSULTADA, Status.CHAVE_INVALIDA,
                                       Status.SEM_CLIENTE, Status.NAO_ENCONTRADA, Status.INTERROMPIDA]
    assert res[1].situacao == "AUTORIZADA" and res[1].protocolo == "135260000000001"
    assert situacoes == [CHAVE]                       # emitente: só situação, sem distribuição
    assert res[4].c_stat == "656" and len(enviados) == 2  # 656 não consulta situação e interrompe
    assert (tmp_path / "11111111000191" / f"{recebida_ok}-procNFe.xml").exists()
    # repetição não consulta de novo
    assert buscar_notas([(recebida_ok, "11111111000191")], clientes, intervalo_seg=0,
                        pasta_base=tmp_path)[0].status == Status.JA_EXISTIA and len(enviados) == 2


def test_sync_nsu(tmp_path, monkeypatch, clientes):
    monkeypatch.setattr(Clientes, "ssl_context", lambda self, c: None)
    monkeypatch.setattr(nfe_sync, "STATE", tmp_path / "state")
    respostas = iter([
        DistResult("138", "ok", [_proc(CHAVE)], ult_nsu="000000000000005", max_nsu="000000000000009"),
        DistResult("138", "ok", [], ult_nsu="000000000000009", max_nsu="000000000000009"),
    ])
    pedidos = []
    monkeypatch.setattr(nfe_sync.nfe_distribuicao, "enviar", lambda env, *a: (pedidos.append(env), next(respostas))[1])
    c = clientes.lista[0]
    r = nfe_sync.sincronizar_cliente(c, clientes, intervalo_seg=0, pasta_base=tmp_path)
    assert r.documentos == 1 and r.xml_completos == 1 and r.ult_nsu == "000000000000009"
    assert "<ultNSU>000000000000000</ultNSU>" in pedidos[0] and "<ultNSU>000000000000005</ultNSU>" in pedidos[1]
    # alcançou maxNSU: próxima consulta só após 1h
    assert nfe_sync.sincronizar_cliente(c, clientes, pasta_base=tmp_path).mensagem.startswith("Aguardando")
    assert len(pedidos) == 2


def test_parse_nsu():
    b64 = base64.b64encode(gzip.compress(b"<resNFe><chNFe>" + CHAVE.encode() + b"</chNFe></resNFe>")).decode()
    r = nfe_distribuicao.parse_response(
        f'<cStat>138</cStat><ultNSU>000000000000007</ultNSU><maxNSU>000000000000010</maxNSU>'
        f'<docZip NSU="000000000000007" schema="resNFe_v1.01.xsd">{b64}</docZip>')
    assert r.ult_nsu == "000000000000007" and r.docs[0].tipo == "resNFe" and r.docs[0].chave == CHAVE


def test_pfx_para_ssl_context(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TESTE:53565663000209")])
    agora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(key.public_key())
            .serial_number(1).not_valid_before(agora).not_valid_after(agora + timedelta(days=30))
            .sign(key, hashes.SHA256()))
    pfx = tmp_path / "t.pfx"
    pfx.write_bytes(pkcs12.serialize_key_and_certificates(b"t", key, cert, None, BestAvailableEncryption(b"senha")))
    assert criar_ssl_context(pfx, "senha") is not None
    assert validade(pfx, "senha").date() == (agora + timedelta(days=30)).date()
    assert not list(tmp_path.glob("*.pem"))
    with pytest.raises(ValueError):
        criar_ssl_context(pfx, "errada")
