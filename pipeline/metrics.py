def calcular_metricas(df):
    return {
        'total': df['valor'].sum(),
        'total_transacoes': len(df),
        'media': df['valor'].mean(),
        'melhor_dia': df.groupby('data')['valor'].sum().idxmax(),
        'pior_dia': df.groupby('data')['valor'].sum().idxmin()
        'top_produtos': df.groupby('produto')['quantidade'].sum().sort_values(ascendind=False).head(5),
        'vendas_por_dia': df.groupby('dia')['valor'].sum()
    }