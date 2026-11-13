#!/usr/bin/env bash
# TransE on WN18RR
#
# 注意 --cpu_num 1：原代码默认 10，在 Windows 上会开 10 个 DataLoader worker，
# 每进程约 500MB，内存不足时互相等待形成死锁（表现为日志停滞、CPU 时间零增长）。

set -e
cd "$(dirname "$0")/../KnowledgeGraphEmbedding" 2>/dev/null || {
    echo "未找到 KnowledgeGraphEmbedding，请先执行 bash scripts/setup.sh"; exit 1; }

python -u codes/run.py \
    --do_train --cuda --do_valid --do_test \
    --data_path data/wn18rr --model TransE \
    -n 512 -b 512 -d 500 -g 6.0 -a 0.5 -adv -lr 0.00005 \
    --max_steps 80000 \
    -save models/TransE_wn18rr \
    --test_batch_size 8 --cpu_num 1 --seed 0
