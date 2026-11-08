"""Publisher-native parsers vendored from the previously validated body161/body165 captures.

Only the parsers and publication-date evidence helper are reused. No source captures,
article text, credentials, or original capture paths are included.
"""
from __future__ import annotations
import html
import json
import re
import urllib.parse
from html.parser import HTMLParser
from .subscription_gate import assert_no_subscription_lock

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK = {"address", "article", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "figure", "h1", "h2", "h3", "h4", "hr", "li", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul"}
SKIP = {"script", "style", "noscript", "template"}
MEDIA = {"img", "picture", "video", "audio", "source", "iframe", "embed", "object", "track"}

class SSPaiParser(HTMLParser):
    """Extract first closed div.article-body, retaining text whitespace verbatim."""

    def __init__(self, requested_url):
        super().__init__(convert_charrefs=True)
        self.requested_url = requested_url
        self._line_offsets = [0]
        self._text_len = 0
        self.found = False
        self.closed = False
        self.outer_tag = None
        self.stack = []
        self.skip_stack = []
        self.parts = []
        self.outer_start = self.inner_start = self.closing_start = self.outer_end = None
        self.inner_html = None
        self.media_refs = []
        self.canonical = []
        self.og_url = []
        self.og_title = []
        self.h1 = []
        self.document_titles = []
        self.meta_author = []
        self.published_meta = []
        self.modified_meta = []
        self.time_values = []
        self.jsonld_raw = []
        self._jsonld = None
        self._text_captures = []
        self.header_author_text = []
        self.header_date_text = []
        self.reading_time_text = []

    def _offset(self):
        line, col = self.getpos()
        while len(self._line_offsets) < line:
            self._line_offsets.append(self._text_len)
        return self._line_offsets[line - 1] + col

    def feed(self, data):
        self._line_offsets = [0]
        offset = 0
        for part in data.splitlines(keepends=True):
            offset += len(part)
            self._line_offsets.append(offset)
        self._text_len = len(data)
        return super().feed(data)

    def _start_capture(self, tag, classes):
        if tag in {"h1", "title"}:
            self._text_captures.append({"kind": tag, "tag": tag, "parts": []})
        if "article__header__author" in classes:
            self._text_captures.append({"kind": "visible_author_header", "tag": tag, "parts": []})
        if "article__header__date" in classes:
            self._text_captures.append({"kind": "visible_header_date", "tag": tag, "parts": []})
        if "article__header__reading-time" in classes:
            self._text_captures.append({"kind": "reading_time", "tag": tag, "parts": []})

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        rel = set((attrs.get("rel") or "").lower().split())
        raw_tag = self.get_starttag_text() or ""
        pos = self._offset()

        if tag == "link" and "canonical" in rel and attrs.get("href"):
            self.canonical.append(attrs["href"])
        if tag == "meta":
            prop = (attrs.get("property") or "").lower()
            name = (attrs.get("name") or "").lower()
            if prop == "og:url" and attrs.get("content"):
                self.og_url.append(attrs["content"])
            if prop == "og:title" and attrs.get("content"):
                self.og_title.append(attrs["content"])
            if prop == "article:published_time" and attrs.get("content"):
                self.published_meta.append({"source": "meta[property=article:published_time]", "value": attrs["content"]})
            if prop == "article:modified_time" and attrs.get("content"):
                self.modified_meta.append({"source": "meta[property=article:modified_time]", "value": attrs["content"]})
            if name == "author" and attrs.get("content"):
                self.meta_author.append(attrs["content"])
        if tag == "time" and attrs.get("datetime"):
            self.time_values.append({"source": "time[datetime]", "value": attrs["datetime"]})
        if tag == "script" and "application/ld+json" in (attrs.get("type") or "").lower():
            self._jsonld = []

        self._start_capture(tag, classes)
        if not self.found and tag == "div" and "article-body" in classes:
            self.found = True
            self.outer_tag = tag
            self.stack = [tag]
            self.outer_start = pos
            self.inner_start = pos + len(raw_tag)
            return

        inside = self.found and not self.closed and bool(self.stack)
        if inside:
            if tag in MEDIA:
                values = {k: attrs[k] for k in ("src", "data-src", "srcset", "poster", "data-original", "alt", "title", "type") if attrs.get(k)}
                if values:
                    self.media_refs.append({"position": len(self.media_refs) + 1, "tag": tag, "attributes": values})
            if tag in BLOCK and not self.skip_stack:
                self.parts.append("\n")
            if tag in SKIP:
                self.skip_stack.append(tag)
            if tag not in VOID:
                self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        pos = self._offset()
        if self._jsonld is not None and tag == "script":
            self.jsonld_raw.append("".join(self._jsonld))
            self._jsonld = None

        for i in range(len(self._text_captures) - 1, -1, -1):
            cap = self._text_captures[i]
            if cap["tag"] == tag:
                value = "".join(cap["parts"])
                if value.strip():
                    if cap["kind"] == "h1":
                        self.h1.append(value)
                    elif cap["kind"] == "title":
                        self.document_titles.append(value)
                    elif cap["kind"] == "visible_author_header":
                        self.header_author_text.append(value)
                    elif cap["kind"] == "visible_header_date":
                        self.header_date_text.append(value)
                    elif cap["kind"] == "reading_time":
                        self.reading_time_text.append(value)
                del self._text_captures[i:]
                break

        if not self.found or self.closed or not self.stack:
            return
        if tag in BLOCK and not self.skip_stack:
            self.parts.append("\n")
        if tag in self.skip_stack:
            for i in range(len(self.skip_stack) - 1, -1, -1):
                if self.skip_stack[i] == tag:
                    del self.skip_stack[i:]
                    break
        if tag in self.stack:
            idx = len(self.stack) - 1 - self.stack[::-1].index(tag)
            if idx == 0 and tag == self.outer_tag:
                self.closed = True
                self.closing_start = pos
                self.outer_end = pos + len(f"</{tag}>")
                self.stack = []
            else:
                del self.stack[idx:]

    def handle_data(self, data):
        if self._jsonld is not None:
            self._jsonld.append(data)
        for cap in self._text_captures:
            cap["parts"].append(data)
        if self.found and not self.closed and self.stack and not self.skip_stack:
            self.parts.append(data)

    def metadata(self):
        nodes = []

        def walk(value):
            if isinstance(value, dict):
                nodes.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for raw in self.jsonld_raw:
            try:
                walk(json.loads(raw))
            except Exception:
                pass
        date_published, date_modified, authors, headlines = [], [], [], []
        for node in nodes:
            if node.get("datePublished"):
                date_published.append({"source": "JSON-LD datePublished", "value": node["datePublished"]})
            if node.get("dateModified"):
                date_modified.append({"source": "JSON-LD dateModified", "value": node["dateModified"]})
            if node.get("author"):
                authors.extend(node["author"] if isinstance(node["author"], list) else [node["author"]])
            if node.get("headline"):
                headlines.append(node["headline"])
        evidence = self.published_meta + date_published + self.time_values
        canonical = self.canonical[0] if self.canonical else (self.og_url[0] if self.og_url else None)
        return {
            "canonical_raw": canonical,
            "canonical_evidence": self.canonical,
            "og_url_evidence": self.og_url,
            "og_title_evidence": self.og_title,
            "title_evidence": {"h1": self.h1, "document_title": self.document_titles, "jsonld_headline": headlines},
            "author_evidence": {"meta_author": self.meta_author, "visible_author_header_text": self.header_author_text, "jsonld_author": authors},
            "visible_header_date_text": self.header_date_text,
            "reading_time_text": self.reading_time_text,
            "published_time_evidence": evidence,
            "modified_time_evidence": self.modified_meta + date_modified,
        }

class EntryParser(HTMLParser):
    def __init__(self,requested_url):
        super().__init__(convert_charrefs=True);self.requested_url=requested_url;self.lines=[0];self.text_length=0
        self.found=False;self.closed=False;self.outer_tag=None;self.open_tags=[];self.skip_stack=[];self.parts=[];self.media_refs=[]
        self.canonical=[];self.og_url=[];self.og_title=[];self.meta_author=[];self.published_meta=[];self.meta_modified=[];self.time_values=[]
        self.h1_values=[];self.title_values=[];self.author_links=[];self.author_class_values=[];self._captures=[];self._author_link=None;self._author_class=None;self._jsonld_current=None;self.jsonld_blocks=[]
        self.outer_start_char=None;self.inner_start_char=None;self.outer_end_char_exclusive=None
    def _offset(self):
        line,col=self.getpos()
        while len(self.lines)<line:self.lines.append(self.text_length)
        return self.lines[line-1]+col
    def feed(self,data):
        self.lines=[0];self.text_length=len(data);pos=0
        for part in data.splitlines(keepends=True):pos+=len(part);self.lines.append(pos)
        return super().feed(data)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);pos=self._offset();rawtag=self.get_starttag_text() or '';classes=set((a.get('class') or '').split());rel=set((a.get('rel') or '').lower().split())
        if tag=='link' and 'canonical' in rel and a.get('href'):self.canonical.append(a['href'])
        if tag=='meta':
            prop=(a.get('property') or '').lower();name=(a.get('name') or '').lower()
            if prop=='og:url' and a.get('content'):self.og_url.append(a['content'])
            if prop=='og:title' and a.get('content'):self.og_title.append(a['content'])
            if prop=='article:published_time' and a.get('content'):self.published_meta.append({'source':'meta[property=article:published_time]','value':a['content']})
            if prop=='article:modified_time' and a.get('content'):self.meta_modified.append({'source':'meta[property=article:modified_time]','value':a['content']})
            if name=='author' and a.get('content'):self.meta_author.append(a['content'])
        if tag=='time' and a.get('datetime'):self.time_values.append({'source':'time[datetime]','value':a['datetime']})
        if tag=='script' and 'application/ld+json' in (a.get('type') or '').lower():self._jsonld_current={'raw':[],'source':'script[type=application/ld+json]'}
        if 'entry-content' in classes and not self.found:
            self.found=True;self.outer_tag=tag;self.open_tags=[tag];self.outer_start_char=pos;self.inner_start_char=pos+len(rawtag);return
        inside=self.found and not self.closed and bool(self.open_tags)
        if inside:
            if tag in MEDIA:
                keep={k:a[k] for k in ('src','data-src','srcset','poster','data-original','alt','title','type') if a.get(k)}
                if keep:self.media_refs.append({'position':len(self.media_refs)+1,'element':tag,'attributes':keep,'resolved_urls':{k:urllib.parse.urljoin(self.requested_url,v) for k,v in keep.items() if k in ('src','data-src','poster','data-original') and not v.startswith('data:')}})
            if tag in BLOCK and not self.skip_stack:self.parts.append('\n')
            if tag in SKIP:self.skip_stack.append(tag)
            if tag not in VOID:self.open_tags.append(tag)
        if tag in ('h1','title'):self._captures.append({'tag':tag,'parts':[]})
        if 'author' in classes or 'byline' in classes or 'post-author' in classes:self._author_class={'tag':tag,'parts':[]}
        if tag=='a' and 'author' in rel:self._author_link={'tag':tag,'parts':[],'href':a.get('href')}
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        pos=self._offset()
        if self._jsonld_current is not None and tag=='script':self.jsonld_blocks.append(''.join(self._jsonld_current['raw']));self._jsonld_current=None
        if self._author_link is not None and tag==self._author_link['tag']:
            self.author_links.append({'text':''.join(self._author_link['parts']).strip(),'href':self._author_link.get('href')});self._author_link=None
        if self._author_class is not None and tag==self._author_class['tag']:
            val=''.join(self._author_class['parts']).strip()
            if val:self.author_class_values.append(val)
            self._author_class=None
        for i in range(len(self._captures)-1,-1,-1):
            if self._captures[i]['tag']==tag:
                cap=self._captures.pop(i);val=''.join(cap['parts']).strip()
                if tag=='h1' and val:self.h1_values.append(val)
                if tag=='title' and val:self.title_values.append(val)
                break
        if not self.found or self.closed or not self.open_tags:return
        if tag in BLOCK and not self.skip_stack:self.parts.append('\n')
        if tag in self.skip_stack:
            for i in range(len(self.skip_stack)-1,-1,-1):
                if self.skip_stack[i]==tag:del self.skip_stack[i:];break
        if tag in self.open_tags:
            idx=len(self.open_tags)-1-self.open_tags[::-1].index(tag)
            if idx==0 and tag==self.outer_tag:
                self.open_tags=[];self.closed=True;self.outer_end_char_exclusive=pos+len('</'+tag+'>')
            else:del self.open_tags[idx:]
    def handle_data(self,data):
        if self._jsonld_current is not None:self._jsonld_current['raw'].append(data)
        for cap in self._captures:cap['parts'].append(data)
        if self._author_link is not None:self._author_link['parts'].append(data)
        if self._author_class is not None:self._author_class['parts'].append(data)
        if self.found and not self.closed and self.open_tags and not self.skip_stack:self.parts.append(data)
    def metadata(self):
        nodes=[]
        def walk(v):
            if isinstance(v,dict):
                nodes.append(v)
                for z in v.values():walk(z)
            elif isinstance(v,list):
                for z in v:walk(z)
        for raw in self.jsonld_blocks:
            try:walk(json.loads(raw))
            except Exception:pass
        pub=[];authors=[];headlines=[]
        for z in nodes:
            if z.get('datePublished'):pub.append({'source':'JSON-LD datePublished','value':z['datePublished']})
            if z.get('author'):
                authors.extend(z['author'] if isinstance(z['author'],list) else [z['author']])
            if z.get('headline'):headlines.append(z['headline'])
        evidence=self.published_meta+pub+self.time_values
        return {'primary_published_time':evidence[0] if evidence else None,'published_time_evidence':evidence,'modified_time_evidence':self.meta_modified,'canonical':self.canonical[0] if self.canonical else None,'canonical_evidence':self.canonical,'og_url':self.og_url[0] if self.og_url else None,'og_title':self.og_title,'title_evidence':{'h1':self.h1_values,'document_title':self.title_values,'jsonld_headline':headlines},'author_evidence':{'meta_author':self.meta_author,'visible_rel_author':self.author_links,'author_class_text':self.author_class_values,'jsonld_author':authors}}

