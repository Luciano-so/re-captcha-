from app.models.captcha_result import OfficialAlternative
from app.portals.base import PortalDefinition

# A Receita Federal não mantém consulta de NF-e separada: o Portal Nacional da NF-e
# (nfe.fazenda.gov.br) é o serviço da RFB/ENCAT. Aqui apenas registramos isso.
PORTAL = PortalDefinition(
    key="receita",
    nome="Receita Federal do Brasil",
    url_consulta=None,
    alternativas=[
        OfficialAlternative(
            nome="Mesmos web services do Portal Nacional da NF-e (Ambiente Nacional)",
            url_documentacao="https://www.nfe.fazenda.gov.br/portal/webServices.aspx",
            requisitos="Certificado digital ICP-Brasil.",
        ),
    ],
    observacoes="Sem consulta própria de chave de NF-e; ver Portal Nacional da NF-e.",
)
