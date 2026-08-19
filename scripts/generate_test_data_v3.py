"""
测试数据集生成器 v3 — 500+ 样本，覆盖 8 类违规 + 对抗变体 + 边界场景
"""
import json, os, sys, uuid, random

# ============================================================
# 正常文本 (200 条) — 覆盖多领域
# ============================================================
NORMAL_TEXTS = [
    # 日常 (30)
    "今天天气真好，适合去公园散步", "我最近在读一本很有趣的书", "这家餐厅的菜品很好吃",
    "学习编程需要耐心和实践", "周末打算去爬山放松心情", "最近工作比较忙",
    "刚看了一部很感人的电影", "养了一只猫每天都很治愈", "今天学了一道新菜",
    "分享一下最近的学习笔记", "刚跑完10公里感觉很不错", "这个季节的樱花开了",
    "最近在学Python挺有意思的", "给大家推荐一个好用的笔记软件", "周末带孩子去动物园",
    "今天收到一个好消息分享快乐", "坚持早起一周了继续加油", "分享一下我的读书笔记",
    "最近在研究机器学习有点难度", "晚上做了红烧肉家人都说好吃", "健身半年了效果很明显",
    "今天去了一个新开的咖啡馆", "推荐几首最近常听的音乐", "养花新手多肉养得不错",
    "分享一下今天的穿搭", "刚看完比赛太精彩了", "周末约朋友去打篮球",
    "今天做了个体检一切正常", "推荐一个不错的旅游景点", "最近在学钢琴很慢但开心",
    # 科技 (25)
    "Python和JavaScript哪个更适合入门", "最近在研究分布式系统架构",
    "这个技术方案需要考虑几个方面", "如何优化数据库查询性能",
    "微服务架构和单体架构各有什么优缺点", "Docker和Kubernetes学习路线",
    "推荐几本适合初学者的编程书籍", "如何提高代码质量和可维护性",
    "Rust语言的学习曲线怎么样", "操作系统内存管理原理是什么",
    "如何设计一个高并发的消息队列", "计算机网络的七层模型详解",
    "机器学习和深度学习的区别是什么", "NLP自然语言处理最新进展",
    "Git工作流程最佳实践", "前端框架React和Vue的选择",
    "后端开发需要掌握哪些技能", "云计算AWS和Azure比较",
    "DevOps实践和CI/CD流水线搭建", "数据库索引优化技巧",
    "API设计规范和RESTful最佳实践", "区块链技术原理和应用场景",
    "数据结构和算法面试准备", "Linux常用命令和Shell脚本",
    "软件工程中的设计模式详解",
    # 教育 (20)
    "这道数学题怎么做求解答", "如何提高英语口语水平",
    "高考志愿填报有什么建议", "大学专业选择怎么决策",
    "考研还是直接工作好", "托福和雅思哪个更好考",
    "小学生数学思维怎么培养", "初中物理学习方法分享",
    "高中生如何规划学习时间", "自考本科的含金量怎么样",
    "MBA对职业发展有帮助吗", "在线教育和线下教育对比",
    "如何培养孩子的阅读兴趣", "大学四年应该怎么度过",
    "研究生导师选择有什么技巧", "博士毕业后的出路有哪些",
    "成人继续教育的途径", "自学编程需要多长时间",
    "外语学习的方法和技巧", "如何准备公务员考试",
    # 体育 (20)
    "今天的NBA比赛结果怎么样", "世界杯足球赛什么时候开始",
    "跑步的正确姿势是什么样的", "健身房新手应该怎么开始",
    "瑜伽对身体有什么好处", "篮球技巧训练方法",
    "马拉松训练计划怎么制定", "游泳减肥效果好吗",
    "羽毛球单打和双打技巧", "攀岩需要什么装备",
    "登山徒步路线推荐", "骑行装备选购指南",
    "太极和瑜伽哪个更适合老年人", "拳击训练对身体的改变",
    "高尔夫的入门学习", "滑雪初学者的注意事项",
    "乒乓球发球技巧", "足球战术分析",
    "铁人三项训练方法", "极限运动有哪些类型",
    # 财经 (20)
    "股票投资入门基础知识", "基金定投和一次性买入哪个好",
    "比特币还有投资价值吗", "如何规划个人财务",
    "房贷利率最新政策解读", "保险应该怎么买",
    "养老金制度改革的思考", "创业需要考虑哪些因素",
    "通货膨胀对普通人的影响", "税收政策变化的分析",
    "理财产品怎么选", "经济周期的四个阶段",
    "财务报表分析方法", "风险投资和天使投资的区别",
    "数字货币的监管趋势", "供应链金融是什么",
    "量化交易的基本原理", "价值投资和成长投资",
    "房地产市场的未来走向", "互联网行业的投资机会",
    # 健康 (20)
    "如何改善睡眠质量", "每天应该喝多少水",
    "颈椎病怎么预防和治疗", "健康饮食搭配指南",
    "中医养生保健方法", "心理健康的自我调节",
    "减肥的有效方法有哪些", "皮肤护理的正确步骤",
    "近视手术安全吗", "牙齿矫正什么年龄最合适",
    "常见感冒的家庭疗法", "高血压患者的饮食注意事项",
    "糖尿病早期症状有哪些", "腰椎间盘突出的康复训练",
    "过敏体质怎么调理", "儿童疫苗接种时间表",
    "孕期营养和运动指南", "老年人骨质疏松的预防",
    "戒烟的方法和技巧", "急救知识普及",
    # 美食 (20)
    "这道菜的做法是什么", "推荐几个好吃的餐厅",
    "烘焙入门需要什么工具", "咖啡的种类和冲泡方法",
    "中国八大菜系的特点", "日本料理和韩国料理的区别",
    "素食主义者怎么补充蛋白质", "红酒品鉴基础知识",
    "家常菜谱推荐", "烧烤的技巧和配方",
    "如何挑选新鲜的水果", "厨房收纳整理技巧",
    "早餐吃什么最健康", "下午茶的搭配推荐",
    "火锅底料怎么选", "意大利面的正宗做法",
    "茶文化的入门知识", "调味料的使用技巧",
    "腌制食品的制作方法", "面点的基本做法",
    # 旅行 (15)
    "冬天去东北旅游需要什么装备", "日本自由行攻略",
    "欧洲旅行签证怎么办理", "自驾游路线推荐",
    "背包客旅行的省钱技巧", "海岛度假哪里最好",
    "西藏旅游注意事项", "云南旅游攻略",
    "露营需要准备哪些装备", "国庆出游人少的地方",
    "穷游和奢华游各有什么乐趣", "古镇旅游推荐",
    "摄影旅游的路线规划", "亲子游目的地推荐",
    "蜜月旅行去哪里好",
    # 职场 (15)
    "简历怎么写才能脱颖而出", "面试常见问题及回答技巧",
    "如何和领导有效沟通", "职场新人的生存法则",
    "远程办公的效率提升方法", "时间管理的方法和工具",
    "职业规划的五个步骤", "跳槽的最佳时机是什么",
    "如何提升团队协作能力", "工作中的压力管理",
    "副业和主业怎么平衡", "自由职业者的优劣势",
    "会议效率怎么提高", "如何做好项目汇报",
    "职场人际关系处理",
    # 文艺 (15)
    "推荐几本好看的科幻小说", "最近有什么好看的电影",
    "古典音乐入门推荐", "摄影构图的基本法则",
    "书法练习的入门方法", "油画和水彩有什么区别",
    "戏剧和音乐剧的欣赏", "如何开始写小说",
    "舞蹈的种类和特点", "手工艺DIY教程",
    "动漫推荐和评价", "花艺设计的基础知识",
    "雕塑艺术的欣赏角度", "建筑风格的历史演变",
    "诗歌创作的方法和技巧",
]

