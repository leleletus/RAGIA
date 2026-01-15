import os
import json
import re
import time
import google.genai as genai
from google.genai import types 
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

# --- CARGAR CLAVES ---
load_dotenv(".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY: raise ValueError("Falta GEMINI_API_KEY en .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# --- CONFIGURACIÓN ---
MODEL_LOGIC = "models/gemini-2.5-flash"
MODEL_RAG = "models/gemini-3-flash-preview"
EMBEDDING_MODEL = "models/text-embedding-004"
TABLE_NAME = "documentos_dj"

# --- 0. UTILIDAD DE HORA (NUEVO) ---
def obtener_hora_lima():
    """Calcula la hora de Lima (UTC-5) manualmente para no depender de librerías extra."""
    utc_now = datetime.now(timezone.utc)
    lima_time = utc_now - timedelta(hours=5)
    return lima_time.strftime("%A %d de %B del %Y, %I:%M %p (Hora Perú)")

# --- 1. SEGURIDAD ---
def call_gemini_safe(model, prompt, retries=3, notify_callback=None, tools=None):
    """
    Función maestra para llamar a la IA. Soporta herramientas (Google Search) y reintentos.
    """
    for attempt in range(retries):
        try:
            config = None
            if tools:
                config = types.GenerateContentConfig(tools=tools)

            return client.models.generate_content(
                model=model, 
                contents=prompt,
                config=config
            ).text.strip()
            
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = 25 
                msg = f"🚦 IA saturada. Esperando {wait_time}s... (Intento {attempt+1})"
                print(f"   {msg}")
                if notify_callback: notify_callback(msg)
                time.sleep(wait_time)
            else:
                return f"Error IA: {str(e)}"
    return "Sistema saturado. Intenta más tarde."

# --- 2. HERRAMIENTAS DB ---
def detectar_esquema_db():
    try:
        resp = supabase.table(TABLE_NAME).select("metadata").limit(1).execute()
        if resp.data: return list(resp.data[0]['metadata'].keys())
        return []
    except: return []

COLUMNAS_REALES = detectar_esquema_db()

def obtener_estados_validos():
    try:
        resp = supabase.table(TABLE_NAME).select("metadata").limit(200).execute()
        estados = set()
        if resp.data:
            for d in resp.data:
                estado = d['metadata'].get('estado de oferta')
                if estado: estados.add(str(estado).upper())
        return list(estados)
    except:
        return ["PENDIENTE", "ADJUDICADO", "NO ADJUDICADO"]

def execute_sql_query(sql_query):
    try:
        clean_sql = re.sub(r"```sql|```", "", sql_query, flags=re.IGNORECASE).strip().replace(";", "")
        if not clean_sql.lower().startswith("select"): return "Error: SQL inválido."
        print(f"   [Debug SQL]: {clean_sql}") 
        resp = supabase.rpc("query_exec", {"query": clean_sql}).execute()
        return resp.data
    except Exception as e: return f"Error DB: {str(e)}"

# --- 3. BUSCADOR VECTORIAL/EXACTO ---
def get_embedding(text):
    try:
        resp = client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
        return resp.embeddings[0].values
    except: return []

def search_exact_flexible(query):
    resultados = []
    ids_encontrados = set()
    patron_txt = re.findall(r"\b((?:OF|SZ|SZ\d)-[\w\d_.-]+)\b", query, re.IGNORECASE)
    patron_num = re.findall(r"\b(\d+)\b", query)
    tokens = set(patron_txt + patron_num)

    if not tokens: return []
    
    for token in tokens:
        cols_codigo = [c for c in COLUMNAS_REALES if "codigo" in c or "oferta" in c]
        for col in cols_codigo:
            try:
                res = supabase.table(TABLE_NAME).select("*").ilike(f"metadata->>{col}", f"%{token}%").execute()
                for d in res.data:
                    if d['id'] not in ids_encontrados:
                        d['source_type'] = f"EXACTO ({col})"
                        resultados.append(d)
                        ids_encontrados.add(d['id'])
            except: pass
        
        if token.isdigit() and "id_excel" in COLUMNAS_REALES:
            try:
                res = supabase.table(TABLE_NAME).select("*").eq("metadata->>id_excel", token).execute()
                for d in res.data:
                    if d['id'] not in ids_encontrados:
                        d['source_type'] = "ID EXCEL"
                        resultados.append(d)
                        ids_encontrados.add(d['id'])
            except: pass
    return resultados

def search_vector(query_text, top_k=5):
    vec = get_embedding(query_text)
    if not vec: return []
    try:
        return supabase.rpc("match_documentos", {"query_embedding": vec, "match_threshold": 0.45, "match_count": top_k}).execute().data or []
    except: return []

def format_history(history):
    if not history: return "Sin historial."
    return "\n".join([f"{'USER' if m['role']=='user' else 'IA'}: {m['content']}" for m in history[-6:]])

# --- 4. ROUTER INTELIGENTE ---
def decide_route(q, history, cb):
    q_lower = q.lower()

    # RUTA 1: BASE DE DATOS (Fast-Path)
    # Palabras clave del negocio fuerzan SQL.
    keywords_db = [
        "pendiente", "adjudicad", "ganad", "perdid", "oferta", "licitacion", 
        "cliente", "202", "201", "200", "estado", "codigo", "id", "of-", "sz-", 
        "disponible", "vigente", "proceso", "base de datos"
    ]
    for kw in keywords_db:
        if kw in q_lower: return "SQL"

    # RUTA 2: WEB (Fast-Path)
    # Consultas de internet.
    keywords_web = [
        "hora", "clima", "tiempo", "noticia", "dolar", "dólar", "precio", 
        "busca en google", "quién es", "cuando es", "resultados del", 
        "actualidad", "hoy"
    ]
    for kw in keywords_web:
        if kw in q_lower: return "WEB"

    # RUTA 3: IA DECIDE
    hist = format_history(history)
    prompt = f"""
    Router. HISTORIAL: {hist}\nPREGUNTA: '{q}'
    Clasifica:
    1. 'SQL': Preguntas sobre la empresa, licitaciones, ofertas internas.
    2. 'WEB': Preguntas de cultura general actual, clima, hora, noticias.
    3. 'GENERAL': Chistes, saludos, consejos, filosofía.
    Respuesta (SOLO PALABRA):"""
    return call_gemini_safe(MODEL_LOGIC, prompt, notify_callback=cb).upper()

# --- 5. AGENTE WEB (CON HORA LOCAL) ---
def response_web(q, history, cb):
    print("   [Modo]: WEB SEARCH (Google)")
    hora_actual = obtener_hora_lima() # <--- AQUÍ LA CLAVE
    
    google_search_tool = [types.Tool(google_search=types.GoogleSearch())]
    prompt = f"""
    Responde a la pregunta del usuario usando Google Search.
    
    CONTEXTO OBLIGATORIO:
    - Hora y Fecha actual del usuario (Perú): {hora_actual}.
    - Si preguntan "qué hora es", USA ESTE DATO, no busques en Google si no es necesario.
    
    Usuario: "{q}"
    Contexto conversación: {history[-1]['content'] if history else ''}
    
    Sé directo y útil.
    """
    return call_gemini_safe(MODEL_LOGIC, prompt, notify_callback=cb, tools=google_search_tool)

# --- 6. AGENTE SQL (CORPORATIVO) ---
def response_sql(q, history, cb):
    print("   [Modo]: SQL")
    keys_json = ', '.join(COLUMNAS_REALES)
    
    prompt = f"""
    ERES UN EXPERTO EN SQL POSTGRESQL. TABLA: '{TABLE_NAME}'.
    CLAVES METADATA: {keys_json}.
    
    HISTORIAL: {format_history(history)}
    PREGUNTA: '{q}'
    
    REGLAS OBLIGATORIAS:
    1. **NO USES COLUMNAS DIRECTAS.** Usa SIEMPRE `metadata->>'clave'`.
    
    2. **FECHAS Y AÑOS (REGLA MAESTRA):**
       - ¡NO USES COLUMNAS DE FECHA! BUSCA EN EL CÓDIGO DE OFERTA.
       - Si piden "del 2024" -> `(metadata->>'codigo de oferta' ILIKE '%OF-24%' OR metadata->>'codigo de oferta' ILIKE '%_24%')`
       - Si piden "del 2017" -> `(metadata->>'codigo de oferta' ILIKE '%OF-17%' OR metadata->>'codigo de oferta' ILIKE '%_17%')`
       - Si hay códigos SZ, busca `_XX` al final (ej: `SZ%_17`).
       
    3. **ESTADOS (LÓGICA EXACTA):**
       - "Adjudicadas" -> `metadata->>'estado de oferta' ILIKE '%ADJUDICAD%' AND metadata->>'estado de oferta' NOT ILIKE '%NO%'`
         (Esto es vital para no contar las 'NO ADJUDICADAS' como ganadas).
       - "No Adjudicadas" -> `metadata->>'estado de oferta' ILIKE '%NO ADJUDICAD%'`
       - "Pendientes/Disponibles" -> `metadata->>'estado de oferta' ILIKE '%PENDIENT%'`
    
    4. **ANTI-CONTAMINACIÓN:**
       - Si la pregunta NO especifica año, NO filtres por año (aunque el historial lo mencione). Cuenta el TOTAL HISTÓRICO.
    
    Genera SOLO SQL.
    """
    sql = call_gemini_safe(MODEL_LOGIC, prompt, notify_callback=cb)
    
    if "SELECT" not in sql.upper():
         return response_hybrid_rag(q, history, cb)

    res = execute_sql_query(sql)
    
    if isinstance(res, str): return f"Error SQL: {res}"
    
    if not res or (isinstance(res, list) and len(res) == 0) or (isinstance(res, list) and len(res)==1 and res[0].get('count') == 0):
        estados_reales = obtener_estados_validos()
        prompt_sugerencia = f"""
        Usuario buscó: "{q}". SQL dio 0 resultados.
        ESTADOS REALES: {json.dumps(estados_reales)}
        INSTRUCCIONES: Di que no hay coincidencias y sugiere un estado real.
        """
        return call_gemini_safe(MODEL_RAG, prompt_sugerencia, notify_callback=cb)

    narracion = f"Pregunta: {q}\nDatos: {json.dumps(res, ensure_ascii=False)}\nResponde natural. Si es lista: * [CODIGO]: [CLIENTE] ([ESTADO])"
    return call_gemini_safe(MODEL_RAG, narracion, notify_callback=cb)

# --- 7. AGENTE RAG ---
def response_hybrid_rag(q, history, cb):
    q_ctx = q
    if len(history)>0 and len(q.split())<4: q_ctx = f"{q} (Contexto: {history[-1]['content']})"

    exact = search_exact_flexible(q)
    vec = search_vector(q_ctx)
    
    combined = []
    ids = set()
    for d in exact:
        if d['id'] not in ids: combined.append(d); ids.add(d['id'])
    for d in vec:
        if d['id'] not in ids: d['source_type'] = "VECTOR"; combined.append(d); ids.add(d['id'])

    evidencia = ""
    for d in combined:
        meta = d.get('metadata', {})
        evidencia += f"--- DOC ({d.get('source_type')}) ---\nMeta: {json.dumps(meta, ensure_ascii=False)}\nTexto: {d.get('content')}\n"

    prompt = f"""
    Eres un ANALISTA DE LICITACIONES.
    HISTORIAL: {format_history(history)}
    EVIDENCIA: {evidencia}
    PREGUNTA: "{q}"
    Responde usando la evidencia.
    """
    return call_gemini_safe(MODEL_RAG, prompt, notify_callback=cb)

# --- 8. MAIN (PERSONALIDAD + HORA LOCAL) ---
def chatear(q, history, datos_usuario="Anónimo", callback=None):
    try:
        print(f"   👤 {datos_usuario}")
        ruta = decide_route(q, history, callback)
        print(f"   [Ruta]: {ruta}")
        
        if "SQL" in ruta: 
            resp = response_sql(q, history, callback)
        elif "WEB" in ruta:
            resp = response_web(q, history, callback)
        elif "RAG" in ruta: 
            resp = response_hybrid_rag(q, history, callback)
        else: 
            # --- RUTA GENERAL CON HORA ---
            hora_peru = obtener_hora_lima()
            prompt_general = f"""
            Eres una IA útil y amigable llamada 'Analista IA'.
            Usuario: {datos_usuario}.
            CONTEXTO: La hora actual en Perú es {hora_peru}.
            Pregunta: "{q}"
            
            INSTRUCCIONES:
            1. Si piden chistes, consejos o charla, sé AMIGABLE y DIVERTIDO.
            2. Si piden la hora, DASELA directamente del contexto (no busques).
            3. NO hables de licitaciones si no te preguntan.
            """
            resp = call_gemini_safe(MODEL_RAG, prompt_general, notify_callback=callback)
            
        return resp
    except Exception as e: return f"Error crítico: {e}"

if __name__ == "__main__":
    print("--- CHAT RAG DEFINITIVO (WEB + DB + GENERAL) ---")
    hist = []
    while True:
        q = input("Pregunta: ")
        if q == "salir": break
        def dummy(msg): print(msg)
        print(chatear(q, hist, "Admin", dummy))