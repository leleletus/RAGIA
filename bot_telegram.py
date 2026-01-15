import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# Importamos tu cerebro
from consultas import chatear

load_dotenv(".env")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TOKEN: raise ValueError("❌ Falta TELEGRAM_BOT_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
user_histories = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bienvenida bonita."""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 **¡Hola {user.first_name}!**\n\n"
        "Soy tu **Analista de Licitaciones**. 🤖📊\n"
        "Estoy conectado a tu base de datos.\n\n"
        "🔹 **Pregúntame:** 'Cuantos pendientes hay', 'Busca la oferta 10'.\n"
        "💡 *Tip:* Si la red está saturada, te avisaré mientras espero."
    , parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejo de mensajes con Notificación en Tiempo Real."""
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    
    info_usuario = f"Nombre: {user.first_name}, User: @{user.username}, ID: {user_id}"
    
    if user_id not in user_histories: user_histories[user_id] = []
    history = user_histories[user_id]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # --- CALLBACK: El puente entre Cerebro y Telegram ---
    def notificar_usuario(mensaje):
        async def enviar():
            try:
                # Manda el mensaje de "🚧 IA saturada..."
                await update.message.reply_text(f"🚧 {mensaje}")
                # Renueva el estado "escribiendo..."
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            except: pass
        
        # Inyectamos esto en el hilo principal de Telegram
        asyncio.run_coroutine_threadsafe(enviar(), loop)

    try:
        loop = asyncio.get_running_loop()
        print(f"📩 Mensaje de {user.first_name}: {text}")
        
        # Pasamos 'notificar_usuario' al cerebro
        response = await asyncio.to_thread(chatear, text, history, info_usuario, notificar_usuario)

        history.append({"role": "user", "content": text})
        history.append({"role": "model", "content": response})
        if len(history) > 10: user_histories[user_id] = history[-10:]

        try:
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        except:
            await update.message.reply_text(response)

    except Exception as e:
        print(f"⚠️ Error: {e}")
        await update.message.reply_text("Error interno.")

async def reset_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("🧠 Memoria borrada.")

if __name__ == '__main__':
    print("🤖 BOT ONLINE...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('borrar', reset_memory))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.run_polling()