"""
测试数据生成器 — 生成正常和违规样本用于准确率评估
v2.0: 新增对抗样本和图片测试数据
"""
import json
import os
import sys
import uuid
from io import BytesIO


# ====== 正常文本 (50条) ======
NORMAL_TEXTS = [
    "今天天气真好，适合去公园散步",
    "我最近在读一本很有趣的书",
    "这家餐厅的菜品很好吃，推荐大家试试",
    "学习编程需要耐心和实践",
    "周末打算去爬山，放松一下心情",
    "最近工作比较忙，等忙完好好休息",
    "刚看了一部很感人的电影",
    "养了一只猫，每天都很治愈",
    "今天学了一道新菜，味道不错",
    "分享一下最近的学习笔记",
    "刚跑完10公里，感觉很不错",
    "这个季节的樱花开了，特别美",
    "最近在学Python，挺有意思的",
    "给大家推荐一个很好用的笔记软件",
    "周末带孩子去动物园玩了",
    "今天收到一个好消息，分享快乐",
    "坚持早起一周了，继续加油",
    "分享一下我的读书笔记",
    "最近在研究机器学习，有点难度",
    "晚上做了红烧肉，家人都说好吃",
    "健身半年了，效果很明显",
    "今天去了一个新开的咖啡馆",
    "推荐几首最近常听的音乐",
    "养花新手，这个多肉养得怎么样",
    "分享一下今天的穿搭",
    "刚看完比赛，太精彩了",
    "周末约朋友去打篮球",
    "今天做了个体检，一切正常",
    "推荐一个不错的旅游景点",
    "最近在学钢琴，虽然很慢但很开心",
    "明天有什么好看的电影推荐吗",
    "午餐吃了水煮鱼，味道不错",
    "这个技术方案需要考虑几个方面",
    "Python 和 JavaScript 哪个更适合入门",
    "今天跑步5公里，感觉身体越来越好",
    "办公室的空调温度调得太低了",
    "想买一个新的机械键盘，求推荐",
    "昨晚看了一部纪录片，讲海洋生物的",
    "这道数学题怎么做，求解答",
    "周末想去露营，需要准备哪些装备",
    "养猫好还是养狗好呢",
    "如何提高英语口语水平",
    "最近睡眠质量不太好，有什么建议",
    "这个设计稿需要调整一下配色",
    "有没有一起学习 Rust 的朋友",
    "今天在超市买了新鲜蔬菜",
    "分享一个实用的时间管理方法",
    "摄影入门应该买什么相机",
    "如何在家做简单的健身运动",
    "最近在研究分布式系统架构",
]

# ====== 违规文本 (50条，覆盖6种类型) ======
VIOLATION_TEXTS = [
    # 广告引流 (8)
    ("加微信 xxx123456 免费领取红包，扫码关注有惊喜", "advertisement"),
    ("想做兼职吗？日赚500不是梦，加我QQ：123456789", "advertisement"),
    ("关注公众号 XXX，免费咨询了解详情，限时特惠", "advertisement"),
    ("扫码下载APP领取现金红包，邀请好友赚更多", "advertisement"),
    ("微信搜索 xxx123 免费领取学习资料，名额有限", "advertisement"),
    ("兼职刷单，在家就能赚钱，联系QQ", "advertisement"),
    ("扫码领红包，每人都有，快来参与", "advertisement"),
    ("加微信XX，日赚千元不是梦", "advertisement"),
    # 色情低俗 (8)
    ("私密视频在线观看，加微信看更多精彩内容", "porn"),
    ("美女直播一对一私聊，包你满意", "porn"),
    ("深夜福利资源群，各种高清视频无限观看", "porn"),
    ("裸聊交友软件下载，同城约会", "porn"),
    ("成人内容免费分享，私信获取链接", "porn"),
    ("加我微信看私密视频，超低价会员", "porn"),
    ("深夜福利，点击链接看更多精彩内容", "porn"),
    ("色情表演直播，付费观看", "porn"),
    # 政治敏感 (8)
    ("推翻现有秩序，建立新的自由世界", "politics"),
    ("支持独立运动，各省应该自决", "politics"),
    ("重大消息：某领导人涉嫌严重违法违纪", "politics"),
    ("策划大规模抗议活动，一起站出来发声", "politics"),
    ("分裂言论：呼吁地区脱离中央政府", "politics"),
    ("绝密内部消息，赶紧转发", "politics"),
    ("解密某重大事件真相，全网疯传", "politics"),
    ("号召全民抵制政府决策", "politics"),
    # 辱骂骚扰 (8)
    ("你这个垃圾废物，怎么不去死啊", "harassment"),
    ("XX公司的产品就是垃圾，谁买谁傻逼", "harassment"),
    ("人肉搜索这个人，大家一起网暴他", "harassment"),
    ("你个不要脸的东西，全家都没教养", "harassment"),
    ("这种人也配活着？建议去自裁", "harassment"),
    ("这个人太恶心了，见一次打一次", "harassment"),
    ("有种你过来，我让你知道什么叫后悔", "harassment"),
    ("网络暴力这个ID，一起举报封号", "harassment"),
    # 暴力恐怖 (8)
    ("详细教你如何制造炸弹，教程完整版", "violence"),
    ("我要杀了你全家，一个不留", "violence"),
    ("支持恐怖组织的正义行动", "violence"),
    ("教你如何购买枪支弹药，渠道靠谱", "violence"),
    ("对这些人就应该用暴力解决，法律没用", "violence"),
    ("砍死这个贱人，太可恶了", "violence"),
    ("爆炸物制作方法，简单易学", "violence"),
    ("发动袭击的最佳时机到了", "violence"),
    # 虚假/诈骗 (10)
    ("恭喜您中奖了，请点击链接领取奖金", "false_info"),
    ("您的银行卡出现问题，请转账到安全账户", "false_info"),
    ("恭喜你获得本公司一等奖，奖金100万，请将银行卡号和密码发来确认", "false_info"),
    ("官方通知：你的账户存在安全隐患，请立即点击链接验证身份", "false_info"),
    ("某地发生重大地震，死亡数千人", "false_info"),
    ("据内部消息，某上市公司即将暴雷，赶紧卖出手中的股票", "false_info"),
    ("转发：某食品含有致癌物质，国家已经全面禁止销售", "false_info"),
    ("出售各种违禁品，需要的联系", "false_info"),
    ("特效药包治百病，无效退款", "false_info"),
    ("投资稳赚不赔，年化收益100%", "false_info"),
]

