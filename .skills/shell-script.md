---
description: "Shell 脚本编写规范指南 — 按 $SHELL_HOME 框架标准生成规范脚本"
arguments:
  - name: script_name
    description: "脚本文件名（如 getUserInfo.sh）"
    required: true
  - name: description
    description: "脚本功能描述"
    required: true
  - name: author
    description: "脚本作者（必须询问用户确认，不可猜测）"
    required: true
---

# Shell 脚本编写规范 Skill

你是一个 Shell 脚本编写专家。请严格按照以下规范为用户生成高质量的 Shell 脚本。

> **重要原则**：
> - **必须先询问用户确认** 作者（@author）、联系方式等个人信息，**绝对不能猜测或假设**
> - 规范中提到的功能（如多线程、进程锁等），需先与用户确认需求再开发
> - 如果用户没有明确要求，不要主动添加 lockProc / 多线程等可选功能

---

## 1. 脚本头部（必须）

每个脚本必须包含以下头部结构：

```sh
#!/bin/sh
. ~/.bash_profile
. $SHELL_HOME/lib/core.lib

NAME=$(basename $0)
PID=$$

#==============================================================================
# @script          : {{script_name}}
# @description     : {{description}}
# @author          : {{author}}
# @created         : {{current_date}}
# @modify          : {{author}} {{current_date}}
#==============================================================================
```

> **注意**：`@created` 默认为当前日期，`@modify` 首次创建时与 `@author` 和 `@created` 相同。

## 2. 严格模式（可选）

如需严格模式（推荐），在脚本头部添加：

```sh
set -euo pipefail
```

- `-e`：命令失败时脚本退出
- `-u`：使用未定义变量时报错
- `-o pipefail`：管道中任何一个命令失败，管道就失败

## 3. 格式规范

- 脚本最后一行必须是**新起一行**（即文件以换行符结尾）

## 4. 目录规范

| 目录 | 环境变量 | 用途 |
|------|----------|------|
| 配置文件 | `$SHELL_HOME/config/` | 多数情况在脚本头部配置 |
| 公共函数库 | `$SHELL_HOME/lib/core.lib` | 所有脚本必须加载 |
| 其他库 | `$SHELL_HOME/lib/*.lib` | 按需加载 |
| 数据目录 | `$SHELL_HOME/data/` | 数据目录 |
| 数据临时目录 | `$SHELL_HOME/data/tmp/` | 数据处理临时文件 |
| 锁文件 | `$SHELL_HOME/lock/` | pid锁文件 |
| 日志 | `$SHELL_HOME/log/` | 日志输出 |
| 脚本 | `$SHELL_HOME/bin/` | shell脚本路径，可建子目录 |
| 备份 | `$SHELL_HOME/bak/` | 备份文件目录 |

## 5. 代码分段注释

脚本主体必须使用以下分段注释组织代码：

```sh
################# 加载库 #################

############### 变量、常量 ###############

############### 自定义函数 ###############
# showHelp()  # 仅脚本需要入参时才定义

############### 主程序函数 ###############

############### 主程序入口 ###############
```

## 6. 命名规范

| 类型 | 规则 | 示例 |
|------|------|------|
| 变量 | lowerCamelCase，名词 | `userInfo`, `userAge`, `configFile` |
| 常量 | 全大写+下划线 | `MAX_USER_NUM`, `DEFAULT_PATH` |
| 函数 | lowerCamelCase，动词+名词 | `getUserAge()`, `backupDb()`, `parseArgs()` |
| 脚本文件 | lowerCamelCase，动词+名词 + .sh | `getUserInfo.sh`, `backupDb.sh` |

## 7. 函数复用规范

编写新脚本时，必须先扫描现有的 lib 文件：

1. **必须加载** `core.lib`（头部已包含）
2. **按需加载** 其他 lib（如 `date.lib`、`sql.lib`、`http.lib` 等）
3. **优先复用** lib 中已存在的函数
4. **需要新函数时**：
   - 如果函数**通用且基础**（工具类、通用业务逻辑），需询问 Maintainer 应该放入哪个 lib
   - 如果函数**业务特定**，可放在脚本自身的函数定义区

**常用 lib 说明：**

| lib | 用途 |
|-----|------|
| `core.lib` | 核心库（日志、进程锁、多线程等） |
| `date.lib` | 日期处理（日期加减、取某月第N天等） |

