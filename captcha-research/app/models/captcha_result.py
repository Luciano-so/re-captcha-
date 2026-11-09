from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class CaptchaType(str, Enum):
    NONE = "Nenhum"
    RECAPTCHA_V2 = "Google reCAPTCHA v2"
    RECAPTCHA_V3 = "Google reCAPTCHA v3"
    RECAPTCHA_ENTERPRISE = "Google reCAPTCHA Enterprise"
    HCAPTCHA = "hCaptcha"
    TURNSTILE = "Cloudflare Turnstile"
    CLOUDFLARE_CHALLENGE = "Cloudflare challenge (JS/managed)"
    IMAGE_CAPTCHA = "CAPTCHA próprio (imagem)"
    OTHER = "Outra verificação anti-robô"


class CaptchaEvidence(BaseModel):
    type: CaptchaType
    element: str  # seletor/URL do componente (sem tokens)
    frame_url: str | None = None


class CaptchaResult(BaseModel):
    portal: str
    url: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    captcha_found: bool
    types: list[CaptchaType] = []
    evidences: list[CaptchaEvidence] = []
    analysis: str = ""


class Viabilidade(str, Enum):
    VIAVEL = "Viável"
    NAO_COMPROVADA = "Não comprovada"
    NAO_DISPONIVEL = "Não disponível"


class OfficialAlternative(BaseModel):
    nome: str
    url_documentacao: str
    requisitos: str
    implementado: bool = False


class PortalReport(BaseModel):
    portal: str
    url: str
    captcha: CaptchaResult | None = None
    consulta_concluida: bool = False
    alternativas: list[OfficialAlternative] = []
    automacao: Viabilidade = Viabilidade.NAO_COMPROVADA
    justificativa: str = ""
    evidencias: list[str] = []
    erro: str | None = None
