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

                logger.debug("initiating force update")

            except asyncio.TimeoutError:

                logger.debug("initiating scheduled update")

            await self._update()

            self._update_requested.clear()

    def request_update(self) -> bool:

        if self._ongoing_update.locked():
            logger.debug("update process is already running")
            return False

        if self._update_requested.is_set():
            logger.debug("force update has already been requested")
            return False

        self._loop.call_soon_threadsafe(
            self._update_requested.set
        )

        logger.debug("force update requested")

        return True

    @staticmethod
    def _extract_token(
        request: nodriver.cdp.network.Request,
    ) -> Optional[TokenInfo]:

        post_data = request.post_data

        try:

            post_data_json = json.loads(post_data)

            visitor_data = (
                post_data_json["context"]
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
                "failed to extract token: %s: %s",
                type(error).__name__,
                error,
            )

            return None

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
                "hard update timeout exceeded"
            )

    async def _perform_update(self) -> None:

        if self._ongoing_update.locked():
            logger.debug("update is already in progress")
            return

        async with self._ongoing_update:

            logger.info("update started (v8 embed + network enable)")

            self._extraction_done.clear()

            # FIX 1: the real nodriver parameter is "sandbox" (there is
            # no "no_sandbox"), and the Chromium path must not be None.
            executable = (
                str(self.browser_path)
                if self.browser_path
                else "/usr/bin/chromium"
            )

            logger.info(
                "DIAGNOSTIC: launching Chromium, executable=%s",
                executable,
            )

            logger.info(
                "DIAGNOSTIC: profile=%s",
                self.profile_path,
            )

            try:

                browser = await nodriver.start(
                    headless=False,
                    sandbox=False,
                    browser_executable_path=executable,
                    browser_args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                    user_data_dir=self.profile_path,
                )

            except FileNotFoundError as error:

                logger.exception(
                    "Chromium executable was not found"
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

            # FIX 2: always stop Chromium, even if something fails,
            # so no stuck browser processes remain.
            try:

                tab = browser.main_tab

                tab.add_handler(
                    nodriver.cdp.network.RequestWillBeSent,
                    self._send_handler,
                )

                # FIX 4: make sure the Network domain is enabled so the
                # handler really receives request events.
                await tab.send(nodriver.cdp.network.enable())

                logger.info(
                    "DIAGNOSTIC: opening YouTube"
                )

                await tab.get(
                    "https://www.youtube.com/embed/jNQXAC9IVRw"
                )

                logger.info(
                    "DIAGNOSTIC: YouTube page opened"
                )

                player_clicked = await self._click_on_player(tab)

                logger.info(
                    "DIAGNOSTIC: player_clicked=%s",
                    player_clicked,
                )

                if player_clicked:
                    await self._wait_for_handler()

                await tab.close()

            finally:

                try:
                    browser.stop()
                except Exception as error:
                    logger.warning(
                        "DIAGNOSTIC: browser stop failed: %s",
                        error,
                    )

    @staticmethod
    async def _click_on_player(
        tab: nodriver.Tab,
    ) -> bool:

        try:

            # FIX 3: wait up to 25s (was 10s). In a test run the
            # player appeared late on the first attempt.
            player = await tab.select(
                "#movie_player",
                25,
            )

        except asyncio.TimeoutError:

            logger.warning(
                "update failed: unable to locate YouTube player"
            )

            return False

        await player.click()

        logger.info(
            "DIAGNOSTIC: YouTube player clicked"
        )

        return True

    async def _wait_for_handler(self) -> bool:

        try:

            await asyncio.wait_for(
                self._extraction_done.wait(),
                timeout=30,
            )

        except asyncio.TimeoutError:

            logger.warning(
                "update failed: timeout waiting "
                "for outgoing YouTube API request"
            )

            return False

        logger.info(
            "update was successful"
        )

        return True

    async def _send_handler(
        self,
        event: nodriver.cdp.network.RequestWillBeSent,
    ) -> None:

        request = event.request

        # DEBUG: show every POST request (shortened) to see what the page sends
        if request.method == "POST":
            logger.info("DEBUG POST: %s", request.url[:110])

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
            "DIAGNOSTIC: YouTube player API request detected"
        )

        token_info = self._extract_token(request)

        if token_info is None:

            logger.warning(
                "DIAGNOSTIC: player request did not contain "
                "a usable poToken/visitorData pair"
            )

            return

        logger.info(
            "new token: %s",
            token_info.to_json(),
        )

        self._token_info = token_info

        self._extraction_done.set()
