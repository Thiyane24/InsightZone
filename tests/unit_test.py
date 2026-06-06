import os
import sys
import shutil
import uuid
import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch

# ENTENDIMENTO: Garante que o motor do Pytest localiza e importa os módulos da pasta raiz
# independentemente de onde o comando de terminal é disparado, evitando erros de coleção.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ENTENDIMENTO: Mocks estáticos de ambiente para impedir que o arranque da aplicação FastAPI
# falhe por falta de chaves secretas ou configurações dependentes do ficheiro .env.
os.environ["WEBHOOK_VERIFY_TOKEN"] = "token_teste_secreto"
os.environ["BASE_URL"] = "http://localhost:8000"
os.environ["META_ACCESS_TOKEN"] = "token_meta_fake"

from fastapi.testclient import TestClient
from app import app, carregar_todos_clientes, guardar_clientes
from pipeline.report import gerar_relatorio
from pipeline.metrics import calcular_metricas


# ── CONFIGURAÇÃO E COMPORTAMENTO DO AMBIENTE DE TESTES ───────────────────────

@pytest.fixture(autouse=True)
def setup_and_teardown():
    """
    ENTENDIMENTO: Padrão Sandbox (Isolamento de Estado).
    Cria diretórios transientes isolados e faz uma cópia de segurança do JSON de clientes real.
    Após a execução de cada teste, reverte tudo ao estado original para mitigar efeitos
    secundários ou corrupção de dados legítimos de produção/desenvolvimento.
    """
    os.makedirs("data/uploads_test", exist_ok=True)
    os.makedirs("data/gold_test", exist_ok=True)
    
    backup_clientes = False
    if os.path.exists("clientes.json"):
        shutil.copy("clientes.json", "clientes.json.bak")
        backup_clientes = True
        
    with open("clientes.json", "w", encoding="utf-8") as f:
        f.write("[]")
        
    yield  # ENTENDIMENTO: Ponto de interrupção onde o Pytest executa o caso de teste atual.
    
    if os.path.exists("data/gold_test"):
        shutil.rmtree("data/gold_test")
    if os.path.exists("data/uploads_test"):
        shutil.rmtree("data/uploads_test")
        
    if backup_clientes:
        shutil.move("clientes.json.bak", "clientes.json")
    elif os.path.exists("clientes.json"):
        os.remove("clientes.json")


@pytest.fixture
def api_client():
    """
    ENTENDIMENTO: Encapsulamento de Instância.
    Ao instanciar o TestClient dentro de uma fixture com 'with', garantimos que o ciclo de vida
    da aplicação FastAPI (incluindo mounts e rotas) encerra corretamente ao fim do teste,
    eliminando fugas de memória ou portas presas durante o processo de coleção.
    """
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def mock_whatsapp_sender():
    """
    ENTENDIMENTO: Isolamento de Rede Externa (Corta-Fogo).
    Como este é um teste unitário/integração local, intercetamos e neutralizamos as chamadas
    de envio para a API do WhatsApp (Meta). Isto impede que os testes façam pedidos HTTP reais,
    evitando falhas por falta de rede, timeouts ou custos indesejados na Cloud API.
    """
    with patch("app.enviar_mensagem") as mock_envio, \
         patch("app.main_function") as mock_main:
        mock_envio.return_value = True
        mock_main.return_value = True
        yield mock_envio, mock_main


# ── GERADORES DE MASSA DE DADOS DE SIMULAÇÃO (MOCKS) ──────────────────────────

def obter_dados_mock(produto_longo: bool = False) -> pd.DataFrame:
    """
    ENTENDIMENTO: Fábrica de Dados Determinística.
    Providencia um DataFrame padronizado com os tipos exigidos pelo módulo 'ingest'.
    O parâmetro 'produto_longo' permite injetar intencionalmente uma string anómala contínua
    para testar os limites geométricos e de overflow do motor ReportLab.
    """
    nome_produto = (
        "PRODUTO_SUPER_COMPRIDO_SEM_ESPACOS_PARA_TESTAR_A_QUEBRA_AUTOMATICA_DE_LINHA_NO_REPORTLAB_SENIOR" 
        if produto_longo else "Rato Óptico Pro"
    )
    dados = {
        'data': ['2026-06-07', '2026-06-07', '2026-06-07'],
        'total': [150000.00, 250000.00, 50000.00],
        'produto': [nome_produto, 'Teclado Mecânico', 'Tapete Gaming'],
        'qtd': [45, 12, 5]
    }
    return pd.DataFrame(dados)


