这个目录放 README「界面预览」章节用的截图。

- `main.png` —— 主界面。由 `python tests/capture_ui_states.py` 生成，是真实运行界面的
  原始截图（`QWidget.grab()`），没有拼接或美化；改了界面重跑一次即可更新。
- `discussion.png` —— 群聊讨论中的画面，**目前还没有**。需要配好 `.env`（或本地
  Ollama）跑一次真实讨论才能截，所以 README 里那行先注释掉了，免得显示碎图。
  补上之后把 README 里的注释解开就行。

命名保持 `main.png` / `discussion.png`，README 按这两个名字引用。
