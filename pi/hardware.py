"""LCD1602(I2C)・アクティブブザー・タクトスイッチの制御(仕様書 §11)。

RGB LED は購入部品に含まれないため、状態表現は LCD テキスト + ブザー回数のみ
(仕様書 §11 の対応表)。

複数スレッド(ボタンコールバック・Slack ハンドラ・再送/棚卸しワーカー)から
表示更新が飛んでくるが、I2C バスと LCD を直接操作するのは `display_queue` を
消費する専用スレッドだけにして競合を避ける。

`OKOZUKAI_HARDWARE=dummy` を指定すると GPIO/I2C を一切使わず、表示内容を
ログに出すだけの実装に切り替わる(この開発機など Pi 以外での動作確認用)。
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

import config

logger = logging.getLogger("okozukai.hardware")

# LCD に表示する状態メッセージ(仕様書 §11 の対応表)
WAITING_FOR_APPROVAL = "WAITING FOR APPROVAL"
ALREADY_DONE_TODAY = "ALREADY DONE TODAY"


class _LcdBackend:
    """実機の LCD1602。RPLCD が入っていない/I2C が無い環境では使わない。"""

    def __init__(self) -> None:
        from RPLCD.i2c import CharLCD  # 遅延 import(dummy モードでは不要)

        self._lcd = CharLCD(
            i2c_expander="PCF8574",
            address=config.LCD_I2C_ADDRESS,
            cols=16,
            rows=2,
        )

    def write(self, line1: str, line2: str = "") -> None:
        self._lcd.clear()
        self._lcd.write_string(line1[:16])
        self._lcd.crlf()
        self._lcd.write_string(line2[:16])


class _DummyLcdBackend:
    def write(self, line1: str, line2: str = "") -> None:
        logger.info("[LCD] %s / %s", line1, line2)


class _BuzzerBackend:
    def __init__(self) -> None:
        from gpiozero import Buzzer

        self._buzzer = Buzzer(config.BUZZER_PIN)

    def beep(self, times: int, on_seconds: float = 0.15, off_seconds: float = 0.15) -> None:
        import time

        for i in range(times):
            self._buzzer.on()
            time.sleep(on_seconds)
            self._buzzer.off()
            if i < times - 1:
                time.sleep(off_seconds)


class _DummyBuzzerBackend:
    def beep(self, times: int, on_seconds: float = 0.15, off_seconds: float = 0.15) -> None:
        logger.info("[BUZZER] beep x%d", times)


class DisplayEvent:
    """display_queue に積むイベント。sticky=True の間は残高表示に戻さない。"""

    def __init__(self, line1: str, line2: str = "", buzzer: int = 0, sticky: bool = False):
        self.line1 = line1
        self.line2 = line2
        self.buzzer = buzzer
        self.sticky = sticky


class HardwareController:
    def __init__(self, balance_provider: Callable[[], int]) -> None:
        self._balance_provider = balance_provider
        self.display_queue: "queue.Queue[DisplayEvent]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        use_dummy = config.HARDWARE_BACKEND != "gpio"
        try:
            self._lcd = _DummyLcdBackend() if use_dummy else _LcdBackend()
            self._buzzer = _DummyBuzzerBackend() if use_dummy else _BuzzerBackend()
        except Exception:
            logger.exception("実機ハードウェアの初期化に失敗したため dummy backend にフォールバックします")
            self._lcd = _DummyLcdBackend()
            self._buzzer = _DummyBuzzerBackend()

    # --- ボタン ---

    def register_buttons(self, on_press: Callable[[str], None]) -> None:
        if config.HARDWARE_BACKEND != "gpio":
            logger.info("dummy backend のため物理ボタンは登録しません(services から直接呼び出してください)")
            return

        from gpiozero import Button

        for task_id, pin in config.BUTTON_PINS.items():
            button = Button(pin, bounce_time=config.BUTTON_BOUNCE_TIME)
            button.when_pressed = lambda tid=task_id: on_press(tid)

    # --- 表示スレッド ---

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="hardware-display", daemon=True)
        self._thread.start()
        self.show_balance()

    def stop(self) -> None:
        self._stop.set()

    def show_balance(self) -> None:
        self.display_queue.put(DisplayEvent("BALANCE", f"{self._balance_provider()} YEN", sticky=True))

    def push(self, line1: str, line2: str = "", buzzer: int = 0) -> None:
        self.display_queue.put(DisplayEvent(line1, line2, buzzer=buzzer))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.display_queue.get(timeout=config.DISPLAY_MESSAGE_SECONDS)
            except queue.Empty:
                # 一定時間イベントが無ければ残高表示に戻る(仕様書 §11)
                self._render(DisplayEvent("BALANCE", f"{self._balance_provider()} YEN", sticky=True))
                continue

            self._render(event)
            if event.buzzer:
                self._buzzer.beep(event.buzzer)

    def _render(self, event: DisplayEvent) -> None:
        self._lcd.write(event.line1, event.line2)
