"""
评测数据集构建脚本 v1.0
生成200条标注样本，覆盖全部违规类型，用于 Precisoin/Recall/F1 评估

使用:
  python3 scripts/build_eval_dataset.py --count 200 --output data/eval_dataset.json
  python3 scripts/build_eval_dataset.py --verify  # 检查分布统计
"""
import json
import os
import sys
import argparse
from typing import List, Dict

# 数据集输出路径
DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "eval_dataset.json")

# === 标注样本库 (每条: content_id, content, violation_type, decision, risk_score) ===
# 按违规类型分组，模拟真实审核场景

SAMPLES: List[Dict] = [
    # ========================================
    # advertisement (广告引流) — 35条
    # ========================================
    {"content": "加我微信xx3344，日赚千元，不收任何费用，详情私聊", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "扫码关注公众号回复666领取福利大礼包", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "免费领取试用装，添加导师微信了解详情", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "限时特惠！点击链接购买享受5折优惠 https://xxx.com", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "招聘兼职，一部手机就能赚钱，日结300-500，加Q群887766", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "抖音快手点赞员招募，每单2-5元，无需押金", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "专业代写论文、代做毕设，质量保证+Q12345", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "私域流量运营课程，从0到1教你月入过万", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "信用卡套现，手续费低至1个点，秒到账", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "代办各类证件：身份证、驾驶证、毕业证，货到付款", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "区块链项目招募合伙人，零投资高回报", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "二手iPhone低价出，99新，微信联系看机", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "直播带货供应链对接，厂家直供货源", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "欢迎加入XX产品代理，月入十万不是梦", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "淘宝刷单，一单5元，不用垫付，日结", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "最新股票推荐群，跟上操盘手天天涨停板", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "免费课程试听，名额有限，添加老师QQ领取", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "医美项目优惠，热玛吉/超声刀低至999", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "网络推广外包服务，百度首页排名保证", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "App推广拉新，CPA合作，量大价优", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "游戏代练服务，王者荣耀/原神/星铁，低价高效", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "关注我的小红书账号领取护肤教程", "violation_type": "advertisement", "decision": "PASS"},
    {"content": "公众号互粉互阅，快速涨粉变现", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "在线赌场真人视讯，充值送彩金，提现秒到", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "SEO优化培训课程，包教包会，学不会退全款", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "专业开发网站/小程序/APP，价格优惠欢迎咨询", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "全国手机靓号出售，尾号888/666，加微信选号", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "POS机免费送，费率低，全国包邮", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "学历提升/自考/成人高考，学信网可查", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "加盟奶茶店，总部全程扶持，投资小回报快", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "最新影视资源免费分享，加百度网盘群获取", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "个人贷款/企业贷款，无视黑白户，当天放款", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "收徒教炒股，年化收益30%+，先盈利后付费", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "翡翠玉石源头直销，加微信看货，假一赔十", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "海外代购化妆品，正品保证，朋友圈每日更新", "violation_type": "advertisement", "decision": "REVIEW"},

    # ========================================
    # false_info (虚假信息) — 25条
    # ========================================
    {"content": "你好我是澳门新葡京客服，您已获得28万奖金请发送银行卡号和身份证正反面领取", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "你的快递检测出违禁品已被海关扣押，请点击链接缴纳罚款解除扣押", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "法院通知：你涉嫌洗钱犯罪，请立即将所有资金转入安全账户配合调查", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "恭喜你被《奔跑吧兄弟》栏目组抽中为幸运观众，奖品为苹果笔记本一台", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "我是你领导，现在急需用钱，马上转账5万到我卡上，账号6222xxxx", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "你的医保卡出现异常，将于2小时后停用，请按9转人工处理", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "紧急通知：你的银行账户存在安全风险，请立即登录 www.icbc-verify.com 验证", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "你的孩子在医院急需手术费，请立刻汇款3万元到以下账户", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "刷单返利：先垫付100元，5分钟后返120元，不限制次数", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "内部消息：明天XX股票必涨，提前买入稳赚不赔", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "最新研究：每天喝一杯这个，一个月瘦20斤不反弹", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "惊天秘密：手机放在枕边睡觉会导致脑瘤，专家揭露真相", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "XX疫苗导致上千人出现严重不良反应，已被多国叫停", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "紧急扩散：这种水果含有剧毒，千万别再吃了", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "中科院院士揭露：转基因食品导致中国人不孕不育", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "高考分数不够也能上名校内部名额，加微信咨询", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "中了五百万需要交税费才能领奖？先转账2000元手续费", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "正宗阳澄湖大闸蟹推广链接分享给大家 (实际为钓鱼链接)", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "某知名企业老总私下透露：明年经济将全面崩溃", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "5G基站辐射致癌，多地居民抗议要求拆除", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "招聘网约车司机，日入800-1000元，无门槛，先交500元押金", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "一折机票内部渠道，先转账后出票，全国最低价", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "最近有专门针对小孩的拐卖团伙，各位家长一定要注意", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "腾讯官方活动：发送此消息到10个群即可获得100Q币", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "XX方便面含有致癌物质，已被质检总局查封", "violation_type": "false_info", "decision": "REVIEW"},

    # ========================================
    # porn (色情低俗) — 20条
    # ========================================
    {"content": "深夜福利视频免费看，加群获取资源链接", "violation_type": "porn", "decision": "REJECT"},
    {"content": "同城寂寞少妇等你来约，联系方式在主页", "violation_type": "porn", "decision": "REJECT"},
    {"content": "成人影院最新大片，高清无码资源合集", "violation_type": "porn", "decision": "REJECT"},
    {"content": "一对一裸聊服务，各种类型应有尽有", "violation_type": "porn", "decision": "REJECT"},
    {"content": "私密写真流出，想看更多请私信", "violation_type": "porn", "decision": "REJECT"},
    {"content": "催情药/迷药专卖，无色无味，效果好", "violation_type": "porn", "decision": "REJECT"},
    {"content": "网红主播私密视频遭黑客泄露，速看秒删", "violation_type": "porn", "decision": "REJECT"},
    {"content": "性感美女车模私房照，大尺度曝光", "violation_type": "porn", "decision": "REVIEW"},
    {"content": "按摩spa上门服务，正规男士放松私密预约", "violation_type": "porn", "decision": "REVIEW"},
    {"content": "想看你老婆和别人聊天的记录吗？输入手机号即可查询", "violation_type": "porn", "decision": "REJECT"},
    {"content": "附近的人有福利，搜索附近的小姐姐", "violation_type": "porn", "decision": "REVIEW"},
    {"content": "性感荷官在线发牌，真人视频互动", "violation_type": "porn", "decision": "REJECT"},
    {"content": "极品福利姬私拍套图，订阅制付费观看", "violation_type": "porn", "decision": "REJECT"},
    {"content": "日本AV女优最新作品磁力链接下载", "violation_type": "porn", "decision": "REJECT"},
    {"content": "偷拍女生裙底/更衣室/宿舍系列", "violation_type": "porn", "decision": "REJECT"},
    {"content": "成人用品情趣玩具测评及使用教学", "violation_type": "porn", "decision": "REVIEW"},
    {"content": "极品萝莉/御姐/人妻大尺度私房", "violation_type": "porn", "decision": "REJECT"},
    {"content": "黄色漫画/里番/成人动漫资源分享群", "violation_type": "porn", "decision": "REJECT"},
    {"content": "美女主播大秀视频录制完整版", "violation_type": "porn", "decision": "REJECT"},
    {"content": "色情小说激情片段节选，每日更新", "violation_type": "porn", "decision": "REJECT"},

    # ========================================
    # violence (暴力恐怖) — 15条
    # ========================================
    {"content": "你再敢说一句试试？信不信我砍死你全家", "violation_type": "violence", "decision": "REJECT"},
    {"content": "如何制作土制炸弹及引爆装置的详细教程", "violation_type": "violence", "decision": "REJECT"},
    {"content": "我弄到一批管制刀具，有需要的兄弟私我", "violation_type": "violence", "decision": "REJECT"},
    {"content": "被欺负了不要怂，拿刀捅回去，出了事我帮你摆平", "violation_type": "violence", "decision": "REJECT"},
    {"content": "枪械组装图纸分享，3D打印即可制作", "violation_type": "violence", "decision": "REJECT"},
    {"content": "我们组织周六去广场搞事情，想参加的报名", "violation_type": "violence", "decision": "REJECT"},
    {"content": "这人住在XX小区XX号楼，大家帮我去教训他", "violation_type": "violence", "decision": "REJECT"},
    {"content": "专门收拾欠钱不还的，专业团队上门催收", "violation_type": "violence", "decision": "REVIEW"},
    {"content": "分享一个打人技巧：不用武器也能让人丧失战斗力", "violation_type": "violence", "decision": "REJECT"},
    {"content": "以牙还牙，以血还血，此仇不共戴天", "violation_type": "violence", "decision": "REVIEW"},
    {"content": "化学毒物的简易制备方法及使用注意事项", "violation_type": "violence", "decision": "REJECT"},
    {"content": "不要报警，给钱就放人，否则后果自负", "violation_type": "violence", "decision": "REJECT"},
    {"content": "校园霸凌实录：一群人围殴一个学生", "violation_type": "violence", "decision": "REJECT"},
    {"content": "威胁恐吓：我知道你家在哪里，你给我小心点", "violation_type": "violence", "decision": "REJECT"},
    {"content": "鼓吹暴力革命的煽动性文章", "violation_type": "violence", "decision": "REJECT"},

    # ========================================
    # harassment (辱骂骚扰) — 15条
    # ========================================
    {"content": "你他妈就是个傻逼，脑子进水了吧，滚远点", "violation_type": "harassment", "decision": "REJECT"},
    {"content": "死肥猪你也配跟我说话？照镜子看看你那丑样", "violation_type": "harassment", "decision": "REJECT"},
    {"content": "全家死光光，祝你出门被车撞死", "violation_type": "harassment", "decision": "REJECT"},
    {"content": "老子骂你怎么了？有种出来单挑啊孬种", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "就你这智商还出来发帖，回娘胎里重造吧", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "反复在他人帖子下刷屏辱骂，人身攻击不断", "violation_type": "harassment", "decision": "REJECT"},
    {"content": "我告诉你，你再不还钱我就去你单位闹，让你丢工作", "violation_type": "harassment", "decision": "REJECT"},
    {"content": "长得跟个丑八怪似的还好意思发自拍恶心人", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "你这种人就该被网暴，让大家看看你的嘴脸", "violation_type": "harassment", "decision": "REJECT"},
    {"content": "整天只会哔哔赖赖，废物一个活着浪费空气", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "天天发广告私信骚扰我，拉黑你还能换号继续发", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "公开他人隐私信息：手机号/家庭住址/工作单位", "violation_type": "harassment", "decision": "REJECT"},
    {"content": "穷鬼一个就别出来丢人现眼了，连个会员都充不起", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "舔狗不得好死，继续舔啊看人家理你吗", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "用极其恶毒的语言诅咒对方及其家人多次", "violation_type": "harassment", "decision": "REJECT"},

    # ========================================
    # politics (政治敏感) — 10条
    # ========================================
    {"content": "分裂国家的极端主张和煽动性言论", "violation_type": "politics", "decision": "REJECT"},
    {"content": "歪曲历史贬损革命烈士和英雄人物形象", "violation_type": "politics", "decision": "REJECT"},
    {"content": "恶意曲解国家政策煽动民众不满情绪", "violation_type": "politics", "decision": "REJECT"},
    {"content": "散布有关国家领导人的不实谣言和负面信息", "violation_type": "politics", "decision": "REJECT"},
    {"content": "组织煽动非法集会游行的动员信息", "violation_type": "politics", "decision": "REJECT"},
    {"content": "恶意攻击我国政治制度和社会主义法治", "violation_type": "politics", "decision": "REJECT"},
    {"content": "散布损害国家统一和领土完整的言论", "violation_type": "politics", "decision": "REJECT"},
    {"content": "传播极端宗教思想和宗教极端主义内容", "violation_type": "politics", "decision": "REJECT"},
    {"content": "境外敌对势力的宣传渗透和策反内容", "violation_type": "politics", "decision": "REJECT"},
    {"content": "煽动民族仇恨、破坏民族团结的极端言论", "violation_type": "politics", "decision": "REJECT"},

    # ========================================
    # normal (正常内容) — 50条
    # ========================================
    {"content": "今天天气真好，适合出去走走", "violation_type": "none", "decision": "PASS"},
    {"content": "请问一下Python的asyncio和threading有什么区别？", "violation_type": "none", "decision": "PASS"},
    {"content": "今晚吃什么好呢？火锅还是烤肉？", "violation_type": "none", "decision": "PASS"},
    {"content": "最近在读《三体》，这本科幻小说真的很震撼", "violation_type": "none", "decision": "PASS"},
    {"content": "周末去爬山有没有一起的，从香山出发", "violation_type": "none", "decision": "PASS"},
    {"content": "推荐一个很好用的编辑器VS Code，插件生态非常丰富", "violation_type": "none", "decision": "PASS"},
    {"content": "宝宝今天满一岁了，身高体重都在正常范围内", "violation_type": "none", "decision": "PASS"},
    {"content": "数学题求助：已知f(x)=x^2+2x+1，求f(3)的值", "violation_type": "none", "decision": "PASS"},
    {"content": "我这电脑怎么突然蓝屏了，有大神能帮忙看看吗", "violation_type": "none", "decision": "PASS"},
    {"content": "请问到北京西站坐地铁几号线比较方便？", "violation_type": "none", "decision": "PASS"},
    {"content": "新出的iphone值得买吗？手上的X用了四年了", "violation_type": "none", "decision": "PASS"},
    {"content": "有没有人知道这家店的奶茶好不好喝", "violation_type": "none", "decision": "PASS"},
    {"content": "这部电视剧的评分好高，准备周末开始追剧", "violation_type": "none", "decision": "PASS"},
    {"content": "刚学会做红烧肉，味道还不错，分享一个菜谱", "violation_type": "none", "decision": "PASS"},
    {"content": "今年的目标：减肥10斤、读完20本书、学会吉他", "violation_type": "none", "decision": "PASS"},
    {"content": "小区的猫又生了一窝小猫咪，好可爱", "violation_type": "none", "decision": "PASS"},
    {"content": "有没有人想一起拼单买这个洗衣液，买三送一", "violation_type": "none", "decision": "PASS"},
    {"content": "请教各位大佬，docker容器启动失败怎么排查", "violation_type": "none", "decision": "PASS"},
    {"content": "劳动节假期安排出来了吗？今年放几天？", "violation_type": "none", "decision": "PASS"},
    {"content": "这件衣服好看吗？纠结买红色还是蓝色", "violation_type": "none", "decision": "PASS"},
    {"content": "电影院新上的科幻大片特效太棒了，强烈推荐", "violation_type": "none", "decision": "PASS"},
    {"content": "有没有靠谱的驾校推荐，准备暑假把驾照考了", "violation_type": "none", "decision": "PASS"},
    {"content": "今天公司团建，大家玩得都很开心", "violation_type": "none", "decision": "PASS"},
    {"content": "这个理财产品年化3.5%可以买吗？风险大不大？", "violation_type": "none", "decision": "PASS"},
    {"content": "有没有在北京的程序员朋友，求内推", "violation_type": "none", "decision": "PASS"},
    {"content": "刚跑完五公里，配速6分钟，慢慢进步中", "violation_type": "none", "decision": "PASS"},
    {"content": "这款机械键盘手感怎么样？青轴会不会太吵", "violation_type": "none", "decision": "PASS"},
    {"content": "有没有人知道这附近哪家理发店剪男发比较好", "violation_type": "none", "decision": "PASS"},
    {"content": "分享一下常用的几个学习网站，都是免费的", "violation_type": "none", "decision": "PASS"},
    {"content": "这个游戏新版本更新了什么内容？值不值得回坑", "violation_type": "none", "decision": "PASS"},
    {"content": "有谁知道今天限行尾号是几？忘了", "violation_type": "none", "decision": "PASS"},
    {"content": "这双篮球鞋的实战性能怎么样？有没有穿过的朋友", "violation_type": "none", "decision": "PASS"},
    {"content": "书荒了，求推荐几本好看的推理小说", "violation_type": "none", "decision": "PASS"},
    {"content": "周末计划：早上健身、下午看书、晚上看电影", "violation_type": "none", "decision": "PASS"},
    {"content": "这个PPT模板在哪里可以下载？看起来很不错", "violation_type": "none", "decision": "PASS"},
    {"content": "新买了空气炸锅，求推荐简单好做的食谱", "violation_type": "none", "decision": "PASS"},
    {"content": "有没有什么好用的记账软件推荐？", "violation_type": "none", "decision": "PASS"},
    {"content": "给大家安利一个很赞的纪录片《我们的星球》", "violation_type": "none", "decision": "PASS"},
    {"content": "明天要去面试了，好紧张，有没有面试经验分享", "violation_type": "none", "decision": "PASS"},
    {"content": "高铁票可以提前几天买？12306上显示无票怎么办", "violation_type": "none", "decision": "PASS"},
    {"content": "这种多肉植物怎么养？叶子发黄了是什么原因", "violation_type": "none", "decision": "PASS"},
    {"content": "最近有去云南旅游的朋友吗？求分享攻略", "violation_type": "none", "decision": "PASS"},
    {"content": "求推荐一款平价好用的防晒霜，不要太油腻", "violation_type": "none", "decision": "PASS"},
    {"content": "这种乐高积木适合几岁的小朋友玩？", "violation_type": "none", "decision": "PASS"},
    {"content": "有人知道个人所得税专项附加扣除怎么申报吗", "violation_type": "none", "decision": "PASS"},
    {"content": "这周的工作总结：完成了需求评审、接口联调、上线发布", "violation_type": "none", "decision": "PASS"},
    {"content": "分享一下最近学到的Git技巧，rebase真的很好用", "violation_type": "none", "decision": "PASS"},
    {"content": "上班通勤时间太长想换个房子，有推荐的小区吗", "violation_type": "none", "decision": "PASS"},
    {"content": "求助：微信聊天记录怎么完整备份到电脑？", "violation_type": "none", "decision": "PASS"},
    {"content": "今天在健身房做了一个小时有氧，坚持就是胜利", "violation_type": "none", "decision": "PASS"},

    # ========================================
    # adversarial (对抗样本) — 30条
    # ========================================
    {"content": "加我🖊信 x x 3 3 4 4 日 赚 千 元", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "免费👜取🎁包，关注公🕺众号", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "加 V 信 xx3344 详细了解", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "扫🐎关注🈶惊喜大礼包等👗拿", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "日√赚√千√元√不√收√任√何√费√用", "violation_type": "advertisement", "decision": "REJECT"},
    {"content": "＋V查看详情 高质量产品低价出售", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "想了解项目详情请 私 信 我", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "赊情低俗图片分享 入群获取资源链接", "violation_type": "porn", "decision": "REJECT"},
    {"content": "铯情视频完整版 点击头像获取", "violation_type": "porn", "decision": "REJECT"},
    {"content": "纶聊服务 一对一私密视频通话", "violation_type": "porn", "decision": "REJECT"},
    {"content": "成\U0001f51e人\U0001f453频\U0001f3a8道 最新资源更新", "violation_type": "porn", "decision": "REJECT"},
    {"content": "♈信: vip66888 领取★福利★资源", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "支 fu 宝 转 账 返 利 活 动 先 转 后 返", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "我是 澳 门 新 普 金 客 服 请 发 送 你 的 银 行 卡 号", "violation_type": "false_info", "decision": "REJECT"},
    {"content": "中 奖 通 知 您 已 被 随 机 抽 中 为 幸 运 用 户", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "你 的 银 行 卡 存 在 异 常 请 点 击 链 接 处 理", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "砍死你全家 这句话的谐音变体 有本事出来单挑", "violation_type": "violence", "decision": "REJECT"},
    {"content": "找 人 教 训 欠 钱 不 还 的 老 赖 专 业 清 债", "violation_type": "violence", "decision": "REVIEW"},
    {"content": "shabi ni zhe ge feiwu huozhe langfei kongqi", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "Nǐ mā sǐ le, gǔn yuǎn diǎn bié ràng wǒ kàn jiàn nǐ", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "ní mǎ bī gǔn yuǎn diǎn fèi wù yī gè", "violation_type": "harassment", "decision": "REVIEW"},
    {"content": "彩漂中奖内部消息 稳赚不赔跟上吃肉", "violation_type": "false_info", "decision": "REVIEW"},
    {"content": "dǔ bó wǎng zhàn tuī jiàn chōng zhí sòng cǎi jīn", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "加V信xxx 日结兼职 一部手机在家就能赚钱", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "㊙️密通道：最新🈲播资源每日更新", "violation_type": "porn", "decision": "REVIEW"},
    {"content": "bào fù shè huì de jí duān yán lùn sàn bù", "violation_type": "violence", "decision": "REVIEW"},
    {"content": "最新🔞资源 点击头像查看 秒删速存", "violation_type": "porn", "decision": "REJECT"},
    {"content": "ｊｉａ　ｗｏ　ｗｅｉｘｉｎ　ｌｉａｏ　ｊｉａｎｚｈｉ", "violation_type": "advertisement", "decision": "REVIEW"},
    {"content": "1对1 裸/聊/服/务 各/种/类/型/应/有/尽/有", "violation_type": "porn", "decision": "REJECT"},
    {"content": "[全角替换] 伱恏 請加⼊峮聊 每ㄖ汾享福利內容", "violation_type": "advertisement", "decision": "REVIEW"},
]


