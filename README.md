<div align="center">

<img src="https://img.shields.io/badge/Status-Em%20Desenvolvimento-yellow?style=for-the-badge" />
<img src="https://img.shields.io/badge/Stack-Python%20%7C%20Flask%20%7C%20WhatsApp-25D366?style=for-the-badge&logo=whatsapp&logoColor=white" />
<img src="https://img.shields.io/badge/Mercado-Moçambique%20%2F%20África-FF6B35?style=for-the-badge" />

<br/><br/>

# InsightZone WhatsApp

### Business Intelligence pelo WhatsApp para pequenas empresas em Moçambique e África

**Envia o teu ficheiro de vendas → Recebe um relatório PDF profissional automaticamente**  
Sem instalar nada. Sem fazer login. Sem aprender nenhuma ferramenta nova.

<br/>

[**Ver PRD**](#-documentação) · [**Stack**](#-stack) · [**Roadmap**](#-roadmap) · [**Modelo de Negócio**](#-modelo-de-negócio)

</div>

---

## O Problema

As pequenas empresas em Moçambique salões de beleza, retalhistas, prestadores de serviços não têm acesso a ferramentas de business intelligence. Excel é complicado. Power BI requer formação. Ferramentas SaaS são caras e em inglês.

Mas **toda a gente tem WhatsApp**.

O InsightZone resolve isto: o dono do negócio envia os dados de vendas pelo WhatsApp que já usa todos os dias, e recebe de volta um relatório PDF profissional com os KPIs (Key Performance Indicators) da semana automaticamente, em menos de 60 segundos.

---

## O que o InsightZone faz

| Funcionalidade | Descrição |
|---|---|
| **Recepção de ficheiros** | Aceita CSV, Excel (.xlsx/.xls) e PDF com texto seleccionável via WhatsApp |
| **Processamento automático** | Pipeline calcula métricas de vendas em segundos |
| **Relatório PDF profissional** | KPIs, gráficos e insights entregues de volta no WhatsApp |
| **Resumo rápido** | Comando `resumo` devolve 3 KPIs em texto sem PDF |
| **Relatório semanal automático** | Enviado todas as segundas-feiras às 8h sem o cliente pedir |
| **Alertas proactivos** | Notificação quando há quedas de vendas > 20% vs semana anterior |
| **Semana recorde** | Alerta quando é a melhor semana do mês |

---

##  Arquitectura

```
Cliente (WhatsApp)
        │
        │  Envia ficheiro CSV / Excel / PDF
        ▼
┌───────────────────┐
│   Meta Cloud API  │  ← Webhook POST
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│     app.py        │  Flask — recebe webhook, responde 200 OK
│  (Webhook Handler)│  e delega para o pipeline em background
└─────────┬─────────┘
          │
          ▼
┌─────────────────────────────────────────┐
│              Pipeline                   │
│                                         │
│  reader.py  →  metrics.py  →  report.py │
│  (Lê ficheiro) (Calcula KPIs) (Gera PDF)│
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌───────────────────┐
│    sender.py      │  Envia PDF de volta pelo WhatsApp
└───────────────────┘
          │
          ▼
Cliente recebe o PDF no WhatsApp 
```

### Componentes

| Componente | Tecnologia | Responsabilidade |
|---|---|---|
| **WhatsApp Gateway** | Meta Cloud API | Receber mensagens/ficheiros, enviar PDF de volta |
| **Webhook Handler** | Flask (Python) | Receber POST da Meta, responder 200 OK, encaminhar para o pipeline |
| **File Reader** | Pandas + pdfplumber | Ler CSV, Excel, ou PDF com texto seleccionável |
| **Metrics Engine** | Pandas | Calcular KPIs: total, melhor dia, top produtos, ticket médio |
| **Report Generator** | ReportLab + Matplotlib | Gerar PDF < 5 MB com KPIs e gráficos |
| **Scheduler** | APScheduler | Envio automático todas as segundas-feiras às 8h |
| **Client Store** | JSON / SQLite | Guardar número, sector e histórico de cada cliente |
| **Hosting** | Render.com | Flask server + ficheiros estáticos (PDFs) online 24/7 |

---

##  Estrutura do Projecto

```
InsightZone/
│
├── app.py                  # Ponto de entrada — webhook Flask
├── scheduler.py            # APScheduler — envio automático semanal
├── clients.json            # Base de dados simples dos clientes
├── requirements.txt        # Dependências com versões fixas
├── .env                    # Chaves de API (nunca commitar no GitHub)
├── .gitignore
│
├── pipeline/
│   ├── reader.py           # Lê CSV, Excel, PDF → DataFrame normalizado
│   ├── metrics.py          # Calcula os 7 KPIs a partir do DataFrame
│   ├── report.py           # Gera o PDF com ReportLab e Matplotlib
│   └── sender.py           # Envia mensagens e PDFs pela Meta Cloud API
│
├── static/                 # PDFs gerados — acessíveis por URL público
│
└── tests/
    ├── conftest.py         # Fixtures partilhadas
    ├── unit_test.py        # Unit tests para reader.py e metrics.py
    └── integration_test.py # Testes de integração (webhook → pipeline)
```

---

##  Métricas calculadas

O `metrics.py` calcula automaticamente os seguintes KPIs a partir do ficheiro de vendas:

| Métrica | Descrição |
|---|---|
| **Revenue total** | Soma de todos os valores da semana |
| **Total de transacções** | Contagem de linhas — volume de negócio |
| **Ticket médio** | Revenue total ÷ número de transacções |
| **Melhor dia** | Dia com maior soma de vendas |
| **Pior dia** | Dia com menor soma de vendas |
| **Top 5 produtos** | Produtos mais vendidos por quantidade |
| **Vendas por dia (série)** | Base do gráfico de barras do relatório |

---

## Relatório PDF

O relatório gerado tem **máximo 2 páginas** e é optimizado para leitura no telemóvel:

```
┌─────────────────────────────────────────┐
│  InsightZone — Salão do Thiyane         │
│  Semana 20/05 – 26/05/2026              │
├─────────────────────────────────────────┤
│  "A tua melhor semana do mês!"        │
├──────────┬──────────┬────────┬──────────┤
│ MZN 4500 │    23    │  Seg.  │  Corte   │
│ Revenue  │ Transac. │ Melhor │ Top Prod │
├─────────────────────────────────────────┤
│  📊 Vendas por dia                      │
│  ████████ ██ ████ ██████ ████ ██ ██    │
│  Seg  Ter  Qua  Qui  Sex  Sáb  Dom     │
├─────────────────────────────────────────┤
│  🏆 Top 5 Produtos                      │
│  1. Corte de cabelo     ×12             │
│  2. Coloração           ×6              │
│  3. Manicure            ×3              │
│  ...                                    │
├─────────────────────────────────────────┤
│  Gerado pelo InsightZone                │
└─────────────────────────────────────────┘
```

### Restrições técnicas (WhatsApp)

| Restrição | Valor | Razão |
|---|---|---|
| Tamanho máximo do PDF | < 5 MB | Limite do WhatsApp para documentos |
| Resolução dos gráficos | 100 DPI | Reduz tamanho sem perder legibilidade |
| Tamanho mínimo do texto | 11 pt | Legível em ecrã de telemóvel |
| Número de páginas | Máximo 2 | PDF longo não é lido no telemóvel |

---

## Schema do ficheiro de vendas

O cliente envia um ficheiro com este formato mínimo:

| Coluna | Tipo | Exemplo | Obrigatória? |
|---|---|---|---|
| `data` | texto ou data | `2026-05-20` ou `20/05/2026` | Sim |
| `produto` | texto | `Corte de cabelo` | Sim |
| `quantidade` | número inteiro | `1`, `3`, `10` | Sim |
| `valor` | número decimal | `250.00`, `1500` | Sim |
| `custo` | número decimal | `100.00` | Opcional |

**Formatos aceites:** `.csv` · `.xlsx` · `.xls` · `.pdf` (com texto seleccionável)  
**Não suportado no MVP:** PDF scaneado / foto

---

## Comandos do Bot

| O cliente envia | O bot responde | Tempo |
|---|---|---|
| `olá`, `oi`, `hello` | Menu com opções numeradas | < 3 s |
| Ficheiro CSV / Excel / PDF | `A processar...` → PDF do relatório | < 60 s |
| `relatório` ou `2` | PDF mais recente guardado | < 5 s |
| `resumo` ou `3` | Texto com 3 KPIs principais | < 5 s |
| `top` ou `4` | Lista top 5 produtos desta semana | < 5 s |
| `ajuda` ou `0` | Menu completo de comandos | < 3 s |
| PDF scaneado / formato inválido | Mensagem de erro + instrução para reenviar | < 3 s |

---

## Stack

| Tecnologia | Versão | Papel |
|---|---|---|
| **Python** | 3.11+ | Linguagem principal |
| **Flask** | 3.0.x | Servidor webhook |
| **Pandas** | 2.x | Leitura de ficheiros e cálculo de métricas |
| **ReportLab** | 4.x | Geração de PDFs |
| **Matplotlib** | 3.x | Gráficos dentro do PDF |
| **pdfplumber** | 0.11.x | Leitura de PDFs com texto seleccionável |
| **APScheduler** | 3.x | Scheduler do relatório semanal |
| **Meta Cloud API** | v19+ | Canal WhatsApp (oficial, sem intermediários) |
| **Render.com** | — | Hosting do Flask + ficheiros estáticos |
| **pytest** | 8.x | Unit e integration tests |

---

## Setup local

### Pré-requisitos

- Python 3.11+
- Conta Meta Business verificada
- [ngrok](https://ngrok.com/) para expor o servidor local ao webhook da Meta

### 1. Clonar o repositório

```bash
git clone https://github.com/Thiyane24/InsightZone.git
cd InsightZone
```

### 2. Criar ambiente virtual e instalar dependências

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente

Cria um ficheiro `.env` na raiz do projecto:

```env
META_ACCESS_TOKEN=your_meta_access_token
META_PHONE_NUMBER_ID=your_phone_number_id
META_VERIFY_TOKEN=your_custom_verify_token
```

> **Nunca commites o `.env` no GitHub.** Já está no `.gitignore`.

### 4. Expor o servidor com ngrok

```bash
# Terminal 1 — iniciar Flask
python app.py

# Terminal 2 — expor com ngrok
ngrok http 5000
```

Copia o URL do ngrok (ex: `https://abc123.ngrok.io`) e define-o como webhook no [Meta Developer Dashboard](https://developers.facebook.com).

### 5. Testar

Envia `olá` para o teu número de teste pelo WhatsApp. O bot deve responder com o menu.

---

## Testes

```bash
pytest tests/ -v
```

### Cobertura de testes

| Módulo | Testes | O que valida |
|---|---|---|
| `reader.py` | `test_read_csv` | CSV válido devolve DataFrame com colunas correctas |
| | `test_read_excel` | Excel válido devolve DataFrame com colunas correctas |
| | `test_unsupported_format` | Formato inválido levanta `ValueError` |
| | `test_empty_file` | Ficheiro vazio levanta `ValueError` com mensagem clara |
| | `test_missing_columns` | CSV sem coluna obrigatória levanta `ValueError` |
| `metrics.py` | `test_total_revenue` | Soma de `valor` retorna valor exacto esperado |
| | `test_best_day` | Dia com maior soma é identificado correctamente |
| | `test_top_products` | Top 5 produtos devolvidos ordenados correctamente |
| | `test_empty_dataframe` | DataFrame vazio levanta `ValueError` |
| | `test_single_row` | DataFrame com uma linha calcula métricas correctamente |

---

##  Roadmap

| Semana | Foco | Gate |
|---|---|---|
| **Semana 1** | Meta Cloud API + Flask | Bot responde `olá de volta` no WhatsApp |
| **Semana 2** | Pipeline de dados + unit tests | Bot responde com total de vendas em texto após receber CSV |
| **Semana 3** | Relatório PDF | PDF profissional recebido no WhatsApp em < 60 s |
| **Semana 4** | Deploy + primeiro cliente real | Uma pessoa real recebe um relatório com os seus dados reais |

### Após o MVP

- [ ] Schemas por sector (salão, retalho, agropecuária, consultoria)
- [ ] Alertas proactivos com análise de tendência
- [ ] Suporte a PDF scaneado com OCR (pós-MVP)
- [ ] Dashboard web para clientes Pro e Empresa
- [ ] Multi-língua (PT + EN + línguas locais)

---

##  Modelo de Negócio

| Plano | Preço / mês | Inclui | Target |
|---|---|---|---|
| **Básico** | $10 / MZN 640 | 4 relatórios/mês, alertas básicos | Vendedores individuais, salões pequenos |
| **Pro** | $25 / MZN 1.600 | Relatórios ilimitados, alertas avançados, suporte WhatsApp | PMEs, lojas, consultores |
| **Empresa** | $60 / MZN 3.840 | Multi-utilizador, relatórios custom, onboarding dedicado | Empresas com múltiplas unidades |

**Unit economics (10 clientes MVP):**
- Receita: $100/mês
- Custo operacional: $0/mês (dentro dos free tiers)
- Margem bruta: **100%**

---

##  Documentação

| Documento | Descrição |
|---|---|
| [PRD v2.2](docs/InsightZone_PRD_v2_2.docx) | Product Requirements Document completo |
| [Guia de Aprendizagem](docs/InsightZone_Guia_Aprendizagem.docx) | O que aprender antes de começar — stack, tempo estimado |

---

## Autor

**Thiyane Xavier**  
Estudante de Diploma em IT@MAHSA University  
Self-teaching Data Engineering

[![GitHub](https://img.shields.io/badge/GitHub-Thiyane24-181717?style=flat&logo=github)](https://github.com/Thiyane24)

---

<div align="center">

**InsightZone** Business Intelligence pelo WhatsApp, feito em Moçambique para África.

</div>
