"""Limite de tentativas de login sem sucesso, por usuário.

Depois de `max_failures` erros dentro de `window_seconds`, o usuário fica bloqueado por
`lockout_seconds`, mesmo que acerte a senha: assim um robô não consegue continuar testando
senhas. O estado fica em memória, o que basta para a API rodando em um único processo;
reiniciar a API zera os contadores.

A chave é o nome de usuário, e não o IP: atrás do proxy da Render o IP do cliente vem de um
cabeçalho que o próprio cliente pode forjar para escapar do limite.
"""

import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock


class LoginThrottle:
    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: float = 15 * 60,
        lockout_seconds: float = 5 * 60,
        clock: Callable[[], float] = time.monotonic,
        max_tracked_keys: int = 10_000,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._clock = clock
        self._max_tracked_keys = max_tracked_keys
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = Lock()

    @staticmethod
    def key_for(username: str) -> str:
        return username.strip().casefold()

    def retry_after(self, username: str) -> int:
        """Segundos até poder tentar de novo; 0 quando a tentativa é permitida."""
        key = self.key_for(username)
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0
            remaining = until - self._clock()
            if remaining <= 0:
                del self._locked_until[key]
                return 0
            return math.ceil(remaining)

    def record_failure(self, username: str) -> None:
        key = self.key_for(username)
        now = self._clock()
        with self._lock:
            if len(self._failures) >= self._max_tracked_keys:
                self._prune(now)
            failures = self._failures.setdefault(key, deque())
            failures.append(now)
            while failures and now - failures[0] > self.window_seconds:
                failures.popleft()
            if len(failures) >= self.max_failures:
                self._locked_until[key] = now + self.lockout_seconds
                failures.clear()

    def reset(self, username: str) -> None:
        key = self.key_for(username)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()

    def _prune(self, now: float) -> None:
        for key in [key for key, times in self._failures.items() if not times or now - times[-1] > self.window_seconds]:
            del self._failures[key]
        for key in [key for key, until in self._locked_until.items() if until <= now]:
            del self._locked_until[key]


login_throttle = LoginThrottle()
