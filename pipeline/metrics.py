import pandas as pd
from datetime import datetime

def calcular_metricas(df: pd.DataFrame, frequencia_cliente: str = "semanal") -> dict:
    # 1. NORMALIZAÇÃO DE COLUNAS
    # Converte todos os nomes de colunas para minúsculas e remove espaços em branco extras nas pontas.
    # Isto evita quebras se o cliente enviar "Produto", "PRODUTO" ou "produto ".
    df.columns = [col.lower().strip() for col in df.columns]
    
    # 2. MAPEAMENTO DINÂMICO DE COLUNAS (DISCOVERY)
    # Procura termos-chave dentro das colunas para identificar onde estão as variáveis cruciais,
    # permitindo que o sistema aceite múltiplos formatos de relatórios/planilhas estruturadas.
    col_data = next((c for c in df.columns if 'data' in c or 'date' in c), None)
    col_total = next((c for c in df.columns if 'total' in c or 'revenue' in c or 'faturac' in c or 'valor' in c), None)
    col_produto = next((c for c in df.columns if 'prod' in c or 'item' in c), None)
    col_qtd = next((c for c in df.columns if 'qtd' in c or 'quant' in c or 'qty' in c), None)

    # 3. TRATAMENTO DE VALORES EM FALTA (FALLBACKS)
    # Se a planilha não tiver uma coluna de "Total", mas tiver a "Quantidade", tenta procurar
    # uma coluna de preço unitário para recalcular e reconstruir o faturamento da linha.
    if not col_total and col_qtd:
        col_preco = next((c for c in df.columns if 'prec' in c or 'price' in c), None)
        if col_preco:
            df['total_calculado'] = df[col_preco] * df[col_qtd]
            col_total = 'total_calculado'

    # 4. PARSING DE DATAS COM SEGURANÇA
    # Tenta converter a coluna de data para o tipo Datetime do Pandas. 
    # Linhas com datas corrompidas ou textos inválidos viram NaT (Not a Time) e são descartadas.
    if col_data:
        df[col_data] = pd.to_datetime(df[col_data], errors='coerce')
        df = df.dropna(subset=[col_data])
    else:
        # Se o ficheiro não contiver nenhuma coluna temporal, assume o dia de hoje como fallback
        # para evitar crashar os agrupamentos por data do ReportLab.
        df['data_fallback'] = pd.to_datetime(datetime.now().date())
        col_data = 'data_fallback'

    # 5. GARANTIA DE TIPOS NUMÉRICOS
    # Força as colunas financeiras e de volume a serem estritamente numéricas (float/int).
    # Caso existam strings misturadas (ex: "MZN 150" ou campos vazios), preenche com valores seguros padrão (0.0 ou 1).
    if col_total:
        df[col_total] = pd.to_numeric(df[col_total], errors='coerce').fillna(0.0)
    else:
        df['total_zero'] = 0.0
        col_total = 'total_zero'
        
    if col_qtd:
        df[col_qtd] = pd.to_numeric(df[col_qtd], errors='coerce').fillna(1)
    else:
        df['qtd_um'] = 1
        col_qtd = 'qtd_um'

    # 6. CÁLCULO DOS CORES KPIs (MÓDULO DATA-DRIVEN)
    # Soma o faturamento total bruto.
    total_faturado = float(df[col_total].sum())
    
    # Identifica transações únicas. Se houver coluna de ID/Fatura/Recibo, conta os códigos únicos.
    # Se não houver, assume que cada linha da planilha representa uma venda isolada.
    col_id = next((c for c in df.columns if 'id' in c or 'fatura' in c or 'recibo' in c), None)
    total_transacoes = int(df[col_id].nunique()) if col_id else int(len(df))

    # Agrupa as vendas por dia do calendário e descobre qual foi a data com maior volume financeiro.
    vendas_por_dia = df.groupby(df[col_data].dt.date)[col_total].sum()
    if not vendas_por_dia.empty:
        melhor_dia_dt = vendas_por_dia.idxmax()
        melhor_dia_str = melhor_dia_dt.strftime('%Y-%m-%d')
    else:
        melhor_dia_str = datetime.now().strftime('%Y-%m-%d')

    # Agrupa pelo nome do produto, soma as quantidades absolutas vendidas e extrai os 5 líderes (Top 5).
    # Converte o output do Pandas para um dicionário Python nativo aceitável pelo ReportLab.
    if col_produto:
        produtos_agrupados = df.groupby(col_produto)[col_qtd].sum().sort_values(ascending=False)
        top_produtos_dict = produtos_agrupados.head(5).to_dict()
    else:
        top_produtos_dict = {"Nenhum produto detetado": 0}

    # 7. MÉTRICAS AVANÇADAS PARA A TOMADA DE DECISÃO
    # Coleta o nome do mês atual para relatórios mensais e calcula o Ticket Médio (Faturamento / Transações).
    mes_nome = datetime.now().strftime('%B')
    ticket_medio = total_faturado / total_transacoes if total_transacoes > 0 else 0.0

    # 8. ESTRUTURAÇÃO DO DICIONÁRIO DE RETORNO (DADOS COMPATÍVEIS COM O REPORT.PY)
    # Agrupa todas as variáveis calculadas num payload limpo. Mantém chaves duplicadas (mensal/semanal)
    # para garantir que o layout do PDF não quebre se o cliente alternar o modo operacional no chatbot.
    metricas = {
        "total": total_faturado,
        "total_transacoes": total_transacoes,
        "ticket_medio": ticket_medio,
        "melhor_dia": melhor_dia_str,
        "top_produtos": top_produtos_dict,
        
        "total_mensal": total_faturado,
        "transacoes_mensal": total_transacoes,
        "ticket_medio_mensal": ticket_medio,
        "melhor_dia_mes": melhor_dia_str,
        "top_produtos_mes": top_produtos_dict,
        "mes_nome": mes_nome,
        
        "variacao_pct": None 
    }

    return metricas