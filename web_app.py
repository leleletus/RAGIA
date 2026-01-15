import streamlit as st
import time
from consultas import chatear # Importamos tu cerebro maestro

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Analista Licitaciones",
    page_icon="🤖",
    layout="centered"
)

# --- TÍTULO Y ESTILO ---
st.title("🤖 Analista de Licitaciones IA")
st.caption("Experto en Base de Datos SQL, Documentos RAG y Búsqueda Web.")

# --- GESTIÓN DE MEMORIA (SESSION STATE) ---
# Streamlit se reinicia con cada clic, así que guardamos el historial aquí
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- MOSTRAR HISTORIAL PREVIO ---
# Cada vez que la app se actualiza, redibujamos lo que ya se habló
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- FUNCIÓN DE CALLBACK (Para avisos de espera) ---
def notificar_web(mensaje):
    # st.toast muestra una notificación flotante bonita en la esquina
    st.toast(mensaje, icon="🚦")

# --- CAPTURA DE ENTRADA DEL USUARIO ---
if prompt := st.chat_input("Escribe tu consulta aquí..."):
    
    # 1. Mostrar mensaje del usuario
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Guardar en historial
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 2. Generar respuesta de la IA
    with st.chat_message("assistant"):
        contenedor_respuesta = st.empty() # Lugar donde aparecerá el texto
        
        # Efecto de "Pensando..."
        with st.spinner("Analizando base de datos y fuentes..."):
            try:
                # Preparamos el historial en el formato que le gusta a tu cerebro
                # (consultas.py espera una lista de diccionarios, que ya tenemos en session_state)
                historial_para_cerebro = st.session_state.messages[:-1] # Excluimos el último actual
                
                # LLAMAMOS A TU CEREBRO
                # Pasamos "Usuario Web" para que sepa quién es
                respuesta = chatear(
                    q=prompt, 
                    history=historial_para_cerebro, 
                    datos_usuario="Usuario Web", 
                    callback=notificar_web # Pasamos la función de notificaciones
                )
                
                # Mostrar respuesta final
                contenedor_respuesta.markdown(respuesta)
                
                # Guardar respuesta en historial
                st.session_state.messages.append({"role": "model", "content": respuesta})
                
            except Exception as e:
                st.error(f"Ocurrió un error: {e}")

# --- BARRA LATERAL (OPCIONAL) ---
with st.sidebar:
    st.header("⚙️ Controles")
    if st.button("🗑️ Borrar Historial"):
        st.session_state.messages = []
        st.rerun() # Recarga la página
    
    st.markdown("---")
    st.info("💡 **Tips:**\n- Pregunta por 'Pendientes' u 'Ofertas del 2024'.\n- Pregunta la hora o el clima.\n- Pide un chiste.")