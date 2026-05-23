APP_TITLE = "全自动答题系统 v2.0"
APP_AUTHOR = "阿飞"
APP_WEBSITE = "www.aiopcl.wiki"
TARGET_URL = "https://sia.sinopec.com/mobile/#/sygc/login"
POLL_INTERVAL_MS = 800
LOG_MAX_LINES = 500
MATCH_THRESHOLD = 0.82
WAIT_AFTER_EXPAND_MS = 800
WAIT_AFTER_NEXT_MS = 800
# 答题间隔（每题答完后等待时间，调大可防止漏题）
ANSWER_INTERVAL_MS = 2000
DATA_DIR_NAME = "data"
DB_FILENAME = "question_bank.db"

# 登录配置（默认空，由用户自行保存）
LOGIN_USERNAME = ""  # 账号
LOGIN_PASSWORD = ""  # 密码

# 答题循环配置
DEFAULT_CYCLE_COUNT = 1  # 默认循环答题轮数（0表示无限循环）
AUTO_CLICK_RETRY_COUNT = 3  # 自动点击重试次数

# 题库配置
AUTO_RUN_QUESTION_BANK_AFTER_CYCLE = False  # 每轮答完后是否自动跑一遍题库
CLEAR_OLD_QUESTIONS_BEFORE_RECORD = False  # 录题前是否清空旧题目

# 选项匹配配置
USE_OPTION_TEXT_MATCH = True  # 使用选项文字匹配（而非ABCD识别）
OPTION_TEXT_SIMILARITY_THRESHOLD = 0.85  # 选项文字相似度阈值

# 题库选择配置 (1-5)
# 1: 1钻（修）井/基本素养和形势任务Ⅱ
# 2: 1钻（修）井/专业知识
# 3: 1钻（修）井/HSE通用知识Ⅱ
# 4: 1钻（修）井/HSE法律法规Ⅱ
# 5: 0石油工程基础/基本素养和形势任务Ⅱ
DEFAULT_QUESTION_BANK = 1

# 授权配置
LICENSE_ENABLED = True  # 是否启用授权验证
