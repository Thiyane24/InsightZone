# InsightZone: Pipeline de Ingestão de Dados e Serviço de Entrega de Business Intelligence via WhatsApp

O InsightZone é uma arquitetura de portfólio de engenharia de dados e backend de nível produção, desenhada para automatizar a ingestão, transformação e análise de dados transacionais. O sistema extrai dados de vendas em bruto, submetidos através do WhatsApp como texto não estruturado ou ficheiros tabulares, normaliza os dados através de um pipeline de três camadas, e entrega um relatório analítico profissional em formato PDF de forma assíncrona dentro de 60 segundos.

O objetivo principal deste projeto é demonstrar soluções robustas para desafios críticos de engenharia de dados em ambiente empresarial: restrições severas de memória em ambientes de cloud efémeros, segurança de perímetro através de validação criptográfica, idempotência de eventos, limitação de pedidos (rate limiting), e alinhamento heurístico de esquemas para layouts de dados inconsistentes.

## Desenho Arquitetural e Fluxo de Dados

O ciclo de vida dos dados segue rigorosamente a Arquitetura Medallion (padrões de desenho Bronze, Silver e Gold) para garantir a qualidade dos dados e evitar corrupção analítica a jusante.

```
[Interface do Utilizador: WhatsApp] ---> [Payload de Ficheiro/Texto] ---> [Webhook da Meta Cloud API]
                                                                  |
                                              (Rate Limiter / Verificação HMAC SHA 256)
                                                                  v
[Armazenamento Cloudinary] <--- [Stream de PDF ReportLab] <--- [Núcleo do Backend FastAPI]
                                                                  |
                                                      (BackgroundTasks / APScheduler)
                                                                  v
                                                  [pipeline/reader.py (Pandas)]
                                                                  |
                                                  (Normalização Heurística de Esquema)
                                                                  v
                                          [PostgreSQL / pipeline/metrics.py (Matplotlib)]
```

**Camada de Ingestão e Perímetro:** O cliente submete um payload de dados (CSV, Excel, PDF legível por máquina, ou texto em bruto). O webhook FastAPI intercepta o pedido HTTPS POST, aplica limitação de pedidos para proteger contra abuso e tráfego excessivo, executa a verificação da assinatura criptográfica, e delega o payload a uma thread de trabalho assíncrona em segundo plano.

**Camada Bronze (Ingestão em Bruto):** O ficheiro ou input de texto em bruto é ingerido em memória. Um mecanismo de routing heurístico baseado em dicionário deteta e mapeia colunas com base em terminologia sinónima em múltiplas línguas (por exemplo, Date, Data, Item, Price, Preço, Qty, Total).

**Camada Silver (Validação e Limpeza):** Os dados são estruturados em DataFrames Pandas. A imposição de tipos é aplicada rigorosamente, e linhas anómalas, como campos primários em falta, registos corrompidos, ou quantidades transacionais negativas, são sistematicamente isoladas e removidas.

**Camada Gold (Análise e Persistência):** São calculadas agregações estatísticas e Indicadores-Chave de Desempenho (KPIs). Gráficos e resumos visuais são gerados com Matplotlib para inclusão no relatório final. As métricas de negócio e os estados de interação do cliente são persistidos numa instância relacional PostgreSQL. A alocação de memória dos DataFrames é instantaneamente otimizada através da execução explícita de garbage collection (`gc.collect()`).

**Geração e Envio do Artefacto:** O relatório analítico final é compilado num stream binário de PDF utilizando módulos de lazy-loading do ReportLab, incorporando os gráficos gerados pelo Matplotlib, é enviado para armazenamento seguro na cloud via Cloudinary, e o URL permanente é despachado de volta ao utilizador final através da Meta Cloud API.

## Capacidades do Sistema

### 1. Motor de Ingestão de Dados Híbrido

O pipeline ingere estruturas de dados heterogéneas de forma nativa, sem exigir mutação manual de estado por parte do utilizador:

- **Análise de Ficheiros Tabulares:** Extração automatizada de anexos estruturados (.csv, .xlsx, .pdf).
- **Análise de Texto para Stream Estruturado:** Ingestão direta de registos transacionais submetidos como texto simples. O parser analisa o payload sequencialmente com base em delimitadores de nova linha e variáveis separadas por vírgulas:

```
Produto/Serviço, Quantidade, Valor
Frango Grelhado, 3, 250
Consultoria de TI, 1, 5000
```

### 2. Orquestração Empresarial de Agendamento e Cadência

Recorrendo ao APScheduler integrado diretamente no ciclo de vida da aplicação FastAPI, a infraestrutura gere intervalos automatizados de relatórios (diário, semanal, mensal). Os estados de distribuição são persistidos na base de dados, acionando tarefas de avaliação deterministas sincronizadas com os fusos horários regionais.

### 3. Máquina de Estados de Onboarding com Persistência

Ao intercetar comunicação de uma entidade não registada, o backend inicia um fluxo de onboarding com estado, governado por parâmetros da base de dados (`onboarding_passo`). Isto recolhe metadados essenciais do negócio antes de permitir o acesso ao pipeline central de processamento ETL.

### 4. Limitação de Pedidos (Rate Limiting)

Para proteger o serviço contra abuso, tráfego excessivo, e potenciais condições de negação de serviço, a camada de webhook impõe um rate limiter antes da validação criptográfica e do processamento do pipeline. Isto garante que os recursos computacionais são reservados para tráfego legítimo e bem comportado, e que um único cliente não consegue degradar o serviço para os restantes.

