"""
텔레그램 알림 유틸리티

환경변수:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request


logger = logging.getLogger(__name__)
_last_polling_check_at = 0.0


def is_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_message(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return 200 <= response.status < 300
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            logger.warning("텔레그램 알림 전송 실패: %s | body=%s", exc, body)
            return False
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 3:
                logger.warning("텔레그램 알림 전송 실패: %s", exc)
                return False
            time.sleep(2.0 * (attempt + 1))
    return False


def get_updates(offset: int | None = None, timeout: int = 0) -> list[dict]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return []

    params = {}
    if offset is not None:
        params["offset"] = str(offset)
    if timeout:
        params["timeout"] = str(timeout)
    query = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    if query:
        url = f"{url}?{query}"

    try:
        with urllib.request.urlopen(url, timeout=max(timeout + 15, 20)) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if payload.get("ok"):
                return payload.get("result", [])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        logger.warning("텔레그램 업데이트 조회 실패: %s | body=%s", exc, body)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("텔레그램 업데이트 조회 실패: %s", exc)
    return []


def ensure_polling_mode() -> bool:
    global _last_polling_check_at
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return False

    import time
    now = time.monotonic()
    if now - _last_polling_check_at < 300:
        return True
    _last_polling_check_at = now

    webhook_info_url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    try:
        with urllib.request.urlopen(webhook_info_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            webhook_url = payload.get("result", {}).get("url", "")
            if not webhook_url:
                return True
    except TimeoutError:
        logger.info("텔레그램 webhook 조회 시간 초과 - 기존 polling 설정 유지")
        return False
    except urllib.error.URLError as exc:
        if "timed out" in str(exc).lower():
            logger.info("텔레그램 webhook 조회 시간 초과 - 기존 polling 설정 유지")
            return False
        logger.warning("텔레그램 webhook 조회 실패: %s", exc)
        return False
    except Exception as exc:
        logger.warning("텔레그램 webhook 조회 실패: %s", exc)
        return False

    delete_url = f"https://api.telegram.org/bot{token}/deleteWebhook"
    payload = json.dumps({"drop_pending_updates": False}).encode("utf-8")
    request = urllib.request.Request(
        delete_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            ok = 200 <= response.status < 300
            if ok:
                logger.info("텔레그램 polling 모드로 전환됨 (webhook 삭제)")
            return ok
    except TimeoutError:
        logger.info("텔레그램 webhook 삭제 시간 초과 - 다음 polling 주기에서 재시도")
    except urllib.error.URLError as exc:
        if "timed out" in str(exc).lower():
            logger.info("텔레그램 webhook 삭제 시간 초과 - 다음 polling 주기에서 재시도")
            return False
        body = ""
        logger.warning("텔레그램 webhook 삭제 실패: %s | body=%s", exc, body)
        return False
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        logger.warning("텔레그램 webhook 삭제 실패: %s | body=%s", exc, body)
    except Exception as exc:
        logger.warning("텔레그램 webhook 삭제 실패: %s", exc)
    return False