def publication_from_page(source, meta):
    # The old parser's generic time list is retained as evidence but is not
    # automatically considered publication (a time can describe an update).
    pubs = [x for x in meta['published_time_evidence']
            if x['source'] != 'time[datetime]']
    times = []
    for match in re.finditer(r'<time\b([^>]*)>(.*?)</time>', source, re.S | re.I):
        attrs, visible = match.group(1), html.unescape(re.sub('<[^>]+>', '', match.group(2))).strip()
        dt = re.search(r'\bdatetime\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
        published = bool(re.search(r'\bitemprop\s*=\s*["\']datePublished["\']', attrs, re.I)
                         or re.search(r'\bclass\s*=\s*["\'][^"\']*\bpublished\b', attrs, re.I))
        updated = bool(re.search(r'\bupdated\b|dateModified', attrs, re.I))
        item = {'source': 'original page time', 'datetime': html.unescape(dt.group(1)) if dt else None,
                'visible': visible, 'semantic': 'published' if published and not updated else 'modified' if updated else 'UNKNOWN',
                'start': match.start(), 'end': match.end(), 'quote': match.group()}
        times.append(item)
        if item['semantic'] == 'published' and (item['datetime'] or visible):
            pubs.append({'source': 'original page time marked published',
                         'value': item['datetime'] or visible})
    return {'primary': pubs[0] if pubs else None, 'publication_evidence': pubs,
            'all_original_page_times': times, 'modified_evidence': meta['modified_time_evidence'],
            'unknown_if_absent': True, 'index_updated_used_as_publication': False}

SUPPORTED = {"appinn.com": "appinn", "sspai.com": "sspai"}

def source_family(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or p.username or p.password:
        raise ValueError("只接受 HTTPS 且无凭据的公开来源 URL")
    family = SUPPORTED.get(host.removeprefix("www."))
    if family is None:
        raise ValueError("来源只支持 Appinn 与 SSPai 的公开页面")
    if family == "sspai" and not re.fullmatch(r"/post/[0-9]+/?", p.path):
        raise ValueError("SSPai正文URL必须是稳定 /post/<数字ID> 路径")
    if family == "appinn" and p.path in {"", "/"}:
        raise ValueError("Appinn首页不能作为正文候选")
    return family

def parse_page(url: str, raw: bytes) -> dict:
    """Guard the complete response before parsing a known closed content root."""
    family = source_family(url)
    guard = assert_no_subscription_lock(raw)
    source = raw.decode("utf-8", errors="strict")
    if family == "appinn":
        parser = EntryParser(url)
        parser.feed(source)
        if not parser.found or not parser.closed or parser.outer_tag != "div":
            raise ValueError("Appinn div.entry-content 未完整闭合")
        meta = parser.metadata()
        date = publication_from_page(source, meta)
        title_values = meta["title_evidence"]["h1"] or meta["title_evidence"]["document_title"]
        authors = meta["author_evidence"]
        body = "".join(parser.parts)
        root_range = [parser.outer_start_char, parser.outer_end_char_exclusive]
        media = parser.media_refs
        canonical = meta["canonical"] or meta["og_url"]
        published = date["primary"]["value"] if date["primary"] else None
        publication_evidence = date
    else:
        parser = SSPaiParser(url)
        parser.feed(source)
        if not parser.found or not parser.closed or parser.outer_tag != "div":
            raise ValueError("SSPai div.article-body 未完整闭合")
        meta = parser.metadata()
        body = "".join(parser.parts)
        title_values = meta["title_evidence"]["h1"] or meta["title_evidence"]["document_title"] or meta["title_evidence"]["jsonld_headline"]
        authors = meta["author_evidence"]
        canonical = meta["canonical_raw"]
        root_range = [parser.outer_start, parser.outer_end]
        media = parser.media_refs
        # Generic <time datetime> is retained as evidence but not promoted to publication.
        reliable = [x for x in meta["published_time_evidence"] if x["source"] != "time[datetime]"]
        published = reliable[0]["value"] if reliable else None
        publication_evidence = {"primary": ({"source": reliable[0]["source"], "value": published} if reliable else None),
                                "all_published_candidates": reliable,
                                "modified_time_evidence": meta["modified_time_evidence"],
                                "visible_header_date_text": meta["visible_header_date_text"],
                                "unknown_if_absent": True}
    if not body.strip():
        raise ValueError("闭合正文容器为空")
    canonical_url = urllib.parse.urljoin(url, canonical) if canonical else None
    if canonical_url and source_family(canonical_url) != family:
        raise ValueError("canonical 指向其他来源，停止人工核验身份")
    canonical_title = title_values[0].strip() if title_values else None
    return {"publisher": family, "requested_url": url, "canonical_url": canonical_url,
            "title": canonical_title, "title_evidence": meta["title_evidence"],
            "author_evidence": authors, "published_at": published,
            "publication_evidence": publication_evidence, "body_text": body,
            "body_container": "div.entry-content" if family == "appinn" else "div.article-body",
            "body_container_char_range": root_range, "body_chars": len(body),
            "media_references_not_downloaded": media,
            "full_page_guard": guard, "qualification": "PENDING_INDEPENDENT_REVIEW"}

def parser_self_check() -> dict:
    appinn_html = ('<html><head><meta property="article:published_time" content="2026-01-02T03:04:05Z">'
                   '<link rel="canonical" href="https://www.appinn.com/sample/">'
                   '<script type="application/ld+json">{"author":{"name":"Synthetic Author"}}</script></head>'
                   '<body><h1>合成测试标题</h1><div class="entry-content"><p>alpha &amp; beta</p>'
                   '<pre>  keep indent</pre><img src="/fake.png" alt="sample"><script>ignored()</script>'
                   '</div><p>outside</p></body></html>').encode()
    sspai_html = ('<html><head><link rel="canonical" href="https://sspai.com/post/99">'
                  '<script type="application/ld+json">{"@type":"Article","datePublished":"2026-01-02T03:04:05Z","author":{"name":"Synthetic Author"}}</script>'
                  '</head><body><h1>合成测试标题</h1><div class="article-body"><p>正文 &amp; 实体</p>'
                  '<pre><code>第一行\r\n  缩进代码\r\n</code></pre><img src="/fake.png">'
                  '<script>ignored()</script></div><p>outside</p></body></html>').encode()
    a=parse_page('https://www.appinn.com/sample/', appinn_html)
    s=parse_page('https://sspai.com/post/99', sspai_html)
    assert a["title"] == "合成测试标题" and a["published_at"] == "2026-01-02T03:04:05Z"
    assert "alpha & beta" in a["body_text"] and "outside" not in a["body_text"] and len(a["media_references_not_downloaded"]) == 1
    assert s["title"] == "合成测试标题" and s["published_at"] == "2026-01-02T03:04:05Z"
    assert "正文 & 实体" in s["body_text"] and "outside" not in s["body_text"]
    paywall='<html><div class="subscription__lock">本文为付费内容</div><div class="article-body">x</div></html>'.encode()
    try: parse_page('https://sspai.com/post/100', paywall)
    except Exception as exc:
        from .subscription_gate import SubscriptionLockDetected
        assert isinstance(exc, SubscriptionLockDetected)
    else: raise AssertionError("full-response subscription lock not blocked")
    return {"passed":True,"network_requests":0,"adapters":["appinn","sspai"],"guard_before_parser":True}
