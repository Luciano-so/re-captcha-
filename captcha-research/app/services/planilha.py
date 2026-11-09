"""Leitura da planilha de notas (exportação do comparativo fiscal / Domínio) em CSV ou XLSX.

Colunas usadas (nomes sem diferenciar acento/maiúscula):
  Chave (obrigatória), Classificação (Emitida/Recebida), Cód. Domínio, Número, Situação SEFAZ.
Notas recebidas usam o certificado do cliente cujo 'codigo_dominio' é o 'Cód. Domínio' da linha.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from app.services.clientes import Clientes


class ItemNota(BaseModel):
    linha: int
    chave: str
    cnpj_cliente: str | None = None
    classificacao: str = ""
    numero: str = ""
    situacao_sefaz: str = ""


class PlanilhaInvalida(ValueError):
    pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


COLUNAS = {"chave": "chave", "chavedeacesso": "chave", "classificacao": "classificacao",
           "coddominio": "dominio", "codigodominio": "dominio", "numero": "numero",
           "situacaosefaz": "situacao"}


def _abrir_csv(arquivo: Path) -> tuple[list[list[str]], str, str]:
    """Retorna (linhas, encoding, delimitador)."""
    raw = arquivo.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    for enc in ("utf-8-sig" if bom else "utf-8", "cp1252"):
        try:
            texto = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    delim = csv.Sniffer().sniff(texto.splitlines()[0], delimiters="\t;,").delimiter
    return list(csv.reader(io.StringIO(texto), delimiter=delim)), enc, delim


def _linhas_csv(arquivo: Path) -> list[list[str]]:
    return _abrir_csv(arquivo)[0]


def _linhas_xlsx(arquivo: Path) -> list[list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise PlanilhaInvalida("Para .xlsx instale: pip install openpyxl") from e
    ws = load_workbook(arquivo, read_only=True, data_only=True).active
    out = []
    for row in ws.iter_rows(values_only=True):
        cel = []
        for v in row:
            if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) > 1e15:
                cel.append(f"{v:E}")  # número grande = precisão já perdida no Excel
            else:
                cel.append("" if v is None else str(v))
        out.append(cel)
    return out


def ler_planilha(arquivo: Path, clientes: Clientes | None = None) -> list[ItemNota]:
    linhas = _linhas_xlsx(arquivo) if arquivo.suffix.lower() in (".xlsx", ".xlsm") else _linhas_csv(arquivo)
    if not linhas:
        raise PlanilhaInvalida("Planilha vazia")
    idx = {COLUNAS[_norm(h)]: i for i, h in enumerate(linhas[0]) if _norm(h) in COLUNAS}
    if "chave" not in idx:
        raise PlanilhaInvalida(f"Coluna 'Chave' não encontrada. Cabeçalho: {linhas[0]}")

    def get(row, campo):
        i = idx.get(campo)
        return row[i].strip() if i is not None and i < len(row) else ""

    itens, cientificas = [], []
    for n, row in enumerate(linhas[1:], start=2):
        chave = get(row, "chave")
        if not chave:
            continue
        if re.search(r"\d[,.]\d+E\+?\d+", chave, re.I):
            cientificas.append(n)
            continue
        classif = get(row, "classificacao")
        cnpj = None
        if clientes and _norm(classif).startswith(("recebid", "entrad")):
            c = clientes.por_dominio(get(row, "dominio"))
            cnpj = c.cnpj_cpf if c else None
        itens.append(ItemNota(linha=n, chave=chave, cnpj_cliente=cnpj, classificacao=classif,
                              numero=get(row, "numero"), situacao_sefaz=get(row, "situacao")))
    if cientificas:
        raise PlanilhaInvalida(
            f"{len(cientificas)} chave(s) em notação científica (ex.: linha {cientificas[0]}). "
            "O Excel arredondou os 44 dígitos e a chave original foi perdida. Exporte novamente "
            "com a coluna 'Chave' como TEXTO (ou abra o CSV sem passar pelo Excel).")
    return itens


COLUNAS_RESULTADO = ["Download status", "Download cStat", "Download mensagem",
                     "Download XML", "Download PDF", "Download em",
                     "Situação consultada", "Protocolo"]


def gravar_resultados(arquivo: Path, itens: list[ItemNota], resultados: list) -> Path:
    """Escreve o resultado de cada nota em colunas no final da planilha (mesmo formato).
    Faz backup do original em <arquivo>.bak na primeira vez. Reexecuções atualizam as colunas."""
    from datetime import datetime

    por_chave = {r.chave: r for r in resultados}
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    def valores(item: ItemNota) -> list[str] | None:
        r = por_chave.get("".join(item.chave.split()))
        if r is None:
            return None
        return [r.status.value, r.c_stat or "", r.mensagem, r.xml_path or "", r.pdf_path or "", agora,
                getattr(r, "situacao", None) or "", getattr(r, "protocolo", None) or ""]

    backup = arquivo.with_name(arquivo.name + ".bak")
    if not backup.exists():
        backup.write_bytes(arquivo.read_bytes())

    xlsx = arquivo.suffix.lower() in (".xlsx", ".xlsm")
    if xlsx:
        from openpyxl import load_workbook
        wb = load_workbook(arquivo)
        ws = wb.active
        cab = [c.value or "" for c in ws[1]]
    else:
        linhas, enc, delim = _abrir_csv(arquivo)
        cab = linhas[0]

    # posição de cada coluna de resultado (reaproveita se já existir)
    pos = {}
    for nome in COLUNAS_RESULTADO:
        if nome in cab:
            pos[nome] = cab.index(nome)
        else:
            cab.append(nome)
            pos[nome] = len(cab) - 1

    if xlsx:
        for nome, i in pos.items():
            ws.cell(row=1, column=i + 1, value=nome)
        for item in itens:
            v = valores(item)
            if v:
                for nome, val in zip(COLUNAS_RESULTADO, v):
                    ws.cell(row=item.linha, column=pos[nome] + 1, value=val)
        wb.save(arquivo)
        return arquivo

    linhas[0] = cab
    for row in linhas[1:]:
        if row:
            row.extend([""] * (len(cab) - len(row)))
    for item in itens:
        v = valores(item)
        if not v:
            continue
        row = linhas[item.linha - 1]
        row.extend([""] * (len(cab) - len(row)))
        for nome, val in zip(COLUNAS_RESULTADO, v):
            row[pos[nome]] = val
    buf = io.StringIO()
    csv.writer(buf, delimiter=delim, lineterminator="\r\n").writerows(linhas)
    arquivo.write_bytes(buf.getvalue().encode(enc, errors="replace"))
    return arquivo
