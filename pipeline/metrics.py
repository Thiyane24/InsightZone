import pandas as pd
import os

def calcular_metricas(df: pd.DataFrame, df_anterior: pd.DataFrame = None) -> dict:

    required = {'data', 'valor', 'produto', 'quantidade'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'Colunas em falta: {missing}')
    if df.empty:
        raise ValueError('DataFrame vazio nenhuma linha para processar')

    vendas_por_data = df.groupby('data')['valor'].sum()
    total = df['valor'].sum()

    metricas = {
        'total': total,
        'total_transacoes': len(df),
        'media': df['valor'].mean(),
        'melhor_dia': vendas_por_data.idxmax(),
        'pior_dia': vendas_por_data.idxmin(),
        'top_produtos': df.groupby('produto')['quantidade'].sum().sort_values(ascending=False).head(5),
        'vendas_por_dia': vendas_por_data
    }

    # Variação vs semana anterior, só se df_anterior for fornecido
    if df_anterior is not None and not df_anterior.empty:
        total_anterior = df_anterior['valor'].sum()
        metricas['variacao_pct'] = ((total - total_anterior) / total_anterior) * 100

    # Salva silver layer
    os.makedirs('data/silver', exist_ok=True)
    semana = str(df['data'].max()).replace('/', '-')     
    df.to_parquet(f'data/silver/{semana}.parquet', index=False)

    return metricas