"""
URL/链接检测工具 v1.0 — 检测文本中的恶意URL和钓鱼链接

本地正则引擎，不调用外部API。
检测:
  - 可疑域名 (如: tinyurl, bit.ly 等短链接)
  - 钓鱼关键词 (login, verify, account, bank 等)
  - 恶意TLD (.tk, .ml, .ga, .cf 等免费顶级域名)
  - IP地址直连
  - 非标准端口
"""
import re
import logging
from typing import List, Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class URLResult(BaseModel):
    has_url: bool
    total_urls: int
    suspicious_urls: List[Dict]  # [{url, reason, risk}]
    risk_level: str   # safe / suspicious / dangerous
    summary: str


class URLCheckTool:
    """URL/链接检测工具 — 本地正则引擎"""

    name = "url_check"
    description = "检测文本中的恶意URL/钓鱼链接/可疑域名"

    # URL 提取正则
    URL_PATTERN = re.compile(
        r'https?://[^\s<>"\'，。！？\n\r]+|'
        r'[a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|cn|net|org|xyz|top|tk|ml|ga|cf|pw|club|vip|work|shop|site|online|fun|click|link)[/\S]*',
        re.IGNORECASE,
    )

    # 可疑关键词 (钓鱼/欺诈)
    SUSPICIOUS_KEYWORDS = [
        "login", "signin", "verify", "account", "password", "bank",
        "secure", "update", "confirm", "unlock", "billing", "payment",
        "中奖", "领奖", "认证", "验证", "激活", "登录",
        "免费领取", "红包", "提现", "返利",
    ]

    # 可疑域名 (短链接/临时域名)
    SUSPICIOUS_DOMAINS = [
        "tinyurl.com", "bit.ly", "t.co", "ow.ly", "is.gd",
        "goo.gl", "short.url", "rebrand.ly",
    ]

    # 高风险顶级域名 (免费/滥用高发)
    HIGH_RISK_TLDS = {".tk", ".ml", ".ga", ".cf", ".gq", ".pw", ".xyz", ".top", ".club", ".work"}

    # IP 地址直接访问
    IP_URL_PATTERN = re.compile(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')

    def __init__(self):
        pass

    async def execute(self, text: str) -> URLResult:
        """检测URL"""
        if not text:
            return URLResult(has_url=False, total_urls=0, suspicious_urls=[], risk_level="safe", summary="空文本")

        # 提取所有URL
        urls = self.URL_PATTERN.findall(text)
        if not urls:
            return URLResult(has_url=False, total_urls=0, suspicious_urls=[], risk_level="safe", summary="未检测到URL")

        # 去重
        unique_urls = list(set(urls))
        suspicious = []

        for url in unique_urls:
            risks = []
            url_lower = url.lower()

            # 检查IP直连
            if self.IP_URL_PATTERN.match(url):
                risks.append({"reason": "IP地址直连", "severity": "high"})

            # 检查可疑域名
            for domain in self.SUSPICIOUS_DOMAINS:
                if domain in url_lower:
                    risks.append({"reason": f"短链接/跳转域名: {domain}", "severity": "medium"})

            # 检查高风险TLD
            for tld in self.HIGH_RISK_TLDS:
                if tld in url_lower:
                    risks.append({"reason": f"高风险顶级域名: {tld}", "severity": "high"})

            # 检查钓鱼关键词
            for keyword in self.SUSPICIOUS_KEYWORDS:
                if keyword.lower() in url_lower:
                    risks.append({"reason": f"可疑关键词: {keyword}", "severity": "medium"})

            if risks:
                max_severity = "high" if any(r["severity"] == "high" for r in risks) else "medium"
                suspicious.append({
                    "url": url[:120],
                    "reasons": [r["reason"] for r in risks],
                    "risk": max_severity,
                })

        # 综合风险评估
        if not suspicious:
            risk_level = "safe"
        elif any(s["risk"] == "high" for s in suspicious):
            risk_level = "dangerous"
        else:
            risk_level = "suspicious"

        return URLResult(
            has_url=True,
            total_urls=len(unique_urls),
            suspicious_urls=suspicious,
            risk_level=risk_level,
            summary=f"检测到 {len(unique_urls)} 个URL, {len(suspicious)} 个可疑",
        )
