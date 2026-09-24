import json
import math
import re
import unicodedata
from collections import defaultdict
import pint

# Arquivo gerado pelo junta_resultados.py (contém as quatro categorias: com/sem RAG x com/sem instrução)
ARQUIVO_COMBINADO = "dados_combinados_v3.json"

# Instancia o registro de unidades globalmente
ureg = pint.UnitRegistry()

def pre_processar_para_pint(texto):
    if not texto: return ""
    # Remove aspas, asteriscos (negrito markdown) e ponto final que o LLM de extração às vezes devolve
    t = str(texto).strip().strip('\'"`*').rstrip('.')
    # Remove espaços e formata decimais, mas NÃO joga para minúsculo,
    # pois a Pint diferencia V (Volts) de v (velocidade/nada), M (Mega) de m (mili).
    t = t.replace(' ', '').replace(',', '.')

    # Ajustes de notação para forçar equivalência binária (Memória)
    t = re.sub(r'(?i)(kbytes?|kb)$', 'KiB', t)
    t = re.sub(r'(?i)(mbytes?|mb)$', 'MiB', t)
    t = re.sub(r'(?i)(gbytes?|gb)$', 'GiB', t)

    # Frequência
    t = re.sub(r'(?i)ghz$', 'GHz', t)
    t = re.sub(r'(?i)mhz$', 'MHz', t)
    t = re.sub(r'(?i)khz$', 'kHz', t)
    t = re.sub(r'(?i)hz$', 'Hz', t)

    return t

def comparar_com_pint(val1, val2):
    """
    Compara dois valores como grandezas físicas usando a Pint.
    Retorna True/False quando ambos são grandezas válidas, ou None quando algum
    deles não pode ser interpretado como grandeza (ex: 'Sim', 'Não').
    """
    t1 = pre_processar_para_pint(val1)
    t2 = pre_processar_para_pint(val2)
    # Sem dígito não é grandeza: evita que textos como 'N/A' sejam lidos como unidades (newton/ampere)
    if not re.search(r'\d', t1) or not re.search(r'\d', t2):
        return None
    try:
        q1 = ureg.Quantity(t1)
        q2 = ureg.Quantity(t2)
    except Exception:
        return None
    if q1.dimensionality != q2.dimensionality:
        return False
    # Compara em unidades base com tolerância, pois 72MHz == 0.072GHz falha em ponto flutuante
    return math.isclose(q1.to_base_units().magnitude, q2.to_base_units().magnitude, rel_tol=1e-9)

def normalizar_texto(texto):
    if not texto:
        return ""
    # Minúsculo e sem acentos (ex: 'Não' -> 'nao')
    texto = unicodedata.normalize('NFKD', str(texto).lower()).encode('ASCII', 'ignore').decode('ASCII')
    # Troca vírgula por ponto (para padronizar separadores decimais, ex: 3,3V -> 3.3V)
    texto = texto.replace(',', '.')
    # Mantém apenas letras, dígitos e ponto (remove espaços, aspas, asteriscos, etc.)
    texto = re.sub(r'[^a-z0-9.]', '', texto)
    return texto.strip('.')

def eh_nao_sei(valor_extraido):
    texto_limpo = unicodedata.normalize('NFKD', str(valor_extraido).lower()).encode('ASCII', 'ignore').decode('ASCII')
    texto_limpo = re.sub(r'[^a-z]', '', texto_limpo)
    return "naosei" in texto_limpo

ERRO_API = "erro_api"

# Marcadores de erro gravados por versões anteriores dos scripts (para avaliar resultados antigos)
ERROS_LEGADOS_EXTRACAO = {"erro na extração", "erro na extracao", "texto_vazio", "resposta_vazia"}
ERROS_LEGADOS_RESPOSTA = ("Erro na API", "Erro ao chamar API", "Erro: Resposta vazia",
                          "Erro ao analisar resposta da Cloudflare", "ERRO: Falha ao gerar embedding")

def eh_erro_api(valor_extraido, resposta_completa=""):
    """True quando a geração ou a extração falhou: não há resposta do modelo para avaliar."""
    valor = str(valor_extraido).strip()
    resposta = str(resposta_completa or "").strip()
    return (valor.lower().startswith(ERRO_API) or valor.lower() in ERROS_LEGADOS_EXTRACAO
            or resposta.startswith(ERRO_API) or resposta.startswith(ERROS_LEGADOS_RESPOSTA))

