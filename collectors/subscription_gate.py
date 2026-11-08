"""Offline full-response gate for future captures. No I/O or network requests.

Offsets refer to raw bytes decoded as UTF-8, with CRLF and entities unchanged.
This is a known subscription-lock detector, not a universal access-wall detector.
"""
import hashlib
import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}
LOCK_CLASSES = {"subscription__lock", "series__lock", "article__paywall"}
BODY_MESSAGES = {
    "订阅栏目查看完整内容", "本文为付费内容", "本文為付費內容",
    "本文仅限少数派会员阅读", "购买后可阅读全文", "購買後可閱讀全文",
    "开通会员后阅读全文", "加入会员阅读全文", "登录后阅读全文",
    "请登录后查看全文", "登录后继续阅读", "登入後閱讀全文",
}


class SubscriptionLockDetected(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__("FULL_PAGE_SUBSCRIPTION_LOCK_NO_RETRY")


class _Page(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.lines = [0] + [m.end() for m in re.finditer("\n", source)]
        self.stack = []
        self.hits = []

    def raw_position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set(a.get("class", "").split())
        parent = self.stack[-1] if self.stack else None
        hidden = ("hidden" in a or a.get("aria-hidden", "").lower() == "true"
                  or re.search(r"(?:^|;)\s*display\s*:\s*none\b", a.get("style", ""), re.I))
        ignored = bool(hidden or tag in {"script", "style", "template", "pre", "code"}
                       or (parent and parent["ignored"]))
        node = {"tag": tag, "start": self.raw_position(),
                "opening_end": self.raw_position() + len(self.get_starttag_text()),
                "body": "article-body" in classes or bool(parent and parent["body"]),
                "lock": sorted(classes & LOCK_CLASSES), "ignored": ignored,
                "text": []}
        if not ignored and node["lock"]:
            self.hits.append({"reason": "VISIBLE_KNOWN_LOCK_CONTAINER",
                              "start": node["start"], "end": node["opening_end"],
                              "lock_classes": node["lock"]})
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, text):
        if self.stack and not self.stack[-1]["ignored"]:
            for node in self.stack:
                if node["body"] and not node["ignored"]:
                    node["text"].append(text)

    def handle_endtag(self, tag):
        indexes = [i for i, node in enumerate(self.stack) if node["tag"] == tag]
        if not indexes:
            return
        index = indexes[-1]
        node = self.stack[index]
        if node["body"] and not node["ignored"]:
            message = re.sub(r"\s+", "", "".join(node["text"])).strip("。！!：:")
            if message in BODY_MESSAGES:
                self.hits.append({"reason": "STANDALONE_ARTICLE_BODY_ACCESS_MESSAGE",
                                  "start": node["start"],
                                  "end": self.raw_position() + len("</" + tag + ">"),
                                  "message": message})
        del self.stack[index:]


def detect_subscription_lock(raw_html: bytes) -> dict:
    """Check the ENTIRE HTML response, never only article-body text.

    A known visible lock container anywhere blocks; a standalone access message
    in article-body also blocks. Ordinary subscribe navigation, product purchase
    links, free-trial labels, code examples and script strings do not suffice.
    Decode errors propagate: callers must stop rather than treat errors as clear.
    """
    source = raw_html.decode("utf-8", errors="strict")
    parser = _Page(source)
    parser.feed(source)
    parser.close()
    hits = []
    for hit in parser.hits:
        quote = source[hit["start"]:hit["end"]]
        hits.append({**hit, "quote": quote,
                     "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest()})
    return {"blocked": bool(hits), "reason": "SUBSCRIPTION_LOCK" if hits else None,
            "source_sha256": hashlib.sha256(raw_html).hexdigest(),
            "coordinate": "raw UTF-8 Unicode 0-based [start,end); no newline normalization",
            "evidence": hits,
            "clear_means": "NO_KNOWN_LOCK_DETECTED_NOT_FULL_BODY_OR_QUALITY_APPROVAL"}


def assert_no_subscription_lock(raw_html: bytes) -> dict:
    """Raise before extraction/another GET; batch caller must persist STOP and break."""
    result = detect_subscription_lock(raw_html)
    if result["blocked"]:
        raise SubscriptionLockDetected(result)
    return result