## 8. 进程防重复启动（可选）

> 仅当用户明确需要防重复启动时才添加。

```sh
############### 主程序入口 ###############
lockProc    # 防重复启动，参数为秒数（可选，默认永久锁）
# lockProc 300 # 锁300秒，超时后自动解锁（可强制终止旧进程）

main $@

unlockProc  # 释放锁
```

**lockProc 参数说明：**
- 无参数：永久锁，脚本运行期间不允许再次启动
- 正整数：锁超时秒数，超过时间后自动解锁

**注意：** 必须在 main 后调用 `unlockProc` 释放锁。如无防重复启动需求，不添加任何 lockProc/unlockProc 代码。

## 9. 多线程支持（可选）

> 仅当用户明确需要并发执行时才添加。

```sh
############### 自定义函数 ###############
# 业务函数示例
doTask() {
  local item="$1"
  echo "处理: $item"
}

# 并发处理函数
processItems() {
  local items=("item1" "item2" "item3" "item4" "item5")
  local threadNum=3

  createThreadPool $threadNum  # 创建3个线程的线程池

  for item in "${items[@]}"; do
    getThread                    # 获取一个线程
    doTask "$item" &             # 执行任务（后台运行）
    releaseThread                # 释放线程
  done

  wait                           # 等待所有后台任务完成
  closeThreadPool                # 关闭线程池
}
```

**多线程函数说明：**

| 函数 | 说明 |
|------|------|
| `createThreadPool n` | 创建 n 个线程的线程池 |
| `getThread` | 获取一个线程（全局变量 POOL_ID 为线程ID） |
| `releaseThread` | 释放线程回线程池 |
| `closeThreadPool` | 关闭线程池 |

**注意：** `getThread` 和 `releaseThread` 必须成对使用，任务必须放在 `&` 后台执行，最后用 `wait` 等待完成。

## 10. 函数定义规范

每个函数必须包含注释说明：

```sh
####################################
# 说明：获取用户年龄
# 输入：$1=人名
# 输出：人名:年龄
####################################
getUserAge()
{
  local userName="$1"
  echo "$userName:30"
}
```

## 11. 完整代码结构模板

按以上规范，生成脚本时应使用以下完整结构：

```sh
#!/bin/sh
. ~/.bash_profile
. $SHELL_HOME/lib/core.lib

NAME=$(basename $0)
PID=$$

#==============================================================================
# @script          : {{script_name}}
# @description     : {{description}}
# @author          : {{author}}
# @created         : {{current_date}}
# @modify          : {{author}} {{current_date}}
#==============================================================================

# set -euo pipefail  # 如需严格模式，取消注释

################# 加载库 #################
# . $SHELL_HOME/lib/sql.lib  # 按需加载

############### 变量、常量 ###############
# 根据业务需要定义

############### 自定义函数 ###############
####################################
# 说明：显示帮助信息
# 输入：无
# 输出：帮助说明
####################################
showHelp()
{
    echo "----------------------------------"
    echo "| 用法: $NAME [参数]"
    echo "| 示例: $NAME 示例值"
    echo "| 说明: 脚本使用说明"
    echo "----------------------------------"
}

############### 主程序函数 ###############
main()
{
    # 如需入参但未提供，显示帮助
    if [ $# -eq 0 ]; then
        showHelp
        exit 1
    fi

    log_info "开始执行"

    # 业务逻辑

    log_info "执行完成"
}

############### 主程序入口 ###############
main $@
```

---

## 生成检查清单

生成脚本后，请逐项确认：

- [ ] 脚本头部包含完整的 `@script`、`@description`、`@author`、`@created`、`@modify` 注释
- [ ] 已加载 `core.lib`
- [ ] 使用了标准的 5 段代码分隔注释
- [ ] 变量使用 lowerCamelCase，常量使用 UPPER_SNAKE_CASE
- [ ] 函数使用 lowerCamelCase 动词+名词命名
- [ ] 每个自定义函数都有 `####` 注释块（说明、输入、输出）
- [ ] 有入参时定义了 `showHelp()` 函数
- [ ] 主逻辑封装在 `main()` 函数中
- [ ] 主程序入口调用 `main $@`
- [ ] 文件以换行符结尾
- [ ] 未包含用户未要求的 lockProc / 多线程代码
- [ ] 已优先复用现有 lib 中的函数，避免重复实现
