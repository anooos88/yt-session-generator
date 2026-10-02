import asyncio
import inspect
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import nodriver


logger = logging.getLogger("extractor")


class TokenInfo:
    def __init__(self, visitor_data: str, potoken: str):
        self.visitor_data = visitor_data
        self.potoken = potoken


async def _chromium_probe():
    """
    Launch Chromium directly (without nodriver) and log what it says.
    Purpose: find the REAL reason Chromium fails inside the container.
    """
    exe = shutil.which("chromium") or "/usr/bin/chromium"

    logger.info("PROBE exe=%s DISPLAY=%s", exe, os.environ.get("DISPLAY"))
    logger.info("PROBE whoami uid=%s", os.getuid())

    try:
        logger.info(
            "PROBE nodriver.start signature=%s",
            inspect.signature(nodriver.start),
        )
    except Exception as e:
        logger.info("PROBE could not read nodriver.start signature: %s", e)

    try:
        p = await asyncio.create_subprocess_exec(
            exe,
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9333",
            "--user-data-dir=/tmp/probe-profile",
            "about:blank",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        logger.info("PROBE could not start process: %r", e)
        return

    await asyncio.sleep(6)

    logger.info("PROBE returncode after 6s=%s", p.returncode)

    if p.returncode is None:
        p.kill()

    out, err = await p.communicate()

    logger.info(
        "PROBE stdout=%s",
        out.decode(errors="replace")[-1500:],
    )
    logger.info(
        "PROBE stderr=%s",
        err.decode(errors="replace")[-3000:],
    )


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
        logger.info("DIAGNOSTIC: update started (v6 probe build)")
        logger.info("DIAGNOSTIC: browser_path=%s", self.browser_path)
        logger.info("DIAGNOSTIC: profile=%s", self.profile_path)

        self.profile_path.mkdir(parents=True, exist_ok=True)

        browser = None

        try:
            # Step 1: run Chromium directly and log its own output.
            await _chromium_probe()

            logger.info("DIAGNOSTIC: launching Chromium")

            # Step 2: launch through nodriver with safer settings.
            # NOTE: "sandbox=False" is believed to be nodriver's real
            # parameter name. The PROBE signature line above shows
            # the real parameter names in the installed version.
            browser = await nodriver.start(
                headless=False,
                sandbox=False,
                browser_executable_path="/usr/bin/chromium",
                browser_args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
                user_data_dir=str(self.profile_path),
            )

            logger.info("DIAGNOSTIC: Chromium started successfully")

            page = await browser.get("https://www.youtube.com/")

            logger.info("DIAGNOSTIC: YouTube page opened")

            await asyncio.sleep(5)

            try:
                logger.info("DIAGNOSTIC: current URL=%s", page.url)
            except Exception as e:
                logger.warning("DIAGNOSTIC: unable to read current URL: %s", e)

            try:
                title = await page.evaluate("document.title")
                logger.info("DIAGNOSTIC: page title=%s", title)
            except Exception as e:
                logger.warning("DIAGNOSTIC: unable to read page title: %s", e)

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
                logger.info("DIAGNOSTIC: body preview=%s", body_preview)
            except Exception as e:
                logger.warning("DIAGNOSTIC: unable to read body: %s", e)

            # Open a known YouTube video.
            video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

            logger.info("DIAGNOSTIC: opening test video=%s", video_url)

            page = await browser.get(video_url)

            await asyncio.sleep(5)

            logger.info("DIAGNOSTIC: test video page loaded, url=%s", page.url)

            try:
                title = await page.evaluate("document.title")
                logger.info("DIAGNOSTIC: video title=%s", title)
            except Exception as e:
                logger.warning("DIAGNOSTIC: unable to read video title: %s", e)

            # Search for YouTube player.
            try:
                player = await page.select("#movie_player")

                if player:
                    logger.info("DIAGNOSTIC: #movie_player found")

                    try:
                        await player.click()
                        logger.info("DIAGNOSTIC: clicked #movie_player")
                    except Exception as e:
                        logger.warning("DIAGNOSTIC: player click failed: %s", e)
                else:
                    logger.warning("DIAGNOSTIC: #movie_player not found")

            except Exception as e:
                logger.warning("DIAGNOSTIC: player lookup failed: %s", e)

            logger.info("DIAGNOSTIC: waiting for YouTube player requests")

            # Give YouTube enough time to issue player requests.
            await asyncio.sleep(10)

            # Try to extract visitorData from page globals.
            # NOTE: poToken is NOT extracted here, so this build
            # is for diagnosing Chromium startup only.
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
                logger.warning("DIAGNOSTIC: page token extraction failed: %s", e)

            if visitor_data:
                logger.info(
                    "DIAGNOSTIC: visitor_data found, length=%d",
                    len(visitor_data),
                )
            else:
                logger.warning("DIAGNOSTIC: visitor_data NOT found")

            if po_token:
                logger.info(
                    "DIAGNOSTIC: poToken found, length=%d",
                    len(po_token),
                )
            else:
                logger.warning("DIAGNOSTIC: poToken NOT found")

            if visitor_data and po_token:
                self.token_info = TokenInfo(
                    visitor_data=visitor_data,
                    potoken=po_token,
                )

                logger.info("DIAGNOSTIC: token extraction successful")

                return self.token_info

            logger.warning("DIAGNOSTIC: token extraction incomplete")

            return None

        except Exception:
            logger.exception(
                "DIAGNOSTIC: Chromium failed to start or extraction failed"
            )

            return None

        finally:
            if browser is not None:
                try:
                    logger.info("DIAGNOSTIC: closing Chromium")

                    browser.stop()

                except Exception as e:
                    logger.warning("DIAGNOSTIC: browser shutdown failed: %s", e)

    async def run_once(self) -> Optional[TokenInfo]:
        return await self.update()

    async def run(self):
        while True:
            try:
                await self.update()

            except Exception:
                logger.exception("DIAGNOSTIC: update loop failed")

            logger.info(
                "DIAGNOSTIC: sleeping for %s seconds",
                self.update_interval,
            )

            await asyncio.sleep(self.update_interval)
