# 通过comfyui网页的websocket等协议实现mcp工具

支持 comfyui_login 插件认证；
支持 传入特定的json工作流执行
支持 解析已经存在的comfyui工作流，分辨其输入输出参数执行

## 参考工程

本地目录中有一个工程，可以参考其中comfyui处理方式，切记不要修改！

D:\Code\Python\server_ai_video_maker

已经用软连接方式，放入本项目  的  "参考项目（禁止修改）" 目录了！

## 运行环境

采用 conda 中的 base 环境，作为python环境，来调试本项目！


## 目录结构

采用 fastapi 项目的通行结构！

main.py 为服务主程序！

## 回避

不要采用github上comfyui_mcp,mcp_proxy,comfyui_cli库中的方法，因为不支持token!

## 测试目录

tests 子目录中，存放测试代码，临时文件，等非正式的文件，记录入 tests\ReadME.md 文件中！

## PowerShell 避坑

智能体调用 PowerShell 会经过多层解析，引号/`$`/`&`/`|`/中文极易被转义丢失。完整方案（本机实测）见 `PowerShell_Fix.md`，要点：

- **首选 `-EncodedCommand`**：整段命令用 **UTF-16LE（`Unicode`）编码为 Base64**（用 UTF-8 必挂）；`powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $enc`；只能是一句命令（多句用 `;`），原始脚本约 4KB 上限。
- **备选：临时 `.ps1` + `-File`**：文件内免转义，但注意 BOM 陷阱——PS 5.1 对无 BOM 的 `.ps1` 按 GBK 解码（中文乱码），pwsh 7 按 UTF-8，行为相反；跨工具写入务必用 **UTF-8 with BOM**，或脚本只用 ASCII。
- **辅助技巧**：调用外部程序且参数含特殊字符时在程序名后紧跟 `--%`；字符串优先单引号 `'...'`；支持参数数组时别拼大字符串；显式指定 `powershell.exe`（5.1）或 `pwsh.exe`（7）。
- **排查顺序**：先手动跑一遍完整命令行；乱码→编码层（BOM/UTF-8 混用）；命令找不到/参数错乱→转义层，换 `-EncodedCommand`；中文传到外部程序异常→控制台代码页 `chcp 65001`。


## 大牛8卡4090服务器（用于正式部署）调试阶段在本机调试

GPU：8× RTX 4090（每张 24GB 显存），后 4 张已在使用

ssh 公网连接IP地址：119.84.39.2

ssh 端口  20022

用户名：newgoai 密码：Newgoai@147#@!
（sudo 需要输密码，非 NOPASSWD）

证书登录：本机 `~/.ssh/id_rsa.pub` 已放置到服务器的 root 用户和 newgoai 用户的 `~/.ssh/authorized_keys`，可证书免密登录

首选连接方式（root，免密）：`ssh 119.84.39.2`（`~/.ssh/config` 已有 `Host 119.84.39.2` 条目：User root / Port 20022）
或显式：`ssh -i ~/.ssh/id_rsa -p 20022 root@119.84.39.2`

备选连接方式，一半不用的：（newgoai，免密）：`ssh -i ~/.ssh/id_rsa -p 20022 newgoai@119.84.39.2`

采用服务器的  conda 的 base 环境来执行正式部署程序，但是不能与其他程序的库版本冲突！