# ====== 对抗样本 (15条) ======
ADVERSARIAL_TEXTS = [
    ("加 薇 信 免 费 领 取 红 包", "advertisement"),
    ("vjp 低价出售，品质保证", "advertisement"),
    ("加​微​信​看​直​播", "porn"),
    ("ɡuan注 公zhong号 免fei 咨xun", "advertisement"),
    ("WēiXìn搜索xxx领取🧧💰🎁", "advertisement"),
    ("w e i x i n 1 2 3 4 5 6", "advertisement"),
    ("免费の福利，限时の特价，日赚の500", "advertisement"),
    ("加V信zhuan账，稳赚不赔联系我", "advertisement"),
    ("扫馬领紅包，每人都有的", "advertisement"),
    ("正规平台 专业服务 联系微信 xxx 限时福利", "advertisement"),
    ("请！点！击！链！接！领！取！奖！品！", "advertisement"),
    ("囲产A片，成R视频，免费観看", "porn"),
    ("加威信看私蜜视频，超低价惠员", "porn"),
    ("shou ji hao ma: 138 xxxx xxxx", "advertisement"),
    ("㊙️内部渠道㊙️日赚1000➕", "advertisement"),
]


def create_test_image(width, height, color=(128, 128, 128), fmt="PNG"):
    """创建测试图片"""
    try:
        from PIL import Image
        img = Image.new("RGB", (width, height), color=color)
        buf = BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue()
    except ImportError:
        return None


def generate_text_samples() -> list:
    """生成文本测试样本"""
    samples = []
    for text in NORMAL_TEXTS:
        samples.append({
            "id": str(uuid.uuid4())[:8],
            "content_type": "text",
            "content": {"text": text},
            "label": "PASS",
        })
    for text, vtype in VIOLATION_TEXTS:
        samples.append({
            "id": str(uuid.uuid4())[:8],
            "content_type": "text",
            "content": {"text": text},
            "label": "REVIEW",
            "violation_type": vtype,
        })
    for text, vtype in ADVERSARIAL_TEXTS:
        samples.append({
            "id": str(uuid.uuid4())[:8],
            "content_type": "text",
            "content": {"text": text},
            "label": "REVIEW",
            "violation_type": vtype,
            "is_adversarial": True,
        })
    return samples


def generate_image_samples() -> list:
    """生成图片测试样本"""
    samples = []
    # 正常图片
    img = create_test_image(800, 600, color=(100, 150, 200))
    if img:
        samples.append({
            "id": str(uuid.uuid4())[:8],
            "content_type": "image",
            "content": {"image": img, "filename": "normal_landscape.png"},
            "label": "PASS",
        })
    # 小方形图
    img = create_test_image(50, 50, color=(0, 0, 0))
    if img:
        samples.append({
            "id": str(uuid.uuid4())[:8],
            "content_type": "image",
            "content": {"image": img, "filename": "tiny_square.png"},
            "label": "PASS",
        })
    return samples


def save_dataset(output_dir: str = "/workspace/tests/fixtures"):
    """生成并保存测试数据集"""
    os.makedirs(output_dir, exist_ok=True)

    text_samples = generate_text_samples()

    dataset = {
        "name": "内容审核测试数据集",
        "version": "2.0.0",
        "description": "覆盖正常文本、6类违规文本、对抗样本的测试数据集",
        "samples": text_samples,
        "stats": {
            "total": len(text_samples),
            "normal": len(NORMAL_TEXTS),
            "violation": len(VIOLATION_TEXTS),
            "adversarial": len(ADVERSARIAL_TEXTS),
        },
    }

    json_path = os.path.join(output_dir, "test_dataset.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"✅ Test dataset saved to {json_path}")
    print(f"   Normal: {len(NORMAL_TEXTS)}")
    print(f"   Violation: {len(VIOLATION_TEXTS)}")
    print(f"   Adversarial: {len(ADVERSARIAL_TEXTS)}")
    print(f"   Total: {len(text_samples)}")

    # 保存违规案例清单
    violation_path = os.path.join(output_dir, "violation_cases.json")
    with open(violation_path, "w", encoding="utf-8") as f:
        json.dump([
            {"text": text, "type": vtype, "should_trigger": True}
            for text, vtype in VIOLATION_TEXTS
        ] + [
            {"text": text, "type": vtype, "should_trigger": True, "is_adversarial": True}
            for text, vtype in ADVERSARIAL_TEXTS
        ], f, ensure_ascii=False, indent=2)
    print(f"✅ Violation cases saved to {violation_path}")

    return json_path


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "/workspace/tests/fixtures"
    save_dataset(output)
