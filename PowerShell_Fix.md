# 智能体调用 PowerShell（Windows）转义问题的解决方案

智能体调用 PowerShell 时，命令会经过多层解析（Agent 字符串处理 → 启动器 → PowerShell CLI），导致引号、`$`、`&`、`` ` ``、`|`、中文等被反复转义或丢失。手动逐层加转义极其脆弱，Win11 + PowerShell 5.1/7 混用时更明显。以下方案均经本机实测（2026-08-22）。

## 一、首选：`-EncodedCommand`（实测可用）

整段命令用 **UTF-16LE** 编码为 Base64，命令行里只剩 Base64 字符，无任何引号和特殊字符。

```powershell
# 生成 Base64
$command = 'Write-Host "Hello `"World`" 中文 & $x"'
$enc = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($command))

# 智能体实际调用（powershell.exe = Windows PowerShell 5.1；装了 7 可用 pwsh.exe）
powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $enc
```

实测输出：`Hello "World" 中文 & $x`，引号/变量/`&`/中文全部无损。

**关键点（踩坑点）：**

- **必须用 `Unicode`（UTF-16LE），用 UTF-8 编码必挂**：实测 UTF-8 编码的 Base64 传入后按 UTF-16 解码，中文变 `牗瑩ⵥ潈` 这类错乱，且可能直接 `CommandNotFoundException`。
- 编码后的脚本**只能是一句命令**（无换行可用 `;` 连接）；`@'...'@` here-string 在编码前的"生成"脚本里可以任意复杂。
- 命令行有长度上限（约 8KB Base64，即原始脚本约 4KB 字符），超长用方案二。
- 部分杀软对 `-EncodedCommand` 敏感，被拦截用方案二。
- 加 `-NoProfile -ExecutionPolicy Bypass`，避免环境和执行策略干扰。

## 二、备选：临时 `.ps1` + `-File`（实测可用，注意编码）

把命令写入 `.ps1` 文件，`-File` 执行，文件内无需任何转义：

```powershell
$p = Join-Path $env:TEMP 'agent_cmd.ps1'
Set-Content $p 'Write-Host "中文 `&` special"' -Encoding UTF8
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p
Remove-Item $p
```

实测输出：`中文 & special` 正常。

**BOM 陷阱（比转义更隐蔽）：**

- Windows PowerShell 5.1 对**无 BOM** 的 `.ps1` 按 ANSI（中文系统 = GBK）解码：文件若是外部工具/UTF-8 无 BOM 写入，中文全部乱码（实测输出 `涓枃`）。
- `Set-Content -Encoding UTF8` 在 5.1 里自带 BOM，安全；但跨工具/跨平台写入务必用 **UTF-8 with BOM**，或脚本中只用 ASCII。
- PowerShell 7 的 `pwsh.exe` 默认按 UTF-8 无 BOM 解码，行为相反——所以 5.1 和 7 对无 BOM 中文文件恰好是镜像的坑。
- 纯 ASCII 脚本则两种解释器、有无 BOM 都没问题，优先保证这点。

## 三、辅助技巧（按场景）

| 场景 | 做法 |
| --- | --- |
| 调用外部程序、参数有特殊字符 | 在**外部程序名后**紧跟 `--%`：`cmd --% /c echo "a & b"`（实测有效：`$var`、`&` 原样传给外部程序；`--%` 必须直接跟在程序名后，不能出现在 cmdlet 上或行首） |
| 减少转义 | 优先单引号 `'...'`（内部几乎免转义，仅 `'` 本身用 `''` 转义）；需变量展开才用双引号 |
| Agent 框架支持参数数组 | 别把命令拼成大字符串，按参数数组传，从根上避免转义层 |
| 明确指定解释器 | 显式写 `powershell.exe`（5.1）或 `pwsh.exe`（7），两者转义/编码规则不同 |

## 四、验证与排查顺序

1. 先确认最终完整命令行（打印出来在本机跑一遍），确认无误再交给智能体。
2. 出问题时按层定位：
   - 输出乱码 → 编码层（UTF-8/UTF-16 混用、无 BOM 的 `.ps1`）；
   - 命令找不到/参数错乱 → 转义层（引号被某层解析掉）→ 换 `-EncodedCommand`；
   - 中文参数传到外部程序异常 → 控制台代码页（`chcp 65001` 或改用 UTF-16 传参）。