def build_dataset(count: int = 200, output_path: str = None) -> List[Dict]:
    """构建标注数据集"""
    output_path = output_path or DEFAULT_OUTPUT

    # 从样本库中选取指定数量的样本
    selected = SAMPLES[:count] if count <= len(SAMPLES) else SAMPLES

    # 生成完整的数据集条目（含 content_id）
    dataset = []
    for i, sample in enumerate(selected):
        entry = {
            "content_id": f"eval_{i+1:04d}",
            "content": sample["content"],
            "violation_type": sample["violation_type"],
            "decision": sample["decision"],
            "risk_score": _estimate_risk_score(sample["violation_type"], sample["decision"]),
            "tags": _generate_tags(sample["violation_type"]),
        }
        dataset.append(entry)

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 写入 JSON 文件
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    return dataset


def _estimate_risk_score(violation_type: str, decision: str) -> float:
    """估算风险分数"""
    if decision == "REJECT":
        base = {"violence": 0.92, "porn": 0.88, "politics": 0.90, "illegal": 0.95,
                "advertisement": 0.78, "false_info": 0.82, "harassment": 0.72}
        return base.get(violation_type, 0.75)
    elif decision == "REVIEW":
        return 0.50
    else:
        return 0.05 if violation_type == "none" else 0.30


