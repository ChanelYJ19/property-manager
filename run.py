"""Entry point: runs the Telegram bot and the daily reminder scheduler."""
import asyncio
import logging

from app.scheduler import start_scheduler
from app.telegram_bot import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    tg_app = build_app()

    async with tg_app:
        loop = asyncio.get_running_loop()
        scheduler = start_scheduler(tg_app.bot, loop)

        await tg_app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram bot polling started")

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await tg_app.updater.stop()
            scheduler.shutdown()
            log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
