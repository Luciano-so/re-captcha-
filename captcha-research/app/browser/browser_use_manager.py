"""Navegação assistida por IA (Browser Use), opcional.

Roda em sessão de navegador PRÓPRIA, nunca compartilhada com o Playwright,
e somente depois que a sessão Playwright foi encerrada.
Exige uma chave de LLM no .env; sem ela, o módulo é ignorado.
A tarefa instrui explicitamente a NÃO interagir com CAPTCHAs.
"""
from __future__ import annotations

import os

TASK_TEMPLATE = (
    "Abra {url}. Descreva os campos do formulário de consulta de NF-e, "
    "os botões e se existe CAPTCHA. NÃO tente resolver, clicar ou contornar CAPTCHA. "
    "NÃO envie o formulário. Liste também links para documentação técnica, "
    "web services ou manuais de integração encontrados na página."
)


class BrowserUseManager:
    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("BROWSER_USE_MODEL", "claude-sonnet-5-5")

    @property
    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import browser_use  # noqa: F401
        except ImportError:
            return False
        return True

    async def describe_page(self, url: str) -> str:
        if not self.available:
            return "Browser Use indisponível (sem chave de LLM ou pacote não instalado)."
        from browser_use import Agent

        if os.getenv("ANTHROPIC_API_KEY"):
            from browser_use import ChatAnthropic as Chat
        else:
            from browser_use import ChatOpenAI as Chat
        agent = Agent(task=TASK_TEMPLATE.format(url=url), llm=Chat(model=self.model))
        history = await agent.run(max_steps=8)
        return history.final_result() or "Sem resultado final do agente."
