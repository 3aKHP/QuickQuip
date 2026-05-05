from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from time import time
import random
from typing import Optional

from quickquip.games.config import BlackjackConfig
from quickquip.games.economy import GameEconomyStore
from quickquip.games.registry import BaseGame, GameResult


_SUITS = ("♠", "♥", "♦", "♣")
_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


def _new_deck() -> list[str]:
    deck = [f"{s}{r}" for s in _SUITS for r in _RANKS]
    random.shuffle(deck)
    return deck


def _card_value(card: str) -> int:
    """Return the face value of a card (A→11, J/Q/K→10)."""
    rank = card[1:]
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def _score(cards: list[str]) -> int:
    """Best score (Aces reduced from 11→1 as needed to avoid bust)."""
    total = sum(_card_value(c) for c in cards)
    aces = sum(1 for c in cards if c[1:] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and _score(cards) == 21


def _cards_str(cards: list[str]) -> str:
    return " ".join(cards) if cards else "—"


def _parse_bet(text: str) -> int | None:
    """Parse '入场 500' or bare '500' into a bet amount."""
    t = text.strip()
    if t.startswith("入场 "):
        t = t[3:].strip()
    elif t.startswith("入场"):
        t = t[2:].strip()
    try:
        bet = int(t)
        return bet if bet > 0 else None
    except (ValueError, OverflowError):
        return None


@dataclass
class _BJPlayer:
    user_id: str
    bet: int
    cards: list[str] = field(default_factory=list)
    stood: bool = False


@dataclass
class _BJSession:
    players: list[_BJPlayer] = field(default_factory=list)
    dealer_cards: list[str] = field(default_factory=list)
    deck: list[str] = field(default_factory=_new_deck)
    deck_pos: int = 0
    playing: bool = False
    expires_at: float = 0.0
    started_by: str = ""
    champ_bet: int = 0


class BlackjackGame(BaseGame):
    """21 点 (Blackjack) group game.

    Flow::

         /game start 21点 <赌注>   → 发起者自动入场
         入场 <赌注>                → 其他人加入
         开局                       → 发牌
         拿牌 / 停牌                → 轮流操作
         结束                       → 强制结算

    The bot acts as dealer (硬17停牌).  Blackjack (起手21点) beats
    ordinary 21.  Winners split the pot proportionally to their bets.
    """

    @property
    def name(self) -> str:
        return "21点"

    @property
    def aliases(self) -> list[str]:
        return ["blackjack", "bj", "21"]

    def __init__(self, economy: GameEconomyStore | None = None, config: BlackjackConfig | None = None, max_sessions: int = 512):
        self._economy = economy
        self._config = config or BlackjackConfig()
        self._sessions: OrderedDict[str, _BJSession] = OrderedDict()
        self._max_sessions = max_sessions

    # ── BaseGame API ─────────────────────────────────────────────────────

    def start(self, group_id: str, user_id: str, start_arg: str = "") -> str:
        bet = _parse_bet(start_arg)
        if bet is None:
            return f"用法：/game start 21点 <赌注>\n赌注范围：{self._config.min_bet} ~ 你的金币余额"

        if bet < self._config.min_bet:
            return f"最低赌注为 {self._config.min_bet} 金币"

        if self._economy:
            bal = self._economy.get_balance(user_id, group_id)
            if bal["gold"] < bet:
                return f"金币不足！你当前有 {bal['gold']} 金币"

        session = _BJSession(
            players=[_BJPlayer(user_id=str(user_id), bet=bet)],
            expires_at=time() + self._config.timeout_seconds,
            started_by=str(user_id),
            champ_bet=bet,
        )
        self._sessions[str(group_id)] = session
        self._touch(str(group_id))
        self._prune()

        # Deduct the first player's bet immediately
        if self._economy:
            self._economy.deduct_gold(str(user_id), str(group_id), bet)

        return (
            f"🃏 21点游戏开始！\n"
            f"发起者已下注 {bet} 金币（最低入场：{max(self._config.min_bet, bet // 2)}）\n"
            f"发送 入场 <金额> 加入（最多 {self._config.max_players} 人）\n"
            f"发送 开局 开始发牌"
        )

    def stop(self, group_id: str) -> Optional[str]:
        session = self._sessions.pop(str(group_id), None)
        if session is None:
            return None
        # Refund all players
        if self._economy:
            for p in session.players:
                self._economy.add_gold(p.user_id, str(group_id), p.bet)
        if session.playing:
            return "游戏已终止，所有下注已退还"
        return "游戏已取消，下注已退还"

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

        # Timeout check
        if now_ts > session.expires_at:
            return self._settle(key, session, f"超时 {self._config.timeout_seconds}s，自动结算")

        if not session.playing:
            return self._process_waiting(key, session, uid, t, now_ts)
        return self._process_playing(key, session, uid, t, now_ts)

    # ── waiting phase ────────────────────────────────────────────────────

    def _process_waiting(
        self, key: str, s: _BJSession, uid: str, t: str, now_ts: float
    ) -> Optional[GameResult]:

        if t in ("开局", "开始", "发牌"):
            if len(s.players) < 1:
                return GameResult(reply="至少需要 1 名玩家才能开局")
            return self._deal(key, s)

        if t.startswith("入场"):
            return self._add_player(key, s, uid, t)

        # Try bare number as bet
        bet = _parse_bet(t)
        if bet is not None:
            return self._add_player_with_bet(key, s, uid, bet)

        return None

    def _add_player(self, key: str, s: _BJSession, uid: str, text: str) -> Optional[GameResult]:
        bet = _parse_bet(text)
        if bet is None:
            return GameResult(reply="用法：入场 <金额>，例如 入场 500")
        return self._add_player_with_bet(key, s, uid, bet)

    def _add_player_with_bet(self, key: str, s: _BJSession, uid: str, bet: int) -> Optional[GameResult]:
        gid = key

        # Already joined?
        for p in s.players:
            if p.user_id == uid:
                return GameResult(
                    reply=f"你已入场，当前下注 {p.bet} 金币。发送 开局 开始游戏吧！",
                    at_user_id=uid,
                )

        min_entry = max(self._config.min_bet, s.champ_bet // 2)
        if bet < min_entry:
            return GameResult(
                reply=f"最低入场为 {min_entry} 金币（发起者赌注的 1/2）",
                at_user_id=uid,
            )

        if len(s.players) >= self._config.max_players:
            return GameResult(reply=f"最多 {self._config.max_players} 人参与")

        if self._economy:
            bal = self._economy.get_balance(uid, gid)
            if bal["gold"] < bet:
                return GameResult(
                    reply=f"金币不足！你当前有 {bal['gold']} 金币",
                    at_user_id=uid,
                )
            self._economy.deduct_gold(uid, gid, bet)

        s.players.append(_BJPlayer(user_id=uid, bet=bet))
        s.expires_at = time() + self._config.timeout_seconds
        self._touch(key)

        names = [f"QQ:{p.user_id}" for p in s.players]
        return GameResult(
            reply=f"入场成功！已下注 {bet} 金币\n"
                   f"当前玩家（{len(s.players)}/{self._config.max_players}）：{'、'.join(names)}\n"
                   f"发送 入场 <金额> 继续加入，发送 开局 开始",
            at_user_id=uid,
        )

    # ── dealing ──────────────────────────────────────────────────────────

    def _deal(self, key: str, s: _BJSession) -> GameResult:
        s.playing = True
        s.expires_at = time() + self._config.timeout_seconds
        self._touch(key)

        # Deal 2 cards to each player and dealer
        for _ in range(2):
            for p in s.players:
                p.cards.append(s.deck[s.deck_pos])
                s.deck_pos += 1
            s.dealer_cards.append(s.deck[s.deck_pos])
            s.deck_pos += 1

        # Build status
        lines = ["🃏 发牌完毕！"]
        for i, p in enumerate(s.players):
            bj = " ← Blackjack!" if _is_blackjack(p.cards) else ""
            lines.append(
                f"玩家{i + 1} (QQ:{p.user_id}) [{_cards_str(p.cards)}] "
                f"共 {_score(p.cards)} 点 下注 {p.bet}{bj}"
            )
        lines.append(f"庄家 [{s.dealer_cards[0]} ?]")
        lines.append("发送 拿牌 或 停牌 操作")

        # If someone has blackjack in their first 2 cards, note it
        has_bj = any(_is_blackjack(p.cards) for p in s.players)
        if has_bj:
            lines.append("有人起手 Blackjack！庄家将亮牌比大小。")

        # Check if all players already have 21
        all_done = all(_score(p.cards) >= 21 for p in s.players)
        if all_done:
            auto = self._settle(key, s, "全员21点，自动结算")
            return auto

        return GameResult(reply="\n".join(lines))

    # ── playing phase ────────────────────────────────────────────────────

    def _process_playing(
        self, key: str, s: _BJSession, uid: str, t: str, now_ts: float
    ) -> Optional[GameResult]:

        if t in ("结束", "结算"):
            player = self._find_player(s, uid)
            if player is None:
                return GameResult(reply="你没有入场", at_user_id=uid)
            if not player.stood:
                player.stood = True
            return self._settle(key, s, "有玩家发起结算")

        if t in ("停牌", "停"):
            player = self._find_player(s, uid)
            if player is None:
                return GameResult(reply="你没有入场")
            if player.stood:
                return GameResult(
                    reply=f"你已经停牌了（{_score(player.cards)} 点）",
                    at_user_id=uid,
                )
            player.stood = True
            s.expires_at = now_ts + self._config.timeout_seconds
            self._touch(key)

            if self._all_stood(s):
                return self._settle(key, s, "全员停牌，自动结算")

            return GameResult(
                reply=f"QQ:{uid} 停牌（{_cards_str(player.cards)} = {_score(player.cards)} 点）",
                at_user_id=uid,
            )

        if t in ("拿牌", "要牌", "hit"):
            player = self._find_player(s, uid)
            if player is None:
                return GameResult(reply="你没有入场")
            if player.stood:
                return GameResult(
                    reply=f"你已经停牌了（{_score(player.cards)} 点），不能拿牌",
                    at_user_id=uid,
                )
            if _score(player.cards) >= 21:
                return GameResult(
                    reply=f"你已是 {_score(player.cards)} 点，不能拿牌",
                    at_user_id=uid,
                )

            card = s.deck[s.deck_pos]
            s.deck_pos += 1
            player.cards.append(card)
            score = _score(player.cards)
            s.expires_at = now_ts + self._config.timeout_seconds
            self._touch(key)

            if score > 21:
                player.stood = True
                msg = (
                    f"QQ:{uid} 拿牌 {card}\n"
                    f"手牌：{_cards_str(player.cards)} = {score} 点 💥 爆了！"
                )
                if self._all_stood(s):
                    settle = self._settle(key, s, "全员停牌，自动结算")
                    msg += f"\n{settle.reply}"
                    return GameResult(
                        reply=msg,
                        at_user_id=uid,
                        finished=True,
                        rule_name=settle.rule_name,
                    )
                return GameResult(reply=msg, at_user_id=uid)

            if score == 21:
                player.stood = True
                msg = (
                    f"QQ:{uid} 拿牌 {card}\n"
                    f"手牌：{_cards_str(player.cards)} = 21 点！自动停牌"
                )
                if self._all_stood(s):
                    settle = self._settle(key, s, "全员停牌，自动结算")
                    msg += f"\n{settle.reply}"
                    return GameResult(
                        reply=msg,
                        at_user_id=uid,
                        finished=True,
                        rule_name=settle.rule_name,
                    )
                return GameResult(reply=msg, at_user_id=uid)

            return GameResult(
                reply=f"QQ:{uid} 拿牌 {card}\n"
                       f"手牌：{_cards_str(player.cards)} = {score} 点",
                at_user_id=uid,
            )

        return None

    # ── settlement ───────────────────────────────────────────────────────

    def _settle(self, key: str, s: _BJSession, reason: str) -> GameResult:
        # Dealer plays: hit on 16, stand on 17
        while _score(s.dealer_cards) < self._config.dealer_stand_threshold:
            s.dealer_cards.append(s.deck[s.deck_pos])
            s.deck_pos += 1
        dealer_score = _score(s.dealer_cards)
        dealer_bj = _is_blackjack(s.dealer_cards)

        lines = [f"🃏 结算（{reason}）"]
        lines.append(f"庄家手牌：[{_cards_str(s.dealer_cards)}] = {dealer_score} 点"
                      + (" ← Blackjack!" if dealer_bj else "")
                      + (" 💥 爆牌！" if dealer_score > 21 else ""))

        # Any player with blackjack beats dealer who doesn't have blackjack
        # Player with blackjack gets 1.5x their bet back

        for p in s.players:
            p_score = _score(p.cards)
            p_bj = _is_blackjack(p.cards)
            uid = p.user_id
            gid = key

            if p_score > 21:
                # Busted — lost bet already deducted
                lines.append(f"QQ:{uid} [{_cards_str(p.cards)}] {p_score} 点 爆牌 — -{p.bet} 💰")
                continue

            if dealer_score > 21:
                # Dealer busts — all standing players win
                win = p.bet * 2
                if self._economy:
                    self._economy.add_gold(uid, gid, win)
                lines.append(f"QQ:{uid} [{_cards_str(p.cards)}] {p_score} 点 庄家爆牌 — +{p.bet} 💰")
                continue

            if p_bj and not dealer_bj:
                # Player blackjack beats dealer — 1.5x payout
                win = p.bet + int(p.bet * 1.5)
                if self._economy:
                    self._economy.add_gold(uid, gid, win)
                lines.append(f"QQ:{uid} [{_cards_str(p.cards)}] Blackjack! — +{int(p.bet * 1.5)} 💰")
                continue

            if dealer_bj and not p_bj:
                # Dealer blackjack beats player
                lines.append(f"QQ:{uid} [{_cards_str(p.cards)}] {p_score} 点 庄家 Blackjack — -{p.bet} 💰")
                continue

            if p_score > dealer_score:
                # Player wins
                win = p.bet * 2
                if self._economy:
                    self._economy.add_gold(uid, gid, win)
                lines.append(f"QQ:{uid} [{_cards_str(p.cards)}] {p_score} > {dealer_score} 胜! — +{p.bet} 💰")
            elif p_score < dealer_score:
                lines.append(f"QQ:{uid} [{_cards_str(p.cards)}] {p_score} < {dealer_score} 负 — -{p.bet} 💰")
            else:
                # Push — refund
                if self._economy:
                    self._economy.add_gold(uid, gid, p.bet)
                lines.append(f"QQ:{uid} [{_cards_str(p.cards)}] {p_score} = {dealer_score} 平 — 退还 {p.bet} 💰")

        self._sessions.pop(key, None)
        return GameResult(
            reply="\n".join(lines),
            finished=True,
            rule_name="blackjack_settle",
        )

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _find_player(s: _BJSession, uid: str) -> Optional[_BJPlayer]:
        for p in s.players:
            if p.user_id == uid:
                return p
        return None

    def _all_stood(self, s: _BJSession) -> bool:
        return all(p.stood or _score(p.cards) >= 21 for p in s.players)

    def _touch(self, key: str) -> None:
        if key in self._sessions:
            self._sessions.move_to_end(key)

    def _prune(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
