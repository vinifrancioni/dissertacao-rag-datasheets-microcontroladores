import json
import csv
from scipy.stats import pointbiserialr
import ijson
import matplotlib.pyplot as plt
import os
from matplotlib.backends.backend_pdf import PdfPages

# Mesmo critério de acerto (Pint) usado no avalia_respostas_rag.py
from avalia_respostas_rag import classificar_resposta, ARQUIVO_COMBINADO

def plot_histograms(input_file):
    modelos_data = {}

    print(f"Lendo o arquivo {input_file} e processando dados...")
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            # Usando ijson para evitar carregar o arquivo inteiro na memória
            objects = ijson.items(f, 'item')
            
            for item in objects:
                resp_verdadeira = item.get('resposta_verdadeira', '')
                respostas_modelos = item.get('respostas_modelos', [])
                
                for resp in respostas_modelos:
                    modelo = resp.get('modelo', 'Desconhecido')
                    valor_extraido = resp.get('valor_extraido', '')
                    resposta_completa = resp.get('resposta_completa', '')
                    
                    if modelo not in modelos_data:
                        modelos_data[modelo] = {'certos': [], 'errados': [], 'nao_sei': [], 'erro_api': 0}

                    comprimento = len(str(resposta_completa))

                    resultado = classificar_resposta(resp_verdadeira, valor_extraido, resposta_completa)

                    # Erros de API não têm resposta do modelo: só são contados, ficam fora dos gráficos
                    if resultado == 'erro_api':
                        modelos_data[modelo]['erro_api'] += 1
                    elif resultado == 'nao_sei':
                        modelos_data[modelo]['nao_sei'].append(comprimento)
                    elif resultado is True:
                        modelos_data[modelo]['certos'].append(comprimento)
                    else:
                        modelos_data[modelo]['errados'].append(comprimento)
                        
    except Exception as e:
        print(f"Erro durante a leitura do arquivo: {e}")
        return
                
    print("\nResumo dos Dados por Modelo:")
    print("-" * 126)
    print(f"{'Modelo':<45} | {'Certas':<8} | {'Erradas':<8} | {'Não Sei':<8} | {'Total':<8} | {'Erro API':<8} | {'Corr (r)':<9} | {'p-value':<9}")
    print("-" * 126)

    csv_filename = 'resumo_modelos.csv'
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['Modelo', 'Certas', 'Erradas', 'Não Sei', 'Total', 'Erro API', 'Correlacao (r)', 'p-value'])

        for modelo, dados_modelo in sorted(modelos_data.items()):
            qtd_certos = len(dados_modelo['certos'])
            qtd_errados = len(dados_modelo['errados'])
            qtd_nao_sei = len(dados_modelo['nao_sei'])
            qtd_erro_api = dados_modelo['erro_api']
            # Total de respostas válidas (sem os erros de API)
            total = qtd_certos + qtd_errados + qtd_nao_sei
            
            r_value, p_value = None, None
            if (qtd_certos > 0 and qtd_errados > 0) and (qtd_certos + qtd_errados > 1):
                x = dados_modelo['certos'] + dados_modelo['errados']
                y = [1] * qtd_certos + [0] * qtd_errados
                try:
                    r_value, p_value = pointbiserialr(x, y)
                except Exception:
                    pass
            
            r_str = f"{r_value:.4f}" if r_value is not None else "N/A"
            p_str = f"{p_value:.4f}" if p_value is not None else "N/A"
            
            if total > 0 or qtd_erro_api > 0:
                print(f"{modelo[:45]:<45} | {qtd_certos:<8} | {qtd_errados:<8} | {qtd_nao_sei:<8} | {total:<8} | {qtd_erro_api:<8} | {r_str:<9} | {p_str:<9}")
                csvwriter.writerow([modelo, qtd_certos, qtd_errados, qtd_nao_sei, total, qtd_erro_api, r_value, p_value])

    print("-" * 126 + "\n")
    print(f"Os dados da tabela foram salvos em: {csv_filename}\n")
    
    print("Gerando gráficos no arquivo PDF...")
    
    pdf_filename = 'histogramas_modelos.pdf'
    
    with PdfPages(pdf_filename) as pdf:
        # Ordenando alfabeticamente pelo nome do modelo
        for modelo, dados_modelo in sorted(modelos_data.items()):
            certos = dados_modelo['certos']
            errados = dados_modelo['errados']
            nao_sei = dados_modelo['nao_sei']
            
            if not certos and not errados and not nao_sei:
                print(f"Sem dados para o modelo: {modelo}")
                continue
                
            plt.figure(figsize=(10, 6))
            
            if errados:
                plt.hist(errados, bins=50, color='red', alpha=0.5, label='Erradas', edgecolor='black')
            if certos:
                plt.hist(certos, bins=50, color='green', alpha=0.5, label='Certas', edgecolor='black')
            if nao_sei:
                # Plotando "não sei" em cinza e com linhas pontilhadas (dotted)
                plt.hist(nao_sei, bins=50, color='gray', alpha=0.5, label='Não Sei', edgecolor='black', linestyle=':', linewidth=2)
            
            plt.title(f'Histograma de Comprimento de "resposta_completa"\nModelo: {modelo}')
            plt.xlabel('Comprimento (quantidade de caracteres)')
            plt.ylabel('Frequência')
            plt.legend()
            plt.grid(axis='y', alpha=0.75, linestyle='--')
            
            # Salvar no PDF
            pdf.savefig(bbox_inches='tight')
            plt.close()
            
        print("Gerando gráficos boxplot no final do arquivo PDF...")
        for modelo, dados_modelo in sorted(modelos_data.items()):
            certos = dados_modelo['certos']
            errados = dados_modelo['errados']
            
            if not certos and not errados:
                continue
                
            plt.figure(figsize=(8, 6))
            
            data_to_plot = []
            labels = []
            colors = []
            
            if errados:
                data_to_plot.append(errados)
                labels.append('Erradas')
                colors.append('lightcoral')
            if certos:
                data_to_plot.append(certos)
                labels.append('Certas')
                colors.append('lightgreen')
                
            bplot = plt.boxplot(data_to_plot, labels=labels, patch_artist=True)
            
            for patch, color in zip(bplot['boxes'], colors):
                patch.set_facecolor(color)
                
            plt.title(f'Boxplot de Comprimento (Certas vs Erradas)\nModelo: {modelo}')
            plt.ylabel('Comprimento (quantidade de caracteres)')
            plt.grid(axis='y', alpha=0.75, linestyle='--')
            
            # Salvar no PDF
            pdf.savefig(bbox_inches='tight')
            plt.close()
            
    print(f"Todos os gráficos foram salvos com sucesso em: {pdf_filename}")

if __name__ == '__main__':
    arquivo_entrada = ARQUIVO_COMBINADO
    
    if not os.path.exists(arquivo_entrada):
        print(f"Erro: O arquivo '{arquivo_entrada}' não foi encontrado.")
    else:
        plot_histograms(arquivo_entrada)
