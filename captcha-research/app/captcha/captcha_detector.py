"""Detecção passiva de CAPTCHA a partir do DOM e das URLs dos frames.

Apenas lê a página: não interage com o desafio nem extrai tokens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.captcha_result import CaptchaEvidence, CaptchaType

# (tipo, regex aplicado ao HTML ou à URL de frame/script)
SIGNATURES: list[tuple[CaptchaType, re.Pattern[str]]] = [
    (CaptchaType.RECAPTCHA_ENTERPRISE, re.compile(r"recaptcha/enterprise(\.js)?|grecaptcha\.enterprise", re.I)),
    (CaptchaType.RECAPTCHA_V3, re.compile(r"recaptcha/api\.js\?[^\"']*render=(?!explicit)[\w-]+", re.I)),
    (CaptchaType.RECAPTCHA_V2, re.compile(r"class=[\"'][^\"']*g-recaptcha|recaptcha/api2/anchor|www\.(google|recaptcha)\.(com|net)/recaptcha/api\.js", re.I)),
    (CaptchaType.HCAPTCHA, re.compile(r"hcaptcha\.com/(1/api\.js|captcha)|class=[\"'][^\"']*h-captcha|newassets\.hcaptcha\.com", re.I)),
    (CaptchaType.TURNSTILE, re.compile(r"challenges\.cloudflare\.com/turnstile|class=[\"'][^\"']*cf-turnstile", re.I)),
    (CaptchaType.CLOUDFLARE_CHALLENGE, re.compile(r"cdn-cgi/challenge-platform|cf-chl-|Just a moment\.\.\.", re.I)),
    (CaptchaType.IMAGE_CAPTCHA, re.compile(r"<img[^>]+(captcha|imagemValidacao|GerarImagem)[^>]*>|id=[\"'][^\"']*captcha[^\"']*[\"']", re.I)),
]


@dataclass
class PageSnapshot:
    html: str
    frame_urls: list[str]
    script_urls: list[str]


def detect(snapshot: PageSnapshot) -> list[CaptchaEvidence]:
    found: dict[CaptchaType, CaptchaEvidence] = {}
    sources = [("html", snapshot.html)]
    sources += [("frame", u) for u in snapshot.frame_urls]
    sources += [("script", u) for u in snapshot.script_urls]

    for kind, text in sources:
        for ctype, pattern in SIGNATURES:
            if ctype in found:
                continue
            m = pattern.search(text)
            if m:
                found[ctype] = CaptchaEvidence(
                    type=ctype,
                    element=f"{kind}: {_sanitize(m.group(0))}",
                    frame_url=_sanitize(text) if kind == "frame" else None,
                )

    # reCAPTCHA Enterprise/v3 também batem na assinatura v2 genérica: manter o mais específico.
    if {CaptchaType.RECAPTCHA_ENTERPRISE, CaptchaType.RECAPTCHA_V3} & found.keys():
        found.pop(CaptchaType.RECAPTCHA_V2, None)
    # Captcha próprio só se não houver provedor de terceiros (ids "captcha" são genéricos).
    if len(found) > 1:
        found.pop(CaptchaType.IMAGE_CAPTCHA, None)
    return list(found.values())


_SECRET_PARAMS = re.compile(r"([?&](k|sitekey|token|c|v|co|hl)=)[^&\"'\s]+", re.I)


def _sanitize(text: str) -> str:
    """Remove valores de parâmetros (sitekeys/tokens) das evidências."""
    return _SECRET_PARAMS.sub(r"\1***", text)[:200]
