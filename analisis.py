import pandas as pd
import os

# CONFIGURA AQUÍ TU ARCHIVO
ARCHIVO_EXCEL = "file_4.xlsx"
TABLA_DESTINO = "documentos_dj"

def analizar_excel():
    if not os.path.exists(ARCHIVO_EXCEL):
        print(f"❌ No encuentro {ARCHIVO_EXCEL}")
        return

    print(f"🔍 Analizando {ARCHIVO_EXCEL}...")
    try:
        df = pd.read_excel(ARCHIVO_EXCEL)
    except:
        df = pd.read_csv(ARCHIVO_EXCEL)

    # Limpieza de nombres de columnas
    cols_originales = df.columns.tolist()
    # Convertimos a minúsculas, quitamos espacios extra
    cols_limpias = [c.strip().lower() for c in cols_originales]

    print("\n📋 COLUMNAS DETECTADAS:")
    for orig, limpia in zip(cols_originales, cols_limpias):
        print(f"   - '{orig}'  ->  se guardará como: '{limpia}'")

    # Generar SQL
    sql = f"""
    -- CÓDIGO SQL GENERADO AUTOMÁTICAMENTE
    -- Cópialo y pégalo en Supabase SQL Editor si deseas resetear la tabla
    
    create extension if not exists vector;
    drop table if exists {TABLA_DESTINO};
    
    create table {TABLA_DESTINO} (
        id bigserial primary key,      -- ID Autoincremental de Supabase
        content text,                  -- Texto para la IA
        metadata jsonb,                -- AQUÍ van todas tus columnas del Excel
        embedding vector(768)          -- Vector para búsquedas
    );
    
    create index on {TABLA_DESTINO} using hnsw (embedding vector_cosine_ops);
    grant all on table {TABLA_DESTINO} to anon, authenticated, service_role;
    """

    # Guardar en TXT
    with open("tabla_sql_actualizado.txt", "w", encoding="utf-8") as f:
        f.write(sql)
    
    with open("columnas_detectadas.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(cols_limpias))

    print("\n✅ Archivos generados:")
    print("   1. 'tabla_sql_actualizado.txt' -> El código para crear tu tabla.")
    print("   2. 'columnas_detectadas.txt' -> Lista de columnas para tu referencia.")

if __name__ == "__main__":
    analizar_excel()