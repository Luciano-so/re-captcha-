"""Cadastro de clientes (um certificado por CNPJ) e escolha do certificado por nota."""
from __future__ import annotations

import json
import os
import ssl
from pathlib import Path

from pydantic import BaseModel

from app.services.certificados import criar_ssl_context

ROOT = Path(__file__).resolve().parents[2]
CLIENTES_PADRAO = ROOT / "config" / "clientes.json"


class Cliente(BaseModel):
    nome: str
    cnpj_cpf: str           # CNPJ/CPF do certificado (só números)
    cuf: str                # código IBGE da UF do cliente (ex.: 51 = MT)
    pfx: Path               # caminho do certificado A1
    senha_env: str          # NOME da variável de ambiente com a senha (nunca a senha)
    codigo_dominio: str | None = None  # código da empresa no sistema contábil (coluna 'Cód. Domínio')
    ativo: bool = True

    @property
    def raiz(self) -> str:
        return self.cnpj_cpf[:8] if len(self.cnpj_cpf) == 14 else self.cnpj_cpf


class Clientes:
    def __init__(self, clientes: list[Cliente], ca_bundle: str | None = None):
        self.lista = [c for c in clientes if c.ativo]
        self.ca_bundle = ca_bundle
        self._ctx: dict[str, ssl.SSLContext] = {}

    @classmethod
    def carregar(cls, arquivo: Path = CLIENTES_PADRAO) -> "Clientes":
        if not arquivo.exists():
            raise ValueError(f"Cadastro não encontrado: {arquivo} (copie config/clientes.example.json)")
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        lista = [Cliente(**c) for c in dados]
        for c in lista:
            if not c.pfx.is_absolute():
                c.pfx = ROOT / c.pfx
        return cls(lista, os.getenv("NFE_CA_BUNDLE") or None)

    def por_documento(self, cnpj_cpf: str) -> Cliente | None:
        doc = "".join(ch for ch in cnpj_cpf if ch.isdigit())
        exato = next((c for c in self.lista if c.cnpj_cpf == doc), None)
        if exato or len(doc) != 14:
            return exato
        return next((c for c in self.lista if c.raiz == doc[:8]), None)  # filial da mesma raiz

    def por_dominio(self, codigo: str) -> Cliente | None:
        return next((c for c in self.lista if c.codigo_dominio and c.codigo_dominio == codigo.strip()), None)

    def escolher(self, chave: str, cnpj_informado: str | None = None) -> tuple[Cliente, str] | None:
        """Retorna (cliente, documento a informar no pedido).
        1) CNPJ informado na lista (ex.: destinatário); 2) emitente da chave; 3) cliente único."""
        if cnpj_informado:
            c = self.por_documento(cnpj_informado)
            return (c, "".join(ch for ch in cnpj_informado if ch.isdigit())) if c else None
        emitente = chave[6:20]
        c = self.por_documento(emitente)
        if c:
            return c, emitente
        if len(self.lista) == 1:
            return self.lista[0], self.lista[0].cnpj_cpf
        return None

    def ssl_context(self, c: Cliente) -> ssl.SSLContext:
        if c.cnpj_cpf not in self._ctx:
            senha = os.getenv(c.senha_env)
            if senha is None:
                raise ValueError(f"Variável {c.senha_env} (senha de {c.nome}) não definida")
            self._ctx[c.cnpj_cpf] = criar_ssl_context(c.pfx, senha, self.ca_bundle)
        return self._ctx[c.cnpj_cpf]
