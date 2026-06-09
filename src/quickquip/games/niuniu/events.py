"""Event definitions and message templates for 牛牛大作战."""

import random

# ── gluing events (打胶事件) ──────────────────────────────────────────────

GLUE_EVENTS = [
    {
        "name": "normal",
        "weight": 30,
        "category": "growth",
        "pos": [
            "你嘿咻嘿咻一下，促进了牛牛发育，牛牛增加了 {diff} cm！",
            "你打了个舒服痛快的🦶，牛牛增加了 {diff} cm！",
            "哇哦！你的一🦶让牛牛变长了 {diff} cm！",
            "你的牛牛感受到了你的热情，增加了 {diff} cm！",
        ],
        "neg": [
            "哦吼！？看来你的牛牛凹进去了 {diff} cm！",
            "你突发恶疾！你的牛牛凹进去了 {diff} cm！",
            "笑死，你因为打🦶过度导致牛牛凹进去了 {diff} cm！",
            "阿哦，你过度打🦶，牛牛缩短了 {diff} cm 呢！",
            "小打怡情，大打伤身，强打灰飞烟灭！牛牛缩短了 {diff} cm！",
        ],
        "zero": [
            "你打了个🦶，但是什么变化也没有，好奇怪捏~",
            "你的牛牛刚开始变长了，可过了一会又回来了，什么变化也没有",
            "你在打胶时，感觉这个世界似乎发生了什么变化",
        ],
    },
    {
        "name": "lucky_day",
        "weight": 5,
        "category": "growth",
        "pos": [
            "🍀 今天运势极佳！牛牛疯狂生长了 {diff} cm！",
            "幸运女神掀起了你的裙子！牛牛暴增 {diff} cm！",
            "黄历说今日宜打胶，果然！牛牛增长了 {diff} cm！",
        ],
    },
    {
        "name": "mirror",
        "weight": 5,
        "category": "mirror",
        "pos": [
            "🪞 你的牛牛穿过了镜子！长度反转了！现在 {new_length} cm！",
            "牛牛误入了异次元裂缝，正负颠倒！当前 {new_length} cm！",
            "镜之国度的魔法！你的牛牛变成了 {new_length} cm！",
        ],
    },
    {
        "name": "blessing",
        "weight": 3,
        "category": "jackpot",
        "pos": [
            "🌈 牛牛之神降下了祝福！牛牛暴涨 {diff} cm！！",
            "上古牛神显灵！你的牛牛获得了神力加持，暴增 {diff} cm！",
            "天降祥瑞！七彩祥云笼罩了你的牛牛，增长 {diff} cm！",
        ],
    },
    {
        "name": "gambler",
        "weight": 4,
        "category": "gambler",
        "pos": [
            "🎰 你押上了全部身家……赢了！牛牛暴涨 {diff} cm！！",
            "赌徒的胜利！牛牛狂增 {diff} cm！",
        ],
        "neg": [
            "🎰 你押上了全部身家……输光了！牛牛暴跌 {diff} cm...",
            "赌狗不得好死！牛牛缩水了 {diff} cm...",
        ],
    },
    {
        "name": "zen",
        "weight": 4,
        "category": "zen",
        "pos": [
            "🧘 你进入了贤者模式，牛牛宁静地生长了 {diff} cm",
            "心如止水，牛牛缓缓增长了 {diff} cm",
            "打坐冥想之后，牛牛平和地增加了 {diff} cm",
        ],
    },
    {
        "name": "frenzy",
        "weight": 4,
        "category": "frenzy",
        "pos": [
            "💥 你进入了狂暴状态！牛牛暴涨 {diff} cm！",
            "肾上腺素飙升！牛牛怒长了 {diff} cm！",
            "你磕了药一样疯狂打胶，牛牛暴增 {diff} cm！",
        ],
    },
    {
        "name": "nightmare",
        "weight": 3,
        "category": "shrinkage",
        "neg": [
            "👻 你做了一个关于牛牛的噩梦！吓缩了 {diff} cm...",
            "深夜惊醒，发现牛牛被鬼压床！缩短了 {diff} cm...",
        ],
    },
    {
        "name": "shrinkage",
        "weight": 8,
        "category": "shrinkage",
        "neg": [
            "由于你在换蛋期打胶，你的牛牛断掉了呢！当前长度 {new_length} cm！",
            "bro换蛋期就不要打胶了！你的牛牛萎缩了 {diff} cm！",
        ],
    },
    {
        "name": "arrested",
        "weight": 2,
        "category": "arrested",
        "pos": [
            "打胶时被窗外的路人发现了，对方报警了！你被抓走关进小黑屋 {ban_time}s！",
        ],
    },
    {
        "name": "special_boost",
        "weight": 4,
        "category": "growth",
        "pos": [
            "你收到了群主私发的女装，冲！！！牛牛长大了 {diff} cm！",
            "一股神秘力量涌来！牛牛暴增 {diff} cm！",
        ],
    },
]