def classificar_resposta(resposta_verdadeira, valor_extraido, resposta_completa=""):
    """
    Critério único de acerto, usado para todas as categorias (com/sem RAG, com/sem instrução)
    e por todos os scripts do projeto. Retorna True, False, "nao_sei" ou "erro_api".
    - Erros de API não contam como resposta errada: ficam em uma categoria própria.
    - Valores numéricos (Flash, Speed, Number of I/O) são comparados pela Pint.
    - Valores categóricos (Sim/Não), que não são grandezas, são comparados como texto normalizado.
    """
    if eh_erro_api(valor_extraido, resposta_completa):
        return ERRO_API
    if eh_nao_sei(valor_extraido):
        return "nao_sei"

    resultado = comparar_com_pint(resposta_verdadeira, valor_extraido)
    if resultado is None:
        verdadeira_norm = normalizar_texto(resposta_verdadeira)
        resultado = verdadeira_norm != "" and verdadeira_norm == normalizar_texto(valor_extraido)
    return resultado

def nome_categoria(modelo):
    rag = "Com RAG" if modelo.get("rag") else "Sem RAG"
    instrucao = "com instrução" if modelo.get("instrucao") else "sem instrução"
    return f"{rag}, {instrucao}"

def imprimir_resumo(titulo, contagens):
    # Percentuais calculados sobre as respostas válidas (total - erros de API)
    print(f"\n{titulo}")
    print("-" * 140)
    print(f"{'':<60} | {'Corretas':<18} | {'Não sei':<18} | {'Erradas':<18} | {'Erro API':<10}")
    print("-" * 140)
    for nome, c in sorted(contagens.items()):
        validas = c["total"] - c["erro_api"]
        erradas = validas - c["corretas"] - c["nao_sei"]
        pct = lambda n: f"{n}/{validas} ({(n/validas)*100:.1f}%)" if validas else "0"
        print(f"{nome[:60]:<60} | {pct(c['corretas']):<18} | {pct(c['nao_sei']):<18} | {pct(erradas):<18} | {c['erro_api']:<10}")
    print("-" * 140)
    print("Percentuais sobre as respostas válidas. Respostas com erro de API não entram no cálculo.")

def avaliar_respostas(filepath):
    print(f"Lendo dados de {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        dados = json.load(f)

    por_modelo = defaultdict(lambda: {"corretas": 0, "nao_sei": 0, "erro_api": 0, "total": 0})
    por_categoria = defaultdict(lambda: {"corretas": 0, "nao_sei": 0, "erro_api": 0, "total": 0})

    for item in dados:
        resposta_verdadeira = item.get("resposta_verdadeira", "")

        if "respostas_modelos" in item:
            for i, modelo in enumerate(item["respostas_modelos"]):
                valor_extraido = modelo.get("valor_extraido", "")
                is_correct = classificar_resposta(resposta_verdadeira, valor_extraido, modelo.get("resposta_completa", ""))

                # Reconstruir o dicionário para garantir que 'correto'
                # fique logo abaixo de 'valor_extraido'
                novo_modelo = {}
                for k, v in modelo.items():
                    if k == "correto":
                        continue
                    novo_modelo[k] = v
                    if k == "valor_extraido":
                        novo_modelo["correto"] = is_correct

                # Caso a chave valor_extraido não exista por algum motivo
                if "valor_extraido" not in modelo:
                    novo_modelo["correto"] = is_correct

                item["respostas_modelos"][i] = novo_modelo

                for contagem in (por_modelo[modelo.get("modelo", "Desconhecido")], por_categoria[nome_categoria(modelo)]):
                    if is_correct is True:
                        contagem["corretas"] += 1
                    elif is_correct == "nao_sei":
                        contagem["nao_sei"] += 1
                    elif is_correct == ERRO_API:
                        contagem["erro_api"] += 1
                    contagem["total"] += 1

    if por_modelo:
        imprimir_resumo("Resultado por modelo:", por_modelo)
        imprimir_resumo("Resultado por categoria:", por_categoria)
    else:
        print("Avaliação concluída. 0 respostas avaliadas.")

    print(f"\nSalvando resultados em {filepath}...")
    with open(filepath, 'w', encoding='utf-8') as f:
        # ensure_ascii=False para manter acentuação correta
        json.dump(dados, f, ensure_ascii=False, indent=4)
    print("Pronto!")

if __name__ == "__main__":
    avaliar_respostas(ARQUIVO_COMBINADO)