## Garantias de Desempenho de Engenharia e Telemetria

- **Latência de Resposta no Perímetro:** O webhook de ingestão confirma a receção dos payloads e devolve um estado HTTP 200 OK ao gateway da Meta API em `<15ms`, mitigando timeouts de rede (HTTP 504) ao delegar o processamento para workers não bloqueantes em segundo plano.
- **Otimização de Memória:** A implementação de manuseamento eficiente de DataFrames e de controlos deterministas de garbage collection limita o consumo de memória do container a `<250MB`, garantindo estabilidade operacional e prevenindo falhas de Falta de Memória (OOM) durante ciclos de processamento concorrente.
- **Idempotência de Transações:** O sistema armazena em cache e cruza referências com o `message_id` único fornecido pela Meta API. Tentativas de entrega duplicadas, despoletadas por retentativas de rede a montante, são imediatamente descartadas, prevenindo escritas redundantes na base de dados.
- **Segurança Criptográfica:** O endpoint `/webhook` impõe validação de perímetro, recalculando a assinatura HMAC SHA 256 com a chave secreta da aplicação contra o payload recebido, rejeitando pedidos não autorizados com um estado HTTP 403.
- **Limitação de Pedidos:** Os pedidos de entrada são limitados na camada de webhook para prevenir abuso e proteger os recursos de processamento a jusante de serem sobrecarregados por tráfego excessivo ou malicioso.

## Estrutura do Diretório do Projeto

```
insightzone/
│
├── app.py                  # Ponto de entrada da aplicação FastAPI, routing de webhooks, e máquina de estados
├── scheduler.py            # Orquestração de cron para distribuição automatizada de relatórios
├── criar_tabela.py         # Script idempotente de migração do esquema da base de dados
├── requirements.txt        # Manifesto de dependências fixadas
├── .env                    # Variáveis de ambiente locais e segredos (ignorado pelo git)
│
├── pipeline/
│   ├── __init__.py
│   ├── reader.py           # Motor de normalização heurística e parsers de stream de texto (Pandas)
│   ├── metrics.py          # Cálculo estatístico, geração de gráficos Matplotlib, e gestão de Garbage Collection
│   ├── report.py           # Layout estrutural e compilação de PDF com ReportLab
│   ├── storage.py          # Gateway de persistência na cloud e purga de ficheiros efémeros
│   └── sender.py           # Despachante da Meta API com retentativas automáticas de exponential backoff
│
└── tests/
    └── test_insightzone.py # Suite de testes automatizados validando qualidade de dados e segurança de perímetro
```

## Esquema da Base de Dados Relacional

A infraestrutura utiliza PostgreSQL para persistência e auditoria:

| Atributo | Tipo de Dados | Descrição Funcional |
|---|---|---|
| `numero` | TEXT (Chave Primária) | String de identificação MSISDN internacional única a nível global. |
| `nome` | TEXT | Nome da entidade comercial registada, capturado durante o onboarding. |
| `negocio` | TEXT | Classificação do setor de atividade (retalho, serviços, agricultura, outro). |
| `frequencia` | TEXT | Cadência ativa de distribuição automática de relatórios (diário, semanal, mensal). |
| `ultimo_ficheiro_url` | TEXT | Apontador de auditoria para o último ficheiro em bruto ingerido. |
| `ultimo_relatorio_url` | TEXT | Link de referência permanente para o último artefacto de PDF analítico compilado. |
| `onboarding_passo` | INTEGER | Índice atual dentro da máquina de estados de onboarding (0 indica conclusão). |
| `modo` | TEXT | Flag de estado operacional (`awaiting_sales`, `awaiting_cadence`). |
| `criado_em` | TIMESTAMP | Registo de timestamp do registo no sistema. |

## Decisões de Engenharia e Resolução de Problemas

**Mitigação de Violações de Disco Efémero:** As plataformas de cloud frequentemente impõem sistemas de ficheiros efémeros, onde as escritas em disco local são eliminadas no reinício do container. Para resolver isto, o `pipeline/storage.py` envia os chunks de output em bruto diretamente para armazenamento temporário, executa uma transferência imediata para armazenamento de longo prazo, e executa uma eliminação obrigatória do ficheiro dentro de um bloco de código `finally` para prevenir fugas de armazenamento.

**Correspondência Heurística de Padrões:** Pequenas empresas frequentemente submetem esquemas de dados variados. O sistema resolve isto recorrendo a Expressões Regulares (Regex) no `pipeline/reader.py` para alcançar o alinhamento de esquema. Inputs sinónimos como "Unit Price", "Valor", "Price", ou "Total" são mapeados de forma padronizada para um modelo de dados Float64 uniforme.

**Proteção Contra Limites de Taxa da Meta API:** Gateways de terceiros podem apresentar instabilidade de rede ou acionar limites de taxa. O despachante a jusante (`pipeline/sender.py`) incorpora uma política robusta de retentativas de execução, utilizando exponential backoff, que interceta imediatamente estados de rede fatais (401, 403) para proteger os recursos computacionais.

**Proteção Contra Abuso de Entrada:** Além da proteção de retentativas de saída, o próprio webhook impõe um rate limiter no perímetro para prevenir que uma única origem sobrecarregue o sistema com pedidos excessivos, garantindo um acesso justo e estável para todos os utilizadores legítimos.
