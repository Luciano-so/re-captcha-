from app.services import nfe_lote
from app.services.nfe_distribuicao import DistResult
from app.services.nfe_lote import NfeConfig, Status, buscar_notas, ler_chaves

CHAVE = "35260353565663000209554200000189181115485768"


def _cfg(tmp_path):
    return NfeConfig(cert_pem="c", key_pem="k", cnpj_cpf="1" * 14, cuf_autor="51",
                     intervalo_seg=0, pasta_saida=tmp_path, gerar_pdf=False)


def test_ler_chaves(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("# comentário\n\n3526 0353;obs\n123,x\n", encoding="utf-8")
    assert ler_chaves(f) == ["3526 0353", "123"]


def test_lote_dedup_invalida_baixada_e_656(tmp_path, monkeypatch):
    chamadas = []
    outra = CHAVE[:-5] + "00000"
    outra = outra[:-1] + nfe_lote.validar_chave.__globals__["calcular_dv"](outra[:43])

    def fake(ch, *a, **k):
        chamadas.append(ch)
        if ch == CHAVE:
            return DistResult("138", "Documento localizado", [("procNFe_v4.00.xsd", "<nfeProc/>")])
        return DistResult("656", "Consumo indevido")

    monkeypatch.setattr(nfe_lote.nfe_distribuicao, "baixar_xml", fake)
    terceira = "51" + CHAVE[2:43]
    terceira += nfe_lote.validar_chave.__globals__["calcular_dv"](terceira)
    res = buscar_notas([CHAVE, CHAVE, "123", outra, terceira], _cfg(tmp_path))

    assert [r.status for r in res] == [Status.BAIXADA, Status.CHAVE_INVALIDA,
                                       Status.NAO_ENCONTRADA, Status.INTERROMPIDA]
    assert res[2].c_stat == "656" and chamadas == [CHAVE, outra]  # parou após 656
    assert (tmp_path / f"{CHAVE}-procNFe.xml").exists()

    # segunda execução: já existe, sem nova requisição
    chamadas.clear()
    assert buscar_notas([CHAVE], _cfg(tmp_path))[0].status == Status.JA_EXISTIA and not chamadas
