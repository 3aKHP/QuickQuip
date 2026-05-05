from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from time import time
import random
from typing import Optional

from quickquip.games.config import RussianRouletteConfig
from quickquip.games.economy import GameEconomyStore
from quickquip.games.registry import BaseGame, GameResult

_LIVE_MSGS = [
    "咔！空枪，你活了下来",
    "扳机扣下——什么都没有发生，运气不错",
    "黑洞洞的枪口里没有火光——安全",
    "呼，这一枪是空的",
    "左轮转过了致命的一格，你安然无恙",
]

_DEATH_MSGS = [
    "嘭！子弹正中眉心，你倒下了",
    "火光一闪，一切都结束了",
    "这一枪带走了你",
    "弹仓转到了实弹的那一格……永别了",
    "轰然一声，你穿越到了异世界",
]


def _build_cylinder(bullet_count: int, total_slots: int = 7) -> list[int]:
    """Create a cylinder with *bullet_count* bullets randomly placed in *total_slots*."""
    arr = [0] * total_slots
    for pos in random.sample(range(total_slots), min(bullet_count, total_slots)):
        arr[pos] = 1
    return arr


def _survival_probability(cylinder: list[int], index: int) -> str:
    """Probability of surviving the NEXT shot (bullets remaining / slots remaining)."""
    remaining_slots = len(cylinder) - index
    remaining_bullets = sum(cylinder[index:])
    if remaining_slots == 0:
        return "0%"
    p = (1 - remaining_bullets / remaining_slots) * 100
    return f"{p:.1f}%"


@dataclass
class _RRSession:
    player1_id: str
    player1_bet: int = 0
    player2_id: str = ""
    phase: str = "bullets"  # "bullets" | "waiting" | "playing"
    cylinder: list[int] = field(default_factory=list)
    cylinder_index: int = 0
    next_player: str = ""  # user_id of who shoots next
    expires_at: float = 0.0