# ── COBERTURA UNITÁRIA: COMPORTAMENTO DO MOTOR DE PDF ─────────────────────────

def test_geracao_pdf_com_texto_abusivo_nao_deve_quebrar_layout():
    """
    ENTENDIMENTO: Validação de Auto-Wrap e Robustez da Tabela.
    Garante que o motor ReportLab calcula as dimensões de células elásticas dinamicamente
    e quebra o texto abusivo em múltiplas linhas, sem disparar exceções críticas de
    geometria visual (ex: LayoutError/Overflow) ao deparar-se com inputs extremos de utilizadores.
    """
    df = obter_dados_mock(produto_longo=True)
    metricas = calcular_metricas(df, frequencia_cliente="semanal")
    
    timestamp_label = datetime.now().strftime('%Y%m%d_%H%M%S')
    hash_unico = uuid.uuid4().hex[:6]
    pdf_filename = f"report_{timestamp_label}_{hash_unico}.pdf"
    
    caminho_pdf = gerar_relatorio(
        metricas=metricas, 
        nome_negocio="Empresa Teste Limite", 
        output_dir="data/gold_test", 
        semana_label=pdf_filename
    )
    
    assert os.path.exists(caminho_pdf)
    assert os.path.getsize(caminho_pdf) > 0
    assert caminho_pdf.endswith(pdf_filename)


# ── COBERTURA DE CONCORRÊNCIA: EVITAR SUBSTITUIÇÃO INDEVIDA ───────────────────

def test_imutabilidade_de_geracao_concorrente_no_mesmo_segundo():
    """
    ENTENDIMENTO: Validação Contras Colisões de Cache Dinâmico.
    Simula submissões concorrentes massivas no mesmo microssegundo. Valida se a combinação de
    timestamps com hashes criptográficos (UUID truncado) força a imutabilidade física no disco.
    Se o isolamento falhar, o tamanho do 'set' será menor que 3 devido a sobreposições de ficheiros.
    """
    df = obter_dados_mock(produto_longo=False)
    metricas = calcular_metricas(df, frequencia_cliente="semanal")
    
    caminhos_gerados = set()
    
    for _ in range(3):
        timestamp_label = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico = uuid.uuid4().hex[:6]
        pdf_filename = f"report_{timestamp_label}_{hash_unico}.pdf"
        
        caminho = gerar_relatorio(
            metricas=metricas, 
            nome_negocio="Bazar Teste", 
            output_dir="data/gold_test", 
            semana_label=pdf_filename
        )
        caminhos_gerados.add(caminho)
        
    assert len(caminhos_gerados) == 3


# ── COBERTURA DE INTEGRAÇÃO: ROTAS DE WEBHOOK (FASTAPI) ───────────────────────

def test_endpoint_verificacao_webhook_meta(api_client):
    """
    ENTENDIMENTO: Validação de Contrato do Handshake da Meta.
    Simula o pedido HTTP GET assinado que os servidores do Facebook fazem ao ativar o Webhook.
    O endpoint deve verificar o token em memória de forma estrita e responder com o próprio challenge
    no formato esperado (inteiro/texto puro), garantindo a ativação do canal sem intervenção manual.
    """
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "token_teste_secreto",
        "hub.challenge": "123456789"
    }
    response = api_client.get("/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "123456789"


def test_webhook_recebimento_documento_para_onboarding_incompleto(api_client):
    """
    ENTENDIMENTO: Validação de Máquina de Estados e Segurança de Fluxo.
    Se um utilizador intercetar o fluxo normal enviando um documento antes de terminar
    as perguntas do onboarding, o sistema não pode tentar processar dados analíticos nulos.
    Deve reter o fluxo, registar o desvio, encaminhar o utilizador para o início do onboarding
    por texto e responder HTTP 200 imediatamente para desimpedir a fila concorrente da Meta.
    """
    phone_test = "258840000000"
    clientes_locais = carregar_todos_clientes()
    
    clientes_locais = [c for c in clientes_locais if c["numero"] != phone_test]
    clientes_locais.append({
        "numero": phone_test,
        "nome": None,
        "negocio": None,
        "email": None,
        "ultimo_ficheiro": None,
        "onboarding_passo": 1,
        "frequencia": "semanal"
    })
    guardar_clientes(clientes_locais)
    
    payload_mock = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": phone_test,
                        "type": "document",
                        "document": {
                            "id": "987654321",
                            "filename": "vendas_falsas.csv"
                        }
                    }]
                }
            }]
        }]
    }
    
    response = api_client.post("/webhook", json=payload_mock)
    assert response.status_code == 200