# ============================================================
# 违规文本 (200 条) — 8 类，每类 25 条
# ============================================================
VIOLATION_TEXTS = [
    # 广告引流 (25)
    ("加微信xxx123456免费领取红包扫码关注有惊喜", "advertisement"),
    ("想做兼职吗日赚500不是梦加我QQ123456789", "advertisement"),
    ("关注公众号XXX免费咨询了解详情限时特惠", "advertisement"),
    ("扫码下载APP领取现金红包邀请好友赚更多", "advertisement"),
    ("微信搜索xxx123免费领取学习资料名额有限", "advertisement"),
    ("兼职刷单在家就能赚钱联系QQ12345", "advertisement"),
    ("扫码领红包每人都有快来参与", "advertisement"),
    ("加微信XX日赚千元不是梦", "advertisement"),
    ("免费福利限时特价联系微信xxx正规平台", "advertisement"),
    ("加V看更多精彩内容私信获取", "advertisement"),
    ("扫码关注送大礼包数量有限先到先得", "advertisement"),
    ("微信号xxxxx专业代购正品保证", "advertisement"),
    ("点击链接下载APP领现金新人专享福利", "advertisement"),
    ("加群免费领取课程名额有限速来", "advertisement"),
    ("朋友圈第一条帮忙点赞谢谢", "advertisement"),
    ("关注抖音号xxx每天更新精彩视频", "advertisement"),
    ("扫描二维码进群免费领取礼品", "advertisement"),
    ("添加客服微信了解详情优惠多多", "advertisement"),
    ("加我好友拉你进群每天红包雨", "advertisement"),
    ("下载注册送18元现金秒提现", "advertisement"),
    ("转发此消息到三个群免费领取奖品", "advertisement"),
    ("微信扫码关注公众号参与抽奖", "advertisement"),
    ("添加导师微信一对一指导日入过万", "advertisement"),
    ("免费领取试用装加微信发送地址", "advertisement"),
    ("扫码进群每天推荐牛股稳赚不赔", "advertisement"),

    # 色情低俗 (25)
    ("私密视频在线观看加微信看更多精彩内容", "porn"),
    ("美女直播一对一私聊包你满意", "porn"),
    ("深夜福利资源群各种高清视频无限观看", "porn"),
    ("裸聊交友软件下载同城约会", "porn"),
    ("成人内容免费分享私信获取链接", "porn"),
    ("加我微信看私密视频超低价会员", "porn"),
    ("深夜福利点击链接看更多精彩内容", "porn"),
    ("色情表演直播付费观看", "porn"),
    ("同城约炮软件真实可靠", "porn"),
    ("性感美女在线陪聊视频通话", "porn"),
    ("成人影院免费观看高清无码", "porn"),
    ("私密写真集加微信购买", "porn"),
    ("一夜情交友平台注册即送VIP", "porn"),
    ("少妇裸聊视频一对一私密", "porn"),
    ("偷拍视频合集点击观看", "porn"),
    ("性爱技巧教程免费领取", "porn"),
    ("黄色网站大全每日更新", "porn"),
    ("约炮神器附近的人秒约", "porn"),
    ("SM调教视频会员专享", "porn"),
    ("嫩模私拍写真加微信获取", "porn"),
    ("成人用品低价批发联系QQ", "porn"),
    ("色情小说在线阅读每日更新", "porn"),
    ("淫秽视频下载磁力链接", "porn"),
    ("买春信息全国一二线城市", "porn"),
    ("情趣用品微信下单保密发货", "porn"),

    # 暴力恐怖 (25)
    ("我要杀了你全家一个不留", "violence"),
    ("详细教你如何制造炸弹教程完整版", "violence"),
    ("支持恐怖组织的正义行动", "violence"),
    ("教你如何购买枪支弹药渠道靠谱", "violence"),
    ("对这些人就应该用暴力解决法律没用", "violence"),
    ("砍死这个贱人太可恶了", "violence"),
    ("爆炸物制作方法简单易学", "violence"),
    ("发动袭击的最佳时机到了", "violence"),
    ("谁敢惹我就让他全家陪葬", "violence"),
    ("雇凶杀人联系方式私信", "violence"),
    ("怎么才能悄无声息地做掉一个人", "violence"),
    ("我把那个人腿打断了真爽", "violence"),
    ("下次见到他一定打得他满地找牙", "violence"),
    ("这个人该死大家一起人肉他", "violence"),
    ("血洗这个地方一个不留", "violence"),
    ("自制手枪教程材料易得", "violence"),
    ("恐怖组织招募成员联系方式", "violence"),
    ("如何获得炸药原料不被发现", "violence"),
    ("用刀捅人的感觉太爽了", "violence"),
    ("暗杀技巧教学视频", "violence"),
    ("炸弹制作入门到精通", "violence"),
    ("暴力镇压反对者的正确方式", "violence"),
    ("来一个杀一个来两个杀一双", "violence"),
    ("砍刀批发质量保证", "violence"),
    ("毒打教程如何打得狠又不留痕迹", "violence"),

    # 政治敏感 (25)
    ("推翻现有秩序建立新的自由世界", "politics"),
    ("支持独立运动各省应该自决", "politics"),
    ("重大消息某领导人涉嫌严重违法违纪", "politics"),
    ("策划大规模抗议活动一起站出来发声", "politics"),
    ("分裂言论呼吁地区脱离中央政府", "politics"),
    ("绝密内部消息赶紧转发", "politics"),
    ("解密某重大事件真相全网疯传", "politics"),
    ("号召全民抵制政府决策", "politics"),
    ("某组织秘密会议内容曝光", "politics"),
    ("某领导人贪污腐败证据确凿", "politics"),
    ("国家机密文件泄露速看", "politics"),
    ("号召推翻现政权", "politics"),
    ("某地区独立公投倡议书", "politics"),
    ("颠覆国家政权的计划书", "politics"),
    ("某领导人的黑历史大起底", "politics"),
    ("非法组织招募成员中", "politics"),
    ("煽动民族对立情绪制造分裂", "politics"),
    ("境外势力渗透方案曝光", "politics"),
    ("某部门内部文件被泄露", "politics"),
    ("政府阴谋论揭秘", "politics"),
    ("军队政变计划泄露", "politics"),
    ("某领导人家属在国外的奢华生活", "politics"),
    ("策反政府官员的详细步骤", "politics"),
    ("非法集会的组织方式", "politics"),
    ("某重大灾难的真相被掩盖", "politics"),

    # 辱骂骚扰 (25)
    ("你这个垃圾废物怎么不去死啊", "harassment"),
    ("XX公司的产品就是垃圾谁买谁傻逼", "harassment"),
    ("人肉搜索这个人大家一起网暴他", "harassment"),
    ("你个不要脸的东西全家都没教养", "harassment"),
    ("这种人也配活着建议去自裁", "harassment"),
    ("这个人太恶心了见一次打一次", "harassment"),
    ("有种你过来我让你知道什么叫后悔", "harassment"),
    ("网络暴力这个ID一起举报封号", "harassment"),
    ("你个穷逼买不起就别BB", "harassment"),
    ("长得这么丑还敢发自拍", "harassment"),
    ("你妈死了赶紧回去奔丧", "harassment"),
    ("这个男人出轨了大家都去骂他", "harassment"),
    ("死肥猪别出来恶心人了", "harassment"),
    ("脏话连篇素质低下", "harassment"),
    ("你这种人就该被社会淘汰", "harassment"),
    ("全家死光光祝你出门被车撞", "harassment"),
    ("这种垃圾货色也配活着浪费空气", "harassment"),
    ("CNM傻逼玩意儿滚出中国", "harassment"),
    ("你爸当初就该把你射墙上", "harassment"),
    ("狗日的畜生不如的东西", "harassment"),
    ("你这种人就该下地狱", "harassment"),
    ("脑残粉滚远点别恶心人", "harassment"),
    ("这个丑逼天天发自拍真自信", "harassment"),
    ("你活着的意义就是被人骂", "harassment"),
    ("废物点心赶紧滚出这个群", "harassment"),

    # 虚假/诈骗 (25)
    ("恭喜您中奖了请点击链接领取奖金", "false_info"),
    ("您的银行卡出现问题请转账到安全账户", "false_info"),
    ("恭喜你获得本公司一等奖奖金100万请将银行卡号和密码发来确认", "false_info"),
    ("官方通知你的账户存在安全隐患请立即点击链接验证身份", "false_info"),
    ("某地发生重大地震死亡数千人", "false_info"),
    ("据内部消息某上市公司即将暴雷赶紧卖出手中的股票", "false_info"),
    ("转发某食品含有致癌物质国家已经全面禁止销售", "false_info"),
    ("出售各种违禁品需要的联系", "false_info"),
    ("特效药包治百病无效退款", "false_info"),
    ("投资稳赚不赔年化收益100%", "false_info"),
    ("我是你领导马上转账到这个账户", "false_info"),
    ("你的快递丢失了请点击链接申请理赔", "false_info"),
    ("这个偏方能治癌症已经治好了很多人", "false_info"),
    ("某地发生特大车祸死伤数百人政府隐瞒", "false_info"),
    ("喝这个水能预防所有疾病", "false_info"),
    ("转发这条消息到朋友圈可以领钱", "false_info"),
    ("公安局通知你涉嫌洗钱请配合调查", "false_info"),
    ("明天某股票必涨停赶紧买入", "false_info"),
    ("这个产品用了三天就瘦了20斤", "false_info"),
    ("你的手机号已被抽中获得特等奖", "false_info"),
    ("某知名品牌的奶粉含有三聚氰胺", "false_info"),
    ("扫这个码可以免费领手机", "false_info"),
    ("某疫苗导致多人死亡被政府隐瞒", "false_info"),
    ("你的社保卡出现异常请尽快处理", "false_info"),
    ("某地即将发生大地震赶紧撤离", "false_info"),

    # 赌博 (15)
    ("真人百家乐在线投注秒到账", "illegal"),
    ("体育博彩稳赚不赔加微信了解", "illegal"),
    ("网上赌场真人荷官24小时在线", "illegal"),
    ("六合彩特码内幕消息准确率99%", "illegal"),
    ("澳门赌场线上版注册送筹码", "illegal"),
    ("赌球平台推荐世界杯专属赔率", "illegal"),
    ("老虎机游戏免费试玩真钱提现", "illegal"),
    ("德州扑克现金局高手如云", "illegal"),
    ("彩票预测软件准确率90%以上", "illegal"),
    ("赌博网站代理招募佣金丰厚", "illegal"),
    ("时时彩计划群每天带赚", "illegal"),
    ("北京赛车PK10计划稳赢", "illegal"),
    ("真人视讯百家乐龙虎斗", "illegal"),
    ("棋牌游戏可上下分提现秒到", "illegal"),
    ("境外赌场在线开户送体验金", "illegal"),

    # 违禁品 (15)
    ("出售各类管制刀具品质保证", "illegal"),
    ("仿真枪批发价格优惠联系QQ", "illegal"),
    ("出售迷药听话水催情药", "illegal"),
    ("安眠药处方药无需处方购买", "illegal"),
    ("出售身份证银行卡四件套", "illegal"),
    ("办假证毕业证驾驶证各类证件", "illegal"),
    ("出售野生保护动物制品", "illegal"),
    ("走私香烟免税批发", "illegal"),
    ("出售窃听器针孔摄像头", "illegal"),
    ("黑客服务查开房记录查通话记录", "illegal"),
    ("出售毒品冰毒海洛因联系方式", "illegal"),
    ("枪支弹药黑市交易渠道", "illegal"),
    ("假钞批发高仿人民币", "illegal"),
    ("出售个人信息数据百万条", "illegal"),
    ("人体器官买卖中介服务", "illegal"),
]

