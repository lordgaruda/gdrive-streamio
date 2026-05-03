from asyncio import get_event_loop, sleep as asleep
import asyncio
import logging
from traceback import format_exc
from pyrogram import idle
from Backend import __version__, db
from Backend.logger import LOGGER
from Backend.config import Telegram, GDrive
from Backend.fastapi import server
from Backend.helper.pyro import restart_notification, setup_bot_commands
from Backend.pyrofork.bot import StreamBot
from Backend.helper.subscription_checker import subscription_checker_loop
from Backend.fastapi.main import app


loop = get_event_loop()

async def start_services():
    try:
        LOGGER.info(f"Initializing GDrive-Stremio v-{__version__}")
        await asleep(1.2)
        
        await db.connect()
        await asleep(1.2)
        
        await StreamBot.start()
        StreamBot.username = StreamBot.me.username
        LOGGER.info(f"Bot Client : [@{StreamBot.username}]")
        await asleep(1.2)

        await setup_bot_commands(StreamBot)
        await asleep(1)

        # Start GDrive scheduled scanning
        token = await db.load_gdrive_token()
        if token:
            LOGGER.info("token.pickle found in DB — starting initial Drive scan")
            from Backend.gdrive.ingest import run_full_ingest
            loop.create_task(run_full_ingest())
        else:
            LOGGER.info("No token.pickle in DB yet — send it to the Telegram bot to connect Drive")

        # Schedule periodic rescans
        async def periodic_rescan():
            while True:
                await asleep(GDrive.SCAN_INTERVAL_HOURS * 3600)
                try:
                    t = await db.load_gdrive_token()
                    if t:
                        LOGGER.info("Running scheduled GDrive rescan...")
                        from Backend.gdrive.ingest import run_full_ingest
                        await run_full_ingest()
                    else:
                        LOGGER.info("Skipping scheduled scan — Drive not configured")
                except Exception as e:
                    LOGGER.error(f"Scheduled rescan error: {e}")

        loop.create_task(periodic_rescan())

        LOGGER.info('Initializing GDrive-Stremio Web Server...')
        await restart_notification()
        loop.create_task(server.serve())
        
        if Telegram.SUBSCRIPTION:
            loop.create_task(subscription_checker_loop(StreamBot))
            LOGGER.info("Subscription Checker Task Started.")
        
        LOGGER.info("GDrive-Stremio Started Successfully!")
        await idle()
    except Exception:
        LOGGER.error("Error during startup:\n" + format_exc())

async def stop_services():
    try:
        LOGGER.info("Stopping services...")

        pending_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending_tasks:
            task.cancel()
        
        await asyncio.gather(*pending_tasks, return_exceptions=True)

        await StreamBot.stop()
        await db.disconnect()
        
        LOGGER.info("Services stopped successfully.")
    except Exception:
        LOGGER.error("Error during shutdown:\n" + format_exc())

if __name__ == '__main__':
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info('Service Stopping...')
    except Exception:
        LOGGER.error(format_exc())
    finally:
        loop.run_until_complete(stop_services())
        loop.stop()
        logging.shutdown()  
