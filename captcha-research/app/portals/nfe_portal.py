from app.models.captcha_result import OfficialAlternative
from app.portals.base import PortalDefinition

# Endpoints oficiais NFeConsultaProtocolo4 (produção), conforme relação de
# web services publicada no Portal Nacional da NF-e. Conferir antes do uso.
WS_CONSULTA_PROTOCOLO = {
    "SP": "https://nfe.fazenda.sp.gov.br/ws/nfeconsultaprotocolo4.asmx",
    "MT": "https://nfe.sefaz.mt.gov.br/nfews/v2/services/NfeConsulta4",
}

PORTAL = PortalDefinition(
    key="nfe",
    nome="Portal Nacional da NF-e",
    url_consulta="https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=resumo",
    campo_chave=[
        "#ctl00_ContentPlaceHolder1_txtChaveAcessoResumo",
        "input[name*='ChaveAcesso']",
        "input[id*='Chave']",
    ],
    alternativas=[
        OfficialAlternative(
            nome="Web service NFeConsultaProtocolo4 (SEFAZ autorizadora da UF da chave)",
            url_documentacao="https://www.nfe.fazenda.gov.br/portal/webServices.aspx",
            requisitos="Certificado digital ICP-Brasil (e-CNPJ/e-CPF A1 ou A3) em TLS mútuo. "
                       "Sem CAPTCHA. Retorna situação/protocolo da NF-e.",
        ),
        OfficialAlternative(
            nome="Web service NFeDistribuicaoDFe (Ambiente Nacional) - consChNFe",
            url_documentacao="https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=ndIjl+iEFdE=",
            requisitos="Certificado do CNPJ/CPF que é ator da NF-e (emitente, destinatário, "
                       "transportador ou autorizado no XML). Retorna o XML/resumo.",
        ),
    ],
    observacoes="Consulta pública via navegador exige resolução humana do CAPTCHA.",
    ws_consulta=WS_CONSULTA_PROTOCOLO,
)
