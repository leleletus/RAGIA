import os
import pandas as pd
import numpy as np
import google.genai as genai
from google.genai import types
from supabase import create_client, Client
from dotenv import load_dotenv
import time
import re
import unicodedata

# --- CARGAR CLAVES ---
load_dotenv(".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY: raise ValueError("Falta GEMINI_API_KEY en .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# --- CONFIGURACIÓN ---
TABLE_NAME = "documentos_dj"
EMBEDDING_MODEL = "models/text-embedding-004"
DIMENSION = 768

# --- HERRAMIENTAS ---
def normalize_vector(vector):
    arr = np.array(vector)
    norm = np.linalg.norm(arr)
    if norm == 0: return vector
    return (arr / norm).tolist()

def get_embedding(text: str):
    try:
        time.sleep(0.1) 
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT", 
                output_dimensionality=DIMENSION
            )
        )
        return normalize_vector(result.embeddings[0].values)
    except Exception as e:
        print(f"❌ Error vectorizando: {e}")
        return None

def limpiar_texto_nuclear(val):
    """Limpia valores y títulos: quita dobles espacios y normaliza."""
    if val is None: return ""
    texto = str(val)
    if texto.lower() in ["nan", "nat", "none", "null", ""]: return ""
    texto = unicodedata.normalize("NFKC", texto)
    # Reemplaza cualquier secuencia de espacios por uno solo
    return re.sub(r'\s+', ' ', texto).strip()

# --- PROCESAMIENTO ---
def procesar_excel_universal(archivo_path):
    print(f"🚀 Iniciando carga a '{TABLE_NAME}' con LIMPIEZA TOTAL...")
    
    try:
        try:
            df = pd.read_excel(archivo_path)
        except:
            df = pd.read_csv(archivo_path, encoding="utf-8")
    except Exception as e:
        print(f"❌ Error leyendo archivo: {e}")
        return

    df = df.fillna("")
    
    # --- PASO 1: LIMPIEZA DE NOMBRES DE COLUMNAS ---
    # Esto arregla "ESTADO DE  CARGA" -> "estado de carga"
    columnas_sucias = df.columns.tolist()
    columnas_limpias = []
    
    for col in columnas_sucias:
        col_limpia = limpiar_texto_nuclear(col).lower()
        columnas_limpias.append(col_limpia)
        
    print(f"📊 Columnas originales: {columnas_sucias}")
    print(f"✨ Columnas limpias:   {columnas_limpias}")
    
    # Asignamos los nombres limpios al DataFrame para trabajar fácil
    df.columns = columnas_limpias
    total = len(df)
    
    batch = []
    
    for index, row in df.iterrows():
        meta = {}
        contenido_partes = []

        for col in columnas_limpias:
            key = col # Ya está limpio (ej: "estado de carga")
            val = limpiar_texto_nuclear(row[col]) # Limpiamos el valor también
            
            # Mapeo de ID
            if key == "id": key = "id_excel"
            
            meta[key] = val
            if val: contenido_partes.append(f"{key}: {val}")

        contenido_final = ". ".join(contenido_partes)

        if len(contenido_final) < 5: continue

        vector = get_embedding(contenido_final)
        
        if vector:
            batch.append({
                "content": contenido_final,
                "metadata": meta,
                "embedding": vector
            })
            
            if (index + 1) % 50 == 0: 
                print(f"   Procesando fila {index+1}/{total}...")

        if len(batch) >= 50:
            try:
                supabase.table(TABLE_NAME).insert(batch).execute()
                print(f"   💾 Lote guardado (Fila {index+1})")
                batch = []
            except Exception as e:
                print(f"   ❌ Error en lote: {e}")
                batch = []

    if batch:
        supabase.table(TABLE_NAME).insert(batch).execute()
        print("   💾 Último lote guardado.")
        
    print("🎉 ¡Ingesta Finalizada! Ahora sí está todo limpio.")

if __name__ == "__main__":
    archivo = "file_4.xlsx"
    
    print("--- INGESTA CON LIMPIEZA DE COLUMNAS ---")
    
    # TRUNCATE OBLIGATORIO PARA QUITAR LA BASURA VIEJA
    confirm = input("¿Vaciar tabla antes de subir (Recomendado)? (s/n): ")
    
    if confirm.lower() == "s":
        print("🗑️  Vaciando tabla...")
        try:
            supabase.table(TABLE_NAME).delete().neq("id", 0).execute()
            print("✅ Datos eliminados.")
            if os.path.exists(archivo):
                procesar_excel_universal(archivo)
        except Exception as e:
            print(f"❌ Error borrando: {e}")
            print("💡 Tip: Si falla, ejecuta 'TRUNCATE TABLE documentos_dj;' en Supabase SQL Editor.")
    else:
        if os.path.exists(archivo):
            procesar_excel_universal(archivo)