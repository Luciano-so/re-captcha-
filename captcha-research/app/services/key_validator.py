"""Validação da chave de acesso NF-e (44 dígitos, DV módulo 11)."""
from __future__ import annotations

import re
from dataclasses import dataclass

UF_CODES = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


@dataclass(frozen=True)
class ChaveInfo:
    original: str
    normalizada: str
    valida: bool
    erros: tuple[str, ...]
    uf: str | None = None
    ano_mes: str | None = None
    cnpj: str | None = None
    modelo: str | None = None
    serie: str | None = None
    numero: str | None = None
    tp_emis: str | None = None
    codigo_numerico: str | None = None
    dv_informado: str | None = None
    dv_calculado: str | None = None


def calcular_dv(chave43: str) -> str:
    """DV pelo módulo 11, pesos 2..9 da direita para a esquerda."""
    if len(chave43) != 43 or not chave43.isdigit():
        raise ValueError("Base do DV deve ter 43 dígitos numéricos")
    total, peso = 0, 2
    for d in reversed(chave43):
        total += int(d) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = total % 11
    return "0" if resto < 2 else str(11 - resto)


def validar_chave(chave: str) -> ChaveInfo:
    """Remove somente espaços; qualquer outro caractere é reportado como erro (sem correção silenciosa)."""
    normalizada = re.sub(r"\s+", "", chave or "")
    erros: list[str] = []
    if not normalizada.isdigit():
        erros.append("Chave contém caracteres não numéricos")
    if len(normalizada) != 44:
        erros.append(f"Chave deve ter 44 dígitos (tem {len(normalizada)})")
    if erros:
        return ChaveInfo(chave, normalizada, False, tuple(erros))

    cuf = normalizada[0:2]
    dv_calc = calcular_dv(normalizada[:43])
    if cuf not in UF_CODES:
        erros.append(f"Código de UF inválido: {cuf}")
    if normalizada[20:22] not in ("55", "65"):
        erros.append(f"Modelo {normalizada[20:22]} não é NF-e (55) nem NFC-e (65)")
    if dv_calc != normalizada[43]:
        erros.append(f"DV inválido: informado {normalizada[43]}, calculado {dv_calc}")

    return ChaveInfo(
        original=chave,
        normalizada=normalizada,
        valida=not erros,
        erros=tuple(erros),
        uf=UF_CODES.get(cuf),
        ano_mes=normalizada[2:6],
        cnpj=normalizada[6:20],
        modelo=normalizada[20:22],
        serie=normalizada[22:25],
        numero=normalizada[25:34],
        tp_emis=normalizada[34],
        codigo_numerico=normalizada[35:43],
        dv_informado=normalizada[43],
        dv_calculado=dv_calc,
    )
