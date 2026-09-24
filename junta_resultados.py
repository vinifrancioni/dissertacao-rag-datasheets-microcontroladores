import json
import os
import re
from collections import defaultdict
import pandas as pd

# --- ARQUIVOS ---
# Resultados já com o campo 'valor_extraido' preenchido:
#  - sem RAG: gerado pelo script-unificado.ipynb (extração feita no próprio script)
#  - com RAG: gerados pelo 1. script_rag_v3_html.ipynb e extraídos pelo 2. extracao.ipynb
ARQUIVOS_ENTRADA = [
    "resultados_sem_rag.json",
    "resultados_rag_phi-4-mini_v3_extraido.json",
    "resultados_rag_gemini-2.5-flash_v3_extraido.json",
]
ARQUIVO_EXCEL = "microcontroladores-populares.xlsx"
ARQUIVO_SAIDA = "dados_combinados_v3.json"

COLUNAS_PERGUNTAS = ["PERGUNTA01", "PERGUNTA02", "PERGUNTA03", "PERGUNTA04", "PERGUNTA05", "PERGUNTA06"]


def mapear_perguntas_excel(arquivo_excel):
    """
    Retorna {texto_da_pergunta: [(linha_excel, coluna_pergunta), ...]}.
    Usado para localizar resultados antigos que não gravavam 'linha_excel'/'coluna_pergunta'.
    Uma lista é necessária porque a planilha possui microcontroladores repetidos.
    """
    df = pd.read_excel(arquivo_excel)
    mapa = defaultdict(list)
    for index, row in df.iterrows():
        for coluna in COLUNAS_PERGUNTAS:
            if isinstance(row[coluna], str):
                mapa[row[coluna].strip()].append((int(index), coluna))
    return mapa


def inferir_instrucao(texto):
    """Procura 'com_instrucao' / 'sem_instrucao' (ou com hífen) em um nome de modelo ou de arquivo."""
    match = re.search(r'(com|sem)[_-]instrucao', texto)
    return None if not match else match.group(1) == "com"


def padronizar_resposta(resposta, item, arquivo):
    """
    Garante que a resposta tenha 'modelo_base', 'rag', 'instrucao' e um nome 'modelo' no formato
    <modelo_base>_<com_rag|sem_rag>_<com_instrucao|sem_instrucao>, inferindo esses campos
    em resultados gerados por versões anteriores dos scripts.
    """
    nome = resposta.get("modelo", "Desconhecido")
    rag = resposta.get("rag", "contexto_recuperado" in item)
    instrucao = resposta.get("instrucao")
    if instrucao is None:
        instrucao = inferir_instrucao(nome)
    if instrucao is None:
        instrucao = inferir_instrucao(os.path.basename(arquivo))
    if instrucao is None:
        raise ValueError(f"Não foi possível identificar se '{nome}' em '{arquivo}' é com ou sem instrução.")

    modelo_base = resposta.get("modelo_base") or re.sub(r'(_(com|sem)_rag)?_(com|sem)[_-]instrucao$', '', nome)
    sufixo_rag = "com_rag" if rag else "sem_rag"
    sufixo_instrucao = "com_instrucao" if instrucao else "sem_instrucao"

    padronizada = dict(resposta)
    padronizada.update({
        "modelo": f"{modelo_base}_{sufixo_rag}_{sufixo_instrucao}",
        "modelo_base": modelo_base,
        "rag": rag,
        "instrucao": instrucao,
    })
    return padronizada


def juntar_resultados(arquivos_entrada, arquivo_excel, arquivo_saida):
    mapa_excel = mapear_perguntas_excel(arquivo_excel)
    combinados = {}

    for arquivo in arquivos_entrada:
        if not os.path.exists(arquivo):
            print(f"AVISO: Arquivo '{arquivo}' não encontrado. Pulando.")
            continue
        with open(arquivo, 'r', encoding='utf-8') as f:
            dados = json.load(f)
        print(f"Lendo '{arquivo}' ({len(dados)} perguntas)...")

        # Controla quais linhas do Excel já foram usadas por pergunta repetida, neste arquivo
        ocorrencias = defaultdict(int)
        sem_extracao = 0

        for item in dados:
            pergunta = str(item.get("pergunta", "")).strip()
            linha = item.get("linha_excel")
            coluna = item.get("coluna_pergunta")

            if linha is None or coluna is None:
                posicoes = mapa_excel.get(pergunta, [])
                n = ocorrencias[pergunta]
                ocorrencias[pergunta] += 1
                if n >= len(posicoes):
                    print(f"   AVISO: Pergunta não encontrada na planilha (ou repetida além do esperado): '{pergunta}'. Pulando.")
                    continue
                linha, coluna = posicoes[n]

            chave = (int(linha), coluna)
            if chave not in combinados:
                combinados[chave] = {
                    "linha_excel": int(linha),
                    "coluna_pergunta": coluna,
                    "pergunta": pergunta,
                    "resposta_verdadeira": item.get("resposta_verdadeira"),
                    "coluna_resposta": item.get("coluna_resposta"),
                    "respostas_modelos": [],
                }
            destino = combinados[chave]

            # O contexto recuperado é o mesmo para todos os modelos (mesma pergunta, mesmo banco vetorial)
            if "contexto_recuperado" in item and "contexto_recuperado" not in destino:
                destino["contexto_recuperado"] = item["contexto_recuperado"]
            if not destino.get("coluna_resposta") and item.get("coluna_resposta"):
                destino["coluna_resposta"] = item["coluna_resposta"]

            modelos_existentes = {r["modelo"] for r in destino["respostas_modelos"]}
            for resposta in item.get("respostas_modelos", []):
                padronizada = padronizar_resposta(resposta, item, arquivo)
                if "valor_extraido" not in padronizada:
                    sem_extracao += 1
                if padronizada["modelo"] in modelos_existentes:
                    print(f"   AVISO: Resposta duplicada de '{padronizada['modelo']}' na linha {linha} ({coluna}). Mantendo a primeira.")
                    continue
                modelos_existentes.add(padronizada["modelo"])
                destino["respostas_modelos"].append(padronizada)

        if sem_extracao:
            print(f"   AVISO: {sem_extracao} respostas sem 'valor_extraido' em '{arquivo}'. Rode a extração antes de juntar.")

    resultado = [combinados[chave] for chave in sorted(combinados)]

    with open(arquivo_saida, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=4)

    contagem = defaultdict(int)
    for item in resultado:
        for resposta in item["respostas_modelos"]:
            contagem[resposta["modelo"]] += 1

    print(f"\n{len(resultado)} perguntas salvas em '{arquivo_saida}'. Respostas por modelo:")
    for modelo, n in sorted(contagem.items()):
        print(f"   {modelo:<70} {n}")


if __name__ == "__main__":
    juntar_resultados(ARQUIVOS_ENTRADA, ARQUIVO_EXCEL, ARQUIVO_SAIDA)
