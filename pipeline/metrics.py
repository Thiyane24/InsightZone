import pandas as pd
import os

def calcular_metricas(df: pd.DataFrame) -> dict:
   
    required = {'data', 'valor', 'produto', 'quantidade'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'Colunas em falta: {missing}')
    if df.empty:
        raise ValueError('DataFrame vazio nenhuma linha para processar')

    vendas_por_data = df.groupby('data')['valor'].sum()  # computed once, reused 3x

    metricas = {
        'total': df['valor'].sum(),
        'total_transacoes': len(df),
        'media': df['valor'].mean(),
        'melhor_dia': vendas_por_data.idxmax(),
        'pior_dia': vendas_por_data.idxmin(),
        'top_produtos': df.groupby('produto')['quantidade'].sum().sort_values(ascending=False).head(5),
        'vendas_por_dia': vendas_por_data
    }

    # Salva silver layer
    os.makedirs('data/silver', exist_ok=True)
    df.to_parquet('data/silver/processed.parquet', index=False)

    return metricas