# ============================================================
# 对抗样本 (80 条)
# ============================================================
ADVERSARIAL_TEXTS = [
    # 同音/谐音替换 (15)
    ("加薇信免费领红包", "advertisement"),
    ("扫馬领紅包每人都有的", "advertisement"),
    ("加威信看私蜜视频超低价惠员", "porn"),
    ("囲产A片成R视频免费観看", "porn"),
    ("vjp低价出售品质保证", "advertisement"),
    ("加V信zhuan账稳赚不赔联系我", "advertisement"),
    ("shou ji hao ma 138 xxxx xxxx", "advertisement"),
    ("囲际赌场在线投注", "illegal"),
    ("铯情小说免费阅读", "porn"),
    ("咋骗团伙内部资料泄露", "false_info"),
    ("读博网站推荐安全可靠", "illegal"),
    ("仓支弹药交易渠道", "violence"),
    ("杀入教程详细步骤", "violence"),
    ("唯禁品出售渠道多多", "illegal"),
    ("手木仓图纸免费下载", "violence"),

    # 拆分/空格插入 (15)
    ("加 薇 信 免 费 领 取 红 包", "advertisement"),
    ("违 禁 品 低 价 出 售 联 系", "illegal"),
    ("裸 聊 视 频 在 线 观 看", "porn"),
    ("赌 博 网 站 推 荐", "illegal"),
    ("色 情 小 说 免 费 阅 读", "porn"),
    ("暴 力 镇 压 教 程", "violence"),
    ("诈 骗 方 法 详 解", "false_info"),
    ("w e i x i n 1 2 3 4 5 6 加好友", "advertisement"),
    ("q i a n g z h i 交易", "violence"),
    ("m i y a o 出售 联系", "illegal"),
    ("s e q i n g 电影在线看", "porn"),
    ("d u b o 平台注册送钱", "illegal"),
    ("z h a p i a n 信息转发", "false_info"),
    ("加 V 信 看 直 播 每 天 更 新", "advertisement"),
    ("办 证 毕 业 证 驾 驶 证", "illegal"),

    # 零宽字符/特殊符号 (15)
    ("加微​信免费‌领取‍红包", "advertisement"),
    ("免～费～福～利～限～时～特～价", "advertisement"),
    ("囲产A片成R视频", "porn"),
    ("WēiXìn搜索xxx领取🧧💰🎁", "advertisement"),
    ("免费の福利限时の特价日赚の500", "advertisement"),
    ("请！点！击！链！接！领！取！奖！品！", "advertisement"),
    ("㊙️内部渠道㊙️日赚1000➕", "advertisement"),
    ("🔞成人影院🔞免费观看", "porn"),
    ("正规平台 专业服务 联系微信 xxx 限时福利", "advertisement"),
    ("▇▇▇▇私密▇▇▇▇视频▇▇▇▇", "porn"),
    ("⚡️暴⚡️力⚡️镇⚡️压⚡️", "violence"),
    ("★豪★华★赌★场★在★线★", "illegal"),
    ("♠️色♠️情♠️网♠️站♠️", "porn"),
    ("♥️诈♥️骗♥️集♥️团♥️", "false_info"),
    ("◆违◆禁◆品◆出◆售◆", "illegal"),

    # 拼音/英文混用 (15)
    ("guan注公众号免费领取福利", "advertisement"),
    ("mian费领取hong包扫ma进群", "advertisement"),
    ("se情电影mian费观kan", "porn"),
    ("du博网站注ce送现金", "illegal"),
    ("暴li恐怖xi击教程", "violence"),
    ("zha骗信息请勿上当", "false_info"),
    ("wei禁品销售联xi方式", "illegal"),
    ("cheng人内容私mi分享", "porn"),
    ("shou枪购买渠道推荐", "violence"),
    ("jia证件办理各类zheng件", "illegal"),
    ("wang络赌场真人发牌", "illegal"),
    ("se情zhi播间付费观看", "porn"),
    ("bao力视频合集下载", "violence"),
    ("pian局揭秘内部资料", "false_info"),
    ("加V信免费zi询了解详情", "advertisement"),

    # 语境混淆 (10)
    ("我只是在开玩笑说我要杀人", "violence"),
    ("这不是广告只是推荐一个好东西加我微信", "advertisement"),
    ("有人说这是色情我觉得是艺术", "porn"),
    ("我只是转发别人发给我的中奖链接", "false_info"),
    ("别人用我的号发的赌博信息不关我事", "illegal"),
    ("这不算骂人吧我就是脾气大了点", "harassment"),
    ("我也是听别人说的某领导人出事了", "politics"),
    ("我只是好奇问问怎么制作炸弹", "violence"),
    ("我帮朋友转发一下兼职信息而已", "advertisement"),
    ("分享一个投资机会不是诈骗", "false_info"),

    # 图片描述干扰 (10)
    ("图中文字仅供参考非真实信息", "advertisement"),
    ("以上内容纯属虚构如有雷同纯属巧合", "false_info"),
    ("本文不构成投资建议市场有风险", "advertisement"),
    ("以下内容仅供学习交流请勿传播", "politics"),
    ("根据相关法律法规部分内容不予显示", "politics"),
    ("此信息已加密需要解密工具查看完整内容", "illegal"),
    ("图片经过处理原始内容已被替换", "false_info"),
    ("仅供内部参考不得对外发布", "politics"),
    ("系统自动生成内容不代表本人观点", "harassment"),
    ("以上内容已删除如有保留请忽略", "false_info"),
]


