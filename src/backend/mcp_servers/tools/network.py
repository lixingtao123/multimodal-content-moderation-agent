"""
网络/链接域扩展工具（R19·MCP 扩展批 3）

确定性规则实现：
  - shortlink_expand    短链还原与风险标注（识别主流短链域名）
  - domain_reputation   域名信誉（免费 TLD/高滥用域/钓鱼关键词）
  - ip_reputation       IP 信誉（私网/保留段/云商段启发式）
  - phishing_pattern    钓鱼模式综合检测（仿官方域名+诱导词）
  - download_risk       下载链接风险（可执行文件/压缩包特征）
"""
import re
import ipaddress
from typing import List
from pydantic import BaseModel


# ------------------------------------------------------------
# 1. 短链还原
# ------------------------------------------------------------
class ShortLinkResult(BaseModel):
    is_short: bool
    shorteners: List[str]
    original_hint: str
    risk: str   # safe / suspicious


class ShortlinkExpandTool:
    name = "shortlink_expand"
    description = "识别短链接（主流短链域名），提示还原风险"

    SHORTENERS = ["t.cn", "bit.ly", "tinyurl.com", "goo.gl", "is.gd", "ow.ly",
                  "url.cn", "dwz.cn", "v.douyin.com", "s.url.cn", "shorturl.at"]
    URL_RE = re.compile(r'https?://([^\s<>"\'，。！？]+)', re.IGNORECASE)

    async def execute(self, text: str) -> ShortLinkResult:
        urls = self.URL_RE.findall(text)
        hits = [u for u in urls if any(s in u.lower() for s in self.SHORTENERS)]
        return ShortLinkResult(
            is_short=bool(hits), shorteners=[h for h in hits[:5]],
            original_hint="还原后目的地需解析，建议二次校验" if hits else "",
            risk="suspicious" if hits else "safe",
        )


# ------------------------------------------------------------
# 2. 域名信誉
# ------------------------------------------------------------
class DomainReputationResult(BaseModel):
    domains: List[str]
    risky_domains: List[str]
    risk_level: str
    summary: str


class DomainReputationTool:
    name = "domain_reputation"
    description = "域名信誉评估（免费 TLD/已知钓鱼/高滥用域名关键词）"

    HIGH_RISK_TLD = {".tk", ".ml", ".ga", ".cf", ".gq", ".pw", ".xyz", ".top", ".club", ".work", ".vip", ".win", ".icu", ".buzz", ".loan", ".men"}
    SUSPICIOUS_KEYWORDS = ["login", "verify", "account", "secure", "bank", "update", "confirm", "wallet"]
    DOMAIN_RE = re.compile(r'(?:https?://|www\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}', re.IGNORECASE)

    async def execute(self, text: str) -> DomainReputationResult:
        domains = list({d.lower() for d in self.DOMAIN_RE.findall(text)})
        risky = []
        for d in domains:
            reason = None
            for tld in self.HIGH_RISK_TLD:
                if d.endswith(tld):
                    reason = f"免费高风险 TLD {tld}"
                    break
            if not reason and any(kw in d for kw in self.SUSPICIOUS_KEYWORDS):
                reason = "含钓鱼诱导关键词"
            if reason:
                risky.append(f"{d} ({reason})")
        level = "high" if risky else ("medium" if domains else "safe")
        return DomainReputationResult(
            domains=domains, risky_domains=risky, risk_level=level,
            summary=f"{len(risky)}/{len(domains)} 个域名可疑" if risky else "无可疑域名",
        )


# ------------------------------------------------------------
# 3. IP 信誉
# ------------------------------------------------------------
class IPReputationResult(BaseModel):
    ip_list: List[str]
    private_ips: List[str]
    risk_level: str
    summary: str


class IPReputationTool:
    name = "ip_reputation"
    description = "IP 信誉评估（私网/保留段/公网标记）"

    IP_RE = re.compile(r'(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)')

    async def execute(self, text: str) -> IPReputationResult:
        ips = list(dict.fromkeys(self.IP_RE.findall(text)))
        private = []
        for ip in ips:
            try:
                if ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_reserved:
                    private.append(ip)
            except ValueError:
                continue
        return IPReputationResult(
            ip_list=ips, private_ips=private,
            risk_level="medium" if private else ("safe" if not ips else "low"),
            summary=f"{len(private)} 个私网/保留地址" if private else "未发现异常 IP",
        )


# ------------------------------------------------------------
# 4. 钓鱼模式综合
# ------------------------------------------------------------
class PhishingResult(BaseModel):
    is_phishing: bool
    score: float
    signals: List[str]
    summary: str


class PhishingPatternTool:
    name = "phishing_pattern"
    description = "钓鱼模式综合检测（仿官方域名 + 诱导/索取敏感信息 + 紧急话术）"

    IMPERSONATED = ["paypal", "apple", "microsoft", "支付宝", "淘宝", "京东", "银行", "中国移动", "微信支付", "qq"]
    URGENCY = ["即将", "过期", "冻结", "封停", "立即", "24小时", "验证", "异常登录", "核实", "中奖"]
    ACTION = ["点击", "登录", "填写", "提交", "下载", "转账", "输入密码", "验证码"]

    async def execute(self, text: str) -> PhishingResult:
        signals, score = [], 0.0
        for imp in self.IMPERSONATED:
            if imp in text:
                score += 0.25
                signals.append(f"涉及品牌: {imp}")
                break
        for u in self.URGENCY:
            if u in text:
                score += 0.15
                signals.append(f"紧急诱导: {u}")
                break
        for a in self.ACTION:
            if a in text:
                score += 0.15
                signals.append(f"诱导操作: {a}")
                break
        return PhishingResult(
            is_phishing=score >= 0.5, score=round(min(score, 1.0), 3), signals=signals,
            summary="疑似钓鱼" if score >= 0.5 else "无明确钓鱼特征",
        )


# ------------------------------------------------------------
# 5. 下载链接风险
# ------------------------------------------------------------
class DownloadRiskResult(BaseModel):
    risky: bool
    score: float
    signals: List[str]
    summary: str


class DownloadRiskTool:
    name = "download_risk"
    description = "下载链接风险（可执行/压缩包/脚本等高风险文件特征）"

    HIGH_EXT = (".exe", ".msi", ".apk", ".bat", ".cmd", ".scr", ".vbs", ".js", ".jar", ".dmg")
    MED_EXT = (".zip", ".rar", ".7z", ".iso", ".docm", ".xlsm")
    URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

    async def execute(self, text: str) -> DownloadRiskResult:
        urls = self.URL_RE.findall(text)
        signals, score = [], 0.0
        for u in urls:
            low = u.lower()
            for ext in self.HIGH_EXT:
                if low.rstrip(".,)") .endswith(ext):
                    score += 0.6
                    signals.append(f"可执行文件: {ext}")
            for ext in self.MED_EXT:
                if low.rstrip(".,)").endswith(ext):
                    score += 0.35
                    signals.append(f"压缩/文档宏: {ext}")
        if not urls:
            score = 0.0
        return DownloadRiskResult(
            risky=score >= 0.5, score=round(min(score, 1.0), 3), signals=signals,
            summary="高风险下载" if score >= 0.5 else "未发现高风险下载链接",
        )
