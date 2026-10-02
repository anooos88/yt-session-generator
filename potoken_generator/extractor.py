import asyncio
import dataclasses
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from typing import Optional

import nodriver

logger = logging.getLogger("extractor")


@dataclass
class TokenInfo:
    updated: int
    potoken: str
    visitor_data: str

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self))


class PotokenExtractor:

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        update_interval: float = 3600,
        browser_path: Optional[Path] = None,
    ) -> None:

        self.update_interval = update_interval
        self.browser_path = browser_path

        self.profile_path = mkdtemp()

        self._loop = loop
        self._token_info: Optional[TokenInfo] = None

        self._ongoing_update = asyncio.Lock()
        self._extraction_done = asyncio.Event()
        self._update_requested = asyncio.Event()

    def get(self) -> Optional[TokenInfo]:
        return self._token_info

    async def run_once(self) -> Optional[TokenInfo]:
        await self._update()
        return self.get()

    async def run(self) -> None:

        await self._update()

        while True:

            try:
                await asyncio.wait_for(
                    self._update_requested.wait(),
                    timeout=self.update_interval,
                )

                logger.info("initiating force update")

            except asyncio.TimeoutError:

                logger.info("initiating scheduled update")

            await self._update()

            self._update_requested.clear()

    def request_update(self) -> bool:

        if self._ongoing_update.locked():
            logger.info("update process is already running")
            return False

        if self._update_requested.is_set():
            logger.info("force update has already been requested")
            return False

        self._loop.call_soon_threadsafe(
            self._update_requested.set
        )

        logger.info("force update requested")

        return True

    @staticmethod
    def _extract_token(
        request: nodriver.cdp.network.Request,
    ) -> Optional[TokenInfo]:

        post_data = request.post_data

        logger.info(
            "DIAGNOSTIC: player request received, post_data=%s",
            bool(post_data),
        )

        if not post_data:
            logger.warning(
                "DIAGNOSTIC: player request has no POST data"
            )
            return None

        try:

            post_data_json = json.loads(post_data)

            visitor_data = (
                post_data_json
                ["context"]
                ["client"]
                ["visitorData"]
            )

            potoken = (
                post_data_json
                ["serviceIntegrityDimensions"]
                ["poToken"]
            )

        except (
            json.JSONDecodeError,
            TypeError,
            KeyError,
        ) as error:

            logger.warning(
                "DIAGNOSTIC: failed to extract token: %s: %s",
                type(error).__name__,
                error,
            )

            return None

        if not visitor_data:
            logger.warning(
                "DIAGNOSTIC: visitorData is empty"
            )
            return None

        if not potoken:
            logger.warning(
                "DIAGNOSTIC: poToken is empty"
            )
            return None

        logger.info(
            "DIAGNOSTIC: visitorData length=%d",
            len(visitor_data),
        )

        logger.info(
            "DIAGNOSTIC: poToken length=%d",
            len(potoken),
        )

        return TokenInfo(
            updated=int(time.time()),
            potoken=potoken,
            visitor_data=visitor_data,
        )

    async def _update(self) -> None:

        try:

            await asyncio.wait_for(
                self._perform_update(),
                timeout=600,
            )

        except asyncio.TimeoutError:

            logger.error(
                "DIAGNOSTIC: hard update timeout exceeded"
            )

        except Exception:

            logger.exception(
                "DIAGNOSTIC: update crashed"
            )

    async def _perform_update(self) -> None:

        if self._ongoing_update.locked():

            logger.info(
                "DIAGNOSTIC: update is already in progress"
            )

            return

        async with self._ongoing_update:

            logger.info(
                "DIAGNOSTIC: ================================"
            )

            logger.info(
                "DIAGNOSTIC: update started"
            )

            logger.info(
                "DIAGNOSTIC: browser_path=%s",
                self.browser_path,
            )

            logger.info(
                "DIAGNOSTIC: profile=%s",
                self.profile_path,
            )

            self._extraction_done.clear()

            logger.info(
                "DIAGNOSTIC: launching Chromium"
            )

            try:

                browser = await nodriver.start(
                    headless=False,
                    no_sandbox=True,
                    browser_executable_path=self.browser_path,
                    user_data_dir=self.profile_path,
                )

            except FileNotFoundError as error:

                logger.exception(
                    "DIAGNOSTIC: Chromium executable was not found"
                )

                raise FileNotFoundError(
                    "Could not find Chromium. "
                    "Make sure Chromium is installed."
                ) from error

            except Exception:

                logger.exception(
                    "DIAGNOSTIC: Chromium failed to start"
                )

                raise

            logger.info(
                "DIAGNOSTIC: Chromium started successfully"
            )

            try:

                tab = browser.main_tab

                logger.info(
                    "DIAGNOSTIC: main tab acquired"
                )

                tab.add_handler(
                    nodriver.cdp.network.RequestWillBeSent,
                    self._send_handler,
                )

                logger.info(
                    "DIAGNOSTIC: network request handler installed"
                )

                youtube_url = (
                    "https://www.youtube.com/watch?v=jNQXAC9IVRw"
                )

                logger.info(
                    "DIAGNOSTIC: opening YouTube URL: %s",
                    youtube_url,
                )

                await tab.get(youtube_url)

                logger.info(
                    "DIAGNOSTIC: YouTube page opened"
                )

                await asyncio.sleep(5)

                try:

                    current_url = await tab.evaluate(
                        "window.location.href"
                    )

                    logger.info(
                        "DIAGNOSTIC: current URL=%s",
                        current_url,
                    )

                except Exception:

                    logger.exception(
                        "DIAGNOSTIC: failed to read current URL"
                    )

                try:

                    page_title = await tab.evaluate(
                        "document.title"
                    )

                    logger.info(
                        "DIAGNOSTIC: page title=%s",
                        page_title,
                    )

                except Exception:

                    logger.exception(
                        "DIAGNOSTIC: failed to read page title"
                    )

                try:

                    body_text = await tab.evaluate(
                        "document.body ? document.body.innerText : ''"
                    )

                    if body_text:

                        clean_text = " ".join(
                            body_text.split()
                        )

                        logger.info(
                            "DIAGNOSTIC: page text preview=%s",
                            clean_text[:1000],
                        )

                    else:

                        logger.warning(
                            "DIAGNOSTIC: page body is empty"
                        )

                except Exception:

                    logger.exception(
                        "DIAGNOSTIC: failed to read page text"
                    )

                player_clicked = await self._click_on_player(tab)

                logger.info(
                    "DIAGNOSTIC: player_clicked=%s",
                    player_clicked,
                )

                if player_clicked:

                    logger.info(
                        "DIAGNOSTIC: waiting for player API request"
                    )

                    success = await self._wait_for_handler()

                    logger.info(
                        "DIAGNOSTIC: token extraction wait result=%s",
                        success,
                    )

                else:

                    logger.warning(
                        "DIAGNOSTIC: player was not clicked"
                    )

            finally:

                logger.info(
                    "DIAGNOSTIC: closing browser"
                )

                try:
                    await tab.close()
                except Exception:
                    logger.exception(
                        "DIAGNOSTIC: failed to close tab"
                    )

                try:
                    browser.stop()
                except Exception:
                    logger.exception(
                        "DIAGNOSTIC: failed to stop browser"
                    )

                logger.info(
                    "DIAGNOSTIC: browser stopped"
                )

            logger.info(
                "DIAGNOSTIC: update finished"
            )

            logger.info(
                "DIAGNOSTIC: ================================"
            )

    @staticmethod
    async def _click_on_player(
        tab: nodriver.Tab,
    ) -> bool:

        logger.info(
            "DIAGNOSTIC: looking for YouTube player"
        )

        try:

            player = await tab.select(
                "#movie_player",
                15,
            )

        except asyncio.TimeoutError:

            logger.warning(
                "DIAGNOSTIC: unable to locate #movie_player"
            )

            return False

        except Exception:

            logger.exception(
                "DIAGNOSTIC: error locating #movie_player"
            )

            return False

        if player is None:

            logger.warning(
                "DIAGNOSTIC: #movie_player returned None"
            )

            return False

        logger.info(
            "DIAGNOSTIC: #movie_player found"
        )

        try:

            await player.click()

            logger.info(
                "DIAGNOSTIC: YouTube player clicked successfully"
            )

            return True

        except Exception:

            logger.exception(
                "DIAGNOSTIC: failed to click YouTube player"
            )

            return False

    async def _wait_for_handler(self) -> bool:

        logger.info(
            "DIAGNOSTIC: waiting up to 60 seconds "
            "for /youtubei/v1/player"
        )

        try:

            await asyncio.wait_for(
                self._extraction_done.wait(),
                timeout=60,
            )

        except asyncio.TimeoutError:

            logger.warning(
                "DIAGNOSTIC: timeout waiting for "
                "outgoing YouTube player API request"
            )

            if self._token_info is None:

                logger.warning(
                    "DIAGNOSTIC: no token has been extracted"
                )

            return False

        logger.info(
            "DIAGNOSTIC: token extraction event received"
        )

        return True

    async def _send_handler(
        self,
        event: nodriver.cdp.network.RequestWillBeSent,
    ) -> None:

        request = event.request

        if "youtubei" in request.url:

            logger.info(
                "YOUTUBE REQUEST: %s %s",
                request.method,
                request.url,
            )

        if request.method != "POST":
            return

        if "/youtubei/v1/player" not in request.url:
            return

        logger.info(
            "DIAGNOSTIC: ================================"
        )

        logger.info(
            "DIAGNOSTIC: YouTube player API request detected"
        )

        logger.info(
            "DIAGNOSTIC: URL=%s",
            request.url,
        )

        token_info = self._extract_token(request)

        if token_info is None:

            logger.warning(
                "DIAGNOSTIC: player request did not contain "
                "a usable poToken/visitorData pair"
            )

            return

        logger.info(
            "DIAGNOSTIC: NEW TOKEN EXTRACTED"
        )

        logger.info(
            "DIAGNOSTIC: token=%s",
            token_info.to_json(),
        )

        self._token_info = token_info

        self._extraction_done.set()

        logger.info(
            "DIAGNOSTIC: extraction event set"
        )

        logger.info(
            "DIAGNOSTIC: ================================"
            )
