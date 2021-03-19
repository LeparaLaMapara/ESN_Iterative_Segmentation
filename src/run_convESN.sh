#!/bin/bash
#SBATCH --job-name=100CESN
#SBATCH --nodes=5
#SBATCH --cpus-per-task=4        # cpu-cores per task (>1 if multi-threaded tasks)
#SBATCH --ntasks-per-node=4      # number of tasks per node
#SBATCH --output=/home-mscluster/tmashinini/MSC/Code/Python/logs/cifar100_4096_convESN.txt
#SBATCH --error=/home-mscluster/tmashinini/MSC/Code/Python/logs/cifar100_4096_convESN.err
num_frames=80
num_dim=64
ch=2
lr=0.9
ep=500
bs=32
# BSR WEIZMANN CIFAR_100 CIFAR_10
for dataset in 'CIFAR_100';
do
    for h in 4096;
    do 
        for lkr in 0.0078125; # leaking rate
        do
            for spy in 0.7; # sparsity
            do 
                for spl in 0.9; # spectral radius
                do
                   for nlyrs in 1;
                   do
                        source ~/.bashrc 
                        conda activate msc
                        # python main_conv3D.py --run-name=${dataset}-conv3d_h1-${h1}_h2-${h2}_dp-${dp} --data-path=/Users/thabang/Documents/msc/data/${dataset} --save-path=/Users/thabang/Documents/msc/data/${dataset}/results  --num-epochs=500  --batch-size=1 --learning-rate=0.1 --num-frames=$num_frames  --num-past-step=1 --num-future-step=1 --image-dimension=$num_dim  --threshold=0.5  --in-channels=200  --sample-size=$num_dim  --sample-duration=$num_frames --hidden-one=$h1 --hidden-two=$h2  --dropout-prob=$dp
                        python3 /home-mscluster/tmashinini/MSC/Code/Python/main_convESN.py --run-name=${dataset}-convESN_h-${h}_lkr-${lkr}_spy-${spy}_spl-${spl} --data-path=/home-mscluster/tmashinini/MSC/Data/processed_data/${dataset} --save-path=/home-mscluster/tmashinini/MSC/Data/processed_data/${dataset}/results  --num-epochs=$ep  --batch-size=$bs --learning-rate=$lr --num-frames=$num_frames  --num-past-step=1 --num-future-step=1 --image-dimension=$num_dim  --threshold=0.5  --in-channels=$ch  --sample-size=$num_dim  --sample-duration=$num_frames --hidden=$h  --num_layers=$nlyrs --leaking-rate=${lkr}  --sparsity=${spy} --spectral-radius=${spl}
            
                    done
                done
            done
        done
    done
done