class RussianRouletteGame(BaseGame):
    """俄罗斯轮盘 (Russian Roulette) — 1v1 dueling game.

    Flow::

         /game start 俄罗斯轮盘 <赌注>  → 发起对决
         发送子弹数（1-6）               → 装弹
         接受对决                          → 对手加入（双方等额下注）
         开枪                              → 轮流扣扳机，撞弹即死，胜者赢取对方赌注

    30 秒空闲自动超时。7 槽弹仓，子弹随机排列。
    """

    @property
    def name(self) -> str:
        return "俄罗斯轮盘"

    @property
    def aliases(self) -> list[str]:
        return ["russian", "轮盘", "rr"]

    def __init__(self, economy: GameEconomyStore | None = None, config: RussianRouletteConfig | None = None, max_sessions: int = 512):
        self._economy = economy
        self._config = config or RussianRouletteConfig()
        self._sessions: OrderedDict[str, _RRSession] = OrderedDict()
        self._max_sessions = max_sessions

    # ── BaseGame API ─────────────────────────────────────────────────────

    def start(self, group_id: str, user_id: str, start_arg: str = "") -> str:
        bet = self._parse_bet(start_arg)
        if bet is None:
            return f"用法：/game start 俄罗斯轮盘 <赌注>\n赌注范围：{self._config.min_bet} ~ 你的金币余额"

        if bet < self._config.min_bet:
            return f"最低赌注为 {self._config.min_bet} 金币"

        uid = str(user_id)
        gid = str(group_id)
        if self._economy:
            bal = self._economy.get_balance(uid, gid)
            if bal["gold"] < bet:
                return f"金币不足！你当前有 {bal['gold']} 金币"

        session = _RRSession(
            player1_id=uid,
            player1_bet=bet,
            expires_at=time() + self._config.timeout_seconds,
        )
        self._sessions[gid] = session
        self._touch(gid)
        self._prune()
        return (
            f"🔫 俄罗斯轮盘对决发起！\n"
            f"赌注：{bet} 金币\n"
            f"请选择装填几颗子弹（1-6），直接发送数字"
        )

    def stop(self, group_id: str) -> Optional[str]:
        session = self._sessions.pop(str(group_id), None)
        if session is None:
            return None
        # Gold is only deducted when player 2 accepts (phase → "playing").
        # Earlier phases: no gold was taken, so no refund is needed.
        if session.phase == "playing" and self._economy:
            self._economy.add_gold(session.player1_id, str(group_id), session.player1_bet)
            if session.player2_id:
                self._economy.add_gold(session.player2_id, str(group_id), session.player1_bet)
            return "对决已终止，赌注已退还"
        return "对决已取消"

    def is_active(self, group_id: str) -> bool:
        return str(group_id) in self._sessions

    def process(
        self, group_id: str, user_id: str, text: str, now_ts: float
    ) -> Optional[GameResult]:
        key = str(group_id)
        session = self._sessions.get(key)
        if session is None:
            return None

        uid = str(user_id)
        t = text.strip()

        if now_ts > session.expires_at:
            return self._timeout(key, session)

        if session.phase == "bullets":
            return self._handle_bullets(key, session, uid, t, now_ts)
        if session.phase == "waiting":
            return self._handle_waiting(key, session, uid, t, now_ts)
        if session.phase == "playing":
            return self._handle_playing(key, session, uid, t, now_ts)

        return None

    # ── phase: bullets ───────────────────────────────────────────────────

    def _handle_bullets(
        self, key: str, s: _RRSession, uid: str, t: str, now_ts: float
    ) -> Optional[GameResult]:
        if uid != s.player1_id:
            return None

        try:
            n = int(t)
        except ValueError:
            return GameResult(
                reply="请输入数字 1-6 来选择子弹数量",
                at_user_id=uid,
            )

        if not 1 <= n <= 6:
            return GameResult(reply="子弹数量须在 1-6 之间", at_user_id=uid)

        s.cylinder = _build_cylinder(n, self._config.cylinder_slots)
        s.cylinder_index = 0
        s.next_player = s.player1_id
        s.phase = "waiting"
        s.expires_at = now_ts + self._config.timeout_seconds
        self._touch(key)

        first_pct = (1 - sum(s.cylinder) / self._config.cylinder_slots) * 100
        return GameResult(
            reply=(
                f"装填完毕！{n} 颗子弹随机排入 {self._config.cylinder_slots} 槽弹仓\n"
                f"第一枪存活概率：{first_pct:.1f}%\n"
                f"等待对手发送 接受对决 加入（{self._config.timeout_seconds}s 超时）"
            ),
        )

    # ── phase: waiting ───────────────────────────────────────────────────

    def _handle_waiting(
        self, key: str, s: _RRSession, uid: str, t: str, now_ts: float
    ) -> Optional[GameResult]:
        if t != "接受对决":
            return None

        if uid == s.player1_id:
            return GameResult(reply="你不能接受自己发起的对决！", at_user_id=uid)

        gid = key
        if self._economy:
            bal = self._economy.get_balance(uid, gid)
            if bal["gold"] < s.player1_bet:
                return GameResult(
                    reply=f"金币不足！你需要 {s.player1_bet} 金币来接受对决（当前 {bal['gold']}）",
                    at_user_id=uid,
                )
            # Deduct both players atomically: if p1's deduction fails, refund p2
            self._economy.deduct_gold(uid, gid, s.player1_bet)
            if not self._economy.deduct_gold(s.player1_id, gid, s.player1_bet):
                self._economy.add_gold(uid, gid, s.player1_bet)
                return GameResult(
                    reply="发起者金币不足，对决取消",
                    at_user_id=uid,
                )

        s.player2_id = uid
        s.phase = "playing"
        s.expires_at = now_ts + self._config.timeout_seconds
        self._touch(key)

        bullet_count = sum(s.cylinder)
        return GameResult(
            reply=(
                f"🔫 对决开始！双方各下注 {s.player1_bet} 金币\n"
                f"弹仓：{bullet_count}/7 颗实弹\n"
                f"QQ:{s.player1_id} 先开枪！发送 开枪"
            ),
        )

    # ── phase: playing ───────────────────────────────────────────────────

    def _handle_playing(
        self, key: str, s: _RRSession, uid: str, t: str, now_ts: float
    ) -> Optional[GameResult]:
        if t != "开枪":
            return None

        if uid not in (s.player1_id, s.player2_id):
            return GameResult(
                reply=f"这是 QQ:{s.player1_id} 和 QQ:{s.player2_id} 的对决，请安静围观~",
                at_user_id=uid,
            )

        if uid != s.next_player:
            return GameResult(
                reply=f"还没轮到你！该 QQ:{s.next_player} 开枪了",
                at_user_id=uid,
            )

        # Fire!
        bullet = s.cylinder[s.cylinder_index]
        s.cylinder_index += 1

        if bullet == 1:
            # DEATH — this player loses
            loser_id = uid
            winner_id = s.player2_id if uid == s.player1_id else s.player1_id
            pot = s.player1_bet * 2  # both bets

            if self._economy:
                self._economy.add_gold(winner_id, key, pot)

            self._sessions.pop(key, None)

            death_msg = random.choice(_DEATH_MSGS)
            return GameResult(
                reply=(
                    f"{death_msg}\n\n"
                    f"🏆 QQ:{winner_id} 获胜！赢得 {s.player1_bet} 金币\n"
                    f"💀 QQ:{loser_id} 损失 {s.player1_bet} 金币"
                ),
                at_user_id=loser_id,
                finished=True,
                rule_name="russian_roulette_win",
            )

        # Empty chamber — survive
        next_player = s.player2_id if uid == s.player1_id else s.player1_id
        s.next_player = next_player
        s.expires_at = now_ts + self._config.timeout_seconds
        self._touch(key)

        live_msg = random.choice(_LIVE_MSGS)
        survival = _survival_probability(s.cylinder, s.cylinder_index)
        return GameResult(
            reply=(
                f"{live_msg}\n"
                f"下一枪存活概率：{survival}\n"
                f"轮到 QQ:{next_player} 开枪！"
            ),
            at_user_id=uid,
        )

    # ── timeout ──────────────────────────────────────────────────────────

    def _timeout(self, key: str, s: _RRSession) -> GameResult:
        msg = "⏰ 对决超时，"
        if s.phase in ("bullets", "waiting"):
            self._sessions.pop(key, None)
            return GameResult(
                reply=msg + "对决已取消",
                finished=True,
                rule_name="russian_roulette_timeout",
            )

        # Playing phase timeout — last shooter wins by default
        winner_id = (
            s.player2_id if s.next_player == s.player1_id else s.player1_id
        )
        loser_id = s.next_player
        pot = s.player1_bet * 2
        if self._economy:
            self._economy.add_gold(winner_id, key, pot)

        self._sessions.pop(key, None)
        return GameResult(
            reply=(
                msg + f"QQ:{loser_id} 超时未开枪，判负！\n"
                f"🏆 QQ:{winner_id} 获胜！赢得 {s.player1_bet} 金币"
            ),
            at_user_id=loser_id,
            finished=True,
            rule_name="russian_roulette_timeout_win",
        )

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_bet(arg: str) -> int | None:
        t = arg.strip()
        if not t:
            return None
        try:
            bet = int(t)
            if bet > 0:
                return bet
        except (ValueError, OverflowError):
            pass
        return None

    def _touch(self, key: str) -> None:
        if key in self._sessions:
            self._sessions.move_to_end(key)

    def _prune(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