# ── length comments (长度评价) ────────────────────────────────────────────

LENGTH_COMMENTS: dict[tuple[float, float], list[str]] = {
    (-1000000000, -1000): [
        "你已经超越了维度的界限……深渊魅魔之神！",
        "凡人无法理解的凹度，你已经成为了传说！",
    ],
    (-1000, -100): [
        "哇哦！你已经进化成魅魔了！魅魔在击剑时有几率吞噬对方牛牛呢！",
    ],
    (-100, -50): [
        "嗯……好像已经穿过了身体吧……从另一面来看也可以算是凸出来的吧？",
        "WOW，真的凹进去了好多呢！",
    ],
    (-50, -25): [
        "这名女生，你的身体很健康哦！",
        "你已经是我们女孩子的一员啦！",
    ],
    (-25, -10): [
        "你已经是一名女生了呢！",
        "从女生的角度来说，你发育良好哦！",
        "你醒啦？你已经是一名女孩子啦！",
    ],
    (-10, 0): [
        "安了安了，不要伤心嘛，做女生有什么不好的啊",
        "加油加油！我看好你哦！",
        "成为香香软软的女孩子吧！",
    ],
    (0, 10): [
        "你行不行啊？细狗！",
        "虽然短，但是小小的也很可爱呢",
        "像一只蚕宝宝",
    ],
    (10, 25): [
        "唔……没话说",
        "已经很长了呢！",
    ],
    (25, 50): [
        "话说这种真的有可能吗？",
        "厚礼谢！",
        "已经突破天际了嘛……",
        "你马上要进化成牛头人了！！",
    ],
    (50, 100): [
        "你这个长度会死人的……！",
        "你是什么怪物，不要过来啊！！",
        "惊世骇俗！你已经进化成牛头人了！牛头人在击剑时有几率支配对手！",
    ],
    (100, 1000): [
        "你已经超越人类极限了……",
        "牛牛之王！",
    ],
    (1000, 1000000000): [
        "你已经是神话级别的存在了！牛牛突破了现实维度！",
        "凡人只能仰望你的长度……牛牛之神降临！",
    ],
}


def get_comment(length: float, text=None) -> str:
    """Return a random flavour comment for the given niuniu length.

    If *text* (NiuNiuText) is provided, uses text.glue_length_comments.
    Otherwise falls back to the built-in LENGTH_COMMENTS.
    """
    if text is not None and text.glue_length_comments:
        for entry in text.glue_length_comments:
            if entry["min"] < length <= entry["max"]:
                return random.choice(entry["messages"])
        return "你的牛牛状态很特殊……"

    for (lo, hi), msgs in LENGTH_COMMENTS.items():
        if lo < length <= hi:
            return random.choice(msgs)
    return "你的牛牛状态很特殊……"


# ── default fencing messages (击剑默认消息) ──────────────────────────────

FENCE_WIN_POS = [
    "你以绝对的长度让对方屈服了！长度 +{gain} cm，对方 -{loss} cm！当前 {my_len} cm！",
    "一剑封喉！你将对手挑落马下！牛牛增长 {gain} cm，当前 {my_len} cm！",
    "击剑大胜利！你从对方身上夺取了 {gain} cm！当前 {my_len} cm！",
    "对方在你面前不堪一击！牛牛怒增 {gain} cm！",
    "你的牛牛坚不可摧！+{gain} cm，对手 -{loss} cm！",
]

FENCE_WIN_NEG = [
    "哦吼！？你的牛牛在长大欸！凹进去的深度减少了 {gain} cm，当前 {my_len} cm！",
    "以凹制胜！凹牛牛反而膨胀了 {gain} cm！当前 {my_len} cm！",
    "负负得正！你的凹牛牛逆势增长 {gain} cm！",
]

FENCE_LOSE_POS = [
    "对方以绝对的长度让你屈服了！长度 -{loss} cm，当前 {my_len} cm！",
    "技不如人！牛牛被对方折服，缩短了 {loss} cm...",
    "败北！你的牛牛缩水了 {loss} cm，当前 {my_len} cm...",
    "你被对手压倒了！牛牛减少了 {loss} cm！",
    "对手的牛牛比你想象的更硬！你损失了 {loss} cm...",
]

