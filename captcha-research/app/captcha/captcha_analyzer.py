from __future__ import annotations

from app.models.captcha_result import CaptchaEvidence, CaptchaResult, CaptchaType

_NOTES = {
    CaptchaType.HCAPTCHA: "hCaptcha exige interação/validação humana; não há modo de teste em produção.",
    CaptchaType.RECAPTCHA_V2: "reCAPTCHA v2 exige interação humana; chaves de teste só valem em sites próprios.",
    CaptchaType.RECAPTCHA_V3: "reCAPTCHA v3 pontua comportamento; automação legítima não é garantida.",
    CaptchaType.RECAPTCHA_ENTERPRISE: "reCAPTCHA Enterprise com avaliação de risco no servidor do portal.",
    CaptchaType.TURNSTILE: "Cloudflare Turnstile; automação depende de liberação do operador do site.",
    CaptchaType.CLOUDFLARE_CHALLENGE: "Desafio Cloudflare na borda; acesso automatizado bloqueado pelo operador.",
    CaptchaType.IMAGE_CAPTCHA: "CAPTCHA próprio do portal (imagem/texto).",
}


def analyze(portal: str, url: str, evidences: list[CaptchaEvidence]) -> CaptchaResult:
    types = [e.type for e in evidences]
    if not types:
        analysis = "Nenhum mecanismo CAPTCHA detectado no DOM/frames carregados."
    else:
        analysis = " ".join(_NOTES.get(t, t.value) for t in types)
        analysis += " Bypass não é implementado; buscar alternativa oficial."
    return CaptchaResult(
        portal=portal, url=url, captcha_found=bool(types), types=types,
        evidences=evidences, analysis=analysis,
    )
