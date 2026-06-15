

# InsightZone: Pipeline Assíncrono de Ingestão de Dados e Serviço de Entrega de Business Intelligence via WhatsApp

O InsightZone é uma arquitetura de backend e engenharia de dados de nível produtivo desenhada para automatizar a ingestão, transformação e análise de dados transacionais. O sistema extrai inputs brutos de vendas submetidos como texto não estruturado ou ficheiros tabulares via WhatsApp normaliza os dados através de um pipeline de três camadas e entrega um relatório analítico profissional em formato PDF de forma assíncrona em menos de 60 segundos.

O objetivo principal deste projeto é demonstrar soluções robustas para desafios críticos de engenharia de dados corporativos: restrições severas de memória em ambientes cloud efémeros, segurança perimetral através de validação criptográfica, idempotência de eventos e alinhamento heurístico de esquemas para layouts de dados inconsistentes.

## Design Arquitetural e Fluxo de Dados

O ciclo de vida dos dados adota estritamente os padrões de desenho da Arquitetura Medalhão (camadas Bronze, Silver e Gold) para garantir a qualidade dos dados e prevenir a corrupção analítica a jusante.

```
[Interface Utilizador: WhatsApp] ---> [Payload Ficheiro/Texto] ---> [Webhook Meta Cloud API]
                                                                            |
                                                                (Validação HMAC SHA 256)
                                                                            v
[Armazenamento Cloudinary] <--- [Stream PDF ReportLab] <--- [Núcleo Backend FastAPI]
                                                                            |
                                                                (BackgroundTasks / APScheduler)
                                                                            v
                                                              [pipeline/reader.py (Polars)]
                                                                            |
                                                                (Normalização Heurística)
                                                                            v
                                                            [PostgreSQL / pipeline/metrics.py]

```

1. **Camada de Ingestão e Perímetro:** O utilizador submete um payload de dados (CSV, Excel, PDF legível por máquina ou texto bruto). O webhook FastAPI intercepa o pedido HTTPS POST, executa a verificação de assinatura criptográfica e delega o payload para uma thread de trabalho em background assíncrona.
2. **Camada Bronze (Ingestão Bruta):** O ficheiro bruto ou input de texto é ingerido em memória. Um mecanismo de encaminhamento heurístico baseado em dicionários deteta e mapeia colunas com base em terminologia sinónima em múltiplos idiomas (exemplo: *Date, Data, Item, Price, Preço, Qty, Total*).
3. **Camada Silver (Validação e Limpeza):** Os dados são estruturados em DataFrames de **Polars** eficientes em termos de memória. A imposição de tipos é aplicada rigidamente e linhas anómalas tais como campos primários em falta, registos corrompidos ou quantidades transacionais negativas são sistematicamente isoladas e expurgadas.
4. **Camada Gold (Analytics e Persistência):** Agregações estatísticas e Indicadores Chave de Desempenho (KPIs) são computados. As métricas de negócio e os estados de interação dos utilizadores são persistidos numa instância relacional **PostgreSQL**. A alocação de memória do Dataframe é instantaneamente otimizada através da execução explícita de recolha de lixo (`gc.collect()`).
5. **Geração de Artefactos e Despacho:** O relatório analítico final é compilado num stream binário PDF utilizando módulos de carregamento lento (**ReportLab**), enviado para armazenamento seguro na cloud via **Cloudinary** e o URL permanente é despachado de volta para o utilizador final através da Meta Cloud API.

## Capacidades do Sistema

### 1. Motor Híbrido de Ingestão de Dados

O pipeline ingere estruturas de dados heterogéneas nativamente sem necessitar de mutação de estado manual por parte do utilizador:

* **Modo Ficheiro Tabular:** Extração automatizada de anexos estruturados (`.csv`, `.xlsx`, `.pdf`).
* **Modo Stream de Texto Estruturado:** Ingestão direta de registos transacionais submetidos como texto plano. O parser analisa o payload sequencialmente com base em delimitadores de nova linha e variáveis separadas por vírgulas:
```text
Produto/Serviço, Quantidade, Valor
Frango Grelhado, 3, 250
Consultoria TI, 1, 5000

```



### 2. Agendamento Corporativo e Orquestração de Cadências

Maximizando o uso do **APScheduler** integrado diretamente no ciclo de vida da aplicação FastAPI, a infraestrutura gere intervalos de relatórios automatizados (`daily`, `weekly`, `monthly`). Os estados de distribuição são persistidos na base de dados, disparando tarefas de avaliação determinísticas sincronizadas com os fusos horários regionais.

### 3. Máquina de Estados de Onboarding Stateful

Ao intercetar comunicações de uma entidade não registada, o backend inicia um fluxo de trabalho de onboarding stateful governado por parâmetros da base de dados (`onboarding_passo`). Isto captura metadados essenciais do negócio antes de permitir o acesso ao pipeline de processamento ETL principal.

## Garantias de Desempenho de Engenharia e Telemetria

