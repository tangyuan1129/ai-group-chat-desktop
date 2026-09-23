# AI 团队群聊(桌面版)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078d6)](#怎么装)
[![Release](https://img.shields.io/github/v/release/tangyuan1129/ai-group-chat-desktop)](https://github.com/tangyuan1129/ai-group-chat-desktop/releases)

让几个 AI 在同一个窗口里互相讨论,而不是每次只跟一个 AI 你问我答。四个角色用的是**不同的模型**——云端 GLM 加本地跑的开源模型——它们观点真的会不一样,讨论起来有来有回,有时候还会互相反驳。

装好之后,输入一句任务,比如:

> 推荐大学生宿舍百元内提升幸福感的小东西

四个 AI 就会自己分角色聊起来:有人拆问题,有人提方案,有人查资料,最后一个人负责验收。聊完会给你一个汇总结果,需要的时候还会把方案直接写成文件存到电脑上。

## ✨ 功能特性

- **每个角色的模型可以单独换** —— 用智谱就填智谱的 key(有免费额度),电脑装了 [Ollama](https://ollama.com) 就能用本地模型,其他 OpenAI 兼容的接口(DeepSeek、Kimi 之类)也能接
- **AI 会用几个小工具** —— 联网搜索、读写文件、查 GitHub、执行只读命令
- **自动存档** —— 每次讨论结束都会存下来,之后可以在"历史记录"里翻出来重看
- **全中文界面** —— Windows 双击就能跑,不需要浏览器

## 🚀 快速开始

### 方式一:最省事(推荐)

去 [Releases 页面](https://github.com/tangyuan1129/ai-group-chat-desktop/releases) 下载 `AI团队群聊-安装程序-v1.1.exe`,双击安装就行——会自动装到 D 盘、在桌面和开始菜单建好快捷方式,还带卸载程序,不需要自己配 Python 环境。

### 方式二:源码运行

需要 Python 3.10+(建议 3.11/3.12),本地模型还需要装 [Ollama](https://ollama.com)(不装也能用,只是少一个本地模型):

```bat
pip install -r requirements.txt
```

然后复制 `.env.example` 为 `.env`,填上你的智谱 API key(在 open.bigmodel.cn 申请,有免费额度)。双击 `start_desktop.bat` 启动,输入任务就行了。

## 📸 界面预览

(运行后截图补在这里——主界面 + 一次群聊讨论的效果图)

## ➠／ 注意事项

- AI 的工具只能读写程序目录下的 `output` 文件夹,删文件、关机这类危险命令被拦掉了
- 智谱免费接口偶尔限流(429),程序会自动等一会儿重试,不用管它
- 这是个人业余项目,代码可能不够完善,遇到问题直接提 [issue](https://github.com/tangyuan1129/ai-group-chat-desktop/issues) 即可

## 📁 目录结构

```
├── desktop_app.py      # 主程序(界面 + 团队调度)
├── tools.py            # AI 的"手臂":搜索 / 文件 / GitHub / 命令
├── glm_client.py       # 智谱 GLM 客户端(含限流自动重试)
├── start_desktop.bat   # 双击启动
├── requirements.txt
├── .env.example        # 密钥模板(复制为 .env 填写)
├── output/             # AI 写出的文件放这里
└── history/            # 聊天记录(自动生成)
```

## 📄 License

MIT