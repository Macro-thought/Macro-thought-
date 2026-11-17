#!/usr/bin/env bash
# RotatE on WN18RR
#
# 与论文的唯一差异：negative_sample_size 由 1024 降至 512（显存限制，见 README）
# 其余超参与官方 best_config.sh 一致；-de 表示 double entity embedding

set -e
cd "$(dirname "$0")/../KnowledgeGraphEmbedding" 2>/dev/null || {
    echo "未找到 KnowledgeGraphEmbedding，请先执行 bash scripts/setup.sh"; exit 1; }

python -u codes/run.py \
    --do_train --cuda --do_valid --do_test \
    --data_path data/wn18rr --model RotatE \
    -n 512 -b 512 -d 500 -g 6.0 -a 0.5 -adv -lr 0.00005 \
    --max_steps 80000 \
    -save models/RotatE_wn18rr \
    --test_batch_size 8 --cpu_num 1 --seed 0 -de