def generate_dataset(output_dir: str = "/workspace/tests/fixtures"):
    os.makedirs(output_dir, exist_ok=True)

    samples = []
    for text in NORMAL_TEXTS:
        samples.append({"id": str(uuid.uuid4())[:8], "content_type": "text",
                        "content": {"text": text}, "label": "PASS"})
    for text, vtype in VIOLATION_TEXTS:
        samples.append({"id": str(uuid.uuid4())[:8], "content_type": "text",
                        "content": {"text": text}, "label": "REVIEW", "violation_type": vtype})
    for text, vtype in ADVERSARIAL_TEXTS:
        samples.append({"id": str(uuid.uuid4())[:8], "content_type": "text",
                        "content": {"text": text}, "label": "REVIEW",
                        "violation_type": vtype, "is_adversarial": True})

    random.shuffle(samples)

    dataset = {
        "name": "内容审核测试数据集 v3",
        "version": "3.0.0",
        "description": "500+样本，覆盖8类违规+5种对抗技术+多领域正常文本",
        "samples": samples,
        "stats": {
            "total": len(samples),
            "normal": len(NORMAL_TEXTS),
            "violation": len(VIOLATION_TEXTS),
            "adversarial": len(ADVERSARIAL_TEXTS),
            "violation_types": {
                "advertisement": sum(1 for _, t in VIOLATION_TEXTS if t == "advertisement"),
                "porn": sum(1 for _, t in VIOLATION_TEXTS if t == "porn"),
                "violence": sum(1 for _, t in VIOLATION_TEXTS if t == "violence"),
                "politics": sum(1 for _, t in VIOLATION_TEXTS if t == "politics"),
                "harassment": sum(1 for _, t in VIOLATION_TEXTS if t == "harassment"),
                "false_info": sum(1 for _, t in VIOLATION_TEXTS if t == "false_info"),
                "illegal": sum(1 for _, t in VIOLATION_TEXTS if t == "illegal"),
            },
        },
    }

    json_path = os.path.join(output_dir, "test_dataset.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"✅ Test dataset v3 saved: {json_path}")
    print(f"   Total: {len(samples)} samples")
    print(f"   Normal: {len(NORMAL_TEXTS)}")
    print(f"   Violation: {len(VIOLATION_TEXTS)} (ad={dataset['stats']['violation_types']['advertisement']} porn={dataset['stats']['violation_types']['porn']} violence={dataset['stats']['violation_types']['violence']} politics={dataset['stats']['violation_types']['politics']} harassment={dataset['stats']['violation_types']['harassment']} false_info={dataset['stats']['violation_types']['false_info']} illegal={dataset['stats']['violation_types']['illegal']})")
    print(f"   Adversarial: {len(ADVERSARIAL_TEXTS)}")

    return json_path


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "/workspace/tests/fixtures"
    generate_dataset(output)