FENCE_LOSE_NEG = [
    "哦吼！？你的牛牛因为击剑凹进去了！又凹了 {loss} cm！当前 {my_len} cm！",
    "雪上加霜！已经凹了还要继续凹...又陷进去 {loss} cm...",
    "反向击剑失败！牛牛凹得更深了 {loss} cm...",
]

# ── fencing events (击剑事件) ────────────────────────────────────────────

FENCE_EVENTS = [
    {"name": "normal", "weight": 50},
    {
        "name": "critical",
        "weight": 12,
        "win_pos": [
            "💥 暴击！你给予了对方致命一击！+{gain} cm，对方 -{loss} cm！",
            "这一剑贯穿天地！暴击！牛牛增长 {gain} cm！",
            "精准命中要害！暴击伤害！+{gain} cm！",
        ],
        "win_neg": [
            "💥 暴击！你的凹牛牛爆发了惊人力量！+{gain} cm！",
        ],
        "lose_pos": [
            "💥 对方使出了暴击！你遭受重创，-{loss} cm...",
            "天哪！对方打出了暴击！牛牛损失 {loss} cm...",
        ],
        "lose_neg": [
            "💥 暴击！你的牛牛被对方打得更凹了...",
        ],
    },
    {
        "name": "glancing",
        "weight": 12,
        "win_pos": [
            "双方擦肩而过，你略占上风！+{gain} cm",
            "这次击剑如同蜻蜓点水……你微微增长了 {gain} cm",
        ],
        "win_neg": [
            "轻轻一碰，你的凹牛牛稍微恢复了一点 +{gain} cm",
        ],
        "lose_pos": [
            "只是擦伤！你仅损失了 {loss} cm，不痛不痒",
            "有惊无险，仅仅缩水了 {loss} cm",
        ],
        "lose_neg": [
            "轻微碰撞，你的牛牛又凹了一点点...",
        ],
    },
    {
        "name": "reversal",
        "weight": 8,
        "win_pos": [
            "🔄 绝地翻盘！你以弱胜强，击溃了对手！+{gain} cm！",
            "惊天逆转！所有人都以为你会输……你赢了！+{gain} cm！",
            "逆天改命！你反杀了比你长的对手！+{gain} cm！",
        ],
        "win_neg": [
            "🔄 绝地翻盘！凹牛牛逆袭成功！+{gain} cm！",
        ],
        "lose_pos": [
            "🔄 你太大意了！被对手绝地翻盘！-{loss} cm...",
            "轻敌的代价！你被对手反杀，损失 {loss} cm...",
        ],
        "lose_neg": [
            "🔄 大意失荆州！被翻盘了...",
        ],
    },
    {
        "name": "dominate",
        "weight": 30,
        "require_role": "niutouren",
        "win_pos": [
            "👹 牛头人威压降临！你支配了对手！+{gain} cm，对方 -{loss} cm！",
            "牛头人之力爆发！你将对手踩在脚下！+{gain} cm！！",
        ],
        "win_neg": [
            "👹 牛头人威压降临！你的凹牛牛顺势膨胀了 {gain} cm！",
        ],
        "lose_pos": [
            "👹 对方使出了牛头人威压！你被支配了，-{loss} cm...",
            "牛头人支配了你！损失 {loss} cm...",
        ],
        "lose_neg": [
            "👹 对方牛头人威压！你的牛牛被压得更凹了...",
        ],
        "sever_pos": [
            "👹 牛头人腰斩！！你一刀斩断了对方的牛牛！{loss} cm 灰飞烟灭！你吸收 {gain} cm！",
            "⚔️ 牛头人处刑！拦腰斩断！对方损失 {loss} cm，你获得 {gain} cm！",
            "🪓 牛头人断头台！对方牛牛被斩落 {loss} cm，你增长了 {gain} cm！",
        ],
        "sever_neg": [
            "👹 牛头人支配！你击穿了对方的防线！深度从 {old_oppo} 翻倍至 {new_oppo} cm！你吸收 {gain} cm！",
            "深渊之力！牛头人的一击让对方的凹度暴增至 {new_oppo} cm！你获得 {gain} cm！",
        ],
        "severed_pos": [
            "👹 对方牛头人腰斩！！你的牛牛被斩落 {loss} cm！当前 {my_len} cm",
            "⚔️ 对方牛头人处刑！你的牛牛被拦腰斩断，损失 {loss} cm！",
            "🪓 对方牛头人断头台降临！你被斩落 {loss} cm...",
        ],
        "severed_neg": [
            "👹 对方牛头人支配！你的凹度从 {old_my} 暴增至 {new_my} cm！",
            "深渊之力！对方牛头人的一击让你的凹度加倍到 {new_my} cm...",
        ],
    },
    {
        "name": "succubus_devour",
        "weight": 30,
        "require_role": "succubus",
        "win_pos": [
            "👁 魅魔吞噬！你从对方身上夺取了 {gain} cm，对方损失 {loss} cm！",
            "魅魔之吻吸走了对方的力量！你增长了 {gain} cm！",
        ],
        "win_neg": [
            "👁 魅魔吞噬！你的凹度吸收了对方 {gain} cm！",
        ],
        "devoured_pos": [
            "👁 对方魅魔吞噬了你！{loss} cm 被吸走...当前 {my_len} cm",
            "魅魔之吻降临！你被吸走了 {loss} cm，对方增长了 {gain} cm！",
        ],
        "devoured_neg": [
            "👁 对方魅魔吞噬！你的凹度被吸得更深了...当前 {my_len} cm",
        ],
    },
    {
        "name": "slip",
        "weight": 8,
        "lose_pos": [
            "💨 你脚下一滑！没刺到对方反而伤了自己！-{loss} cm...",
            "手滑了！你的牛牛撞到了墙上，损失 {loss} cm...",
            "一个趔趄！你的击剑动作失误，自损 {loss} cm！",
        ],
        "lose_neg": [
            "💨 你滑倒了！凹牛牛陷得更深了...",
        ],
    },
    {
        "name": "draw",
        "weight": 5,
        "msg": [
            "🤝 双方牛牛旗鼓相当！两败俱伤，各损失 {loss} cm！当前 {my_len} cm",
            "互不相让，双双重伤！你的牛牛损失了 {loss} cm...",
            "势均力敌！双方牛牛都受到了 {loss} cm 的损伤！",
        ],
    },
]

