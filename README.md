# InsightZone WhatsApp

Serviço de business intelligence entregue directamente pelo WhatsApp Business. O cliente envia um ficheiro de vendas e recebe automaticamente um relatório PDF profissional com os insights da semana — sem instalar nada, sem fazer login em nenhum portal, sem aprender nenhuma ferramenta nova.

---

## Índice

- [Visão Geral](#visão-geral)
- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Estrutura do Projecto](#estrutura-do-projecto)
- [Pipeline de Dados](#pipeline-de-dados)
- [Comandos do Bot](#comandos-do-bot)
- [Segurança](#segurança)
- [Base de Dados](#base-de-dados)
- [Execução Local](#execução-local)
- [Deploy em Produção](#deploy-em-produção)
- [Troubleshooting](#troubleshooting)
- [Modelo de Negócio](#modelo-de-negócio)

---

## Visão Geral

O InsightZone recebe ficheiros de vendas (CSV, Excel ou PDF com texto seleccionável) enviados pelo WhatsApp, processa os dados através de um pipeline automatizado e devolve um relatório PDF profissional ao remetente — tudo em menos de 60 segundos.

O produto foi desenhado para o mercado africano, onde o WhatsApp é o canal de comunicação dominante para pequenas e médias empresas. A proposta de valor assenta na ausência total de fricção de adopção: o cliente já usa o WhatsApp e não precisa de aprender nenhuma ferramenta nova.

---

## Arquitectura

```
Cliente (WhatsApp)
    |
    | envia ficheiro CSV / Excel / PDF
    v
Meta Cloud API
    |
    | webhook POST
    v
FastAPI (app.py)
    |
    |__ pipeline/reader.py      lê o ficheiro, normaliza colunas, devolve DataFrame
    |__ pipeline/metrics.py     calcula métricas, liberta DataFrame com gc.collect()
    |__ pipeline/report.py      gera PDF com ReportLab (imports lazy)
    |__ pipeline/storage.py     faz upload do PDF para o Cloudinary, devolve URL público
    |__ pipeline/sender.py      envia PDF via Meta Cloud API
    |
    | PDF enviado para Cloudinary
    | URL permanente enviado ao cliente pelo WhatsApp
    v
Cliente recebe PDF no WhatsApp
```

O FastAPI responde imediatamente com `200 OK` à Meta e processa o ficheiro em background via `BackgroundTasks`, evitando timeouts no webhook.

O APScheduler corre dentro do FastAPI e envia relatórios automaticamente de forma diária, semanal ou mensal para todos os clientes registados.

---

## Requisitos

- Python 3.11 ou superior
- Conta Meta for Developers com app WhatsApp Business configurada
- Base de dados PostgreSQL (Render free tier disponível)
- Conta Cloudinary para armazenamento de PDFs (free tier disponível)
- ngrok (para desenvolvimento local) ou servidor com URL público (produção)

---

## Instalação

```bash
# Clonar o repositório
git clone https://github.com/o-teu-utilizador/insightzone.git
cd insightzone

# Criar e activar ambiente virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# Instalar dependências
pip install -r requirements.txt
```

---

## Configuração

Cria um ficheiro `.env` na raiz do projecto com as seguintes variáveis:

```env
META_ACCESS_TOKEN=o_teu_token_aqui
META_PHONE_NUMBER_ID=o_teu_phone_number_id
META_WABA_ID=o_teu_waba_id
META_APP_SECRET=o_teu_app_secret
WEBHOOK_VERIFY_TOKEN=token_que_defines
DATABASE_URL=postgresql://user:password@host:5432/insightzone_db
CLOUD_NAME=o_teu_cloud_name
API_KEY=a_tua_api_key
API_SECRET=o_teu_api_secret
```

### Obter as credenciais Meta

1. Acede a [developers.facebook.com](https://developers.facebook.com)
2. Cria uma app com o use case "Connect with customers through WhatsApp"
3. Em **API Setup**, gera um access token temporário (válido 24 horas para testes)
4. Para produção, cria um token permanente através do System User no Business Manager
5. Copia o **Phone Number ID** e o **WhatsApp Business Account ID** da mesma página
6. Em **App Settings → Basic**, copia o **App Secret** para a variável `META_APP_SECRET`

> **Atenção:** O Phone Number ID e o WhatsApp Business Account ID são valores distintos. Confirma os valores correctos correndo este comando após configurar o `.env`:
> ```bash
> python -c "import httpx, os; from dotenv import load_dotenv; load_dotenv(); r = httpx.get('https://graph.facebook.com/v25.0/' + os.getenv('META_WABA_ID') + '/phone_numbers', headers={'Authorization': 'Bearer ' + os.getenv('META_ACCESS_TOKEN')}); print(r.json())"
> ```

### Obter as credenciais Cloudinary

1. Cria conta gratuita em [cloudinary.com](https://cloudinary.com)
2. No dashboard vai a **Settings → API Keys**
3. Copia `Cloud Name`, `API Key` e `API Secret` para o `.env` como `CLOUD_NAME`, `API_KEY` e `API_SECRET`

### Configurar o webhook

1. Corre o servidor localmente com ngrok a expor a porta 8000
2. Em Configuration, preenche o Callback URL com `https://o-teu-ngrok-url/webhook`
3. Preenche o Verify Token com o valor de `WEBHOOK_VERIFY_TOKEN`
4. Clica "Verify and save" e subscreve o campo `messages`

---

## Estrutura do Projecto

```
insightzone/
|
|__ app.py                  ponto de entrada FastAPI, webhook, comandos, onboarding
|__ scheduler.py            APScheduler, envio automático diário/semanal/mensal
|__ criar_tabela.py         script único para criar/migrar a tabela na base de dados
|__ requirements.txt        dependências Python com versões fixas
|__ .env                    credenciais (nunca commitar)
|__ .gitignore
|
|__ pipeline/
|   |__ __init__.py
|   |__ reader.py           leitura de CSV, Excel e PDF com normalização automática de colunas
|   |__ metrics.py          cálculo de métricas de vendas, libertação de memória com gc
|   |__ report.py           geração do relatório PDF com ReportLab (imports lazy)
|   |__ storage.py          upload de PDFs para o Cloudinary, devolve URL público permanente
|   |__ sender.py           envio de mensagens e PDFs via Meta API, com retry automático
|
|__ tests/
|   |__ test_insightzone.py suite de 21 testes (metrics, reader, sender)
|
|__ data/
|   |__ uploads/            ficheiros temporários — apagados automaticamente após processamento
```

> **Nota:** O sistema de ficheiros do Render é efémero — ficheiros guardados em disco desaparecem a cada deploy ou restart. Os PDFs são enviados para o Cloudinary imediatamente após geração e o ficheiro local é apagado. Apenas a pasta `data/uploads/` é usada, exclusivamente para ficheiros temporários durante o processamento.

---

## Pipeline de Dados

O pipeline segue a arquitectura medalhão (bronze, silver, gold):

| Camada | Responsabilidade | Destino |
|--------|-----------------|---------|
| Bronze | Ficheiro bruto do cliente normalizado em DataFrame | memória |
| Silver | DataFrame validado — linhas com valores inválidos rejeitadas | memória |
| Gold | Relatório PDF gerado com ReportLab | Cloudinary |

### Schema do ficheiro do cliente

O bot identifica automaticamente as colunas do ficheiro enviado pelo cliente usando heurística — não é necessário seguir um formato exacto. O schema abaixo é o formato recomendado para melhores resultados:

**Negócios de retalho / agropecuária:**

| Coluna | Tipo | Exemplo |
|--------|------|---------|
| data | texto ou data | 2026-05-17 |
| produto | texto | Frango Grelhado |
| quantidade | inteiro | 3 |
| valor | decimal | 250.00 |

**Negócios de serviços:**

| Coluna | Tipo | Exemplo |
|--------|------|---------|
| data | texto ou data | 2026-05-17 |
| servico | texto | Consultoria |
| quantidade | inteiro | 1 |
| valor | decimal | 5000.00 |

Colunas com nomes alternativos como `Date`, `Item`, `Qty`, `Total`, `Price`, `Description`, `Service` são detectadas e mapeadas automaticamente.

### Métricas calculadas

- Faturação total do período
- Total de transacções
- Ticket médio por transacção
- Melhor dia do período
- Top 5 produtos ou serviços por quantidade
- Hora de pico (relatórios diários, quando disponível)
- Variação percentual face ao dia anterior (relatórios diários, quando disponível)

---

## Comandos do Bot

| O cliente envia | O bot responde |
|----------------|---------------|
| olá / oi / hello / bom dia | Menu de opções |
| ficheiro CSV, Excel ou PDF | Processamento automático e entrega do PDF |
| relatorio / 2 | PDF do último relatório gerado |
| resumo / 3 | Três KPIs principais em texto simples |
| top / 4 | Top 5 produtos ou serviços do período |
| vendas / 5 | Introduzir vendas manualmente por texto |
| frequencia / 6 | Alterar cadência dos relatórios automáticos |

### Introdução de vendas por texto (comando 5)

O cliente pode introduzir vendas sem ficheiro, no formato:

```
produto, quantidade, valor

Frango, 3, 250
Arroz, 5, 150
Feijao, 2, 80
```

Para serviços, o formato é idêntico com a coluna `servico` em vez de `produto`.

### Onboarding

Quando um número novo envia a primeira mensagem, o bot inicia um fluxo de onboarding de três passos antes de aceitar ficheiros:

1. Nome do negócio
2. Tipo de negócio (Serviços, Retalho, Agropecuária, Outro)
3. Cadência de relatórios (Diária, Semanal ou Mensal)

O estado do onboarding é persistido na base de dados PostgreSQL através do campo `onboarding_passo`. O valor `0` indica onboarding completo.

---

## Segurança

### Rate Limiting

O endpoint `/webhook` está protegido com `slowapi` — máximo de 20 pedidos por minuto por IP. Pedidos acima desse limite recebem `429 Too Many Requests` automaticamente.

### Verificação de Assinatura SHA-256

Cada pedido da Meta vem assinado com o `META_APP_SECRET` no header `X-Hub-Signature-256`. O InsightZone verifica esta assinatura antes de processar qualquer mensagem — pedidos sem assinatura válida recebem `403 Assinatura inválida`.

O `META_APP_SECRET` encontra-se em **App Settings → Basic → App Secret** no dashboard da Meta.

### Deduplicação de mensagens

Cada mensagem do WhatsApp tem um `message_id` único. O InsightZone mantém um conjunto em memória dos IDs já processados e ignora duplicados, evitando processamento duplo em caso de reenvio pela Meta.

---

## Base de Dados

O InsightZone usa **PostgreSQL** para persistência de clientes.

### Criar ou migrar a tabela

Após configurar o `DATABASE_URL` no `.env`, corre uma única vez:

```bash
python criar_tabela.py
```

O script é idempotente — se a tabela já existir, adiciona apenas as colunas em falta sem perder dados.

### Schema da tabela `clientes`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| numero | TEXT (PK) | Número WhatsApp do cliente |
| nome | TEXT | Nome do negócio |
| negocio | TEXT | Tipo de negócio (`retalho`, `servicos`, `agropecuaria`, `outro`) |
| frequencia | TEXT | `diario`, `semanal` ou `mensal` |
| ultimo_ficheiro | TEXT | Referência ao último ficheiro processado |
| ultimo_ficheiro_url | TEXT | URL Cloudinary do último ficheiro de vendas |
| ultimo_relatorio_url | TEXT | URL Cloudinary do último relatório PDF gerado |
| onboarding_passo | INTEGER | Passo actual do onboarding (`0` = completo) |
| historico | TEXT | JSON com histórico de interacções |
| modo | TEXT | Estado temporário do bot (`aguardar_vendas`, `aguardar_frequencia`, ou `NULL`) |
| criado_em | TIMESTAMP | Data de registo |

### Criar a base de dados no Render

1. No dashboard do Render clica em **New + → PostgreSQL**
2. Nome: `insightzone-db`, Region: `Frankfurt (EU Central)`, Plan: `Free`
3. Copia o **Internal Database URL** e adiciona ao `.env` como `DATABASE_URL`

---

## Execução Local

```bash
# Terminal 1 — servidor FastAPI
uvicorn app:app --reload --port 8000

# Terminal 2 — túnel ngrok
ngrok http 8000
```

O ngrok fornece um URL público que deves configurar como Callback URL no dashboard da Meta.

O token de acesso da Meta expira a cada 24 horas em modo de desenvolvimento. Para testes prolongados, cria um token permanente via System User no Meta Business Manager.

### Correr os testes

```bash
pip install pytest
pytest tests/test_insightzone.py -v
```

---

## Deploy em Produção

### Render

1. No dashboard do Render clica em **New + → Web Service**
2. Liga ao teu repositório GitHub
3. Configura:
   - **Environment:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Em **Environment Variables**, adiciona todas as variáveis do `.env`
5. Clica **Deploy**

Qualquer push para o branch `main` no GitHub dispara um deploy automático no Render.

### Variáveis de ambiente em produção

Todas as variáveis do `.env` devem ser configuradas no painel de variáveis de ambiente do Render. Nunca incluir o ficheiro `.env` no repositório.

---

## Troubleshooting

**`401 Session has expired`**
O token da Meta expirou. Vai a developers.facebook.com → InsightZone → API Setup e gera um novo token. Substitui no `.env` e reinicia o servidor.

**`Object with ID '...' does not exist`**
O `META_PHONE_NUMBER_ID` está errado. Corre o comando de verificação de credenciais acima para obter o ID correcto associado ao teu WABA.

**`403 Assinatura inválida`**
O `META_APP_SECRET` no `.env` não corresponde ao valor em App Settings → Basic no dashboard da Meta. Confirma que copiaste o valor correcto sem espaços.

**`429 Too Many Requests`**
O rate limiter bloqueou o IP. Normal em testes com muitos pedidos seguidos — aguarda 1 minuto.

**`ValueError: Colunas em falta`**
O ficheiro enviado não tem colunas reconhecíveis. Verifica o output do terminal para ver o mapeamento tentado e adiciona as palavras-chave ao `MAPA_HEURISTICA` em `reader.py`.

**Webhook não verifica (`403 Token inválido`)**
Confirma que o `WEBHOOK_VERIFY_TOKEN` no `.env` é exactamente igual ao valor preenchido no campo "Verify Token" no dashboard da Meta.

**Bot não responde após mensagem**
Verifica se o campo `messages` está subscrito no dashboard da Meta em Configuration → Webhook fields.

**PDF não chega ao cliente**
Confirma que `CLOUD_NAME`, `API_KEY` e `API_SECRET` estão definidos nas variáveis de ambiente do Render. Verifica os logs do serviço para ver se o upload ao Cloudinary retornou erro.

**Render OOM (memory limit exceeded)**
O servidor reiniciou por falta de memória. O pipeline já usa `gc.collect()` e imports lazy do ReportLab para minimizar o consumo. Se persistir, considera upgrade para o plano Starter ($7/mês, 2 GB RAM).

---

## Considerações de Segurança

- O ficheiro `.env` está incluído no `.gitignore` e nunca deve ser commitado
- O token de acesso da Meta deve ser rotacionado regularmente
- O `WEBHOOK_VERIFY_TOKEN` deve ser uma string aleatória e difícil de adivinhar
- A verificação de assinatura HMAC-SHA256 está implementada e activa em produção
- Rate limiting activo no endpoint `/webhook` (20 pedidos/minuto por IP)
- Ficheiros de upload temporários são apagados automaticamente após processamento
- O envio de mensagens e PDFs tem retry automático (3 tentativas com backoff exponencial) e para imediatamente em erros fatais (401, 403, 404)

---

## Modelo de Negócio

| Plano | Preço mensal | Inclui |
|-------|-------------|--------|
| Básico | $10 / 640 MZN | 4 relatórios por mês, alertas básicos |
| Pro | $25 / 1.600 MZN | Relatórios ilimitados, alertas avançados, suporte WhatsApp |
| Empresa | $60 / 3.840 MZN | Relatórios personalizados, onboarding dedicado |

### Custos operacionais — 10 clientes MVP

| Item | Custo mensal |
|------|-------------|
| Meta Cloud API (menos de 1.000 conversas) | $0.00 |
| Render.com (free tier) | $0.00 |
| PostgreSQL (free tier) | $0.00 |
| Cloudinary (free tier, 25 GB) | $0.00 |
| Total | $0.00 |

Com 10 clientes no plano Básico: $100/mês de receita com margem bruta de 100%.

---

## Licença

Projecto privado. Todos os direitos reservados.
