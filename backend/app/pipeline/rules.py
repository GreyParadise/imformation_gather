AD_PATTERNS = [
    "广告", "推广", "优惠券", "限时折扣", "秒杀", "抽奖", "点击领取",
    "扫码", "加微信", "加QQ", "代办", "开发票", "博彩", "彩票", "casino",
    "软文", "付费进群", "限时特惠", "低至1折", "招聘专区",
]
MIN_BODY_LEN = 80


def hard_filter(title: str, body: str | None):
    text = (title or "") + " " + (body or "")[:500]
    low = text.lower()
    if not body or len(body) < MIN_BODY_LEN:
        return False, "short_body"
    for p in AD_PATTERNS:
        if p in low:
            return False, "ad"
    return True, None
