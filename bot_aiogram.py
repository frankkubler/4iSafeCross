import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import asyncio
import requests
from utils.constants import TOKEN, CHAT_ID
import logging
import cv2
import time
import io
import psutil
import platform
import sys
from utils.utils import get_non_local_ips, get_docker_info, get_service_status


class BotThread():

    def __init__(self, overwrite_file):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.overwrite_file = overwrite_file
        self.message_save = None  # Initialiser à None
        self.last_detection_sent = 0  # timestamp de la dernière détection envoyée
        self.bot = Bot(token=TOKEN)  # Initialisation unique ici
        # self.dispatcher.include_router(self.user_router)

    def run(self):
        # Créer une nouvelle boucle d'événements pour ce thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Initialiser le bot et le dispatcher ici
        self.dp = Dispatcher()
        self.logger.info(f"Init BotThread - overwrite file is {self.overwrite_file}")
        self.message_handler()  # Activation des handlers de messages

        # Démarrer la boucle d'événements
        try:
            self.loop.run_until_complete(self.dp.start_polling(self.bot, handle_signals=False))
        # self.loop.run_forever(self.dp.start_polling())
        finally:
            self.loop.close()

    def stopping(self):
        """Gracefully stop the bot's polling loop and close the session."""
        try:
            self.logger.info('bot is stopping')
            self.dp.stop_polling()
            # Fermeture propre de la session du bot
            if hasattr(self, 'bot') and self.bot is not None:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self.bot.session.close())
                    else:
                        loop.run_until_complete(self.bot.session.close())
                except Exception as e:
                    self.logger.error(f"Erreur lors de la fermeture de la session Telegram : {e}")
        except Exception as e:
            self.logger.error(f"Error stopping bot : {e}")

    def send_message_to_bot(self, message):

        # TOKEN = ("6741846240:AAGe2Mcw4sbTmuOCHhN1xJ07Onf9TrSv_fo")
        # chat_id= "-4046288817"
        # message = "hello from your telegram bot"
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
        self.logger.debug(requests.get(url).json())  # this sends the message

    def send_detection_frame(self, frame, caption=None):
        """
        Envoie une frame OpenCV à Telegram si le délai de 120s est respecté (HTTP API, synchrone).
        """
        now = time.time()
        if now - self.last_detection_sent > 1200:
            self.last_detection_sent = now
            self.logger.info("Envoi de la frame de détection à Telegram (HTTP API)")
            ok = self.send_frame_to_telegram(frame, caption)
            if not ok:
                self.logger.error("Erreur lors de l'envoi Telegram (HTTP API)")
        else:
            self.logger.debug("Détection ignorée (moins de 120s depuis le dernier envoi)")

    def send_frame_to_telegram(self, frame, caption=None):
        """
        Envoie une image OpenCV (numpy array) à Telegram via l'API HTTP sans fichier temporaire.
        """
        # Redimensionner si l’image est trop grande
        max_dim = 1024
        if max(frame.shape[:2]) > max_dim:
            scale = max_dim / max(frame.shape[:2])
            frame = cv2.resize(frame, (int(frame.shape[1]*scale), int(frame.shape[0]*scale)))
        ret, buf = cv2.imencode('.jpg', frame)
        if not ret:
            self.logger.error("Erreur d'encodage JPEG de la frame OpenCV.")
            return False
        image_bytes = io.BytesIO(buf.tobytes())
        image_bytes.name = 'detection.jpg'
        files = {'photo': image_bytes}
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto?chat_id={CHAT_ID}"
        data = {}
        if caption:
            data['caption'] = caption
        # Ajout de logs détaillés pour le diagnostic
        self.logger.info(
            f"Préparation envoi image Telegram : taille={image_bytes.getbuffer().nbytes} octets, "
            f"shape={frame.shape}, dtype={frame.dtype}"
        )
        try:
            resp = requests.post(url, files=files, data=data, timeout=30)
            self.logger.debug(f"Réponse Telegram : status_code={resp.status_code}, text={resp.text}")
            resp.raise_for_status()
            self.logger.info("Frame envoyée à Telegram (HTTP API)")
            return True
        except Exception as e:
            self.logger.error(f"Erreur envoi frame Telegram (HTTP API) : {e}")
            if 'resp' in locals():
                self.logger.error(
                    f"Réponse Telegram : status_code={resp.status_code}, text={resp.text}"
                )
            return False

    def message_handler(self):
        """
        Ajoute des handlers de message Telegram, dont /take pour envoyer la frame actuelle de la caméra.
        """
        @self.dp.message(Command("status"))
        async def handle_status_command(message: types.Message):
            cpu_percent = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            try:
                load_str = " / ".join(f"{v:.2f}" for v in os.getloadavg())
            except Exception:
                load_str = "N/A (Windows)"

            ip_str = ', '.join(get_non_local_ips()) or "N/A"
            docker_info = get_docker_info()
            service_status = get_service_status('4isafecross.service')

            msg = (
                "\U0001F4BB *Status du PC*\n"
                f"Adresse(s) IP : `{ip_str}`\n"
                f"CPU utilisé : {cpu_percent} %\n"
                f"RAM utilisée : {mem.used // (1024*1024)} / {mem.total // (1024*1024)} MB\n"
                f"Disque utilisé : {disk.used // (1024*1024*1024)} / {disk.total // (1024*1024*1024)} GB ({disk.percent} %)\n"
                f"Load average (1/5/15min) : {load_str}\n"
                f"OS : {platform.system()} {platform.release()}"
                f"{docker_info}"
                f"\n\n*Service 4isafecross.service :* `{service_status}`"
            )
            await message.reply(msg, parse_mode="Markdown")

        @self.dp.message(Command("take"))
        async def handle_take_command(message: types.Message):
            # Import dynamique pour éviter les cycles
            try:
                if 'app' in sys.modules:
                    app_module = sys.modules['app']
                else:
                    import app as app_module
                manager = app_module.manager
                # ...existing code...
                CAM_IDS = app_module.CAM_IDS
                for cid in range(len(CAM_IDS)):
                    frame = manager.get_frame_array(CAM_IDS[cid])
                    if frame is not None:
                        ok = self.send_frame_to_telegram(frame, caption=f"Caméra {cid}")
                        if ok:
                            await message.reply(f"Photo envoyée pour caméra {cid} !")
                        else:
                            await message.reply(f"Erreur lors de l'envoi de la photo pour caméra {cid}.")
                    else:
                        await message.reply(f"Aucune image disponible pour caméra {cid}.")
            except Exception as e:
                await message.reply(f"Erreur lors de la récupération de la frame : {e}")
                self.logger.error(f"Erreur dans handle_take_command : {e}")

        # ...autres handlers ici si besoin...
