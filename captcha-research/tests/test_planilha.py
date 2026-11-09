import pytest

from app.services.clientes import Cliente, Clientes
from app.services.planilha import PlanilhaInvalida, ler_planilha

CAB = "Cód. Domínio\tClassificação\tChave\tNúmero\tSituação SEFAZ\n"
CH = "51261107478673000109550010002835801123456785"


@pytest.fixture
def clientes():
    return Clientes([Cliente(nome="A", cnpj_cpf="07478673000109", cuf="51", pfx="a.pfx",
                             senha_env="X", codigo_dominio="117")])


def test_cp1252_tab_emitida_e_recebida(tmp_path, clientes):
    f = tmp_path / "p.csv"
    f.write_bytes((CAB + f"117\tEmitida\t{CH}\t283580\tCOMPLETO\n117\tRecebida\t{CH[:-1]}9\t1\tCOMPLETO\n")
                  .encode("cp1252"))
    itens = ler_planilha(f, clientes)
    assert [(i.chave, i.cnpj_cliente) for i in itens] == [(CH, None), (CH[:-1] + "9", "07478673000109")]
    assert itens[0].numero == "283580" and itens[0].linha == 2


def test_gravar_resultados_csv(tmp_path, clientes):
    from app.services.nfe_lote import NotaResultado, Status
    from app.services.planilha import gravar_resultados
    f = tmp_path / "p.csv"
    original = (CAB + f"117\tEmitida\t{CH}\t283580\tCOMPLETO\n117\tEmitida\t\t1\tX\n").encode("cp1252")
    f.write_bytes(original)
    itens = ler_planilha(f, clientes)
    res = [NotaResultado(chave=CH, status=Status.BAIXADA, c_stat="138", mensagem="ação ok", xml_path="a.xml")]
    gravar_resultados(f, itens, res)
    gravar_resultados(f, itens, [res[0].model_copy(update={"status": Status.JA_EXISTIA})])  # reexecução

    assert (tmp_path / "p.csv.bak").read_bytes() == original
    linhas = f.read_bytes().decode("cp1252").splitlines()
    cab = linhas[0].split("\t")
    assert cab[5:] == ["Download status", "Download cStat", "Download mensagem", "Download XML",
                       "Download PDF", "Download em", "Situação consultada", "Protocolo"] and len(cab) == 13
    l1 = linhas[1].split("\t")
    assert l1[5:10] == ["ja_existia", "138", "ação ok", "a.xml", ""]
    assert linhas[2].split("\t")[5] == ""  # linha sem chave fica sem resultado
    assert ler_planilha(f, clientes)[0].chave == CH  # continua legível


def test_notacao_cientifica_rejeitada(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text(CAB + "117\tEmitida\t5,12611E+43\t1\tCOMPLETO\n", encoding="utf-8")
    with pytest.raises(PlanilhaInvalida, match="notação científica"):
        ler_planilha(f)


def test_sem_coluna_chave(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(PlanilhaInvalida, match="Chave"):
        ler_planilha(f)