# ── no-niuniu target events (对无牛牛者击剑事件) ───────────────────────

NO_NIUNIU_EVENTS = [
    {
        "name": "reject",
        "weight": 55,
        "msg": [
            "对方还没有牛牛呢！不能击剑！",
            "你对着空气一阵乱刺……对方根本没有牛牛！",
            "击剑？对方连牛牛都没注册，你跟空气击呢？",
            "对方处于无敌状态（没有牛牛），你的击剑无效！",
        ],
    },
    {
        "name": "force_register",
        "weight": 25,
        "msg": [
            "对方被你突如其来的击剑吓到了，慌乱中牛牛长了出来！足足 {oppo_len} cm！",
            "你的剑气唤醒了对方体内的牛牛之力！对方长出了 {oppo_len} cm 的牛牛！",
            "你一剑劈开了对方的牛牛封印！一只 {oppo_len} cm 的牛牛诞生了！",
        ],
    },
    {
        "name": "self_hurt",
        "weight": 20,
        "msg": [
            "你对着空气猛刺一剑，失去平衡摔倒了！牛牛损失 {loss} cm...",
            "目标没有牛牛，你的剑刺空闪到了腰！牛牛缩短了 {loss} cm...",
            "你对着虚空疯狂输出，结果用力过猛，牛牛磨损了 {loss} cm！",
        ],
    },
]

# ── bot fencing messages (与机器人击剑消息) ──────────────────────────────

FENCE_BOT_WIN = [
    "🤖 你竟然战胜了机器人！牛牛增长了 {gain} cm！但机器人毫无波澜，它只是一段代码...",
    "🤖 你击败了机器人守卫！+{gain} cm！机器人默默重启中...",
    "🤖 血肉之躯战胜了钢铁！你的牛牛增长了 {gain} cm！",
]

FENCE_BOT_LOSE = [
    "🤖 你被机器人无情碾压！牛牛损失了 {loss} cm...机器人的牛牛是机械制成的！",
    "🤖 挑战机器人失败！你损失了 {loss} cm！机械牛牛果然更硬？",
    "🤖 机器人使出了精准的机械击剑！你败了，-{loss} cm...",
    "🤖 你被机器人的钢铁牛牛击溃了！损失 {loss} cm...",
]

FENCE_BOT_DRAW = [
    "🤖 你和机器人势均力敌！双方各损失 {loss} cm！当前 {my_len} cm",
    "🤖 机器人和你打成了平手！两败俱伤，你损失了 {loss} cm...",
]


def _normal_fence_event() -> dict:
    """Return the 'normal' fencing event dict."""
    return FENCE_EVENTS[0]
