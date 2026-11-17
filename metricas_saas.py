"""Regras de métricas (MRR, churn e LTV) do projeto ETL.

Cópia das funções de cálculo de churn_ltv.py do repositório
https://github.com/davicarneiroc4-star/etl-saas-pandas-mysql, que gerou os CSVs de dados_limpos/.
Se uma regra mudar lá, atualize aqui também.
"""
import pandas as pd

# Janela usada no churn médio e no LTV
MESES_JANELA = 12


def valor_mensal(df):
    """Valor por mês (MRR) de cada assinatura: plano anual vale 1/12 do preço.
    Regra única do projeto; só a visão SQL mrr_assinaturas (ferramentas.py) repete em SQL."""
    return df['valor_assinatura'].where(df['periodicidade'] != 'anual', df['valor_assinatura'] / 12)


def preparar_dados(assinaturas, planos, cancelamentos):
    df = assinaturas.merge(planos[['id_plano', 'nome_plano', 'periodicidade']], on='id_plano', how='left')
    df = df.merge(cancelamentos[['id_assinatura', 'tipo_cancelamento']], on='id_assinatura', how='left')

    # Só assinaturas pagas: trial e plano Free não geram receita
    df = df[(df['status'] != 'trial') & (df['nome_plano'] != 'Free')].copy()

    df['valor_mensal'] = valor_mensal(df)

    df['data_inicio'] = pd.to_datetime(df['data_inicio'])
    df['data_fim'] = pd.to_datetime(df['data_fim'])

    return df


def periodo_analise(df):
    """Meses da série de churn e a janela dos últimos MESES_JANELA meses."""
    # Os dados de cancelamento vão só até a data em que foram gerados.
    # Usar meses depois disso daria churn 0% falso, então a análise para no último mês com cancelamentos.
    ultimo_mes = df['data_fim'].max().to_period('M')
    # No mês da primeira assinatura ninguém estava ativo no dia 1º, então a série começa no mês seguinte
    primeiro_mes = df['data_inicio'].min().to_period('M') + 1
    meses = pd.period_range(primeiro_mes, ultimo_mes, freq='M')
    return meses, meses[-MESES_JANELA:]


def calcular_churn_mensal(df, meses):
    """Para cada mês: quantas assinaturas estavam ativas no dia 1º e quantas delas cancelaram até o fim do mês."""
    linhas = []
    for mes in meses:
        inicio = mes.start_time
        fim = (mes + 1).start_time

        # Mesma regra do gráfico de MRR: ativa no dia 1º do mês
        ativas = df[(df['data_inicio'] <= inicio) & (df['data_fim'].isna() | (df['data_fim'] > inicio))]
        canceladas = ativas[ativas['data_fim'] <= fim]

        linhas.append({
            'mes': mes,
            'ativas_inicio': len(ativas),
            'canceladas': len(canceladas),
            'voluntarias': (canceladas['tipo_cancelamento'] == 'voluntário').sum(),
            'involuntarias': (canceladas['tipo_cancelamento'] == 'involuntário').sum(),
            'mrr_inicio': ativas['valor_mensal'].sum(),
            'mrr_perdido': canceladas['valor_mensal'].sum(),
        })

    churn = pd.DataFrame(linhas).set_index('mes')
    churn['churn_clientes'] = churn['canceladas'] / churn['ativas_inicio']
    churn['churn_receita'] = churn['mrr_perdido'] / churn['mrr_inicio']
    return churn


def resumir_janela(churn):
    """Churn médio e ticket médio de um período, somando os meses (meses com base maior pesam mais)."""
    churn_medio = churn['canceladas'].sum() / churn['ativas_inicio'].sum()
    ticket_medio = churn['mrr_inicio'].sum() / churn['ativas_inicio'].sum()
    return churn_medio, ticket_medio


def calcular_ltv(df, meses):
    linhas = []
    grupos = [('Geral', df)] + list(df.groupby('nome_plano'))
    for nome, grupo in grupos:
        churn_medio, ticket_medio = resumir_janela(calcular_churn_mensal(grupo, meses))
        vida_media = 1 / churn_medio if churn_medio > 0 else float('inf')
        linhas.append({
            'plano': nome,
            'ticket_mensal': ticket_medio,
            'churn_mensal': churn_medio,
            'vida_media_meses': vida_media,
            'ltv': ticket_medio * vida_media,
        })
    return pd.DataFrame(linhas).set_index('plano')
