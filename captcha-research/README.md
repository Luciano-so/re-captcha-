# captcha-research

Protótipo que identifica CAPTCHAs em portais fiscais oficiais e avalia **alternativas autorizadas** de consulta de NF-e. Ele **não** resolve nem contorna CAPTCHA.

## Instalação
```
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

## Uso manual (terminal)
```
python -m app.main --portal nfe                 # Portal Nacional (padrão)
python -m app.main --portal sefaz-mt
python -m app.main --portal nfe --chave "3526 ..." --headless
python -m app.main --portal nfe --ai            # Browser Use (requer ANTHROPIC_API_KEY)
python -m pytest -q
```
Saídas: `reports/*.txt|json`, `screenshots/`, `logs/run.log`.

## Vários clientes (XML/PDF sem CAPTCHA)
1. Copie `config/clientes.example.json` para `config/clientes.json` e cadastre cada cliente: nome, CNPJ/CPF, cUF, caminho do `.pfx` e `senha_env`.
2. No `.env`, defina a senha de cada certificado na variável indicada em `senha_env`, e também `NFE_CA_BUNDLE`.
3. Comandos:
```
python -m app.main --clientes                    # confere certificados e validade
python -m app.main --lote input/chaves.txt       # linhas: chave  ou  chave;cnpj_cliente
python -m app.main --sincronizar                 # notas novas de todos os clientes (NSU)
python -m app.main --sincronizar 12345678000199  # um cliente
```
Os arquivos ficam em `downloads/<cnpj_cliente>/`: `<chave>-procNFe.xml`, `<chave>-danfe.pdf`, `<chave>-resNFe.xml` e `eventos/`. O NSU de cada cliente fica em `state/`.

Para integrar, chame `app.services.nfe_lote.buscar_notas(itens, Clientes.carregar())` e `app.services.nfe_sync.sincronizar(Clientes.carregar())`. As duas funções retornam modelos Pydantic.

## Fluxo
1. Valida a chave: 44 dígitos e DV módulo 11. Só os espaços são removidos.
2. O Playwright abre o portal em modo visível, preenche a chave e **não envia** o formulário.
3. O detector lê o HTML, os iframes e os scripts (reCAPTCHA v2/v3/Enterprise, hCaptcha, Turnstile, Cloudflare e captcha próprio). Sitekeys e tokens são mascarados.
4. Quando `NFE_CERT_PEM` e `NFE_KEY_PEM` estão configurados, consulta o web service oficial `NFeConsultaProtocolo4` da UF da chave.
5. Gera um relatório por portal.

O Browser Use usa uma sessão própria e só roda depois que o Playwright fecha. As duas ferramentas nunca controlam o mesmo navegador.

## Limitações
- A consulta pública pelo navegador depende de um humano resolver o CAPTCHA.
- A consulta automatizada só é possível pelos web services, com certificado ICP-Brasil (A1 convertido para PEM).
- Os servidores SEFAZ usam a cadeia ICP-Brasil, que não vem no bundle padrão do `certifi`. É preciso instalar a AC raiz ICP-Brasil para validar o TLS. Não desative a verificação.
- O portal SEFAZ-MT só responde por NF-e de MT (cUF 51).
- A Receita Federal não tem consulta própria: o serviço dela é o Portal Nacional.
- Os endpoints dos web services devem ser conferidos em https://www.nfe.fazenda.gov.br/portal/webServices.aspx.
