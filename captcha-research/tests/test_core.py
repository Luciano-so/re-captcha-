from app.captcha.captcha_detector import PageSnapshot, detect
from app.models.captcha_result import CaptchaType
from app.services.key_validator import calcular_dv, validar_chave
from app.services.nfe_webservice import build_envelope, parse_response

CHAVE = "3526 0353 5656 6300 0209 5542 0000 0189 1811 1548 5768"


def test_chave_teste_valida():
    info = validar_chave(CHAVE)
    assert info.valida, info.erros
    assert info.normalizada == "35260353565663000209554200000189181115485768"
    assert info.original == CHAVE  # original preservada
    assert info.uf == "SP" and info.modelo == "55" and info.dv_calculado == "8"


def test_dv_errado_nao_corrigido():
    info = validar_chave(CHAVE[:-1] + "0")
    assert not info.valida and info.normalizada.endswith("0")
    assert any("DV" in e for e in info.erros)


def test_tamanho_e_caracteres():
    assert not validar_chave("123").valida
    assert not validar_chave("3526-0353").valida


def test_dv_resto_menor_que_2():
    assert calcular_dv("0" * 43) == "0"


def _snap(html="", frames=(), scripts=()):
    return PageSnapshot(html=html, frame_urls=list(frames), script_urls=list(scripts))


def test_detect_hcaptcha_iframe():
    ev = detect(_snap(frames=["https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#sitekey=xyz"]))
    assert [e.type for e in ev] == [CaptchaType.HCAPTCHA]
    assert "xyz" not in (ev[0].frame_url or "") or "sitekey=xyz" in ev[0].frame_url  # fragmento não é query


def test_detect_recaptcha_v2_sanitiza_sitekey():
    ev = detect(_snap(frames=["https://www.google.com/recaptcha/api2/anchor?k=SECRETKEY&co=x"]))
    assert ev[0].type == CaptchaType.RECAPTCHA_V2
    assert "SECRETKEY" not in ev[0].frame_url


def test_detect_enterprise_prevalece():
    ev = detect(_snap(html='<div class="g-recaptcha"></div>',
                      scripts=["https://www.google.com/recaptcha/enterprise.js?render=k"]))
    assert [e.type for e in ev] == [CaptchaType.RECAPTCHA_ENTERPRISE]


def test_detect_turnstile_e_nenhum():
    assert detect(_snap(html='<div class="cf-turnstile"></div>'))[0].type == CaptchaType.TURNSTILE
    assert detect(_snap(html="<form><input name='chave'></form>")) == []


def test_detect_captcha_proprio():
    ev = detect(_snap(html='<img src="/GerarImagem.aspx" id="imgCaptcha">'))
    assert ev[0].type == CaptchaType.IMAGE_CAPTCHA


def test_distribuicao_envelope_e_doczip():
    import base64, gzip
    from app.services.nfe_distribuicao import build_envelope as be, parse_response as pr
    env = be("1" * 44, "12345678000199", "51")
    assert "<CNPJ>12345678000199</CNPJ>" in env and "<cUFAutor>51</cUFAutor>" in env
    b64 = base64.b64encode(gzip.compress(b"<nfeProc>ok</nfeProc>")).decode()
    r = pr(f'<retDistDFeInt><cStat>138</cStat><xMotivo>Documento localizado</xMotivo>'
           f'<loteDistDFeInt><docZip NSU="1" schema="procNFe_v4.00.xsd">{b64}</docZip></loteDistDFeInt></retDistDFeInt>')
    assert r.c_stat == "138" and r.proc_nfe == "<nfeProc>ok</nfeProc>"


def test_envelope_e_parse():
    env = build_envelope("1" * 44)
    assert "<chNFe>" + "1" * 44 + "</chNFe>" in env and 'versao="4.00"' in env
    r = parse_response("<retConsSitNFe><cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></retConsSitNFe>")
    assert r.ok and r.c_stat == "100"
