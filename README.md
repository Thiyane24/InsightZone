# InsightZone WhatsApp

Serviço de business intelligence entregue directamente pelo WhatsApp Business. O cliente envia um ficheiro de vendas e recebe automaticamente um relatório PDF profissional com os insights da semana sem instalar nada, sem fazer login em nenhum portal, sem aprender nenhuma ferramenta nova.

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

O InsightZone recebe ficheiros de vendas (CSV, Excel ou PDF com texto seleccionável) enviados pelo WhatsApp, processa os dados através de um pipeline automatizado e devolve um relatório PDF profissional ao remetente tudo em menos de 60 segundos.

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
    |__ pipeline/reader.py      lê o ficheiro, devolve DataFrame
    |__ pipeline/metrics.py     calcula métricas, guarda parquet
    |__ pipeline/report.py      gera PDF com ReportLab
    |__ pipeline/sender.py      envia PDF via Meta Cloud API
    |
    | PDF gerado em data/gold/
    | servido em /reports/ via StaticFiles
    v
Cliente recebe PDF no WhatsApp
```

O FastAPI responde imediatamente com `200 OK` à Meta e processa o ficheiro em background via `BackgroundTasks`, evitando timeouts no webhook.

O APScheduler corre dentro do FastAPI e envia relatórios automaticamente de forma semanal e mensal para todos os clientes registados.

---

## Requisitos

- Python 3.11 ou superior
- Conta Meta for Developers com app WhatsApp Business configurada
- Base de dados PostgreSQL (Render ou Railway — free tier disponível)
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
BASE_URL=https://o-teu-url-publico.com
DATABASE_URL=postgresql://user:password@host:5432/insightzone_db
```

### Obter as credenciais Meta

1. Acede a [developers.facebook.com](https://developers.facebook.com)
2. Cria uma app com o use case "Connect with customers through WhatsApp"
3. Em **API Setup**, gera um access token temporário (válido 24 horas para testes)
4. Para produção, cria um token permanente através do System User no Business Manager
5. Copia o Phone Number ID e o WhatsApp Business Account ID da mesma página

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
|__ scheduler.py            APScheduler, envio automático semanal e mensal
|__ clientes.json           base de dados de clientes (número, negócio, histórico)
|__ requirements.txt        dependências Python com versões fixas
|__ .env                    credenciais (nunca commitar)
|__ .gitignore
|
|__ pipeline/
|   |__ __init__.py
|   |__ reader.py           leitura de CSV, Excel e PDF
|   |__ metrics.py          cálculo de métricas de vendas
|   |__ report.py           geração do relatório PDF com ReportLab
|   |__ sender.py           envio de mensagens e PDFs via Meta API
|
|__ data/
|   |__ bronze/             ficheiros brutos após ingestão (parquet)
|   |__ silver/             dados processados após cálculo de métricas (parquet)
|   |__ gold/               PDFs gerados, servidos publicamente em /reports/
|   |__ uploads/            ficheiros temporários enviados pelos clientes
|
|__ static/                 assets estáticos
```

---

## Pipeline de Dados

O pipeline segue a arquitectura medalhão (bronze, silver, gold):

| Camada | Responsabilidade | Localização |
|--------|-----------------|-------------|
| Bronze | Ficheiro bruto do cliente convertido em parquet | `data/bronze/` |
| Silver | DataFrame com métricas calculadas em parquet | `data/silver/` |
| Gold | Relatório PDF pronto para entrega | `data/gold/` |

### Schema mínimo do ficheiro do cliente

| Coluna | Tipo | Exemplo |
|--------|------|---------|
| data | texto ou data | 2026-05-17 |
| produto | texto | Frango Grelhado |
| quantidade | inteiro | 3 |
| valor | decimal | 250.00 |

Colunas com nomes alternativos como `Date`, `Item`, `Qty`, `Total`, `Price`, `Description` são detectadas e mapeadas automaticamente.

### Métricas calculadas

- Revenue total do período
- Total de transacções
- Ticket médio por transacção
- Melhor dia do período
- Top 5 produtos por quantidade
- Variação percentual face ao período anterior (quando disponível)

---

## Comandos do Bot

| O cliente envia | O bot responde |
|----------------|---------------|
| olá / oi / hello / bom dia | Menu de opções |
| ficheiro CSV ou Excel | Processamento automático e entrega do PDF |
| resumo / 3 | Três KPIs principais em texto simples |
| relatório / 2 | PDF do último relatório gerado |
| top / 4 | Top 5 produtos do período |

### Onboarding

Quando um número novo envia a primeira mensagem (texto ou ficheiro), o bot inicia um fluxo de onboarding de três passos antes de aceitar ficheiros:

1. Nome do negócio
2. Tipo de negócio (Serviços, Retalho, Agropecuária, Outro)
3. Email de backup (opcional)

O estado do onboarding é persistido em `clientes.json` através do campo `onboarding_passo`.

---

## Execução Local

```bash
# Terminal 1 — servidor FastAPI
uvicorn app:app --reload --port 8000

# Terminal 2 — túnel ngrok
ngrok http 8000
```

O ngrok fornece um URL público que deves configurar como Callback URL no dashboard da Meta e como `BASE_URL` no `.env`.

O token de acesso da Meta expira a cada 24 horas em modo de desenvolvimento. Para testes prolongados, cria um token permanente via System User no Meta Business Manager.

---

## Deploy em Produção

### Railway

```bash
# Instalar Railway CLI
npm install -g @railway/cli

# Login e deploy
railway login
railway init
railway up
```

Define as variáveis de ambiente no dashboard do Railway e actualiza o `BASE_URL` com o URL público atribuído.

### Variáveis de ambiente em produção

Todas as variáveis do `.env` devem ser configuradas no painel de variáveis de ambiente da plataforma de hosting. Nunca incluir o ficheiro `.env` no repositório.

---

## Modelo de Negócio

| Plano | Preço mensal | Inclui |
|-------|-------------|--------|
| Básico | $10 / 640 MZN | 4 relatórios por mês, alertas básicos |
| Pro | $25 / 1.600 MZN | Relatórios ilimitados, alertas avançados, suporte WhatsApp |
| Empresa | $60 / 3.840 MZN | Multi-utilizador, relatórios personalizados, onboarding dedicado |

### Custos operacionais — 10 clientes MVP

| Item | Custo mensal |
|------|-------------|
| Meta Cloud API (menos de 1.000 conversas) | $0.00 |
| Railway / Render.com (free tier) | $0.00 |
| PostgreSQL (free tier) | $0.00 |
| Total | $0.00 |

Com 10 clientes no plano Básico: $100/mês de receita com margem bruta de 100%.

---

## Licença

Projecto privado. Todos os direitos reservados.