#!/bin/bash
# Octopus Agent 容器入口脚本

# 加载用户 profile（配置了 alias、PATH 扩展等）
. ~/.bash_profile

exec python /octopus/octopus.py --web
