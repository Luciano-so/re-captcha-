from app.models.captcha_result import OfficialAlternative
from app.portals.base import PortalDefinition
from app.portals.nfe_portal import WS_CONSULTA_PROTOCOLO

PORTAL = PortalDefinition(
    key="sefaz-mt",
    nome="SEFAZ-MT - Consulta NF-e",
    url_consulta="https://www.sefaz.mt.gov.br/nfe/portal/consultanfe",
    campo_chave=["input[name*='chave' i]", "input[id*='chave' i]"],
    alternativas=[
        OfficialAlternative(
            nome="Web service NfeConsulta4 da SEFAZ-MT",
            url_documentacao="https://www.nfe.fazenda.gov.br/portal/webServices.aspx",
            requisitos="Certificado digital ICP-Brasil. Atende apenas NF-e autorizadas pela SEFAZ-MT (cUF 51).",
        ),
    ],
    observacoes="Portal estadual: só responde por NF-e emitidas em MT.",
    ufs_atendidas={"MT"},
    ws_consulta={"MT": WS_CONSULTA_PROTOCOLO["MT"]},
)