* **Latência de Resposta do Perímetro:** O webhook de ingestão reconhece os payloads e retorna um estado `HTTP 200 OK` para o gateway da Meta API em **$< 15\text{ms}$**, mitigando timeouts de rede (`HTTP 504`) ao descarregar o processamento para trabalhadores em background não bloqueantes.
* **Otimização de Memória:** A implementação de avaliação lenta e controlos determinísticos de recolha de lixo limita a pegada de memória do contentor para **$< 250\text{MB}$**, garantindo a estabilidade operacional e prevenindo falhas de falta de memória (OOM) durante ciclos de processamento concorrentes.
* **Idempotência de Transações:** O sistema armazena em cache e cruza a referência do `message_id` único fornecido pela Meta API. Tentativas de entrega duplicadas disparadas por reexecuções de rede a montante são descartadas imediatamente, prevenindo escritas redundantes na base de dados.
* **Segurança Criptográfica:** O endpoint `/webhook` impõe validação de perímetro recalculando a assinatura HMAC SHA 256 usando a chave secreta da aplicação contra o payload de entrada, rejeitando **$100\%$ das requisições não autorizadas** com um estado `HTTP 403`.

## Estrutura de Diretorios do Projeto

```
insightzone/
│
├── app.py                  # Ponto de entrada da aplicação FastAPI, rotas de webhook e máquina de estados
├── scheduler.py            # Orquestração cron para distribuição automatizada de relatórios
├── criar_tabela.py         # Script de migração de esquema de base de dados idempotente
├── requirements.txt        # Manifesto de dependências fixas
├── .env                    # Variáveis de ambiente locais e segredos (ignorado pelo git)
│
├── pipeline/
│   ├── __init__.py
│   ├── reader.py           # Motor de normalização heurística e parsers de stream de texto
│   ├── metrics.py          # Computação estatística e gestão de Garbage Collection
│   ├── report.py           # Layout estrutural ReportLab e compilação de PDF
│   ├── storage.py          # Gateway de persistência cloud e purga de ficheiros efémeros
│   └── sender.py           # Despachante Meta API com retentativas automáticas de backoff exponencial
│
└── tests/
    └── test_insightzone.py # Suite de testes automatizados validando qualidade de dados e segurança

```

## Esquema Relacional da Base de Dados

A infraestrutura utiliza o **PostgreSQL** para persistence e auditoria:

| Atributo | Tipo de Dados | Descrição Funcional |
| --- | --- | --- |
| **numero** | `TEXT (Primary Key)` | String única de identificação internacional MSISDN. |
| **nome** | `TEXT` | Nome da entidade comercial registada capturado durante o onboarding. |
| **negocio** | `TEXT` | Classificação vertical da indústria (`retail`, `services`, `agriculture`, `other`). |
| **frequencia** | `TEXT` | Cadência ativa de distribuição de relatórios automatizados (`daily`, `weekly`, `monthly`). |
| **ultimo_ficheiro_url** | `TEXT` | Ponteiro de pista de auditoria para o último ficheiro bruto ingerido. |
| **ultimo_relatorio_url** | `TEXT` | Link de referência permanente para o artefacto PDF analítico compilado mais recente. |
| **onboarding_passo** | `INTEGER` | Índice atual dentro da máquina de estados de onboarding (0 indica conclusão). |
| **modo** | `TEXT` | Flag de estado operacional (`awaiting_sales`, `awaiting_cadence`). |
| **criado_em** | `TIMESTAMP` | Registo de carimbo de data hora de inscrição no sistema. |

## Decisões de Engenharia e Resolução de Problemas

* **Mitigação de Violações de Disco Efémero:** As plataformas cloud frequentemente impõem sistemas de ficheiros efémeros onde as escritas em disco local são purgadas nos reinícios do contentor. Para resolver isto, o `pipeline/storage.py` direciona blocos de saída brutos diretamente para o armazenamento temporário, executa uma transferência imediata para o armazenamento de longo prazo e corre uma eliminação obrigatória de ficheiros dentro de um bloco de código `finally` para prevenir fugas de armazenamento.
* **Correspondência de Padrões Heurísticos:** As pequenas empresas submetem frequentemente esquemas de dados variados. O sistema aborda isto tirando partido de Expressões Regulares (Regex) em `pipeline/reader.py` para alcançar o alinhamento de esquemas. Inputs sinónimos como *"Unit Price"*, *"Valor"*, *"Price"* ou *"Total"* são mapeados de forma estandardizada para um modelo de dados Float64 uniforme.
* **Proteção de Limite de Taxa da Meta API:** Os gateways de terceiros podem exibir instabilidade de rede ou acionar limites de taxa. O despachante a jusante (`pipeline/sender.py`) incorpora uma política robusta de retentativa de execução utilizando **backoff exponencial**, que intercepa estados de rede fatais (`401`, `403`) imediatamente para proteger os recursos de computação.
