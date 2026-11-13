#!/usr/bin/env bash
# 拉取官方代码并应用兼容性修复
# 用法: bash scripts/setup.sh

set -e

REPO_DIR="KnowledgeGraphEmbedding"
UPSTREAM="https://github.com/DeepGraphLearning/KnowledgeGraphEmbedding.git"

echo "==> 1/3 获取官方代码"
if [ -d "$REPO_DIR" ]; then
    echo "    目录已存在，跳过克隆"
else
    git clone --depth 1 "$UPSTREAM" "$REPO_DIR"
fi

echo "==> 2/3 应用兼容性修复（NumPy 2.x / 随机种子）"
python scripts/apply_fixes.py --repo "$REPO_DIR"

echo "==> 3/3 检查数据集"
if [ -d "$REPO_DIR/data/wn18rr" ]; then
    echo "    WN18RR 已随仓库提供"
else
    mkdir -p "$REPO_DIR/data/wn18rr"
    cp data/wn18rr/* "$REPO_DIR/data/wn18rr/"
    echo "    已从本仓库 data/wn18rr 复制"
fi

echo
echo "完成。下一步："
echo "  bash scripts/train_transe.sh"
echo "  bash scripts/train_rotate.sh"
