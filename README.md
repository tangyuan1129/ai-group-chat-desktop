# AI 团队群聊(桌面版)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078d6)](#-快速开始)
[![Release](https://img.shields.io/github/v/release/tangyuan1129/ai-group-chat-desktop)](https://github.com/tangyuan1129/ai-group-chat-desktop/releases)

让几个 AI 在同一个窗口里互相讨论,而不是每次只跟一个 AI 你问我答。四个角色用的是**不同的模型**——云端 GLM 加本地跑的开源模型——它们观点真的会不一样,讨论起来有来有回,有时候还会互相反驳。

装好之后,输入一句任务,比如:

> 推荐大学生宿舍百元内提升幸福感的小东西

四个 AI 就会自己分角色聊起来:有人拆问题,有人提方案,有人查资料,最后一个人负责验收。聊完可以**接着追问**,它们记得前面聊过什么。

## ✨ 功能特性

- **可以一直追问** —— 讨论完直接接着问"把预算再压低 20%",四个 AI 记得之前的上下文;想重新开始点「新会话」即可
- **逐字流式显示** —— 不用盯着空屏等一整段生成完
- **每个角色的模型可以单独换** —— 用智谱就填智谱的 key(有免费额度),电脑装了 [Ollama](https://ollama.com) 就能用本地模型,其他 OpenAI 兼容的接口(DeepSeek、Kimi 之类)也能接
- **首次启动有引导** —— 选来源、填凭据、**当场测一次连接**,不用猜哪里填错了
- **API Key 加密保存** —— 用 Windows 自带的 DPAPI 按当前用户加密,配置里看不到明文
- **AI 会用几个小工具** —— 联网搜索、读写文件、查 GitHub、执行只读命令
- **自动存档** —— 每次讨论都会存下来,回看时还能看到当时用的模型配置
- **出问题查得到** —— 有日志,「更多 → 导出诊断包」一键打包(密钥自动脱敏),直接发给开发者即可
- **全中文界面** —— Windows 双击就能跑,不需要浏览器

## 🚀 快速开始

### 方式一:最省事(推荐)

去 [Releases 页面](https://github.com/tangyuan1129/ai-group-chat-desktop/releases) 下载 `AI团队群聊-安装程序-v1.1.exe`,双击安装就行。不需要自己配 Python 环境。

### 方式二:源码运行

需要 Python 3.10+(建议 3.11/3.12),本地模型还需要装 [Ollama](https://ollama.com)(不装也能用,只是少一个本地模型):

```bat
pip install -r requirements.txt
```

然后双击 `start_desktop.bat` 启动。**首次启动会弹出配置向导**,跟着填就行:

1. 选一个模型来源(智谱 GLM 最省事,有免费额度)
2. 填 API Key——去 [open.bigmodel.cn](https://open.bigmodel.cn) 或 [api.z.ai](https://api.z.ai) 申请
3. 点「开始测试」确认能连通,再点完成

> 注意:国内站(open.bigmodel.cn)和国际站的 Key **互不通用**,申请哪个站就在向导里选哪个接口地址。

## 📸 界面预览

![主界面](screenshots/main.png)

<!-- 群聊讨论截图还没补上：需要一次真实讨论才能截。
     配好模型后运行 python tests/capture_ui_states.py，
     它会同时产出 screenshots/main.png，讨论中的画面可存成 discussion.png。
     在那之前这里先注释掉，免得首页显示碎图。 -->
<!-- ![群聊讨论](screenshots/discussion.png) -->

## 💡 用法

- **追问**:一轮讨论结束后,直接在输入框里接着问。输入框会变成"继续追问…"的提示,说明上下文还在
- **新会话**:点「🧹 新会话」清空上下文重新开始(上一轮的记录已经存进历史了)
- **停止**:讨论中途可以停。正常是"优雅停止",**上下文会保留**,可以直接接着问;只有极少数情况(网络挂死)才会强制中断并重置上下文,那时界面会明确告诉你
- **换模型**:点「⚙ 配置模型」可以逐个角色改,还能点「测试全部」看哪个角色不通
- **排查问题**:「⋯ 更多 → 导出诊断包」会生成一个 zip(含日志和环境信息,**密钥已自动脱敏**),出问题把它发出来就行

## ⚠️ 注意事项

- **文件工具**只能读写"文档"目录下的 `AI团队群聊` 文件夹,路径越界会被拒绝(含符号链接/junction 逃逸)
- **命令工具**只能执行查询类命令,而且工作目录被锁在那个文件夹里;`.env`、配置文件、SSH 私钥、浏览器凭据等敏感文件一律拒绝读取。**AI 要看文件内容请用 `read_text_file`**,不要用 `Get-Content`
- 数据都存在用户目录下,不依赖安装位置,也不需要管理员权限:
  - 配置、聊天记录、日志 → `%APPDATA%\AI团队群聊\`
  - AI 产出的文件 → `文档\AI团队群聊\`
- 智谱免费接口偶尔限流(429),程序会自动等一会儿重试,不用管它
- 这是个人业余项目,遇到问题直接提 [issue](https://github.com/tangyuan1129/ai-group-chat-desktop/issues) 即可

## 📁 目录结构

```
├── desktop_app.py      # 主程序:界面与交互
├── team_session.py     # 会话:多轮追问 / 流式输出 / 优雅停止
├── llm.py              # 模型客户端构造与连接测试
├── onboarding.py       # 首次启动引导向导
├── app_config.py       # 配置、路径、校验、损坏恢复
├── secret_store.py     # 密钥加密(Windows DPAPI)
├── app_logging.py      # 日志、脱敏、诊断包
├── tools.py            # AI 的"手臂":搜索 / 文件 / GitHub / 命令
├── glm_client.py       # 智谱 GLM 客户端(含限流自动重试)
├── start_desktop.bat   # 双击启动
├── pack.spec           # PyInstaller 打包配置
├── install.iss         # Inno Setup 安装脚本
├── requirements.txt
├── .env.example        # 密钥模板(可选,给开发/高级用户)
├── screenshots/        # 界面预览图
└── tests/              # 回归测试(见下)
```

## 🧪 测试

不需要装 pytest,直接跑:

```bat
python tests\test_config.py            :: 配置读写、密钥加密、损坏恢复
python tests\test_tools_sandbox.py     :: 文件沙箱 + 命令工具拦截
python tests\test_team_session.py      :: 多轮追问 / 流式 / 优雅停止 / 强制停止兜底
python tests\test_session_cleanup.py   :: 模型连接释放
python tests\test_onboarding.py        :: 首启引导向导
python tests\test_ui_flow.py           :: 端到端界面流程
python tests\prove_old_bugs.py         :: 复现修复前的漏洞(取历史提交对比)
```

## 🔨 从源码构建

```bat
pip install -r requirements.txt pyinstaller
pyinstaller pack.spec --noconfirm
```

产物在 `dist\AI团队群聊\`。要出安装包再用 Inno Setup 6 编译 `install.iss`。

## 📄 License

MIT
