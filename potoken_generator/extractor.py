import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import nodriver


logger = logging.getLogger("extractor")


class TokenInfo:
    def __init__(self, visitor_data: str, potoken: str):
        self.visitor_data = visitor_data
        self.potoken = potoken


class PotokenExtractor:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        update_interval: int = 300,
        browser_path: Optional[Path] = None,
    ):
        self.loop = loop
        self.update_interval = update_interval
        self.browser_path = browser_path

        self.profile_path = Path("/tmp/yt-session-profile")

        self.token_info: Optional[TokenInfo] = None

    async def update(self) -> Optional[TokenInfo]:
        logger.info("DIAGNOSTIC: ================================")
        logger.info("DIAGNOSTIC: update started")
        logger.info("DIAGNOSTIC: browser_path=%s", self.browser_path)
        logger.info("DIAGNOSTIC: profile=%s", self.profile_path)

        self.profile_path.mkdir(parents=True, exist_ok=True)

        browser = None

        try:
            logger.info("DIAGNOSTIC: launching Chromium")

            # Force Chromium executable explicitly.
            # The official Alpine image installs Chromium at /usr/bin/chromium.
            browser = await nodriver.start(
                headless=False,
                no_sandbox=True,
                browser_executable_path=Path("/usr/bin/chromium"),
                user_data_dir=self.profile_path,
            )

            logger.info("DIAGNOSTIC: Chromium started successfully")

            page = await browser.get("https://www.youtube.com/")

            logger.info("DIAGNOSTIC: YouTube page opened")

            await asyncio.sleep(5)

            try:
                logger.info(
                    "DIAGNOSTIC: current URL=%s",
                    page.url,
                )
            except Exception as e:
                logger.warning(
                    "DIAGNOSTIC: unable to read current URL: %s",
                    e,
                )

            try:
                title = await page.evaluate("document.title")
                logger.info(
                    "DIAGNOSTIC: page title=%s",
                    title,
                )
            except Exception as e:
                logger.warning(
                    "DIAGNOSTIC: unable to read page title: %s",
                    e,
                )

            try:
                body_preview = await page.evaluate(
                    """
                    (() => {
                        const body = document.body;
                        if (!body) return "";
                        return body.innerText.substring(0, 1000);
                    })()
                    """
                )

                logger.info(
                    "DIAGNOSTIC: body preview=%s",
                    body_preview,
                )

            except Exception as e:
                logger.warning(
                    "DIAGNOSTIC: unable to read body: %s",
                    e,
                )

            # Open a known YouTube video.
            video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

            logger.info(
                "DIAGNOSTIC: opening test video=%s",
                video_url,
            )

            page = await browser.get(video_url)

            await asyncio.sleep(5)

            logger.info(
                "DIAGNOSTIC: test video page loaded, url=%s",
                page.url,
            )

            try:
                title = await page.evaluate("document.title")
                logger.info(
                    "DIAGNOSTIC: video title=%s",
                    title,
                )
            except Exception as e:
                logger.warning(
                    "DIAGNOSTIC: unable to read video title: %s",
                    e,
                )

            # Search for YouTube player.
            try:
                player = await page.select("#movie_player")

                if player:
                    logger.info(
                        "DIAGNOSTIC: #movie_player found"
                    )

                    try:
                        await player.click()
                        logger.info(
                            "DIAGNOSTIC: clicked #movie_player"
                        )
                    except Exception as e:
                        logger.warning(
                            "DIAGNOSTIC: player click failed: %s",
                            e,
                        )

                else:
                    logger.warning(
                        "DIAGNOSTIC: #movie_player not found"
                    )

            except Exception as e:
                logger.warning(
                    "DIAGNOSTIC: player lookup failed: %s",
                    e,
                )

            logger.info(
                "DIAGNOSTIC: waiting for YouTube player requests"
            )

            # Give YouTube enough time to issue player requests.
            await asyncio.sleep(10)

            # Try to extract visitorData and poToken from page globals.
            visitor_data = None
            po_token = None

            try:
                result = await page.evaluate(
                    """
                    (() => {
                        const result = {
                            visitorData: null,
                            poToken: null
                        };

                        try {
                            if (window.ytInitialPlayerResponse) {
                                const pr = window.ytInitialPlayerResponse;

                                if (
                                    pr.responseContext &&
                                    pr.responseContext.mainAppWebResponseContext
                                ) {
                                    result.visitorData =
                                        pr.responseContext
                                          .mainAppWebResponseContext
                                          .loggedOutData
                                          ?.visitorData || null;
                                }
                            }
                        } catch (e) {}

                        try {
                            const html = document.documentElement.innerHTML;

                            const visitorMatch =
                                html.match(/visitorData["']?\\s*[:=]\\s*["']([^"']+)/);

                            if (visitorMatch) {
                                result.visitorData = visitorMatch[1];
                            }
                        } catch (e) {}

                        return result;
                    })()
                    """
                )

                if result:
                    visitor_data = result.get("visitorData")
                    po_token = result.get("poToken")

                logger.info(
                    "DIAGNOSTIC: page extraction result=%s",
                    json.dumps(result, ensure_ascii=False),
                )

            except Exception as e:
                logger.warning(
                    "DIAGNOSTIC: page token extraction failed: %s",
                    e,
                )

            if visitor_data:
                logger.info(
                    "DIAGNOSTIC: visitor_data found, length=%d",
                    len(visitor_data),
                )
            else:
                logger.warning(
                    "DIAGNOSTIC: visitor_data NOT found"
                )

            if po_token:
                logger.info(
                    "DIAGNOSTIC: poToken found, length=%d",
                    len(po_token),
                )
            else:
                logger.warning(
                    "DIAGNOSTIC: poToken NOT found"
                )

            # At this stage the main purpose is diagnosing Chromium startup
            # and YouTube token extraction.
            if visitor_data and po_token:
                self.token_info = TokenInfo(
                    visitor_data=visitor_data,
                    potoken=po_token,
                )

                logger.info(
                    "DIAGNOSTIC: token extraction successful"
                )

                return self.token_info

            logger.warning(
                "DIAGNOSTIC: token extraction incomplete"
            )

            return None

        except Exception:
            logger.exception(
                "DIAGNOSTIC: Chromium failed to start or extraction failed"
            )

            return None

        finally:
            if browser is not None:
                try:
                    logger.info(
                        "DIAGNOSTIC: closing Chromium"
                    )

                    browser.stop()

                except Exception as e:
                    logger.warning(
                        "DIAGNOSTIC: browser shutdown failed: %s",
                        e,
                    )

    async def run_once(self) -> Optional[TokenInfo]:
        return await self.update()

    async def run(self):
        while True:
            try:
                await self.update()

            except Exception:
                logger.exception(
                    "DIAGNOSTIC: update loop failed"
                )

            logger.info(
                "DIAGNOSTIC: sleeping for %s seconds",
                self.update_interval,
            )

            await asyncio.sleep(self.update_interval)
