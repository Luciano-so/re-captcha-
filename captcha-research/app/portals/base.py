from __future__ import annotations

from dataclasses import dataclass, field

from app.models.captcha_result import OfficialAlternative


@dataclass
class PortalDefinition:
    key: str
    nome: str
    url_consulta: str | None
    campo_chave: list[str] = field(default_factory=list)
    alternativas: list[OfficialAlternative] = field(default_factory=list)
    observacoes: str = ""
    # UFs cujas NF-e este portal/web service responde (None = todas)
    ufs_atendidas: set[str] | None = None
    # endpoint SOAP oficial NFeConsultaProtocolo4 por UF (para a alternativa via certificado)
    ws_consulta: dict[str, str] = field(default_factory=dict)