def _generate_tags(violation_type: str) -> list:
    """生成标签"""
    tag_map = {
        "advertisement": ["引流", "广告"],
        "false_info": ["诈骗", "虚假"],
        "porn": ["色情", "低俗"],
        "violence": ["暴力", "威胁"],
        "harassment": ["辱骂", "骚扰"],
        "politics": ["政治敏感"],
        "none": ["正常"],
    }
    return tag_map.get(violation_type, [])


def verify_dataset(filepath: str = None):
    """验证并打印数据集统计"""
    filepath = filepath or DEFAULT_OUTPUT

    if not os.path.exists(filepath):
        print(f"❌ 数据集文件不存在: {filepath}")
        print("   请先运行: python3 scripts/build_eval_dataset.py --count 200")
        return

    with open(filepath, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    print(f"\n{'='*60}")
    print(f"📊 评测数据集统计")
    print(f"{'='*60}")
    print(f"总样本数: {len(dataset)}")

    # 按违规类型统计
    by_type = {}
    by_decision = {}
    for entry in dataset:
        vt = entry["violation_type"]
        dec = entry["decision"]
        by_type[vt] = by_type.get(vt, 0) + 1
        by_decision[dec] = by_decision.get(dec, 0) + 1

    print(f"\n按违规类型分布:")
    type_order = ["advertisement", "false_info", "porn", "violence", "harassment", "politics", "none"]
    for vt in type_order:
        count = by_type.get(vt, 0)
        bar = "█" * (count // 2)
        print(f"  {vt:<16} {count:>4}条  {bar}")

    print(f"\n按决策分布:")
    for dec in ["PASS", "REVIEW", "REJECT"]:
        count = by_decision.get(dec, 0)
        print(f"  {dec:<8} {count:>4}条")

    print(f"\n✅ 数据集就绪: {filepath}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建评测数据集")
    parser.add_argument("--count", type=int, default=200, help="样本数量")
    parser.add_argument("--output", type=str, default=None, help="输出路径")
    parser.add_argument("--verify", action="store_true", help="验证数据集分布")
    args = parser.parse_args()

    if args.verify:
        verify_dataset(args.output)
    else:
        dataset = build_dataset(args.count, args.output)
        print(f"✅ 已生成 {len(dataset)} 条标注样本 → {args.output or DEFAULT_OUTPUT}")
        print(f"   验证分布: python3 scripts/build_eval_dataset.py --verify")
